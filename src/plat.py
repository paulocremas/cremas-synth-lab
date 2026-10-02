"""Camada de PLATAFORMA (Linux x Windows) — tudo que o native/dash pedem ao sistema e muda de um
pro outro: monitores, captura de tela/camera (args do ffmpeg), audio do sistema, "tem dado no
pipe?", navegador do dash, pastas. No Linux repete exatamente o que o codigo ja fazia (xrandr,
x11grab, v4l2, parec); o resto so' vale no Windows:

  monitores     EnumDisplayMonitors (pixels FISICOS: processo marcado DPI-aware, senao 4K com
                escala 150% vira 2560x1440 e o pixel map deixa de ser 1:1)
  tela          ffmpeg -f gdigrab (offset em coordenadas do desktop virtual)
  camera        ffmpeg -f dshow; nomes de `ffmpeg -list_devices true -f dshow`
  audio         loopback WASAPI (PyAudioWPatch) num objeto com cara de Popen (PcmProc: .stdout
                = s16le mono 44100, mesmo formato do parec) -> o audio_thread nao muda
  pipe pronto?  select() nao funciona com pipe no Windows -> PeekNamedPipe
  subprocess    sem janela de console a cada ffmpeg (CREATE_NO_WINDOW por padrao)

Sem import de native_synth/dash_server (os dois importam este).
"""
import os
import re
import shutil
import subprocess
import sys
import threading
import time

import numpy as np

IS_WIN = sys.platform == 'win32'
AUDIO_RATE = 44100

if IS_WIN:   # todo subprocess sem console piscando (app empacotado e' --windowed)
    _Popen0 = subprocess.Popen

    class _QuietPopen(_Popen0):
        def __init__(self, *a, **kw):
            kw.setdefault('creationflags', 0x08000000)   # CREATE_NO_WINDOW
            super().__init__(*a, **kw)

    subprocess.Popen = _QuietPopen


def init_process():
    """Chamar no comeco do processo. Windows: DPI-aware por monitor (coordenadas e tamanhos em
    pixel fisico — o pixel map so' e' 1:1 assim)."""
    if not IS_WIN:
        return
    import ctypes
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except (AttributeError, OSError):
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except (AttributeError, OSError):
            pass


def readable(stream, timeout):
    """True se `stream` (stdout de um processo/pipe) tem dado pra ler ou chegou ao fim, esperando
    ate `timeout` s. = select.select([stream], [], [], timeout)[0] (que no Windows nao aceita pipe)."""
    if not IS_WIN:
        import select
        return bool(select.select([stream], [], [], timeout)[0])
    import ctypes
    import msvcrt
    from ctypes import wintypes
    try:
        h = msvcrt.get_osfhandle(stream.fileno())
    except (OSError, ValueError):
        return True                                  # fechado: o read devolve EOF
    avail = wintypes.DWORD()
    end = time.monotonic() + timeout
    while True:
        if not ctypes.windll.kernel32.PeekNamedPipe(h, None, 0, None, ctypes.byref(avail), None):
            return True                              # pipe quebrado = fim
        if avail.value:
            return True
        if time.monotonic() >= end:
            return False
        time.sleep(0.004)


# ---------------------------------------------------------------- monitores

def _xrandr(args=('--current',)):
    return subprocess.check_output(['xrandr', *args]).decode()


def _win_monitors():
    import ctypes
    from ctypes import wintypes

    class MONITORINFOEXW(ctypes.Structure):
        _fields_ = [('cbSize', wintypes.DWORD), ('rcMonitor', wintypes.RECT), ('rcWork', wintypes.RECT),
                    ('dwFlags', wintypes.DWORD), ('szDevice', wintypes.WCHAR * 32)]
    out = []
    proto = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HMONITOR, wintypes.HDC, ctypes.POINTER(wintypes.RECT), wintypes.LPARAM)

    def cb(hmon, _hdc, _rc, _lp):
        mi = MONITORINFOEXW()
        mi.cbSize = ctypes.sizeof(mi)
        if ctypes.windll.user32.GetMonitorInfoW(hmon, ctypes.byref(mi)):
            r = mi.rcMonitor
            out.append({'name': mi.szDevice.replace('\\\\.\\', ''), 'w': r.right - r.left, 'h': r.bottom - r.top,
                        'x': r.left, 'y': r.top, 'primary': bool(mi.dwFlags & 1)})
        return True
    ctypes.windll.user32.EnumDisplayMonitors(None, None, proto(cb), 0)
    return out


