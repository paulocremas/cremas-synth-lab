"""Servidor do dashboard HTML — substitui (em paralelo) os dashes de terminal por uma
pagina interativa. Stdlib pura: http.server + SSE, sem dependencia nova.

Duas direcoes:
  - numeros SAINDO  : GET /events  -> stream text/event-stream com o `state` do synth
  - knobs ENTRANDO  : POST /knob   -> reescreve a linha em tuning.py; o hot-reload por
                      mtime do audio_thread aplica em <=1 chunk (~23ms), sem code path novo

O write-back e literalmente "editar tuning.py como o Paulo edita, so que por slider" — por
isso a posicao do knob persiste entre execucoes de graca. MIDI/potenciometro fisico depois
e so mais um chamador de set_knob().
"""
import json
import os
import re
import threading
import time
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

_HERE = os.path.dirname(os.path.abspath(__file__))
_HTML = os.path.join(_HERE, 'dash.html')
_FAVICON = os.path.join(_HERE, 'favicon.png')  # copia do de paulocremas.github.io
_DEFAULT_TUNING = os.path.join(_HERE, 'tuning.py')

# knobs "ao vivo" — os fixos que controlam a DINAMICA (ver explicacao no README/CLAUDE.md).
# min/max = trilho do slider e clamp do POST; step so afeta o slider. group = secao na UI.
KNOBS = [
    {"name": "KICK_THRESHOLD",      "min": 1.0,  "max": 3.0,    "step": 0.05,   "group": "kick",     "label": "threshold (x baseline)"},
    {"name": "KICK_DECAY_FRACTION", "min": 0.3,  "max": 1.0,    "step": 0.05,   "group": "kick",     "label": "pulso / intervalo"},
    {"name": "KICK_DECAY_MIN",      "min": 0.3,  "max": 0.9,    "step": 0.01,   "group": "kick",     "label": "decay min (rapido)"},
    {"name": "KICK_DECAY_MAX",      "min": 0.8,  "max": 0.99,   "step": 0.01,   "group": "kick",     "label": "decay max (lento)"},
    {"name": "ATTACK_RATIO",        "min": 0.05, "max": 1.0,    "step": 0.05,   "group": "smooth",   "label": "attack / release (1 = sem soco)"},
    {"name": "SMOOTHING",           "min": 0.5,  "max": 0.99,   "step": 0.01,   "group": "smooth",   "label": "global (amp/bass/mid/treble)"},
    {"name": "SMOOTHING_MIN",       "min": 0.5,  "max": 0.95,   "step": 0.01,   "group": "smooth",   "label": "release grave (Sub-bass)"},
    {"name": "SMOOTHING_MAX",       "min": 0.7,  "max": 0.99,   "step": 0.01,   "group": "smooth",   "label": "release agudo (Air)"},
    {"name": "PEAK_DECAY",          "min": 0.99, "max": 0.9999, "step": 0.0001, "group": "autogain", "label": "memoria do teto (auto-gain)"},
    {"name": "BASS_SCALE",          "min": 0.01, "max": 1.0,    "step": 0.01,   "group": "scale",    "label": "bass x"},
    {"name": "MID_SCALE",           "min": 0.5,  "max": 20.0,   "step": 0.5,    "group": "scale",    "label": "mid x"},
    {"name": "TREBLE_SCALE",        "min": 1.0,  "max": 80.0,   "step": 1.0,    "group": "scale",    "label": "treble x"},
    {"name": "BASS_MID_HZ",         "min": 50,   "max": 500,    "step": 10,     "group": "scale",    "label": "corte bass|mid (Hz)",    "int": True},
    {"name": "MID_TREBLE_HZ",       "min": 1000, "max": 8000,   "step": 100,    "group": "scale",    "label": "corte mid|treble (Hz)",  "int": True},
]
_SPEC = {k["name"]: k for k in KNOBS}

# range de mixagem das 8 faixas finas — editado pela secao "Ranges das faixas" do dash (nao e
# um knob-slider comum, e um endpoint proprio /bands que reescreve o bloco FREQ_BAND_HZ inteiro).
_BAND_NAMES = ['Sub-bass', 'Low-mid', 'Midrange', 'High-mid', 'Presence', 'Treble', 'Brilliance', 'Air']
_HZ_MIN, _HZ_MAX = 20, 20000
_MAX_CHAN = 8  # teto (nao tamanho fixo) — tuning.CHANNELS e lista livre, add/remove no dash
_knob_lock = threading.Lock()  # serializa read-modify-write do tuning.py (set_knob + set_band_ranges)

