#!/usr/bin/env python3
"""RITMO e TOM da musica, a partir dos chunks de audio do native (audio_thread) — so' numpy.

Tempo: fluxo espectral (quanto o espectro SOBE de um chunk pro outro = ataques de bateria, baixo,
acordes; mais que so' o kick) -> autocorrelacao dos ultimos ~8 s -> BPM (70..180, preferencia
suave por ~120 contra erro de oitava). Fase: um "PLL" — cada ataque forte perto da batida prevista
puxa o relogio um pouco pra ele. TAP (botao/MIDI) fixa o BPM e a fase; 1o toque de uma sequencia = o
"1" do compasso. A posicao na batida/compasso e' calculada no RENDER a cada frame (phase()) — lisa.

Tom: cromagrama (energia por nota, 12 classes) com FFT longa (8192 = ~5 Hz de resolucao, preciso
pras notas graves), media longa (~8 s), comparado aos 24 perfis de Krumhansl-Kessler (correlacao):
tonica + maior/menor + confianca (vantagem sobre o 2o colocado).

Cor do tom (key_rgb): 'quintas' = posicao no circulo das quintas vira matiz (tons vizinhos = cores
vizinhas; o menor usa a cor do relativo maior) | 'scriabin' = a tabela do "clavier a lumieres".
"""
import collections
import colorsys
import math

import numpy as np

NOTES = ['Dó', 'Dó♯', 'Ré', 'Mi♭', 'Mi', 'Fá', 'Fá♯', 'Sol', 'Lá♭', 'Lá', 'Si♭', 'Si']
# perfis de Krumhansl-Kessler (1982): o quanto cada grau "pertence" ao tom, maior e menor
_KK_MAJ = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
_KK_MIN = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])
# Scriabin (Prometheus, 1910) por tonica — aproximacoes em RGB comuns na literatura
_SCRIABIN = [(255, 0, 0), (143, 0, 255), (255, 255, 0), (183, 70, 139), (195, 242, 255), (171, 0, 52),
             (127, 139, 253), (255, 127, 0), (187, 117, 252), (51, 204, 51), (169, 103, 124), (142, 201, 255)]


class Tempo:
    """BPM + fase. update() a cada chunk de audio; phase(t) no render. Tempos em segundos (monotonic)."""

    def __init__(self, fps=44100 / 1024, lo=70.0, hi=180.0):
        self.fps, self.lo, self.hi = fps, lo, hi
        self.env = collections.deque(maxlen=int(fps * 8))   # fluxo espectral dos ultimos ~8 s
        self.prev = None
        self.bpm, self.conf = 0.0, 0.0
        self.t0 = None              # instante de uma batida "1" (fase 0 do compasso)
        self.manual = False         # TAP fixou o BPM (o automatico so' ajusta a fase)
        self.taps = []
        self.n = 0
        self.thr = 0.0              # limiar adaptativo dos ataques (media movel do fluxo)

    def update(self, t, spectrum):
        s = np.log1p(np.asarray(spectrum, np.float64) * 100.0)
        flux = float(np.maximum(0.0, s - self.prev).sum()) if self.prev is not None and len(self.prev) == len(s) else 0.0
        self.prev = s
        self.env.append(flux)
        self.n += 1
        if not self.manual and self.n % int(self.fps) == 0 and len(self.env) >= self.fps * 4:
            self._estimate()
        # PLL: ataque forte perto da batida prevista puxa o relogio (20% do erro)
        self.thr = self.thr * 0.97 + flux * 0.03
        if self.bpm > 0 and flux > self.thr * 1.6 and flux > 1e-3:
            T = 60.0 / self.bpm
            if self.t0 is None:
                self.t0 = t
            else:
                k = round((t - self.t0) / T)
                err = t - (self.t0 + k * T)
                if abs(err) < 0.25 * T:
                    self.t0 += err * 0.2

    def _estimate(self):
        x = np.asarray(self.env) - np.mean(self.env)
        n = len(x)
        if not np.any(x):
            return
        f = np.fft.rfft(x, 2 * n)
        ac = np.fft.irfft(f * np.conj(f))[:n]                # autocorrelacao (Wiener-Khinchin)
        if ac[0] <= 0:
            return
        lags = np.arange(n)
        ok = (lags >= 60 * self.fps / self.hi) & (lags <= 60 * self.fps / self.lo)
        bpms = 60 * self.fps / np.maximum(lags, 1)
        w = np.exp(-0.5 * (np.log2(bpms / 120.0) / 0.9) ** 2)  # preferencia suave por ~120 (erro de oitava)
        score = np.where(ok, ac * w, -np.inf)
        L = int(np.argmax(score))
        if 0 < L < n - 1:                                     # refina entre lags (parabola)
            a, b, c = ac[L - 1], ac[L], ac[L + 1]
            d = (a - c) / (2 * (a - 2 * b + c)) if (a - 2 * b + c) != 0 else 0.0
            Lf = L + max(-0.5, min(0.5, d))
        else:
            Lf = L
        bpm = 60 * self.fps / Lf
        self.conf = float(max(0.0, min(1.0, ac[L] / ac[0])))
        if self.conf < 0.08:
            return
        self.bpm = bpm if not self.bpm or abs(bpm - self.bpm) / self.bpm > 0.04 else self.bpm * 0.8 + bpm * 0.2

    def tap(self, t):
        """Toque do TAP. Pausa > 2 s comeca sequencia nova e esse toque vira o '1' do compasso."""
        if self.taps and t - self.taps[-1] > 2.0:
            self.taps = []
        self.taps = (self.taps + [t])[-8:]
        if len(self.taps) == 1:
            self.t0 = t
        else:
            iv = np.diff(self.taps)
            self.bpm, self.manual, self.conf = 60.0 / float(np.median(iv)), True, 1.0
            self.t0 = self.taps[0]                            # o 1o toque da sequencia = o '1'

    def auto(self):
        self.manual, self.taps = False, []

    def phase(self, t, beats_per_bar=4):
        """(posicao na batida 0..1, posicao no compasso 0..1). (0, 0) sem tempo."""
        if not self.bpm or self.t0 is None:
            return 0.0, 0.0
        b = (t - self.t0) * self.bpm / 60.0
        return b % 1.0, (b % beats_per_bar) / beats_per_bar

    def next_boundary(self, t, unit):
        """Instante da proxima batida ('beat') ou do proximo '1' ('bar') a partir de t (None sem tempo)."""
        if not self.bpm or self.t0 is None or unit not in ('beat', 'bar'):
            return None
        T = 60.0 / self.bpm * (4 if unit == 'bar' else 1)
        return self.t0 + math.ceil((t - self.t0) / T + 1e-6) * T