def monitors():
    """Saidas ATIVAS: [{name, w, h, x, y, primary}] (Linux: ordem do xrandr; Windows: DISPLAY1..)."""
    if IS_WIN:
        return _win_monitors()
    res = []
    for line in _xrandr().splitlines():
        m = re.match(r'(\S+) connected (primary )?(\d+)x(\d+)\+(\d+)\+(\d+)', line)
        if m:
            name, primary, w, h, x, y = m.groups()
            res.append({'name': name, 'w': int(w), 'h': int(h), 'x': int(x), 'y': int(y), 'primary': bool(primary)})
    return res


def screen_size():
    """Linux: a tela X inteira (xrandr 'current'). Windows: o monitor principal."""
    if IS_WIN:
        m = next((m for m in _win_monitors() if m['primary']), None)
        return (m['w'], m['h']) if m else (1920, 1080)
    w, h = re.search(r'current (\d+) x (\d+)', _xrandr()).groups()
    return int(w), int(h)


def outputs_text(probe=False):
    """Texto no formato do `xrandr --query` (dash_data.parse_xrandr le). probe=True sonda EDID
    (xrandr --query); no Windows monta o texto a partir das saidas ativas (sem 'desligadas')."""
    if not IS_WIN:
        return subprocess.run(['xrandr', '--query' if probe else '--current'], capture_output=True,
                              text=True, timeout=5).stdout
    ms = _win_monitors()
    right = max((m['x'] + m['w'] for m in ms), default=0)
    lines = [f'Screen 0: minimum 8 x 8, current {right} x {max((m["y"] + m["h"] for m in ms), default=0)}, maximum 32767 x 32767']
    for m in ms:
        lines.append(f"{m['name']} connected{' primary' if m['primary'] else ''} {m['w']}x{m['h']}+{m['x']}+{m['y']} (normal)")
        lines.append(f"   {m['w']}x{m['h']}     60.00*+")
    return '\n'.join(lines) + '\n'


# ---------------------------------------------------------------- video (args do ffmpeg)

_cams = {'t': 0.0, 'v': []}


def _dshow_cams():
    """Nomes das cameras DirectShow (cache de 5 s: o ffmpeg leva ~0.5 s pra listar)."""
    if time.monotonic() - _cams['t'] < 5:
        return _cams['v']
    try:
        err = subprocess.run(['ffmpeg', '-hide_banner', '-list_devices', 'true', '-f', 'dshow', '-i', 'dummy'],
                             capture_output=True, text=True, timeout=10).stderr
    except (OSError, subprocess.SubprocessError):
        err = ''
    _cams.update(t=time.monotonic(), v=parse_dshow_cams(err))
    return _cams['v']


def parse_dshow_cams(text):
    """stderr do `ffmpeg -list_devices true -f dshow -i dummy` -> nomes das cameras (video)."""
    return [m.group(1) for m in re.finditer(r'"([^"]+)"\s*\(video\)', text or '')]


def list_cams():
    """Ids das cameras (sem o prefixo 'webcam:'): /dev/videoN (Linux) | nome DirectShow (Windows)."""
    if IS_WIN:
        return _dshow_cams()
    import glob
    return sorted(glob.glob('/dev/video*'))


def default_cam():
    if IS_WIN:
        cams = _dshow_cams()
        return cams[0] if cams else 'camera'
    return '/dev/video0'


def cam_input_args(device, w, h):
    """Args de ENTRADA do ffmpeg pra uma camera (antes do -vf). Linux: v4l2 pedindo w x h (o
    aspecto dela); Windows: dshow no formato nativo (pedir um tamanho que ela nao tem = erro)."""
    if IS_WIN:
        return ['-f', 'dshow', '-rtbufsize', '64M', '-i', f'video={device}']
    a = ['-f', 'v4l2', '-framerate', '30']
    if device == '/dev/video0':   # so a webcam de verdade precisa forcar o formato
        a += ['-input_format', 'yuyv422']
    return a + ['-video_size', f'{w}x{h}', '-i', device]