_state = {}
_tuning = None
_cfg = {'is_running': lambda: True, 'audio_source': '', 'video_mode': '', 'tuning_path': _DEFAULT_TUNING,
        'on_inputs': None, 'on_set_input': None, 'on_set_output': None}  # callbacks (native_synth)


def set_knob(name, value, tuning_path=None):
    """Reescreve `NAME = <numero>` em tuning.py preservando o comentario da linha. Devolve o
    valor efetivamente gravado (ja clampado ao [min,max] do spec). Levanta KeyError se o nome
    nao for um knob conhecido ou nao existir no arquivo."""
    spec = _SPEC.get(name)
    if spec is None:
        raise KeyError(name)
    value = max(spec['min'], min(spec['max'], float(value)))
    literal = str(int(round(value))) if spec.get('int') else str(round(value, 4))
    path = tuning_path or _cfg['tuning_path']
    with _knob_lock:
        src = open(path).read()
        new, n = re.subn(rf'(?m)^({re.escape(name)} = )[-\d.eE+]+', rf'\g<1>{literal}', src)
        if n != 1:
            raise KeyError(f'{name}: {n} ocorrencias em {path} (esperava 1)')
        open(path, 'w').write(new)
    return value


def _clamp_ranges(overlap, ranges):
    """8 pares [lo, hi] -> versao consistente. Sempre: int, dentro de [20, 20000], lo < hi.
    overlap=1: cada faixa independente (podem se sobrepor). overlap=0 (crossover): faixas
    ordenadas e SEM sobreposicao (band[k].lo >= band[k-1].hi), mas BURACOS sao permitidos
    (band[k].lo pode ser > band[k-1].hi -> essas frequencias nao entram em nenhuma faixa)."""
    r = [[int(round(float(lo))), int(round(float(hi)))] for lo, hi in ranges[:8]]
    r = [[max(_HZ_MIN, min(_HZ_MAX, lo)), max(_HZ_MIN, min(_HZ_MAX, hi))] for lo, hi in r]
    if overlap:
        return [[lo, max(lo + 1, min(_HZ_MAX, hi))] for lo, hi in r]
    out, prev_hi = [], _HZ_MIN
    for lo, hi in r:
        lo = max(lo, prev_hi)               # nao invade a faixa anterior (buraco ok)
        hi = min(max(hi, lo + 1), _HZ_MAX)  # lo < hi, dentro do teto
        lo = min(lo, hi - 1)
        out.append([lo, hi])
        prev_hi = hi
    return out


def set_band_ranges(overlap, ranges, tuning_path=None, enabled=None):
    """Reescreve HZ_OVERLAP e o bloco FREQ_BAND_HZ inteiro em tuning.py; se `enabled` nao for
    None, tambem reescreve BANDS_ENABLED (checkbox "ativar" no dash — 0 silencia u_subbass..
    u_air no shader, sem apagar as ranges). Devolve {'overlap','ranges','enabled'} ja normalizado."""
    overlap = 1 if overlap else 0
    ranges = _clamp_ranges(overlap, ranges)
    body = '\n'.join(f'    [{lo}, {hi}],  # {name}' for (lo, hi), name in zip(ranges, _BAND_NAMES))
    block = f'FREQ_BAND_HZ = [\n{body}\n]'
    path = tuning_path or _cfg['tuning_path']
    with _knob_lock:
        src = open(path).read()
        src, n1 = re.subn(r'(?m)^HZ_OVERLAP = [01]', f'HZ_OVERLAP = {overlap}', src)
        src, n2 = re.subn(r'(?ms)^FREQ_BAND_HZ = \[.*?^\]', block, src)
        if n1 != 1 or n2 != 1:
            raise KeyError(f'tuning.py: HZ_OVERLAP x{n1}, FREQ_BAND_HZ x{n2} (esperava 1 cada)')
        if enabled is not None:
            enabled = 1 if enabled else 0
            src, n3 = re.subn(r'(?m)^BANDS_ENABLED = [01]', f'BANDS_ENABLED = {enabled}', src)
            if n3 != 1:
                raise KeyError(f'tuning.py: BANDS_ENABLED x{n3} (esperava 1)')
        open(path, 'w').write(src)
    out = {'overlap': overlap, 'ranges': ranges}
    if enabled is not None:
        out['enabled'] = enabled
    return out