class Key:
    """Tom por cromagrama. push(samples) a cada chunk; resultado em .tonic/.minor/.conf."""

    def __init__(self, rate=44100, size=8192, tau_s=8.0, every=4):
        self.rate, self.size, self.every = rate, size, every
        self.buf = np.zeros(size, np.float32)
        self.win = np.hanning(size).astype(np.float32)
        f = np.fft.rfftfreq(size, 1.0 / rate)
        band = (f >= 55) & (f <= 2000)                      # La1..Si6: onde mora a harmonia
        self.bins = np.nonzero(band)[0]
        self.pc = (np.round(12 * np.log2(f[self.bins] / 440.0) + 69).astype(int)) % 12
        self.acc = np.zeros(12)
        self.k = 1.0 - math.exp(-(every * 1024 / rate) / tau_s)   # media exponencial de ~tau_s
        self.n = 0
        self.tonic, self.minor, self.conf = -1, 0, 0.0

    def push(self, samples):
        s = np.asarray(samples, np.float32)
        self.buf = np.roll(self.buf, -len(s))
        self.buf[-len(s):] = s
        self.n += 1
        if self.n % self.every:
            return
        if float(np.mean(self.buf[-4096:] ** 2)) < 1e-6:   # silencio: nao aprende ruido
            return
        mag = np.abs(np.fft.rfft(self.buf * self.win))[self.bins]
        chroma = np.bincount(self.pc, weights=mag, minlength=12)
        if chroma.sum() <= 0:
            return
        self.acc += (chroma / chroma.sum() - self.acc) * self.k
        self.estimate()

    def estimate(self):
        c = self.acc - self.acc.mean()
        if not np.any(c):
            return
        scores = []
        for minor, prof in ((0, _KK_MAJ), (1, _KK_MIN)):
            p0 = prof - prof.mean()
            for t in range(12):
                p = np.roll(p0, t)
                scores.append((float(np.dot(c, p) / (np.linalg.norm(c) * np.linalg.norm(p))), t, minor))
        scores.sort(reverse=True)
        (r1, t1, m1), (r2, _, _) = scores[0], scores[1]
        self.tonic, self.minor = t1, m1
        self.conf = float(max(0.0, min(1.0, (r1 - r2) * 5 + max(0.0, r1) * 0.5)))

    def name(self):
        return '' if self.tonic < 0 else NOTES[self.tonic] + (' menor' if self.minor else ' maior')