def screen_input_args(r):
    """Args de ENTRADA do ffmpeg pra um retangulo da tela r = {x, y, w, h}."""
    if IS_WIN:
        return ['-f', 'gdigrab', '-framerate', '30', '-offset_x', str(r['x']), '-offset_y', str(r['y']),
                '-video_size', f"{r['w']}x{r['h']}", '-i', 'desktop']
    display = os.environ.get('DISPLAY', ':0') + f"+{r['x']},{r['y']}"
    return ['-f', 'x11grab', '-framerate', '30', '-video_size', f"{r['w']}x{r['h']}", '-i', display]


# ---------------------------------------------------------------- audio (Windows: WASAPI)

class Resampler:
    """Reamostragem LINEAR em blocos com continuidade (fase fracionaria + ultima amostra entre
    blocos). Pra analise de espectro/medidor basta; nao e' pra masterizar."""

    def __init__(self, src, dst):
        self.step, self.pos, self.prev = src / dst, 0.0, np.zeros(0, np.float32)

    def process(self, x):
        buf = np.concatenate([self.prev, np.asarray(x, np.float32)])
        n = len(buf)
        if n < 2:
            self.prev = buf
            return np.zeros(0, np.float32)
        idx = np.arange(self.pos, n - 1, self.step)
        out = np.interp(idx, np.arange(n), buf).astype(np.float32)
        self.pos = (idx[-1] + self.step if len(idx) else self.pos) - (n - 1)
        self.prev = buf[-1:]
        return out


def _pa():
    try:
        import pyaudiowpatch as pa
    except ImportError as e:
        raise FileNotFoundError('PyAudioWPatch (audio do Windows) nao instalado') from e
    return pa


def list_audio():
    """[{id, name}] das fontes de audio. Windows: loopbacks (o som que sai em cada saida) primeiro,
    depois microfones. id = nome do device (indice muda entre sessoes)."""
    if not IS_WIN:
        return None                                  # Linux: o native lista pelo pactl
    pa = _pa()
    p = pa.PyAudio()
    try:
        devs = [p.get_device_info_by_index(i) for i in range(p.get_device_count())]
        api = p.get_host_api_info_by_type(pa.paWASAPI)['index']
    finally:
        p.terminate()
    devs = [d for d in devs if d['maxInputChannels'] > 0 and d['hostApi'] == api]
    devs.sort(key=lambda d: not d.get('isLoopbackDevice'))
    return [{'id': d['name'], 'name': d['name'].replace(' [Loopback]', ' (som do sistema)')} for d in devs]


def default_audio():
    """Fonte padrao = o som geral do sistema. Linux: monitor do sink padrao (pactl); Windows: o
    loopback da saida padrao."""
    if not IS_WIN:
        sink = subprocess.check_output(['pactl', 'get-default-sink']).decode().strip()
        return sink + '.monitor'
    pa = _pa()
    p = pa.PyAudio()
    try:
        spk = p.get_device_info_by_index(p.get_host_api_info_by_type(pa.paWASAPI)['defaultOutputDevice'])
        lb = next((d for d in p.get_loopback_device_info_generator() if spk['name'] in d['name']), None)
        return (lb or spk)['name']
    finally:
        p.terminate()


