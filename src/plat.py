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


_SETPRIV = None if IS_WIN else shutil.which('setpriv')


def child_cmd(cmd):
    """Comando de um filho que tem que morrer JUNTO com o prisma (ffmpeg das fontes). Linux:
    `setpriv --pdeathsig TERM` (util-linux) — sem isso um prisma morto (crash, kill -9) deixa o
    ffmpeg da camera orfao segurando o /dev/video* (v4l2 e' exclusivo) e a webcam nao abre mais.
    O sinal vem quando a THREAD que criou o filho acaba: so' criar de thread longa ou que mata o
    proprio filho antes de sair. Windows/sem setpriv: o comando como veio."""
    return [_SETPRIV, '--pdeathsig', 'TERM', '--', *cmd] if _SETPRIV else list(cmd)


_x11 = None   # (libX11, display) aberto na 1a vez


def _win_dpi(fn):
    """Windows: roda fn(user32) com ESTA thread em DPI por monitor (v2) — sem isso, com escala de tela != 100%, o Windows
    reescala as coordenadas do SetCursorPos/GetCursorPos (o processo nao declara DPI) e o cursor do arrasto infinito voltava
    pro lugar errado. So' a thread, so' durante a chamada: a janela de saida (pygame) nao muda."""
    import ctypes
    u = ctypes.windll.user32
    old = None
    try:
        u.SetThreadDpiAwarenessContext.restype = ctypes.c_void_p
        u.SetThreadDpiAwarenessContext.argtypes = [ctypes.c_void_p]
        old = u.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))   # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2
    except AttributeError:   # Windows < 10 1607: sem a funcao, fica como era
        pass
    try:
        return fn(u)
    finally:
        if old:
            u.SetThreadDpiAwarenessContext(ctypes.c_void_p(old))


def pointer_pos():
    """Onde o cursor ESTA', em pixel fisico (x, y) — o knob guarda isso no clique e devolve o cursor exatamente pra la' ao
    soltar (sem converter screenX x devicePixelRatio, que erra com escala de tela). Windows: GetCursorPos; Linux: None
    (o dash usa a conta de sempre, que la' funciona)."""
    if not IS_WIN:
        return None
    import ctypes

    class _P(ctypes.Structure):
        _fields_ = [('x', ctypes.c_long), ('y', ctypes.c_long)]
    p = _P()
    try:
        return (p.x, p.y) if _win_dpi(lambda u: u.GetCursorPos(ctypes.byref(p))) else None
    except (OSError, AttributeError):
        return None


def warp_pointer(x, y):
    """Leva o cursor do mouse pra (x, y) em pixel fisico da tela (o knob do dash: ARRASTO INFINITO sem o pointer
    lock do navegador, que mostra um aviso que nao da' pra esconder — o cursor some e volta pro lugar).
    Linux X11 (XWarpPointer) | Windows (SetCursorPos). Wayland/sem X: False (o arrasto so' fica finito)."""
    global _x11
    import ctypes
    try:
        if IS_WIN:
            return bool(_win_dpi(lambda u: u.SetCursorPos(int(x), int(y))))
        if os.environ.get('XDG_SESSION_TYPE') == 'wayland' or not os.environ.get('DISPLAY'):
            return False
        if _x11 is None:
            lib = ctypes.CDLL('libX11.so.6')
            lib.XOpenDisplay.restype = ctypes.c_void_p
            lib.XOpenDisplay.argtypes = [ctypes.c_char_p]
            lib.XDefaultRootWindow.restype = ctypes.c_ulong
            lib.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
            lib.XWarpPointer.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong] + [ctypes.c_int] * 2 + \
                [ctypes.c_uint] * 2 + [ctypes.c_int] * 2
            lib.XFlush.argtypes = [ctypes.c_void_p]
            dpy = lib.XOpenDisplay(None)
            if not dpy:
                return False
            _x11 = (lib, dpy)
        lib, dpy = _x11
        lib.XWarpPointer(dpy, 0, lib.XDefaultRootWindow(dpy), 0, 0, 0, 0, int(x), int(y))
        lib.XFlush(dpy)
        return True
    except (OSError, AttributeError):
        return False


FFMPEG_SIG = ('-fflags', 'nobuffer')   # todo ffmpeg de fonte do prisma leva isso (_FAST_IN no native)


