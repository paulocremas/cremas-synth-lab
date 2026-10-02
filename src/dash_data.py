"""Funcoes puras que produzem os NUMEROS do dashboard (nao formatam terminal nem HTML).

Fonte unica de verdade do dash de audio: o audio_thread chama audio_dash_data() e publica
o dict em state['audio_dash']; tanto o dash de terminal quanto o payload HTTP so renderizam
esse mesmo dict. Sem import de native_synth (evita circular) — so numpy.
"""
import json
import os
import re
import tempfile

import numpy as np


def parse_fx_manifest(src):
    """Nomes dos potenciometros de efeito que um shader expoe, do comentario-cabecalho
    "// fx: nome1, nome2, ..." (aba Efeitos do dash). Sem essa linha -> []. Cada nome vira
    o uniform u_fx_<nome> no GLSL (0..1, 1.0 = cheio) e um slider no dash. "nome=0.5" da' o
    valor padrao do knob (ver parse_fx_defaults)."""
    return list(parse_fx_defaults(src))


def parse_fx_defaults(src):
    """{nome: padrao} do cabecalho "// fx: nome, nome=0.5, ..." — padrao = valor do knob
    enquanto a entrada da pilha nao tem forca gravada (e o do duplo-clique). Sem "=x" -> 1.0."""
    m = re.search(r'(?m)^//\s*fx:\s*(.+)$', src or '')
    out = {}
    for s in (m.group(1).split(',') if m else []):
        n, _, d = s.partition('=')
        if not n.strip():
            continue
        try:
            v = min(1.0, max(0.0, float(d))) if d.strip() else 1.0
        except ValueError:
            v = 1.0
        out[n.strip()] = v
    return out

# espelha FREQ_BANDS (native_synth.py) pro lado web/JSON — nome, [lo, hi] default, cor.
_FREQ_BANDS = [
    ('Sub-bass', 20, 250, (30, 140, 255)), ('Low-mid', 250, 500, (0, 200, 255)),
    ('Midrange', 500, 2000, (0, 230, 200)), ('High-mid', 2000, 4000, (140, 140, 255)),
    ('Presence', 4000, 6000, (190, 100, 255)), ('Treble', 6000, 10000, (225, 80, 255)),
    ('Brilliance', 10000, 16000, (255, 70, 210)), ('Air', 16000, 20000, (255, 110, 160)),
]
FREQ_BAND_RGB = {name: rgb for name, _, _, rgb in _FREQ_BANDS}
_GREY = (95, 95, 95)  # Hz que nao cai em nenhuma faixa (buraco no modo crossover)


def _band_rgb_for_hz(hz, lohi=None):
    """Cor da faixa de mixagem que contem esse Hz, ou cinza se nenhuma. `lohi` = [(lo, hi)]x8
    ao vivo (de native_synth.freq_bands); sem ele usa os defaults de _FREQ_BANDS."""
    pairs = lohi if lohi is not None else [(lo, hi) for _, lo, hi, _ in _FREQ_BANDS]
    for (lo, hi), (*_, rgb) in zip(pairs, _FREQ_BANDS):
        if lo <= hz < hi:
            return rgb
    return _GREY


def band_magnitudes(spectrum, freqs, bars):
    """`bars` faixas log (30Hz-Nyquist): (freq do topo, magnitude media bruta). Faixa mais
    estreita que a resolucao da FFT usa o bin mais proximo do centro (senao viraria 0/-120dB,
    artefato, nao silencio de verdade)."""
    edges = np.logspace(np.log10(30), np.log10(freqs[-1]), bars + 1)
    out = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        mask = (freqs >= lo) & (freqs < hi)
        mag = spectrum[mask].mean() if mask.any() else spectrum[np.argmin(np.abs(freqs - (lo + hi) / 2))]
        out.append((float(hi), float(mag)))
    return out


def audio_dash_data(bands_raw, amp_raw, amp_raw_level, amp_final, amp_smoothing,
                    kick_final, kick_decay, smooth_spectrum, freqs, bars=24, range_db=40.0,
                    band_lohi=None):
    """Monta o dict do dash de audio.

    bands_raw: 8 tuplas (nome, mag_bruta, nivel_bruto, final, smoothing) na ordem grave->agudo
    de FREQ_BANDS. 'bands' sai na ordem de exibicao do terminal: amp primeiro, depois agudo->grave.
    Cada linha tem raw_mag (magnitude crua, sem teto), raw_level (0..1 relativo ao pico da
    propria banda, sem suavizar), final (o que vai pro shader), smoothing (coef attack/release
    que valeu no chunk) e delta = |final - raw_level|.
    'spectrum': `bars` faixas log, agudo em cima, com db absoluto e rel (0..1, dB abaixo do
    pico do frame / range_db)."""
    rows = [{'name': 'amp', 'rgb': None, 'raw_mag': amp_raw, 'raw_level': amp_raw_level,
             'final': amp_final, 'smoothing': amp_smoothing,
             'delta': min(1.0, abs(amp_final - amp_raw_level))}]
    for name, mag, lvl, final, s in reversed(bands_raw):
        rows.append({'name': name, 'rgb': FREQ_BAND_RGB.get(name),
                     'raw_mag': float(mag), 'raw_level': float(lvl), 'final': float(final),
                     'smoothing': float(s), 'delta': min(1.0, abs(float(final) - float(lvl)))})

    mags = band_magnitudes(smooth_spectrum, freqs, bars)
    peak_db = 20.0 * np.log10(max(m for _, m in mags) + 1e-6)
    spectrum = []
    for hz, mag in reversed(mags):
        db = 20.0 * np.log10(mag + 1e-6)
        rel = float(np.clip((db - peak_db + range_db) / range_db, 0.0, 1.0))
        spectrum.append({'hz': int(round(hz)), 'db': round(float(db), 1), 'rel': round(rel, 3),
                         'rgb': _band_rgb_for_hz(hz, band_lohi)})

    return {
        'kick': {'final': round(float(kick_final), 4), 'decay': round(float(kick_decay), 4)},
        'bands': [{k: (round(v, 4) if isinstance(v, float) else v) for k, v in r.items()} for r in rows],
        'spectrum': spectrum,
    }