def set_channels(channels, tuning_path=None):
    """Reescreve o bloco CHANNELS inteiro em tuning.py. `channels`: 0.._MAX_CHAN
    {"name","src","output"} — lista de TAMANHO LIVRE (add/remove pelo dash, sem slot fixo).
    "src": id de source do PulseAudio ou "" (canal ocioso). "output": nome de uma variavel
    existente (kick/amp/bass/mid/treble/subbass/.../air) que esse canal passa a alimentar
    ENQUANTO tiver src bound, ou "" (so aparece no array u_chan/u_chan_hit). Devolve a lista
    normalizada, no tamanho que veio (ate o teto)."""
    ch = [{'name': str(c.get('name', ''))[:24], 'src': str(c.get('src', '')),
           'output': str(c.get('output', ''))} for c in channels[:_MAX_CHAN]]
    body = '\n'.join('    ' + json.dumps(c) + ',' for c in ch)
    block = f'CHANNELS = [\n{body}\n]' if ch else 'CHANNELS = [\n]'
    path = tuning_path or _cfg['tuning_path']
    with _knob_lock:
        src = open(path).read()
        src, n = re.subn(r'(?ms)^CHANNELS = \[.*?^\]', block, src)
        if n != 1:
            raise KeyError(f'tuning.py: CHANNELS x{n} (esperava 1)')
        open(path, 'w').write(src)
    return ch


def _read_knobs():
    return {k['name']: getattr(_tuning, k['name']) for k in KNOBS}


def _payload():
    return {
        'audio': _state.get('audio_dash', {}),   # kick / bands / spectrum — ver dash_data.audio_dash_data
        'image': _state.get('image', {}),
        'dominant': [round(c, 3) for c in _state.get('dominant', (0.0, 0.0, 0.0))],
        'knobs': _read_knobs(),
        'audio_source': _state.get('audio_source') or _cfg['audio_source'],  # muda ao vivo via set_input
        'video_mode': _state.get('video_label') or _cfg['video_mode'],
        # ids no formato das opcoes dos <select> — pro dash sincronizar os dropdowns entre abas
        'inputs': {'audio': _state.get('audio_source', ''), 'video': _state.get('video_id', '')},
        'output': _state.get('output', {}),   # geometria/fps da janela de saida (imagem sintetizada)
        'bands_hz': {'overlap': int(getattr(_tuning, 'HZ_OVERLAP', 0)),
                     'enabled': int(getattr(_tuning, 'BANDS_ENABLED', 1)),
                     'ranges': [list(x) for x in getattr(_tuning, 'FREQ_BAND_HZ', [])],
                     'names': _BAND_NAMES},
        # canais por instrumento (lista de tamanho livre, ver tuning.CHANNELS) — paralelo as
        # bands_hz acima. levels/hits vem de state['chan'/'chan_hit'] (tamanho fixo _MAX_CHAN
        # no Python) cortado pro tamanho de CHANNELS de verdade.
        'channels': {
            'names': [c.get('name', '') for c in getattr(_tuning, 'CHANNELS', [])],
            'srcs': [c.get('src', '') for c in getattr(_tuning, 'CHANNELS', [])],
            'outputs': [c.get('output', '') for c in getattr(_tuning, 'CHANNELS', [])],
            'levels': [round(v, 3) for v in _state.get('chan', [])[:len(getattr(_tuning, 'CHANNELS', []))]],
            'hits': [round(v, 3) for v in _state.get('chan_hit', [])[:len(getattr(_tuning, 'CHANNELS', []))]],
        },
        'html_mtime': os.path.getmtime(_HTML),   # cliente recarrega a aba quando muda
    }


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass  # sem spam de request no stdout do synth

    def _send(self, code, ctype, body):
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split('?')[0]
        if path in ('/', '/dash.html'):
            self._send(200, 'text/html; charset=utf-8', open(_HTML, 'rb').read())
        elif path in ('/favicon.png', '/favicon.ico'):  # navegador tambem sonda /favicon.ico
            try:
                self._send(200, 'image/png', open(_FAVICON, 'rb').read())
            except FileNotFoundError:
                self._send(404, 'text/plain', b'nope')
        elif path == '/knobs':
            self._send(200, 'application/json', json.dumps(KNOBS).encode())
        elif path == '/inputs':
            fn = _cfg.get('on_inputs')
            self._send(200, 'application/json', json.dumps(fn() if fn else {}).encode())
        elif path == '/events':
            self._sse()
        else:
            self._send(404, 'text/plain', b'nope')

    def _sse(self):
        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream')
        self.send_header('Cache-Control', 'no-cache')
        self.end_headers()
        try:
            # `self.server is _cfg['srv']` deixa de bater quando um hot-reload troca o servidor
            # -> este loop sai, o EventSource do browser cai e reconecta sozinho no novo.
            while _cfg['is_running']() and self.server is _cfg.get('srv'):
                self.wfile.write(b'data: ' + json.dumps(_payload()).encode() + b'\n\n')
                self.wfile.flush()
                time.sleep(0.05)  # 20 Hz — o dado novo vem a ~14 Hz (DASH_EVERY_N_CHUNKS)
        except (BrokenPipeError, ConnectionResetError):
            pass  # aba fechou

    def do_POST(self):
        path = self.path.split('?')[0]
        length = int(self.headers.get('Content-Length', 0))
        raw = self.rfile.read(length)
        if path == '/bands':
            try:
                b = json.loads(raw.decode())
                out = set_band_ranges(b.get('overlap'), b['ranges'], enabled=b.get('enabled'))
                self._send(200, 'application/json', json.dumps(out).encode())
            except (KeyError, ValueError, TypeError) as e:
                self._send(400, 'text/plain', str(e).encode())
            return
        if path == '/channels':
            try:
                b = json.loads(raw.decode())
                out = set_channels(b['channels'])
                self._send(200, 'application/json', json.dumps(out).encode())
            except (KeyError, ValueError, TypeError) as e:
                self._send(400, 'text/plain', str(e).encode())
            return
        if path == '/output':
            fn = _cfg.get('on_set_output')
            try:
                fn(json.loads(raw.decode()))
                self._send(200, 'application/json', b'{"ok":true}')
            except (KeyError, ValueError, TypeError) as e:
                self._send(400, 'text/plain', str(e).encode())
            return
        q = urllib.parse.parse_qs(raw.decode())
        if path == '/knob':
            try:
                v = set_knob(q['name'][0], q['value'][0])
                self._send(200, 'application/json', json.dumps({'value': v}).encode())
            except (KeyError, ValueError, IndexError) as e:
                self._send(400, 'text/plain', str(e).encode())
        elif path == '/input':
            fn = _cfg.get('on_set_input')
            try:
                fn(q['kind'][0], q['id'][0])
                self._send(200, 'application/json', b'{"ok":true}')
            except (KeyError, ValueError, IndexError, TypeError) as e:
                self._send(400, 'text/plain', str(e).encode())
        else:
            self._send(404, 'text/plain', b'nope')