def reap_orphans():
    """Linux: mata ffmpeg de fonte ORFAO (pai = init) que um prisma anterior deixou — ele segura a
    camera (v4l2 e' exclusivo) e ela some em TODO app. Reconhece pela assinatura (ffmpeg com
    `-fflags nobuffer` saindo rawvideo no stdout), do mesmo usuario. SIGKILL: o travado ignora TERM.
    Devolve os pids mortos."""
    if IS_WIN or not os.path.isdir('/proc'):
        return []
    out, uid = [], os.getuid()
    for pid in filter(str.isdigit, os.listdir('/proc')):
        try:
            if os.stat('/proc/' + pid).st_uid != uid:
                continue
            with open(f'/proc/{pid}/cmdline', 'rb') as f:
                a = f.read().decode(errors='replace').split('\0')
            with open(f'/proc/{pid}/stat') as f:
                ppid = int(f.read().rsplit(')', 1)[1].split()[1])
            if ppid != 1:   # orfao vira filho do init OU de um subreaper (systemd --user)
                with open(f'/proc/{ppid}/comm') as f:
                    ppid = 1 if f.read().strip() == 'systemd' else ppid
        except (OSError, ValueError, IndexError):
            continue
        if ppid == 1 and a and os.path.basename(a[0]) == 'ffmpeg' and _is_source_ffmpeg(a):
            try:
                os.kill(int(pid), 9)
                out.append(int(pid))
            except OSError:
                pass
    return out


def _is_source_ffmpeg(a):
    s = ' '.join(a)
    return ' '.join(FFMPEG_SIG) in s and '-f rawvideo -' in s + ' '


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