def parse_xrandr(text):
    """Saida de `xrandr --query` -> [{name, primary, active, w, h, x, y, pref}] das saidas CONECTADAS.
    active = tem modo ligado agora (w/h/x/y = geometria atual; 0 se nao). pref = [w, h] do modo
    preferido do EDID (o '+'), senao o 1o listado — e' o que `xrandr --auto` liga. Plug novo
    (telao, processadora, dummy) costuma aparecer conectado mas DESLIGADO."""
    outs, cur = [], None
    for line in (text or '').splitlines():
        m = re.match(r'(\S+) (connected|disconnected)( primary)?(?: (\d+)x(\d+)\+(-?\d+)\+(-?\d+))?', line)
        if m:
            cur = None
            if m.group(2) == 'connected':
                w, h, x, y = (int(v) if v else 0 for v in m.group(4, 5, 6, 7))
                cur = {'name': m.group(1), 'primary': bool(m.group(3)), 'active': bool(m.group(4)),
                       'w': w, 'h': h, 'x': x, 'y': y, 'pref': None}
                outs.append(cur)
            continue
        mm = re.match(r'\s+(\d+)x(\d+)i?\s+(.*)$', line)
        if cur is not None and mm:
            wh = [int(mm.group(1)), int(mm.group(2))]
            if '+' in mm.group(3):
                cur['pref'] = wh
            cur.setdefault('first', wh)
    for o in outs:
        first = o.pop('first', None)
        o['pref'] = o['pref'] or first
    return outs


# TELAO VIRTUAL (src/telao_sim.py): enquanto aberto, o simulador anuncia saidas aqui —
# {"outputs": [{"name": "SIM-1", "w", "h", "label"}], "pid": N}. Native (get_monitors) e dash
# (detectar telao) leem junto com o xrandr; pid morto = arquivo velho, ignorado. A janela de saida
# "vai pra" x = largura da tela X (fora da area visivel; o WM deixa uma tira) e o simulador a
# captura pelo id (composite: pega a janela inteira mesmo fora da tela).
VIRTUAL_OUTPUTS = os.path.join(os.environ.get('XDG_RUNTIME_DIR') or tempfile.gettempdir(), 'prisma-telao-virtual.json')


def _pid_alive(pid):
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, ValueError, TypeError):
        return False


def virtual_outputs(screen_w, path=None, alive=_pid_alive):
    """Saidas do telao virtual no formato do parse_xrandr (+ virtual=True), a direita da tela X
    (x = screen_w). [] sem simulador aberto."""
    try:
        with open(path or VIRTUAL_OUTPUTS) as f:
            d = json.load(f)
    except (OSError, ValueError):
        return []
    if not isinstance(d, dict) or not alive(d.get('pid')):
        return []
    out = []
    for o in d.get('outputs') or []:
        try:
            w, h = int(o['w']), int(o['h'])
        except (KeyError, TypeError, ValueError):
            continue
        if w >= 16 and h >= 16:
            out.append({'name': str(o.get('name') or 'SIM-1'), 'primary': False, 'active': True, 'virtual': True,
                        'w': w, 'h': h, 'x': int(screen_w or 0), 'y': 0, 'pref': [w, h],
                        'label': str(o.get('label') or '')})
    return out


def xrandr_screen_w(text):
    """Largura atual da tela X ('Screen 0: ... current W x H') — onde o telao virtual comeca."""
    m = re.search(r'current (\d+) x (\d+)', text or '')
    return int(m.group(1)) if m else 0