class PcmProc:
    """'Processo' de captura no Windows com a interface que o audio_thread usa do parec: .stdout
    (s16le mono 44100, num pipe de verdade -> readable()/read funcionam), .poll(), .terminate(),
    .kill(), .wait(), .errf. WASAPI loopback nao manda nada enquanto nada toca: aqui vira
    SILENCIO continuo (o parec sempre manda), senao o vigia do native reiniciaria a cada 2 s."""

    def __init__(self, device):
        self._pa = _pa()                            # sem a lib -> FileNotFoundError (= "sem parec")
        import io
        r, w = os.pipe()
        self.stdout, self._w = os.fdopen(r, 'rb'), w
        self.errf, self.returncode = io.BytesIO(), None
        self._stop = threading.Event()
        self._t = threading.Thread(target=self._run, args=(device,), daemon=True)
        self._t.start()

    def _run(self, device):
        pa, p, st = self._pa, None, None
        try:
            p = pa.PyAudio()
            devs = [p.get_device_info_by_index(i) for i in range(p.get_device_count())]
            info = next((d for d in devs if d['name'] == device and d['maxInputChannels'] > 0), None)
            if info is None:
                info = next(d for d in devs if d['name'] == default_audio())
            ch, rate = max(1, int(info['maxInputChannels'])), int(info['defaultSampleRate'])
            st = p.open(format=pa.paInt16, channels=ch, rate=rate, input=True,
                        input_device_index=info['index'], frames_per_buffer=512)
            rs, last = Resampler(rate, AUDIO_RATE), time.monotonic()
            while not self._stop.is_set():
                n = st.get_read_available()
                now = time.monotonic()
                if n >= 256:
                    x = np.frombuffer(st.read(n, exception_on_overflow=False), np.int16).reshape(-1, ch).mean(axis=1)
                    y = rs.process(x)
                    last = now
                elif now - last >= 0.05:                    # nada tocando: silencio do tempo que passou
                    y, last = np.zeros(int((now - last) * AUDIO_RATE), np.float32), now
                else:
                    time.sleep(0.005)
                    continue
                if len(y):
                    os.write(self._w, np.clip(y, -32768, 32767).astype(np.int16).tobytes())
        except Exception as e:                              # noqa: BLE001 — vai pro log do native
            self.errf.write(str(e).encode(errors='ignore'))
        finally:
            for f in (lambda: st and st.close(), lambda: p and p.terminate(), lambda: os.close(self._w)):
                try:
                    f()
                except Exception:                            # noqa: BLE001
                    pass
            self.returncode = 0

    def poll(self):
        return self.returncode

    def terminate(self):
        self._stop.set()

    kill = terminate

    def wait(self, timeout=None):
        self._t.join(timeout)
        if self._t.is_alive():
            raise subprocess.TimeoutExpired('wasapi', timeout)
        return 0


class PcmPlayer:
    """'pacat' do Windows: .stdin.write(s16le mono 44100) toca na saida padrao."""

    def __init__(self):
        pa = _pa()
        self._p = pa.PyAudio()
        self._s = self._p.open(format=pa.paInt16, channels=1, rate=AUDIO_RATE, output=True)
        self.stdin, self.returncode = self, None

    def write(self, data):
        self._s.write(data)

    def flush(self):
        pass

    def poll(self):
        return self.returncode

    def terminate(self):
        if self.returncode is None:
            self.returncode = 0
            try:
                self._s.close()
                self._p.terminate()
            except Exception:                                # noqa: BLE001
                pass

    kill = terminate

    def wait(self, timeout=None):
        return 0


def spawn_audio(device):
    """Captura do audio do sistema -> objeto com .stdout s16le mono 44100 (parec | PcmProc)."""
    if IS_WIN:
        return PcmProc(device)
    import tempfile
    # stderr num ARQUIVO, nao num pipe: ninguem le o pipe enquanto o parec vive, e se ele enche
    # (64 KB de avisos) o parec trava pra sempre sem morrer — o audio "sumia" do nada.
    errf = tempfile.TemporaryFile()
    p = subprocess.Popen(['parec', '--device=' + device, '--format=s16le', '--rate=44100',
                          '--channels=1', '--latency-msec=50'], stdout=subprocess.PIPE, stderr=errf)
    p.errf = errf
    return p


def spawn_player():
    """Tocar s16le mono 44100 (audio do video-fonte-de-audio). None se nao der."""
    if IS_WIN:
        try:
            return PcmPlayer()
        except Exception:                                    # noqa: BLE001
            return None
    try:
        return subprocess.Popen(['pacat', '--playback', '--format=s16le', '--rate=44100',
                                 '--channels=1', '--latency-msec=60', '--client-name=prisma'],
                                stdin=subprocess.PIPE, stderr=subprocess.DEVNULL)
    except FileNotFoundError:
        return None