def keep_on_top(wid):
    """Janela SEMPRE NO TOPO (saida "por cima do PRISMA"): wid = pygame.display.get_wm_info()['window'] (X11: id; Windows:
    HWND). Linux = _NET_WM_STATE_ABOVE pelo wmctrl (sem wmctrl: nada); Windows = HWND_TOPMOST. Devolve True se pediu."""
    if not wid:
        return False
    if IS_WIN:
        import ctypes
        return bool(ctypes.windll.user32.SetWindowPos(int(wid), -1, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0010))   # NOSIZE|NOMOVE|NOACTIVATE
    try:
        subprocess.run(['wmctrl', '-i', '-r', hex(int(wid)), '-b', 'add,above'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2)
        return True
    except (OSError, subprocess.TimeoutExpired):
        return False


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
    return [d for d in sorted(glob.glob('/dev/video*')) if d not in _vcam_busy and _v4l2_captures(d)]


def _v4l2_captures(dev):
    """O no' entrega VIDEO? Webcam UVC cria 2 nos (/dev/video0 = imagem, /dev/video1 = metadados):
    o de metadados abre no ffmpeg e nunca da' frame. VIDIOC_QUERYCAP -> device_caps tem
    VIDEO_CAPTURE (0x1) ou _MPLANE (0x1000). Nao deu pra perguntar (permissao): fica na lista."""
    import fcntl
    try:
        fd = os.open(dev, os.O_RDWR | os.O_NONBLOCK)
    except OSError:
        return True
    try:
        buf = bytearray(104)                        # struct v4l2_capability
        fcntl.ioctl(fd, 0x80685600, buf)            # VIDIOC_QUERYCAP (funciona com a camera em uso)
        caps = int.from_bytes(buf[84:88], 'little')
        dcaps = int.from_bytes(buf[88:92], 'little') if caps & 0x80000000 else caps   # DEVICE_CAPS
        return bool(dcaps & 0x1001)
    except OSError:
        return True
    finally:
        os.close(fd)


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


# ---------------------------------------------------------------- webcam virtual (a SAIDA como camera)

_vcam_busy = set()   # no' que o prisma esta' escrevendo agora: fora do list_cams (senao vira fonte de si mesmo)

VCAM_HELP = ('webcam virtual: carregue o v4l2loopback — sudo apt install v4l2loopback-dkms && '
             'sudo modprobe v4l2loopback devices=1 exclusive_caps=1 card_label=PRISMA')
VCAM_HELP_WIN = 'webcam virtual: instale o OBS Studio (a camera virtual dele recebe a imagem)'


def vcam_devices():
    """Linux: nos do v4l2loopback (virtuais, sem hardware: /sys/devices/virtual/video4linux), o de
    card_label PRISMA primeiro. Windows: [] (o pyvirtualcam acha a camera do OBS sozinho)."""
    if IS_WIN:
        return []
    import glob
    out = []
    for d in sorted(glob.glob('/sys/class/video4linux/video*'), key=lambda p: int(re.sub(r'\D', '', p) or 0)):
        if '/virtual/' not in os.path.realpath(d):
            continue
        try:
            name = open(os.path.join(d, 'name'), encoding='utf-8', errors='replace').read().strip()
        except OSError:
            name = ''
        out.append(('/dev/' + os.path.basename(d), name))
    out.sort(key=lambda dn: 'prisma' not in dn[1].lower())
    return out


def vcam_cmd(dev, w, h, fps):
    """ffmpeg: rgb24 topo->baixo no stdin -> no' v4l2loopback (yuv420p = o que Chrome/Zoom/OBS leem)."""
    return ['ffmpeg', '-loglevel', 'error', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', f'{w}x{h}',
            '-r', str(fps), '-i', '-', '-f', 'v4l2', '-pix_fmt', 'yuv420p', dev]


class VCam:
    """A saida como webcam. send(bytes rgb24 h x w topo->baixo) por quadro; close(). Linux: ffmpeg no
    v4l2loopback (criar de THREAD LONGA: child_cmd/pdeathsig); Windows: pyvirtualcam (camera do OBS).
    Sem o que precisa: RuntimeError com o que instalar. .dev = nome pra mostrar."""

    def __init__(self, w, h, fps):
        self.w, self.h, self.p, self.cam = w, h, None, None
        if IS_WIN:
            try:
                import pyvirtualcam
            except ImportError:
                raise RuntimeError(VCAM_HELP_WIN)
            try:
                self.cam = pyvirtualcam.Camera(w, h, fps, fmt=pyvirtualcam.PixelFormat.RGB)
            except Exception as e:
                raise RuntimeError(f'{VCAM_HELP_WIN} ({e})')
            self.dev = self.cam.device
            return
        devs = vcam_devices()
        if not devs:
            raise RuntimeError(VCAM_HELP)
        if not shutil.which('ffmpeg'):
            raise RuntimeError('webcam virtual: falta o ffmpeg')
        self.dev = devs[0][0]
        self.p = subprocess.Popen(child_cmd(vcam_cmd(self.dev, w, h, fps)), stdin=subprocess.PIPE,
                                  stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        _vcam_busy.add(self.dev)

    def send(self, rgb):
        if self.cam is not None:
            self.cam.send(np.frombuffer(rgb, np.uint8).reshape(self.h, self.w, 3))
            return
        if self.p.poll() is not None:
            err = (self.p.stderr.read() or b'').decode(errors='replace').strip().splitlines()
            raise RuntimeError(f'webcam virtual ({self.dev}): ' + (err[-1] if err else 'ffmpeg saiu'))
        self.p.stdin.write(rgb)

    def close(self):
        if self.cam is not None:
            try:
                self.cam.close()
            except Exception:
                pass
            return
        _vcam_busy.discard(self.dev)
        try:
            self.p.stdin.close()
        except OSError:
            pass
        try:
            self.p.wait(timeout=2)
        except subprocess.TimeoutExpired:
            self.p.kill()


_dda_ok = {}   # (output_idx, w, h) -> o ddagrab capturou 1 frame desse monitor inteiro


def _dda_spec(r, mons):
    """ddagrab (Desktop Duplication, GPU — o que o OBS usa) pro retangulo r, ou None se r nao cabe
    num monitor so'. Offset e' relativo ao monitor. ponytail: output_idx = ordem do
    EnumDisplayMonitors (o DXGI costuma bater; o teste de 1 frame confere o tamanho e pega o
    descasamento quando os monitores diferem) e so' a placa padrao — outro caso cai no gdigrab."""
    for i, m in enumerate(mons):
        x, y = r['x'] - m['x'], r['y'] - m['y']
        if 0 <= x and 0 <= y and x + r['w'] <= m['w'] and y + r['h'] <= m['h']:
            return i, m, (f"ddagrab=output_idx={i}:framerate=30:offset_x={x}:offset_y={y}"
                          f":video_size={r['w']}x{r['h']},hwdownload,format=bgra")
    return None


def screen_input_args(r):
    """Args de ENTRADA do ffmpeg pra um retangulo da tela r = {x, y, w, h}. Windows: ddagrab
    (GPU, aguenta 1080p30 e janela acelerada) quando o teste passa; senao gdigrab (GDI, CPU)."""
    if IS_WIN:
        d = _dda_spec(r, _win_monitors())
        if d:
            i, m, spec = d
            k = (i, m['w'], m['h'])
            if k not in _dda_ok:
                try:
                    _dda_ok[k] = len(subprocess.run(   # 1 frame BGRA do monitor inteiro = tamanho dele?
                        ['ffmpeg', '-loglevel', 'error', '-f', 'lavfi', '-i', f"ddagrab=output_idx={i},hwdownload,format=bgra",
                         '-frames:v', '1', '-f', 'rawvideo', '-'],
                        capture_output=True, timeout=5).stdout) == m['w'] * m['h'] * 4
                except (OSError, subprocess.TimeoutExpired):
                    _dda_ok[k] = False
            if _dda_ok[k]:
                return ['-f', 'lavfi', '-i', spec]
        return ['-f', 'gdigrab', '-framerate', '30', '-offset_x', str(r['x']), '-offset_y', str(r['y']),
                '-video_size', f"{r['w']}x{r['h']}", '-i', 'desktop']
    display = os.environ.get('DISPLAY', ':0') + f"+{r['x']},{r['y']}"
    return ['-f', 'x11grab', '-framerate', '30', '-video_size', f"{r['w']}x{r['h']}", '-i', display]


_VAAPI = ['-hwaccel', 'vaapi', '-hwaccel_output_format', 'vaapi']
_hw_ok = {}   # arquivo -> a GPU decodificou 1 frame dele (testa 1x por arquivo)


def hw_decode(path, vf):
    """(args de ENTRADA, -vf) pra decodificar um VIDEO na GPU: Linux com VAAPI = decode e
    escala la, so' o frame ja pequeno volta pra CPU (1080p60 em software come ~2.5 nucleos).
    Testa 1 frame do arquivo antes (codec que a GPU nao tem = erro); falhou = ([], vf) igual
    antes. ponytail: Windows fica no software — d3d11va quando alguem medir la."""
    head, _, rest = vf.partition(',')
    if IS_WIN or not head.startswith('scale=') or not os.path.exists('/dev/dri/renderD128'):
        return [], vf
    gvf = f'scale_vaapi={head[6:]},hwdownload,format=nv12' + (',' + rest if rest else '')
    if path not in _hw_ok:
        try:
            _hw_ok[path] = subprocess.run(
                ['ffmpeg', '-loglevel', 'error', *_VAAPI, '-i', path, '-frames:v', '1', '-vf', gvf, '-f', 'null', '-'],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5).returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            _hw_ok[path] = False
    return (_VAAPI, gvf) if _hw_ok[path] else ([], vf)


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
            rs, lock, last = Resampler(rate, AUDIO_RATE), threading.Lock(), [time.monotonic()]

            def put(y):
                if len(y):
                    os.write(self._w, np.clip(y, -32768, 32767).astype(np.int16).tobytes())

            # CALLBACK (como o exemplo de loopback do PyAudioWPatch): o PortAudio entrega cada pacote.
            # O modo bloqueante com get_read_available nao e' confiavel no loopback WASAPI (podia
            # ficar em 0 pra sempre = silencio eterno com musica tocando).
            def cb(data, frames, tinfo, status):
                try:
                    with lock:
                        put(rs.process(np.frombuffer(data, np.int16).reshape(-1, ch).mean(axis=1)))
                        last[0] = time.monotonic()
                except Exception as e:                      # noqa: BLE001 — pipe fechado = parando
                    self.errf.write(str(e).encode(errors='ignore'))
                    return None, pa.paAbort
                return None, pa.paContinue

            st = p.open(format=pa.paInt16, channels=ch, rate=rate, input=True,
                        input_device_index=info['index'], frames_per_buffer=512, stream_callback=cb)
            st.start_stream()
            while not self._stop.is_set() and st.is_active():
                time.sleep(0.05)
                with lock:                                  # nada tocando: o loopback cala -> silencio
                    now = time.monotonic()
                    if now - last[0] >= 0.1:
                        put(np.zeros(int((now - last[0]) * AUDIO_RATE), np.float32))
                        last[0] = now
            if not self._stop.is_set():
                self.errf.write(b'captura WASAPI parou sozinha')
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
    vc = vcam_cmd('/dev/video9', 1280, 720, 30)
    assert vc[-1] == '/dev/video9' and '1280x720' in vc and not _is_source_ffmpeg(vc), 'webcam virtual nao e\' fonte orfa'
    assert isinstance(vcam_devices(), list)
    assert IS_WIN or pointer_pos() is None, 'cursor: Linux = None (o dash usa a conta de sempre)'
    if _SETPRIV:   # filho morre junto: pai morto com kill -9 -> o "ffmpeg" (sleep) recebe TERM
        _pai = subprocess.Popen([sys.executable, '-c', 'import subprocess,sys,time;'
                                 f'p=subprocess.Popen({child_cmd(["sleep", "30"])!r});print(p.pid,flush=True);time.sleep(30)'],
                                stdout=subprocess.PIPE, text=True)
        _filho = int(_pai.stdout.readline())
        for _ in range(100):   # so' mata o pai DEPOIS do setpriv armar o pdeathsig e virar o sleep (antes = corrida: o sinal
            try:               # nunca chega; foi o que derrubava o CI de vez em quando)
                with open(f'/proc/{_filho}/comm') as f:
                    if f.read().strip() == 'sleep':
                        break
            except OSError:
                break
            time.sleep(0.02)
        _pai.kill(); _pai.wait()
        def _vivo(pid):   # ZUMBI conta como morto: no CI ninguem recolhe o filho na hora e o kill(pid, 0) ainda acha ele
            try:
                with open(f'/proc/{pid}/stat') as f:
                    return f.read().rsplit(')', 1)[1].split()[0] != 'Z'
            except (OSError, IndexError):
                return False
        for _ in range(100):
            if not _vivo(_filho):
                break
            time.sleep(0.05)
        else:
            raise AssertionError('filho sobreviveu ao pai (pdeathsig)')
    if not IS_WIN:   # orfao com a assinatura morre; ffmpeg alheio (sem assinatura) fica
        assert _is_source_ffmpeg(['ffmpeg', '-loglevel', 'error', *FFMPEG_SIG, '-i', '/dev/video0', '-f', 'rawvideo', '-'])
        assert not _is_source_ffmpeg(['ffmpeg', '-i', 'a.mp4', 'b.mp4'])
        def _orfao(args):   # neto que vira orfao (o filho sai na hora); argv[0] = 'ffmpeg'
            r = subprocess.run([sys.executable, '-c', 'import os,sys\nif os.fork()==0:\n os.setsid()\n'
                                f' os.execv(sys.executable, {["ffmpeg", "-c", "import time; time.sleep(20)", *args]!r})\n'
                                'print(os.getpid())'], capture_output=True, text=True)
            time.sleep(0.4)
            for pid in filter(str.isdigit, os.listdir('/proc')):
                try:
                    with open(f'/proc/{pid}/cmdline', 'rb') as f:
                        if f.read().split(b'\0')[1:3] == [b'-c', b'import time; time.sleep(20)'] and \
                                args[-1].encode() in open(f'/proc/{pid}/cmdline', 'rb').read():
                            return int(pid)
                except (OSError, IndexError):
                    pass
        _sig, _alheio = _orfao([*FFMPEG_SIG, '-f', 'rawvideo', '-', 'sig']), _orfao(['-i', 'x', 'alheio'])
        try:
            if _sig and _alheio:
                mortos = reap_orphans()
                _subreaper = _sig not in mortos   # pai adotivo nao e' init/systemd (ex.: container do CI): pula
                assert _subreaper or _alheio not in mortos
        finally:
            for _p in (_sig, _alheio):
                try:
                    os.kill(_p, 9)
                except (OSError, TypeError):
                    pass
    assert screen_input_args({'x': 10, 'y': 0, 'w': 100, 'h': 50})[-1].endswith('+10,0') or IS_WIN
    ms = [{'x': 0, 'y': 0, 'w': 1920, 'h': 1080}, {'x': 1920, 'y': 0, 'w': 1280, 'h': 720}]
    i, _, s = _dda_spec({'x': 2020, 'y': 10, 'w': 640, 'h': 360}, ms)
    assert i == 1 and 'offset_x=100:offset_y=10:video_size=640x360' in s, s     # relativo ao monitor 2
    assert _dda_spec({'x': 1800, 'y': 0, 'w': 400, 'h': 100}, ms) is None       # cruza 2 monitores -> gdigrab
    assert hw_decode('/nao/existe.mp4', 'scale=640:480,setsar=1') == ([], 'scale=640:480,setsar=1')   # falhou = software
    if not IS_WIN and os.environ.get('DISPLAY') and shutil.which('xrandr'):   # CI sem X: pula
        assert 'connected' in outputs_text()
    print('plat self-check ok')
