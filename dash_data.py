"""Funcoes puras que produzem os NUMEROS do dashboard (nao formatam terminal nem HTML).

Fonte unica de verdade do dash de audio: o audio_thread chama audio_dash_data() e publica
o dict em state['audio_dash']; tanto o dash de terminal quanto o payload HTTP so renderizam
esse mesmo dict. Sem import de native_synth (evita circular) — so numpy.
"""
import numpy as np

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


if __name__ == '__main__':  # self-check (roda: python dash_data.py)
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
    print('dash_data self-check ok')