# ---------------------------------------------------------------- processos / pastas / navegador

def kill_tree(p):
    """Mata o processo e os filhos (o navegador do dash abre varios)."""
    try:
        if IS_WIN:
            subprocess.run(['taskkill', '/PID', str(p.pid), '/T', '/F'], capture_output=True, timeout=5)
        else:
            import signal
            os.killpg(p.pid, signal.SIGTERM)
    except (OSError, subprocess.SubprocessError):
        pass


def quit_self():
    """Pede pro proprio processo sair pelo fluxo normal (handler de SIGTERM do native)."""
    import signal
    if IS_WIN:
        signal.raise_signal(signal.SIGTERM)          # os.kill no Windows = TerminateProcess (sem limpeza)
    else:
        os.kill(os.getpid(), signal.SIGTERM)


def config_dir():
    """~/.config/prisma | %APPDATA%\\prisma"""
    base = os.environ.get('APPDATA') if IS_WIN else None
    return os.path.join(base or os.path.join(os.path.expanduser('~'), '.config'), 'prisma')


def data_dir():
    """Onde o app roda e guarda os dados do usuario: ~/.local/share/prisma | %LOCALAPPDATA%\\prisma
    ($PRISMA_HOME ganha)."""
    if os.environ.get('PRISMA_HOME'):
        return os.environ['PRISMA_HOME']
    if IS_WIN:
        return os.path.join(os.environ.get('LOCALAPPDATA') or os.path.expanduser('~'), 'prisma')
    return os.path.join(os.environ.get('XDG_DATA_HOME') or os.path.expanduser('~/.local/share'), 'prisma')


def app_browser(names):
    """1o Chromium achado (Brave/Chrome/Edge — o dash abre em --app). Windows: tambem nos lugares
    de instalacao padrao (nao ficam no PATH); o Edge vem com o Windows."""
    for n in names:
        p = shutil.which(n)
        if p:
            return p
    if IS_WIN:
        roots = [os.environ.get(k) for k in ('PROGRAMFILES', 'PROGRAMFILES(X86)', 'LOCALAPPDATA')]
        rel = [r'BraveSoftware\Brave-Browser\Application\brave.exe', r'Google\Chrome\Application\chrome.exe',
               r'Microsoft\Edge\Application\msedge.exe']
        for r in rel:
            for root in filter(None, roots):
                p = os.path.join(root, r)
                if os.path.isfile(p):
                    return p
    return None


if __name__ == '__main__':  # self-check das partes puras (roda em qualquer SO)
    rs = Resampler(48000, 44100)
    x = np.sin(np.arange(48000) * 2 * np.pi * 440 / 48000).astype(np.float32)
    y = np.concatenate([rs.process(x[i:i + 512]) for i in range(0, len(x), 512)])
    assert abs(len(y) - 44100) <= 2, len(y)
    ref = np.sin(np.arange(len(y)) * 2 * np.pi * 440 / 44100)
    assert np.max(np.abs(y - ref)) < 0.01, np.max(np.abs(y - ref))       # continuo entre blocos
    rs = Resampler(44100, 44100)
    assert np.allclose(np.concatenate([rs.process(np.arange(i, i + 10)) for i in range(0, 30, 10)]), np.arange(29))
    txt = ('[dshow @ 0x1] "Integrated Camera" (video)\n[dshow @ 0x1]   Alternative name "@device_pnp_\\\\?\\usb"\n'
           '[dshow @ 0x1] "OBS Virtual Camera" (video)\n[dshow @ 0x1] "Microfone (Realtek)" (audio)\n')
    assert parse_dshow_cams(txt) == ['Integrated Camera', 'OBS Virtual Camera']
    assert cam_input_args('/dev/video0', 640, 480)[:2] == ['-f', 'v4l2'] or IS_WIN
    assert screen_input_args({'x': 10, 'y': 0, 'w': 100, 'h': 50})[-1].endswith('+10,0') or IS_WIN
    if not IS_WIN and os.environ.get('DISPLAY') and shutil.which('xrandr'):   # CI sem X: pula
        assert 'connected' in outputs_text()
    print('plat self-check ok')