def key_rgb(tonic, minor, mode='quintas'):
    """Cor (r, g, b 0..255) do tom. quintas: matiz = posicao no circulo das quintas (relativo menor =
    mesma cor do maior, mais escura); scriabin: tabela do Scriabin (menor = a do relativo, mais escura)."""
    if tonic < 0:
        return (128, 128, 128)
    major = (tonic + 3) % 12 if minor else tonic          # relativo maior: La menor -> Do maior
    if mode == 'scriabin':
        r, g, b = _SCRIABIN[major]
        k = 0.6 if minor else 1.0
        return (int(r * k), int(g * k), int(b * k))
    hue = ((major * 7) % 12) / 12.0                        # Do=0, Sol=1/12, Re=2/12... (quintas)
    r, g, b = colorsys.hsv_to_rgb(hue, 0.85 if not minor else 0.7, 1.0 if not minor else 0.6)
    return (int(r * 255), int(g * 255), int(b * 255))


def key_hue(tonic, minor, mode='quintas'):
    """matiz 0..1 da cor do tom (pro shader: u_key_hue)."""
    r, g, b = key_rgb(tonic, minor, mode)
    return colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)[0] if tonic >= 0 else 0.0


if __name__ == '__main__':   # self-check: python src/ritmo.py
    rate, hop = 44100, 1024
    fps = rate / hop
    rng = np.random.default_rng(3)
    # METRONOMO a 128 BPM: ataque de ruido largo no inicio de cada batida, depois silencio
    tp = Tempo(fps)
    period = 60.0 / 128 * rate
    win = np.hanning(hop)
    for i in range(int(fps * 12)):
        start = i * hop
        x = rng.normal(0, 0.003, hop)
        k = math.ceil(start / period) * period
        if k < start + hop:                                    # uma batida cai neste chunk
            j = int(k - start)
            x[j:] += rng.normal(0, 0.5, hop - j) * np.exp(-np.arange(hop - j) / 300)
        tp.update(start / rate, np.abs(np.fft.rfft(x * win)))
    assert abs(tp.bpm - 128) < 2.5, tp.bpm
    b, _ = tp.phase(12 * 60 / 128 * 30 / 30 + 0.0)            # numa batida exata, a fase ~0 (ou ~1)
    assert min(b, 1 - b) < 0.12, ('fase', b)
    assert tp.next_boundary(10.0, 'bar') > 10.0 and tp.next_boundary(10.0, 'beat') <= tp.next_boundary(10.0, 'bar')
    # TAP: 4 toques a 100 BPM fixam o tempo; o 1o toque e' o "1"
    tt = Tempo(fps)
    for i in range(4):
        tt.tap(50.0 + i * 0.6)
    assert abs(tt.bpm - 100) < 0.01 and tt.manual and abs(tt.phase(50.0)[1]) < 1e-6 and abs(tt.phase(50.6)[1] - 0.25) < 1e-6
    tt.tap(60.0)                                               # pausa > 2 s: sequencia nova
    assert tt.taps == [60.0]
    # TOM: progressao I-IV-V-I em Sol maior / i-iv-v-i em Mi menor (notas puras somadas)
    def chords(roots_minor, secs=10):
        ky = Key(rate)
        t = np.arange(hop) / rate
        for i in range(int(fps * secs)):
            notes = roots_minor[(i // int(fps * 1.0)) % len(roots_minor)]
            x = sum(np.sin(2 * np.pi * 440 * 2 ** ((n - 69) / 12) * (t + i * hop / rate)) for n in notes) * 0.1
            ky.push(x)
        return ky
    G = chords([(55, 59, 62, 67), (60, 64, 67, 72), (62, 66, 69, 74), (55, 59, 62, 67)])     # G C D G
    assert (G.tonic, G.minor) == (7, 0), (G.name(), G.conf)
    E = chords([(52, 55, 59, 64), (57, 60, 64, 69), (59, 62, 66, 71), (52, 55, 59, 64)])     # Em Am Bm Em
    assert (E.tonic, E.minor) == (4, 1), (E.name(), E.conf)
    assert key_rgb(9, 1) != key_rgb(0, 0) and key_hue(9, 1) == key_hue(0, 0), 'La menor = cor do Do maior, mais escura'
    assert abs(key_hue(7, 0) - key_hue(0, 0) - 1 / 12) < 0.02, 'Sol = vizinho do Do no circulo das quintas'
    print('ritmo self-check ok ·', round(tp.bpm, 1), 'BPM ·', G.name(), '·', E.name())
