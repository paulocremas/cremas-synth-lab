"""Funcoes puras que produzem os NUMEROS do dashboard (nao formatam terminal nem HTML).

Fonte unica de verdade do dash de audio: o audio_thread chama audio_dash_data() e publica
o dict em state['audio_dash']; tanto o dash de terminal quanto o payload HTTP so renderizam
esse mesmo dict. Sem import de native_synth (evita circular) — so numpy.
"""
import json
import math
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


# ---------- TELAS DO PALCO com forma livre (tuning.SCREENS[i].rot / .poly) ----------
# Uma tela = o PAINEL retangular (x, y, w, h em metros, origem em cima; pw x ph LEDs) GIRADO `rot`
# graus (horario, em volta do centro) e, opcional, recortado pelo poligono `poly` ([[u, v], ...]
# 0..1 no painel SEM giro, origem em cima): fora dele o painel fica apagado. Sem rot/poly = o
# retangulo de sempre. Mesma conta no native (_stage), no dash v2 (shapeAxes) e no telao_sim.
MAX_POLY = 32   # = largura da textura de poligonos do native (POLY_TEX_W)


def screen_poly(t):
    """`poly` valido da tela -> [(u, v), ...] (3..MAX_POLY pontos, 0..1) ou None (= o painel inteiro)."""
    try:
        pts = [(min(1.0, max(0.0, float(p[0]))), min(1.0, max(0.0, float(p[1])))) for p in t.get('poly') or ()]
    except (TypeError, ValueError, IndexError, AttributeError):
        return None
    return pts[:MAX_POLY] if len(pts) >= 3 else None


def screen_axes(t):
    """O painel em metros: (o, ex, ey) — o = canto (u, v) = (0, 0) dele, ex/ey = vetores de u e v
    de 0 a 1. Ponto do painel em metros = o + u*ex + v*ey (ja girado)."""
    x, y, w, h = (float(t[k]) for k in ('x', 'y', 'w', 'h'))
    a = math.radians(float(t.get('rot') or 0.0))
    c, s = math.cos(a), math.sin(a)
    ex, ey = (w * c, w * s), (-h * s, h * c)
    cx, cy = x + w / 2, y + h / 2
    return (cx - (ex[0] + ey[0]) / 2, cy - (ex[1] + ey[1]) / 2), ex, ey


def screen_pts(t):
    """Contorno da tela em metros (o poligono, ou os 4 cantos do painel), ja girado."""
    o, ex, ey = screen_axes(t)
    return [(o[0] + u * ex[0] + v * ey[0], o[1] + u * ex[1] + v * ey[1])
            for u, v in (screen_poly(t) or ((0, 0), (1, 0), (1, 1), (0, 1)))]


def screen_bbox(t):
    """Retangulo (x0, y0, x1, y1) em metros que envolve o contorno da tela."""
    p = screen_pts(t)
    return min(q[0] for q in p), min(q[1] for q in p), max(q[0] for q in p), max(q[1] for q in p)


def pack_raster(screens, rw, rh):
    """ox/oy de cada tela (pw x ph) no raster rw x rh, como a processadora reempacota: 1o canto livre
    (de cima pra baixo) em algumas ordens; fica a 1a que cabe inteira, senao a que deixa menos px de
    fora (essas vao pra baixo do raster). = pmPack do dash v2. Muda as telas; -> as que nao couberam."""
    def hit(a, b):
        return a[0] < b[0] + b[2] and b[0] < a[0] + a[2] and a[1] < b[1] + b[3] and b[1] < a[1] + a[3]
    orders = [lambda t: (-t['ph'], -t['pw']), lambda t: (-t['pw'], -t['ph']),
              lambda t: -t['pw'] * t['ph'], lambda t: -max(t['pw'], t['ph'])]
    best = None
    for key in orders:
        placed, pos, out, bottom = [], {}, 0, 0
        for i, t in sorted(enumerate(screens), key=lambda it: key(it[1])):
            cand = sorted([(0, 0)] + [c for o in placed for c in ((o[0] + o[2], o[1]), (o[0], o[1] + o[3]), (0, o[1] + o[3]))],
                          key=lambda c: (c[1], c[0]))
            at = next((c for c in cand if c[0] + t['pw'] <= rw and c[1] + t['ph'] <= rh
                       and not any(hit((c[0], c[1], t['pw'], t['ph']), o) for o in placed)), None)
            if at is None:
                out += t['pw'] * t['ph']
                at = (0, max(rh, bottom))
            r = (at[0], at[1], t['pw'], t['ph'])
            placed.append(r)
            pos[i] = r
            bottom = max(bottom, r[1] + r[3])
        if best is None or out < best[0]:
            best = (out, pos)
        if not out:
            break
    for i, r in best[1].items():
        screens[i]['ox'], screens[i]['oy'] = r[0], r[1]
    return [t for t in screens if t['ox'] + t['pw'] > rw or t['oy'] + t['ph'] > rh]


def in_poly(pts, x, y):
    """Ponto dentro do poligono (par-impar)."""
    ins, j = False, len(pts) - 1
    for i in range(len(pts)):
        (xi, yi), (xj, yj) = pts[i], pts[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            ins = not ins
        j = i
    return ins


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
    # telas com forma livre: giro em volta do centro, poligono no painel sem giro
    sq = {'x': 0, 'y': 0, 'w': 2, 'h': 1}
    assert [tuple(round(c, 6) for c in p) for p in screen_pts(sq)] == [(0, 0), (2, 0), (2, 1), (0, 1)]
    r = [tuple(round(c, 6) + 0.0 for c in p) for p in screen_pts(dict(sq, rot=90))]
    assert r == [(1.5, -0.5), (1.5, 1.5), (0.5, 1.5), (0.5, -0.5)], r     # em pe', mesmo centro
    assert [round(c, 6) for c in screen_bbox(dict(sq, rot=90))] == [0.5, -0.5, 1.5, 1.5]
    tri = dict(sq, poly=[[0, 1], [0.5, 0], [1, 1]])
    assert screen_bbox(tri) == (0, 0, 2, 1) and in_poly(screen_pts(tri), 1, 0.6) and not in_poly(screen_pts(tri), 0.2, 0.2)
    assert screen_poly({'poly': [[0, 0], [1, 1]]}) is None and screen_poly({'poly': [[0, 0], [2, 'x']]}) is None
    assert screen_poly({'poly': [[-1, 0], [1, 0], [1, 5]]}) == [(0, 0), (1, 0), (1, 1)]
    pk = [{'pw': 256, 'ph': 1024}, {'pw': 1024, 'ph': 256}, {'pw': 256, 'ph': 1024}]
    assert pack_raster(pk, 1920, 1080) == [] and [(t['ox'], t['oy']) for t in pk] == [(0, 0), (512, 0), (256, 0)], pk
    assert [t['pw'] for t in pack_raster([{'pw': 2000, 'ph': 10}, {'pw': 10, 'ph': 10}], 1920, 1080)] == [2000]
    print('dash_data self-check ok')