def pick_led_output(outs):
    """Qual saida e' o telao: a 1a REAL que NAO e' a principal (sem principal marcada, a 1a depois
    da que tem a tela em 0,0); sem nenhuma, o telao VIRTUAL (simulador). None se so' ha' a do
    operador. Real ganha do virtual: simulador esquecido aberto nao rouba o show."""
    real, virt = [o for o in outs if not o.get('virtual')], [o for o in outs if o.get('virtual')]
    rest = [o for o in real if not o['primary']]
    if len(rest) == len(real):
        rest = [o for o in real if not (o['active'] and o['x'] == 0 and o['y'] == 0)] or real[1:]
    if len(real) < 2:
        rest = []
    return (rest + virt)[0] if rest + virt else None


if __name__ == '__main__':  # self-check (roda: python dash_data.py)
    assert parse_fx_manifest('// fx: wave, grain ,vignette\nfoo bar') == ['wave', 'grain', 'vignette']
    assert parse_fx_manifest('//fx:wave') == ['wave']
    assert parse_fx_manifest('nada aqui') == [] and parse_fx_manifest('') == []
    assert parse_fx_manifest('// fx: a=0.5, b') == ['a', 'b']
    assert parse_fx_defaults('// fx: a=0.5, b, c=2, d=x') == {'a': 0.5, 'b': 1.0, 'c': 1.0, 'd': 1.0}

    freqs = np.fft.rfftfreq(1024, d=1 / 44100)
    spec = np.full(len(freqs), 0.01)
    spec[5:15] = 1.0  # pico no grave
    bands_raw = [(n, 0.3, 0.3, 0.2, 0.7) for n in FREQ_BAND_RGB]  # 8, grave->agudo
    d = audio_dash_data(bands_raw, 0.25, 0.8, 0.6, 0.9, 0.5, 0.83, spec, freqs)
    assert d['kick'] == {'final': 0.5, 'decay': 0.83}, d['kick']
    names = [b['name'] for b in d['bands']]
    assert names[0] == 'amp' and names[-1] == 'Sub-bass', names
    assert len(d['bands']) == 9 and len(d['spectrum']) == 24
    assert d['bands'][0]['delta'] == round(abs(0.6 - 0.8), 4), d['bands'][0]
    assert tuple(d['bands'][-1]['rgb']) == (30, 140, 255)
    assert max(s['rel'] for s in d['spectrum']) == 1.0  # faixa mais forte sempre 100%
    assert all(0.0 <= s['rel'] <= 1.0 for s in d['spectrum'])
    # cinza quando o Hz cai num buraco entre faixas (modo crossover)
    assert _band_rgb_for_hz(300, [(20, 200), (400, 600)] + [(0, 0)] * 6) == _GREY
    assert _band_rgb_for_hz(100, [(20, 200), (400, 600)] + [(0, 0)] * 6) == (30, 140, 255)
    xr = ('Screen 0: minimum 8 x 8, current 3286 x 1080\n'
          'HDMI-0 connected primary 1366x768+0+0 (normal left) 434mm x 236mm\n'
          '   1366x768      59.79*+\n   1280x720      60.00\n'
          'DP-0 disconnected (normal left inverted right x axis y axis)\n'
          'HDMI-1 connected (normal left inverted right x axis y axis)\n'
          '   3840x2160     30.00 +  60.00\n   1920x1080     60.00\n'
          'DP-2 connected 1920x1080+1366+0 (normal left) 0mm x 0mm\n'
          '   2560x1440     60.00\n   1920x1080     60.00*+\n')
    o = parse_xrandr(xr)
    assert [x['name'] for x in o] == ['HDMI-0', 'HDMI-1', 'DP-2'], o
    assert o[0]['primary'] and o[0]['active'] and (o[0]['w'], o[0]['h']) == (1366, 768)
    assert not o[1]['active'] and o[1]['pref'] == [3840, 2160], o[1]
    assert o[2]['active'] and o[2]['x'] == 1366 and o[2]['pref'] == [1920, 1080], o[2]
    assert pick_led_output(o)['name'] == 'HDMI-1' and pick_led_output(o[:1]) is None
    np_ = [dict(x, primary=False) for x in o]
    assert pick_led_output(np_)['name'] == 'HDMI-1'
    v = [{'name': 'SIM-1', 'primary': False, 'active': True, 'virtual': True, 'w': 3840, 'h': 1080, 'x': 1366, 'y': 0}]
    assert pick_led_output(o[:1] + v)['name'] == 'SIM-1'          # so' a principal + simulador
    assert pick_led_output(o + v)['name'] == 'HDMI-1'             # real ganha
    assert xrandr_screen_w(xr) == 3286
    vp = os.path.join(tempfile.gettempdir(), 'prisma-vo-test.json')
    json.dump({'pid': 1, 'outputs': [{'name': 'SIM-1', 'w': 3840, 'h': 2160, 'label': '4K'}, {'w': 'x'}]}, open(vp, 'w'))
    vo = virtual_outputs(1366, vp, alive=lambda p: True)
    assert len(vo) == 1 and vo[0]['x'] == 1366 and vo[0]['pref'] == [3840, 2160] and vo[0]['virtual'], vo
    assert virtual_outputs(1366, vp, alive=lambda p: False) == []
    os.remove(vp); assert virtual_outputs(1366, vp) == []
    print('dash_data self-check ok')