def stop():
    """Derruba o servidor atual (usado antes de um hot-reload). shutdown() precisa vir de
    outro thread que nao o do serve_forever — e o caso: quem chama e o audio_thread."""
    srv = _cfg.pop('srv', None)
    if srv is not None:
        srv.shutdown()
        srv.server_close()


def start(state, tuning_mod, tuning_path, is_running, audio_source='', video_mode='',
          port=8765, open_browser=True, on_inputs=None, on_set_input=None, on_set_output=None):
    """Sobe o servidor num thread daemon. Degrada sem travar o synth se a porta estiver ocupada.
    open_browser=False num hot-reload pra nao reabrir as abas. on_inputs/on_set_input = callbacks
    do native_synth pra listar/trocar entrada de audio e video. on_set_output = pedido de troca
    da janela de SAIDA (monitor/tela cheia/dimensao — barra "saida" no topo do dash)."""
    global _state, _tuning
    _state, _tuning = state, tuning_mod
    _cfg.update(is_running=is_running, audio_source=audio_source, video_mode=video_mode,
                tuning_path=tuning_path, on_inputs=on_inputs, on_set_input=on_set_input,
                on_set_output=on_set_output)
    try:
        srv = ThreadingHTTPServer(('127.0.0.1', port), _Handler)
    except OSError as e:
        print(f'dash desligado (porta {port}: {e})')
        return
    srv.daemon_threads = True
    _cfg['srv'] = srv  # o handler do SSE compara com isso pra sair quando um reload troca o srv
    # poll_interval curto: stop() (shutdown) volta em ~0.1s em vez de 0.5s -> hot-reload sem glitch
    threading.Thread(target=lambda: srv.serve_forever(poll_interval=0.1), daemon=True).start()
    url = f'http://127.0.0.1:{port}'
    print(f'dash: {url}  (?panel=audio | ?panel=image)')
    if open_browser:
        try:  # abre uma aba pra audio e outra pra imagem; nao-fatal se nao houver navegador
            webbrowser.open(f'{url}/?panel=audio', new=2)
            webbrowser.open(f'{url}/?panel=image', new=2)
        except webbrowser.Error:
            pass


if __name__ == '__main__':  # self-check do parser de linha (roda: python dash_server.py)
    import tempfile
    p = tempfile.mktemp(suffix='.py')
    open(p, 'w').write('KICK_THRESHOLD = 1.5      # grave cru passa X vezes a media\n'
                       'MID_TREBLE_HZ = 4000\n')
    assert set_knob('KICK_THRESHOLD', 2.0, p) == 2.0
    txt = open(p).read()
    assert 'KICK_THRESHOLD = 2.0 ' in txt, txt
    assert '# grave cru passa X vezes a media' in txt, 'comentario perdido'
    assert set_knob('KICK_THRESHOLD', 99, p) == _SPEC['KICK_THRESHOLD']['max'], 'sem clamp'
    set_knob('MID_TREBLE_HZ', 3000.4, p)
    assert 'MID_TREBLE_HZ = 3000\n' in open(p).read(), 'int knob deve ficar inteiro'
    try:
        set_knob('NOPE', 1, p)
        assert False, 'aceitou nome desconhecido'
    except KeyError:
        pass

    # --- band ranges ---
    default = [[20, 250], [250, 500], [500, 2000], [2000, 4000],
              [4000, 6000], [6000, 10000], [10000, 16000], [16000, 20000]]
    # crossover: sem sobreposicao (empurra o lo do vizinho), mas mantem o buraco
    fixed = _clamp_ranges(0, [[20, 469], [90, 800]] + default[2:])
    assert fixed[0] == [20, 469], fixed                                  # respeitado
    assert fixed[1][0] == 469, fixed                                     # lo empurrado (nao invade)
    assert fixed[1] == [469, 800], fixed
    assert all(fixed[i][1] <= fixed[i + 1][0] for i in range(7)), fixed  # nao sobrepoe
    assert all(fixed[i][0] < fixed[i][1] for i in range(8)), fixed       # lo<hi
    gap = _clamp_ranges(0, [[20, 100], [300, 500]] + default[2:])
    assert gap[0] == [20, 100] and gap[1] == [300, 500], gap             # BURACO 100..300 preservado
    # overlap: mantem sobreposicao
    ov = _clamp_ranges(1, [[39, 469], [200, 500]] + default[2:])
    assert ov[0] == [39, 469] and ov[1] == [200, 500], ov
    # escrita no arquivo
    open(p, 'w').write('HZ_OVERLAP = 0\nBANDS_ENABLED = 1\nFREQ_BAND_HZ = [\n    [20, 250],  # Sub-bass\n]\n')
    out = set_band_ranges(1, [[39, 469], [200, 500]] + default[2:], p, enabled=0)
    txt = open(p).read()
    assert out['overlap'] == 1 and out['enabled'] == 0 and 'HZ_OVERLAP = 1' in txt, txt
    assert 'BANDS_ENABLED = 0' in txt, txt
    assert '[39, 469],  # Sub-bass' in txt and '[200, 500],  # Low-mid' in txt, txt
    assert txt.count('FREQ_BAND_HZ = [') == 1 and txt.rstrip().endswith(']'), txt
    out2 = set_band_ranges(1, default, p)  # enabled=None (default) -> nao mexe na linha
    assert 'enabled' not in out2 and 'BANDS_ENABLED = 0' in open(p).read(), out2

    # --- channels: lista de tamanho livre, sem slot fixo ---
    open(p, 'w').write('CHANNELS = [\n    {"name": "kick", "src": "", "output": ""},\n]\n')
    outc = set_channels([{'name': 'bumbo', 'src': 'alsa_input.foo.monitor', 'output': 'kick'}], p)
    txt = open(p).read()
    assert outc == [{'name': 'bumbo', 'src': 'alsa_input.foo.monitor', 'output': 'kick'}], outc
    assert '"bumbo"' in txt and '"alsa_input.foo.monitor"' in txt and '"output": "kick"' in txt, txt
    assert txt.count('CHANNELS = [') == 1 and txt.rstrip().endswith(']'), txt
    outc2 = set_channels([], p)  # lista vazia -> volta a nao ter canal nenhum, sem erro
    assert outc2 == [] and 'CHANNELS = [\n]' in open(p).read(), (outc2, open(p).read())
    outc3 = set_channels([{'name': 'a', 'src': '', 'output': ''}], p)  # reescreve de novo, sem sobra
    assert len(outc3) == 1, outc3

    os.remove(p)
    print('dash_server self-check ok')
