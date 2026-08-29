#!/usr/bin/env python3
"""Sintese de imagem nativa: webcam ou tela (ffmpeg) + audio do sistema (parec/PulseAudio)
alimentando image.frag numa janela OpenGL, sem navegador nenhum no meio.

Uso: .venv/bin/python native_synth.py [--screen [--source NOME]] [--fullscreen | --monitor [NOME]]
"""
import argparse
import colorsys
import importlib
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
from itertools import zip_longest

import numpy as np
import pygame
from OpenGL.GL import *

import tuning

TUNING_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'tuning.py')

WIDTH, HEIGHT = 640, 480  # resolucao do conteudo (textura); recalculada no --screen
WIN_W, WIN_H = WIDTH, HEIGHT  # resolucao da janela; recalculada no --fullscreen
FRAME_SIZE = WIDTH * HEIGHT * 3  # rgb24
FRAG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'image.frag')

VERT_SRC = """
attribute vec2 a_pos;
void main() { gl_Position = vec4(a_pos, 0.0, 1.0); }
"""

state = {'frame': np.zeros(FRAME_SIZE, dtype=np.uint8), 'amp': 0.0, 'bass': 0.0, 'mid': 0.0, 'treble': 0.0,
         'kick': 0.0, 'dominant': (0.5, 0.5, 0.5),
         # faixas finas de mixagem (Sub-bass..Air) — controlam u_subbass..u_air no shader
         'subbass': 0.0, 'lowmid': 0.0, 'midrange': 0.0, 'highmid': 0.0, 'presence': 0.0,
         'treble_hi': 0.0, 'brilho': 0.0, 'air': 0.0}
running = True


def get_screen_size():
    out = subprocess.check_output(['xrandr', '--current']).decode()
    w, h = re.search(r'current (\d+) x (\d+)', out).groups()
    return int(w), int(h)


def get_monitors():
    """Nome, w, h, x, y, primario de cada saida conectada (ordem do xrandr)."""
    out = subprocess.check_output(['xrandr', '--current']).decode()
    monitors = []
    for line in out.splitlines():
        m = re.match(r'(\S+) connected (primary )?(\d+)x(\d+)\+(\d+)\+(\d+)', line)
        if m:
            name, primary, w, h, x, y = m.groups()
            monitors.append({'name': name, 'w': int(w), 'h': int(h), 'x': int(x), 'y': int(y),
                              'primary': bool(primary)})
    return monitors


def pick_monitor(name=None):
    monitors = get_monitors()
    if not monitors:
        return None
    if name:
        for m in monitors:
            if m['name'] == name:
                return m
        raise SystemExit(f'monitor "{name}" nao encontrado. Disponiveis: {[m["name"] for m in monitors]}')
    non_primary = [m for m in monitors if not m['primary']]
    return non_primary[0] if non_primary else monitors[0]


def pick_window(title=None):
    """Geometria + id X11 de uma janela agora (id serve pra captura via composite, que segue
    a janela mesmo coberta; a geometria e so o fallback pro x11grab por regiao de tela)."""
    if title:
        out = subprocess.check_output(['wmctrl', '-l', '-G']).decode()
        for line in out.splitlines():
            parts = line.split(None, 7)
            if len(parts) >= 8 and title.lower() in parts[7].lower():
                x, y, w, h = (int(v) for v in parts[2:6])
                return {'name': parts[7], 'w': w, 'h': h, 'x': x, 'y': y, 'id': parts[0]}
        raise SystemExit(f'nenhuma janela com titulo contendo "{title}"')
    print('clica na janela que quer usar como fonte...')
    out = subprocess.check_output(['xwininfo']).decode()
    x = int(re.search(r'Absolute upper-left X:\s+(-?\d+)', out).group(1))
    y = int(re.search(r'Absolute upper-left Y:\s+(-?\d+)', out).group(1))
    w = int(re.search(r'Width:\s+(\d+)', out).group(1))
    h = int(re.search(r'Height:\s+(\d+)', out).group(1))
    win_id = re.search(r'Window id:\s+(\S+)', out).group(1)
    name = re.search(r'"([^"]*)"', out)
    return {'name': name.group(1) if name else 'janela', 'w': w, 'h': h, 'x': x, 'y': y, 'id': win_id}


def pick_region():
    """Tira um print da area de trabalho toda e deixa arrastar um retangulo em cima pra recortar."""
    sw, sh = get_screen_size()
    shot = subprocess.run(
        ['ffmpeg', '-loglevel', 'error', '-f', 'x11grab', '-video_size', f'{sw}x{sh}',
         '-i', os.environ.get('DISPLAY', ':0'), '-frames:v', '1', '-pix_fmt', 'rgb24', '-f', 'rawvideo', '-'],
        stdout=subprocess.PIPE, check=True,
    ).stdout
    pygame.init()
    os.environ['SDL_VIDEO_WINDOW_POS'] = '0,0'
    pygame.display.set_mode((sw, sh), pygame.NOFRAME)
    pygame.display.set_caption('arrasta um retangulo e solta pra escolher a regiao — ESC cancela')
    bg = pygame.image.frombuffer(shot, (sw, sh), 'RGB')
    screen = pygame.display.get_surface()

    start = None
    rect = None
    cancelled = False
    picking = True
    while picking:
        for event in pygame.event.get():
            if event.type == pygame.QUIT or (event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE):
                cancelled = True
                picking = False
            elif event.type == pygame.MOUSEBUTTONDOWN:
                start = event.pos
            elif event.type == pygame.MOUSEMOTION and start:
                rect = pygame.Rect(start, (0, 0)).union(pygame.Rect(event.pos, (0, 0)))
            elif event.type == pygame.MOUSEBUTTONUP and start:
                picking = False
        screen.blit(bg, (0, 0))
        if rect:
            pygame.draw.rect(screen, (255, 60, 60), rect, width=3)
        pygame.display.flip()
    pygame.quit()
    del os.environ['SDL_VIDEO_WINDOW_POS']

    if cancelled or not rect or rect.width < 5 or rect.height < 5:
        print('selecao cancelada ou pequena demais')
        return None
    return {'name': 'regiao selecionada', 'w': rect.width, 'h': rect.height, 'x': rect.x, 'y': rect.y}


def clamp_region(region):
    """wmctrl/xwininfo as vezes reportam geometria que passa um pouco da borda da tela
    (decoracao/sombra da janela) — o x11grab rejeita isso de cara, entao encolhe pra caber."""
    sw, sh = get_screen_size()
    x = max(0, min(region['x'], sw - 2))
    y = max(0, min(region['y'], sh - 2))
    w = max(2, min(region['w'], sw - x))
    h = max(2, min(region['h'], sh - y))
    return {**region, 'x': x, 'y': y, 'w': w, 'h': h}


def fit(w, h, max_dim=1280):
    scale = min(1.0, max_dim / max(w, h))
    return max(2, int(w * scale) // 2 * 2), max(2, int(h * scale) // 2 * 2)


def read_exact(stream, n):
    buf = b''
    while len(buf) < n:
        chunk = stream.read(n - len(buf))
        if not chunk:
            return None
        buf += chunk
    return buf


def video_thread(mode, region=None, device='/dev/video0'):
    if mode == 'screen':
        display = os.environ.get('DISPLAY', ':0') + f"+{region['x']},{region['y']}"
        cmd = ['ffmpeg', '-loglevel', 'error', '-f', 'x11grab', '-framerate', '30',
               '-video_size', f"{region['w']}x{region['h']}", '-i', display,
               '-vf', f'scale={WIDTH}:{HEIGHT}', '-pix_fmt', 'rgb24', '-f', 'rawvideo', '-']
    else:
        cmd = ['ffmpeg', '-loglevel', 'error', '-f', 'v4l2']
        if device == '/dev/video0':  # so a webcam de verdade precisa forcar o formato
            cmd += ['-input_format', 'yuyv422']
        cmd += ['-video_size', f'{WIDTH}x{HEIGHT}', '-i', device, '-pix_fmt', 'rgb24', '-f', 'rawvideo', '-']
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE)
    try:
        while running:
            frame = read_exact(proc.stdout, FRAME_SIZE)
            if frame is None:
                break
            state['frame'] = np.frombuffer(frame, dtype=np.uint8)
    finally:
        proc.terminate()


def window_capture_thread(win_id):
    """Le o pixmap composto da janela direto (via ImageMagick 'import'), em vez de um
    retangulo fixo de tela — por isso segue a janela mesmo com outra coisa por cima.
    Mais lento que x11grab (uns 2-5 fps: cada frame e um processo novo + round-trip X)."""
    cmd = ['import', '-window', win_id, '-depth', '8', 'rgb:-']
    warned = False
    while running:
        try:
            out = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=2).stdout
        except FileNotFoundError:
            print('sem "import" (pacote imagemagick)')
            return
        except subprocess.TimeoutExpired:
            if not warned:
                print(f'captura da janela {win_id}: travou (janela deve ter sido fechada/recriada)')
                warned = True
            continue
        if len(out) == FRAME_SIZE:
            state['frame'] = np.frombuffer(out, dtype=np.uint8)
        elif not warned:
            print(f'captura da janela: tamanho inesperado ({len(out)} bytes, esperava {FRAME_SIZE}) '
                  '— a janela deve ter sido fechada ou redimensionada')
            warned = True


def _rgb(r, g, b):
    return f'\033[38;2;{r};{g};{b}m'


ANSI_RE = re.compile(r'\x1b\[[0-9;]*m')


def visible_len(s):
    return len(ANSI_RE.sub('', s))


def pad_visible(s, width):
    """Completa `s` com espacos ate `width` caracteres VISIVEIS — len() normal contaria os
    codigos ANSI de cor como caractere, alinhando errado colunas lado a lado."""
    return s + ' ' * max(0, width - visible_len(s))


# ponytail: os 3 tons ficam espacados de proposito — gap pequeno demais (era 190/255)
# deixa o cinza "parecer" branco por contraste simultaneo do lado das cores saturadas das
# bandas; escuro demais (era 45, depois 90) fica ilegivel/flat perto delas.
NO_BAND_COLOR = _rgb(150, 150, 150)   # cinza claro — cor padrao pra metro sem banda propria (kick/amp)
TRICOLOR_WARN = _rgb(175, 175, 175)   # cinza medio — zona "perto do teto" (era amarelo)
TRICOLOR_CLIP = _rgb(255, 255, 255)   # branco — zona "no teto"/clip (era vermelho)


def tricolor_bar(filled, width, base_color='\033[32m'):
    """Barra com zona de cor fixa por POSICAO: `base_color` nos primeiros 70% (identidade
    da variavel/banda — verde por padrao), cinza claro 70-95%, branco 95-100% (aviso de
    quase-clip/clip, sempre igual em todas as barras). A cor de cada posicao e sempre a
    mesma; so o quanto acende (`filled`) muda com o valor."""
    green_edge = round(width * 0.7)
    yellow_edge = round(width * 0.95)
    chars = []
    for i in range(width):
        color = TRICOLOR_CLIP if i >= yellow_edge else TRICOLOR_WARN if i >= green_edge else base_color
        chars.append(f'{color}█\033[0m' if i < filled else '\033[2m░\033[0m')
    return ''.join(chars)


BAND_COLORS = {'bass': '\033[34m', 'mid': '\033[36m', 'treble': '\033[35m'}  # azul/ciano/magenta


def band_name(hz, bass_mid_hz, mid_treble_hz):
    """Qual banda (bass/mid/treble) esse Hz cai, usando os MESMOS limiares que definem
    bass_bins/mid_bins/treble_bins no audio_thread — muda um, muda o outro junto."""
    if hz < bass_mid_hz:
        return 'bass'
    elif hz < mid_treble_hz:
        return 'mid'
    return 'treble'


# ponytail: faixas de referencia de engenharia de audio/mixagem (mais finas que o
# bass/mid/treble que controla o shader) — so pra colorir o espectrograma, sem relacao
# com bass_bins/mid_bins/treble_bins. Limites sao os mais citados nesse tipo de carta de
# frequencia; ajusta os numeros se sua referencia usar outros cortes.
# Cores em RGB de 24 bits (nao os 8 nomes padrao do terminal) pra garantir 9 tons
# realmente diferentes entre si — azul/ciano/roxo/magenta/rosa em gradiente, evitando
# vermelho/verde/amarelo (ja usados pelo nivel da barra) e evitando pares tipo
# "azul"/"azul claro" que ficam parecidos demais. Todos claros/saturados o bastante pra
# ler bem em fundo escuro.
FREQ_BANDS = [
    ('Sub-bass', 0, 250, _rgb(30, 140, 255)),          # azul vivo — inaudivel abaixo de
                                                        # ~20Hz, mas a FFT (~43Hz/bin) nao
                                                        # resolve isso separado mesmo
    ('Low-mid', 250, 500, _rgb(0, 200, 255)),          # azul-ciano
    ('Midrange', 500, 2000, _rgb(0, 230, 200)),        # ciano-turquesa
    ('High-mid', 2000, 4000, _rgb(140, 140, 255)),     # indigo/periwinkle
    ('Presence', 4000, 6000, _rgb(190, 100, 255)),     # roxo
    ('Treble', 6000, 10000, _rgb(225, 80, 255)),       # violeta
    ('Brilliance', 10000, 16000, _rgb(255, 70, 210)),  # magenta
    ('Air', 16000, float('inf'), _rgb(255, 110, 160)),  # rosa
]

# nome de exibicao -> chave de uniform valida no GLSL (sem hifen/maiuscula; "Treble" vira
# "treble_hi" pra nao colidir com o u_treble do bass/mid/treble classico)
FREQ_BAND_UNIFORM = {
    'Sub-bass': 'subbass', 'Low-mid': 'lowmid', 'Midrange': 'midrange',
    'High-mid': 'highmid', 'Presence': 'presence', 'Treble': 'treble_hi',
    'Brilliance': 'brilho', 'Air': 'air',
}


def band_smoothing_map():
    """{chave de uniform: SMOOTHING daquela banda}, interpolado linear entre
    tuning.SMOOTHING_MIN (Sub-bass, indice 0) e tuning.SMOOTHING_MAX (Air, ultimo indice),
    seguindo a ordem grave->agudo de FREQ_BANDS. Recalcula toda vez que chamada — chamar
    de novo apos um reload do tuning.py pra pegar os valores atualizados."""
    n = len(FREQ_BANDS)
    span = tuning.SMOOTHING_MAX - tuning.SMOOTHING_MIN
    return {
        FREQ_BAND_UNIFORM[name]: tuning.SMOOTHING_MIN + (i / (n - 1)) * span
        for i, (name, _, _, _) in enumerate(FREQ_BANDS)
    }


def freq_band(hz):
    """(nome, cor) da faixa de FREQ_BANDS que esse Hz pertence."""
    for name, lo, hi, color in FREQ_BANDS:
        if lo <= hz < hi:
            return name, color
    return FREQ_BANDS[-1][0], FREQ_BANDS[-1][3]


def named_band_levels(spectrum, freqs, bands, band_peaks, peak_decay):
    """Pra cada (nome, lo, hi, cor) em `bands` (ex. FREQ_BANDS): magnitude bruta (mesmo
    fallback de bin mais proximo do band_magnitudes, pra faixa mais estreita que a
    resolucao da FFT) e nivel relativo ao PICO RECENTE DA PROPRIA banda — nao ao pico
    entre as bandas. Isso importa porque uma banda estruturalmente mais forte que as
    outras (ex. Sub-bass, quase sempre a mais forte em musica de verdade) ficaria travada
    perto de 1.0 quase sempre so por ser mais alta que as demais, nao por estar batendo
    forte de verdade. `band_peaks` (dict {nome: pico atual}) e mantido pelo chamador entre
    chunks: sobe na hora com um pico novo, decai devagar por `peak_decay` a cada chunk —
    e o auto-gain de cada banda, sem escala manual."""
    out = []
    for name, lo, hi, _ in bands:
        mask = (freqs >= lo) & (freqs < hi)
        if mask.any():
            mag = spectrum[mask].mean()
        else:
            mid = (lo + min(hi, freqs[-1])) / 2  # `hi` pode ser infinito (ultima banda)
            mag = spectrum[np.argmin(np.abs(freqs - mid))]
        band_peaks[name] = max(mag, band_peaks[name] * peak_decay, 1e-6)
        level = min(1.0, mag / band_peaks[name])
        out.append((name, mag, level))
    return out


LABEL_W = 10  # largura fixa do rotulo (nome ou Hz) — "Brilliance" e o mais longo, 10 chars.
              # todo painel (medidores, espectrograma) usa o mesmo valor, pra colunas
              # ficarem na mesma posicao horizontal em qualquer secao.


def _meter_row(name, bar_level, printed_value, colors, width):
    c = colors.get(name, '')
    filled = int(round(max(0.0, min(1.0, bar_level)) * width))
    bar = tricolor_bar(filled, width, base_color=c or NO_BAND_COLOR)
    label = f'{c}{name:>{LABEL_W}}\033[0m' if c else f'{name:>{LABEL_W}}'
    return f'{label}  {bar}  {printed_value}'


def bruto_rows(entries, colors=BAND_COLORS, width=30):
    """`entries` = [(nome, magnitude bruta, nivel relativo 0..1), ...] — o nivel so decide
    o quanto a barra acende (mesmo criterio do espectrograma: relativo ao pico do
    instante, SEM suavizar — por isso mostra a versao "crua"/tremida, antes da media
    movel que vira o "final"). O numero impresso do lado e a magnitude bruta de verdade,
    sem escala nem teto."""
    return [_meter_row(name, level, f'{mag:6.3f}', colors, width) for name, mag, level in entries]


def final_rows(meters, colors=BAND_COLORS, width=30):
    """`meters` = [(nome, nivel 0..1), ...] — nivel final ja suavizado, o que realmente
    vai pro shader."""
    return [_meter_row(name, val, f'{val:.2f}', colors, width) for name, val in meters]


def band_magnitudes(spectrum, freqs, bars):
    """Divide o espectro em `bars` faixas log (30Hz-Nyquist) e devolve, por faixa,
    (frequencia do topo da faixa, magnitude media bruta — mesma unidade/sem teto de
    bass_raw/mid_raw/treble_raw)."""
    # ponytail: no grave, as faixas log ficam mais estreitas que a resolucao real da FFT
    # (44100/1024 ~= 43Hz por bin) — sem isso, uma faixa vazia virava 0.0 (-120dB fixo,
    # artefato, nao silencio de verdade). Faixa vazia usa o bin mais proximo do centro dela.
    edges = np.logspace(np.log10(30), np.log10(freqs[-1]), bars + 1)
    out = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        mask = (freqs >= lo) & (freqs < hi)
        if mask.any():
            mag = spectrum[mask].mean()
        else:
            mag = spectrum[np.argmin(np.abs(freqs - (lo + hi) / 2))]
        out.append((hi, mag))
    return out


def spectrum_bands(spectrum, freqs, bars, range_db=40.0):
    """Por faixa, (frequencia do topo, nivel 0..1) — dB RELATIVO ao pico do frame atual,
    nao a uma referencia fixa: se auto-calibra a qualquer volume/fonte, mas por isso
    sempre tem uma faixa em 100% (a mais forte do instante), mesmo em silencio.
    `range_db` = quantos dB abaixo do pico ainda aparecem, o resto vira 0."""
    mags = band_magnitudes(spectrum, freqs, bars)
    peak_db = 20 * np.log10(max(m for _, m in mags) + 1e-6)
    out = []
    for hi, mag in mags:
        db = 20 * np.log10(mag + 1e-6)
        level = np.clip((db - peak_db + range_db) / range_db, 0.0, 1.0)
        out.append((hi, level))
    return out


def spectrum_column(spectrum, freqs, bars=24, width=30):
    """Espectrograma vertical em NIVEL RELATIVO (0-100%, ao pico do proprio frame): boa
    pra comparar as faixas de frequencia ENTRE SI agora. Uma linha por faixa, mais aguda
    em cima, mais grave embaixo. Hz e % vem coloridos pela faixa de FREQ_BANDS."""
    lines = []
    for hi, level in reversed(spectrum_bands(spectrum, freqs, bars)):
        filled = int(round(level * width))
        _, c = freq_band(hi)
        bar = tricolor_bar(filled, width, base_color=c)
        lines.append(f'{c}{int(round(hi)):>{LABEL_W - 2}}Hz\033[0m  {bar}  {c}{level * 100:5.1f}%\033[0m')
    return lines


def spectrum_column_db(spectrum, freqs, bars=24, width=30, db_min=-60.0, db_max=40.0):
    """Espectrograma vertical em dB ABSOLUTO (sem normalizar pelo pico do frame): o
    numero sobe e desce de verdade com o volume real — em silencio, tudo fica baixo, ao
    contrario da versao percentual (que sempre tem uma faixa em 100%). `db_min`/`db_max`
    so recortam a barra visual; o dB impresso ao lado e o valor exato, sem clamp. Hz e dB
    vem coloridos pela faixa de FREQ_BANDS, mesmo esquema do spectrum_column."""
    lines = []
    for hi, mag in reversed(band_magnitudes(spectrum, freqs, bars)):
        db = 20 * np.log10(mag + 1e-6)
        level = np.clip((db - db_min) / (db_max - db_min), 0.0, 1.0)
        filled = int(round(level * width))
        _, c = freq_band(hi)
        bar = tricolor_bar(filled, width, base_color=c)
        lines.append(f'{c}{int(round(hi)):>{LABEL_W - 2}}Hz\033[0m  {bar}  {c}{db:6.1f}dB\033[0m')
    return lines


_RADIAL_MASK_CACHE = {}


def frame_downsample(frame, w, h, max_side=96):
    """Reduz o frame a no maximo `max_side` px no lado maior, por STRIDE (pula pixel, sem
    interpolar) — rapido, e o suficiente pra qualquer medida GLOBAL da imagem (espectro,
    histograma, brilho medio...) que nao precisa de resolucao cheia. None se o frame ainda
    nao bate com w*h (acontece bem no instante de um resize/troca de fonte de video)."""
    try:
        arr = frame.reshape(h, w, 3).astype(np.float32)
    except ValueError:
        return None
    stride = max(1, max(w, h) // max_side)
    return arr[::stride, ::stride]


def frame_color_spectrum(frame, w, h, bars=20, max_side=96):
    """Equivalente do espectrograma de audio, so que pra imagem: FFT 2D de cada canal RGB
    do frame de video, reduzida a um espectro RADIAL 1D (media da magnitude por faixa de
    distancia do centro da FFT) — exatamente a mesma ideia de "bucketar por faixa" que o
    audio faz por Hz, so que aqui a "frequencia" e ESPACIAL: perto do centro = variacao
    lenta no espaco (areas lisas/embacadas), longe do centro = variacao rapida (textura
    fina, ruido, bordas). Pula o bin central (DC, r=0 — e so o brilho medio, nao textura).
    Devolve [(raio, nivel_R, nivel_G, nivel_B), ...] agudo(borda)->grave(centro) ja
    invertido, nivel 0..1 relativo ao pico entre canais e faixas (auto-calibrado).

    ponytail: FFT2 no frame em resolucao cheia (640x480) leva uns 200ms — tempo demais
    rodando dentro do audio_thread, atrasa a leitura do proximo chunk de audio. Por isso usa
    `frame_downsample` antes (so pegando 1 a cada N pixels — nao precisa de qualidade, e so
    um espectro grosso de poucas faixas)."""
    arr = frame_downsample(frame, w, h, max_side)
    if arr is None:
        return []
    stride = max(1, max(w, h) // max_side)
    h, w = arr.shape[:2]
    key = (w, h, bars)
    if key not in _RADIAL_MASK_CACHE:
        cy, cx = h / 2, w / 2
        yy, xx = np.indices((h, w))
        r = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)
        max_r = min(cx, cy)
        edges = np.linspace(1.0, max_r, bars + 1)  # comeca em 1 (pula o DC em r=0)
        masks = [(r >= edges[i]) & (r < edges[i + 1]) for i in range(bars)]
        _RADIAL_MASK_CACHE[key] = (edges, masks)
    edges, masks = _RADIAL_MASK_CACHE[key]

    mags = np.zeros((3, bars))
    for c in range(3):
        spec = np.abs(np.fft.fftshift(np.fft.fft2(arr[:, :, c])))
        for i, m in enumerate(masks):
            mags[c, i] = spec[m].mean() if m.any() else 0.0

    peak_db = 20 * np.log10(mags.max() + 1e-6)
    db = 20 * np.log10(mags + 1e-6)
    levels = np.clip((db - peak_db + 40.0) / 40.0, 0.0, 1.0)

    out = []
    for i in reversed(range(bars)):  # borda (textura fina) em cima, centro (liso) embaixo
        out.append((edges[i + 1] * stride, levels[0, i], levels[1, i], levels[2, i]))
    return out


COLOR_SPECTRUM_RED = _rgb(255, 70, 70)
COLOR_SPECTRUM_GREEN = _rgb(70, 220, 70)
COLOR_SPECTRUM_BLUE = _rgb(90, 150, 255)


def frame_spectrum_rows(frame, w, h, bars=20, width=6):
    """Uma linha por faixa de frequencia espacial (frame_color_spectrum), com 3 barrinhas
    curtas lado a lado — R, G, B — cada uma na cor real do canal que representa. Sem
    numero de porcentagem por canal (a cor + tamanho da barra ja bastam) — largura curta
    de proposito, pra caber do lado do espectrograma de audio sem estourar o terminal."""
    lines = []
    for radius, lr, lg, lb in frame_color_spectrum(frame, w, h, bars):
        r_bar = tricolor_bar(int(round(lr * width)), width, base_color=COLOR_SPECTRUM_RED)
        g_bar = tricolor_bar(int(round(lg * width)), width, base_color=COLOR_SPECTRUM_GREEN)
        b_bar = tricolor_bar(int(round(lb * width)), width, base_color=COLOR_SPECTRUM_BLUE)
        lines.append(f'{int(radius):>4}px {r_bar}{g_bar}{b_bar}')
    return lines


def rgb_to_hsv_np(arr):
    """Mesma formula do colorsys.rgb_to_hsv, vetorizada (arr HxWx3, 0..255) — um loop por
    pixel em Python seria lento demais pra rodar a cada ~230ms dentro do audio_thread.
    Devolve (hue, sat, val), cada um 0..1, mesma shape HxW."""
    r, g, b = arr[..., 0] / 255.0, arr[..., 1] / 255.0, arr[..., 2] / 255.0
    maxc = np.maximum(np.maximum(r, g), b)
    minc = np.minimum(np.minimum(r, g), b)
    delta = maxc - minc
    sat = np.where(maxc > 1e-6, delta / np.where(maxc > 1e-6, maxc, 1.0), 0.0)
    safe_delta = np.where(delta > 1e-6, delta, 1.0)
    rc = (maxc - r) / safe_delta
    gc = (maxc - g) / safe_delta
    bc = (maxc - b) / safe_delta
    hue = np.where(maxc == r, bc - gc, np.where(maxc == g, 2.0 + rc - bc, 4.0 + gc - rc))
    hue = np.where(delta <= 1e-6, 0.0, (hue / 6.0) % 1.0)
    return hue, sat, maxc


def hue_histogram_rows(hue, sat, bins=12, width=24):
    """Histograma de matiz (hue, 0-360°) — o espectrograma de imagem mais parecido em
    espirito com o de audio: cada faixa E literalmente uma cor (nao so um numero), do
    mesmo jeito que cada faixa do espectro de audio e uma frequencia. Pesa cada pixel pela
    propria SATURACAO — um pixel cinza/sem cor tem hue matematico mas nao "e" nenhuma cor
    de verdade, entao conta pouco."""
    counts, edges = np.histogram(hue.ravel(), bins=bins, range=(0.0, 1.0), weights=sat.ravel())
    peak = counts.max() + 1e-9
    lines = []
    for i in range(bins):
        center = (edges[i] + edges[i + 1]) / 2
        r, g, b = colorsys.hsv_to_rgb(center, 1.0, 1.0)
        color = _rgb(int(r * 255), int(g * 255), int(b * 255))
        bar = tricolor_bar(int(round(counts[i] / peak * width)), width, base_color=color)
        lines.append(f'{int(round(center * 360)):>4}°  {bar}')
    return lines


def brightness_histogram_rows(val, bins=16, width=24):
    """Histograma de brilho (canal V do HSV, 0..1) — quantos pixels em cada faixa de
    brilho, claro em cima / escuro embaixo (mesmo sentido grave-embaixo do espectro de
    audio). Cada barra em tom de cinza igual ao brilho que ela representa."""
    counts, edges = np.histogram(val.ravel(), bins=bins, range=(0.0, 1.0))
    peak = counts.max() + 1e-9
    lines = []
    for i in reversed(range(bins)):
        center = (edges[i] + edges[i + 1]) / 2
        gray = int(center * 255)
        bar = tricolor_bar(int(round(counts[i] / peak * width)), width, base_color=_rgb(gray, gray, gray))
        lines.append(f'{gray:>3}  {bar}')
    return lines


def gradient(val):
    """Gradiente espacial simples (diferenca finita, NAO um kernel de Sobel de verdade —
    ponytail: rapido e da o suficiente pra um nivel/histograma, sem convolucao) do canal V.
    Calculado uma vez so no throttle e reaproveitado em 3 lugares (energia de borda,
    orientacao de borda, densidade de borda por regiao) pra nao repetir o np.diff."""
    gx = np.diff(val, axis=1)[:-1, :]
    gy = np.diff(val, axis=0)[:, :-1]
    return gx, gy


def laplacian_variance(val):
    """Variancia do Laplaciano (2a derivada espacial, por diferenca finita — sem kernel
    cv2, mesmo espirito do `gradient()`) — medida classica de nitidez: imagem em foco tem
    bastante variacao de alta frequencia (variancia alta), desfocada/borrada fica lisa
    (variancia baixa)."""
    center = val[1:-1, 1:-1]
    lap = val[:-2, 1:-1] + val[2:, 1:-1] + val[1:-1, :-2] + val[1:-1, 2:] - 4 * center
    return float(lap.var())


def brightness_entropy(val, bins=32):
    """Entropia de Shannon do histograma de brilho, normalizada 0..1 pelo maximo teorico
    (log2(bins)) — 0 = imagem lisa/uniforme (um valor so, zero informacao), perto de 1 =
    brilho espalhado por todas as faixas por igual (o mais "cheio de informacao" possivel).
    Diferente de nitidez: uma imagem borrada mas com MUITOS tons de cinza ainda tem entropia
    alta — sao medidas de coisas diferentes (foco vs. variedade tonal)."""
    counts, _ = np.histogram(val.ravel(), bins=bins, range=(0.0, 1.0))
    total = counts.sum()
    if total == 0:
        return 0.0
    p = counts[counts > 0] / total
    return float(-(p * np.log2(p)).sum()) / np.log2(bins)


def frame_meter_rows(arr, val, sat, gx, gy, prev_val, img_peaks, width=24):
    """Medidores globais de 1 numero (nao-espectrograma) da imagem que NAO tem versao em
    grid em `spatial_grids_section` (brilho, saturacao, temp., contraste, nitidez,
    entropia, bordas e movimento tem grid — ficariam repetidos aqui, entao so aparecem la):
    simetria (metade esquerda vs. direita espelhada, escala heuristica *4 — sem teto
    natural, e so "o quanto" comparado ao maximo raramente atingido numa foto real);
    clipping (% de pixels estourados/escurecidos); correlacao entre canais R/G/B (baixa =
    imagem bem colorida, alta = quase monocromatica); e centro de massa do brilho (onde na
    tela esta o "peso" visual, 0,0 = canto superior esquerdo).

    Ainda assim CALCULA (mas nao imprime) nitidez/bordas/movimento, porque essas tres
    atualizam `img_peaks` (auto-gain por pico decaindo) e movimento atualiza `prev_val[0]`
    — estado que `spatial_grids_section` precisa ler pra normalizar o grid dela; sem rodar
    esse calculo aqui, o grid ficaria sem peso nenhum pra comparar. `prev_val` e uma lista
    de 1 elemento (estado entre chamadas); devolve as linhas prontas."""
    hw = val.shape[1] // 2
    sym_diff = float(np.abs(val[:, :hw] - val[:, val.shape[1] - hw:][:, ::-1]).mean())
    symmetry_level = max(0.0, 1.0 - sym_diff * 4.0)

    sharpness_raw = laplacian_variance(val)
    img_peaks['sharpness'] = max(sharpness_raw, img_peaks['sharpness'] * tuning.PEAK_DECAY, 1e-6)

    edge_raw = float(np.sqrt(gx ** 2 + gy ** 2).mean())
    img_peaks['edge'] = max(edge_raw, img_peaks['edge'] * tuning.PEAK_DECAY, 1e-6)

    if prev_val[0] is not None and prev_val[0].shape == val.shape:
        motion_raw = float(np.abs(val - prev_val[0]).mean())
    else:
        motion_raw = 0.0
    img_peaks['motion'] = max(motion_raw, img_peaks['motion'] * tuning.PEAK_DECAY, 1e-6)
    prev_val[0] = val

    overexposed = float((val > 0.95).mean())
    underexposed = float((val < 0.05).mean())

    r, g, b = arr[..., 0].ravel(), arr[..., 1].ravel(), arr[..., 2].ravel()
    with np.errstate(invalid='ignore'):
        corr_rg = float(np.nan_to_num(np.corrcoef(r, g)[0, 1]))
        corr_rb = float(np.nan_to_num(np.corrcoef(r, b)[0, 1]))
        corr_gb = float(np.nan_to_num(np.corrcoef(g, b)[0, 1]))

    yy, xx = np.indices(val.shape)
    total = float(val.sum()) + 1e-9
    cx = float((xx * val).sum()) / total / max(1, val.shape[1] - 1)
    cy = float((yy * val).sum()) / total / max(1, val.shape[0] - 1)

    return [
        _meter_row('Simetria', symmetry_level, f'{symmetry_level:.2f}', {}, width),
        f'{"Clipping":>{LABEL_W}}  estourado {overexposed * 100:4.1f}%   escuro {underexposed * 100:4.1f}%',
        f'{"Correlação":>{LABEL_W}}  R↔G {corr_rg:+.2f}  R↔B {corr_rb:+.2f}  G↔B {corr_gb:+.2f}',
        f'{"Centro":>{LABEL_W}}  x={cx:.2f}  y={cy:.2f}  (0,0 = canto sup-esq)',
    ]


def colorfulness(arr):
    """Metrica classica (Hasler & Susstrunk, 2003) de "quao colorida" a imagem e — mais
    rigorosa que so a saturacao media, usa a dispersao dos canais opostos rg (R-G) e yb
    (amarelo-azul, aproximado). Sem teto natural, precisa de auto-gain (igual bordas/
    nitidez/movimento)."""
    r, g, b = arr[..., 0], arr[..., 1], arr[..., 2]
    rg = r - g
    yb = 0.5 * (r + g) - b
    return float(np.sqrt(rg.std() ** 2 + yb.std() ** 2) + 0.3 * np.sqrt(rg.mean() ** 2 + yb.mean() ** 2))


def unique_colors(arr):
    """Conta cores distintas depois de quantizar pra 5 bits por canal (mesmo esquema do
    `dominant_color`) — mede complexidade da paleta sem precisar de k-means."""
    quant = arr.astype(np.uint32) >> 3
    packed = (quant[..., 0] << 10) | (quant[..., 1] << 5) | quant[..., 2]
    return int(np.unique(packed).size)


def hue_range_fraction(hue, sat, lo_deg=0.0, hi_deg=50.0, sat_min=0.15):
    """Fracao de pixels "coloridos de verdade" (saturacao > sat_min — senao o matiz nao
    quer dizer nada, pixel cinza tem hue matematico mas sem sentido) cujo matiz cai no
    intervalo [lo_deg, hi_deg) graus. Default cobre tons quentes/pele (vermelho-laranja)."""
    colored = sat > sat_min
    if not colored.any():
        return 0.0
    deg = hue[colored] * 360.0
    return float(((deg >= lo_deg) & (deg < hi_deg)).mean())


def color_stats_rows(arr, hue, sat, prev_dominant, img_peaks, width=24):
    """Medidores especificos de COR (nao brilho/estrutura — esses estao em
    `frame_meter_rows`): cor media (media de verdade dos pixels — diferente da cor
    dominante, que e a MODA/mais frequente, calculada em `dominant_color`; podem divergir
    bastante — um fundo grande e uniforme puxa a moda, mas nao necessariamente a media);
    coloridez (Hasler & Susstrunk, auto-gain via `img_peaks`); paleta (cores unicas
    quantizadas, complexidade sem k-means); mudanca de cor (distancia euclidiana em RGB
    entre a cor media desse frame e do frame anterior — 0..1 natural (255*sqrt(3) e o
    maximo teorico) — a versao "cor" do medidor Movimento, que so olha brilho); e tons
    quentes/pele (fracao dos pixels coloridos numa faixa de matiz). `prev_dominant` e uma
    lista de 1 elemento (estado entre chamadas, RGB 0..255); devolve as linhas prontas."""
    cf_raw = colorfulness(arr)
    img_peaks['colorfulness'] = max(cf_raw, img_peaks['colorfulness'] * tuning.PEAK_DECAY, 1e-6)
    cf_level = min(1.0, cf_raw / img_peaks['colorfulness'])

    mr, mg, mb = (int(round(c)) for c in arr.mean(axis=(0, 1)))
    mean_swatch = f'\033[48;2;{mr};{mg};{mb}m      \033[0m'

    total_px = arr.shape[0] * arr.shape[1]
    n_unique = unique_colors(arr)
    unique_level = min(1.0, n_unique / total_px)

    cur_mean = np.array([mr, mg, mb], dtype=np.float32)
    if prev_dominant[0] is not None:
        color_change = min(1.0, float(np.linalg.norm(cur_mean - prev_dominant[0])) / (255.0 * np.sqrt(3)))
    else:
        color_change = 0.0
    prev_dominant[0] = cur_mean

    warm_frac = hue_range_fraction(hue, sat)

    return [
        f'{"Cor média":>{LABEL_W}}  {mean_swatch}  RGB({mr},{mg},{mb})',
        _meter_row('Coloridez', cf_level, f'{cf_level:.2f}', {}, width),
        f'{"Paleta":>{LABEL_W}}  {n_unique} / {total_px} px ({unique_level * 100:.1f}%)',
        _meter_row('Mud. cor', color_change, f'{color_change:.2f}', {}, width),
        _meter_row('Tom quente', warm_frac, f'{warm_frac:.2f}', {}, width),
    ]


def edge_orientation_rows(gx, gy, bins=9, width=20):
    """Histograma de ORIENTACAO de borda (angulo da linha, 0-180° — 0 e 180 sao a mesma
    orientacao, por isso mod 180 em vez de 360) — nao e "quanta borda tem" (isso e o
    medidor `Bordas` do RESUMO), e "pra que lado as bordas apontam": cena com muita linha
    horizontal (ex. horizonte) vs. vertical (ex. predios) vs. diagonal. Pesado pela
    MAGNITUDE do gradiente, mesmo esquema do hue_histogram_rows (area lisa sem borda conta
    pouco). Cor de cada faixa mapeia o angulo pra uma cor (so pra distinguir visualmente,
    sem significado de matiz de verdade)."""
    mag = np.sqrt(gx ** 2 + gy ** 2)
    angle = np.degrees(np.arctan2(gy, gx)) % 180.0
    counts, edges = np.histogram(angle.ravel(), bins=bins, range=(0.0, 180.0), weights=mag.ravel())
    peak = counts.max() + 1e-9
    lines = []
    for i in range(bins):
        center = (edges[i] + edges[i + 1]) / 2
        r, g, b = colorsys.hsv_to_rgb(center / 180.0, 0.8, 1.0)
        color = _rgb(int(r * 255), int(g * 255), int(b * 255))
        bar = tricolor_bar(int(round(counts[i] / peak * width)), width, base_color=color)
        lines.append(f'{int(round(center)):>3}°  {bar}')
    return lines


def cell_reduce(fn, h, w, grid=3):
    """Aplica `fn(y0,y1,x0,x1)` numa area HxW dividida num grid `grid`x`grid` (ultima
    celula de cada eixo pega o resto, pra cobrir a imagem toda mesmo quando o tamanho nao
    divide exato) — devolve um array (grid,grid) com o resultado de cada celula. Base de
    todos os grids espaciais abaixo, pra nao repetir o particionamento em cada um."""
    out = np.zeros((grid, grid))
    for i in range(grid):
        y0, y1 = i * h // grid, h if i == grid - 1 else (i + 1) * h // grid
        for j in range(grid):
            x0, x1 = j * w // grid, w if j == grid - 1 else (j + 1) * w // grid
            out[i, j] = fn(y0, y1, x0, x1)
    return out


def gray_bg(level):
    g = int(round(np.clip(level, 0.0, 1.0) * 255))
    return f'\033[48;2;{g};{g};{g}m'


def temp_bg(level):
    """level = R-B medio normalizado (-1..1, mesma unidade do medidor `Temp. cor`) — cinza
    neutro no meio, esquenta pra laranja ou esfria pra azul conforme o sinal (mesma escala
    heuristica *3 do medidor global)."""
    t = min(1.0, abs(level) * 3.0)
    base = (255, 140, 80) if level > 0 else (120, 170, 255)
    r, g, b = (int(128 + (c - 128) * t) for c in base)
    return f'\033[48;2;{r};{g};{b}m'


def grid_rows(levels, color_fn=gray_bg, cell_w=4):
    """`levels`: array (grid,grid) ja normalizado (0..1 pra gray_bg, -1..1 pra temp_bg).
    Devolve `grid` linhas, um bloco colorido por celula lado a lado."""
    return [' '.join(f'{color_fn(v)}{" " * cell_w}\033[0m' for v in row) for row in levels]


def grid_total(levels):
    """Media dos 9 blocos de um grid, em modulo, 0..1 — o "quanto no total" desse metro
    (mesmo numero que o medidor escalar equivalente mostraria)."""
    return float(np.clip(np.abs(levels).mean(), 0.0, 1.0))


def bipolar_bar(t, width, cold_color, warm_color):
    """Barra horizontal CENTRADA em zero (`t` de -1 a 1, sem modulo — TEMP. e a unica
    metrica com sinal de verdade, as outras sao 0..1). O meio da barra e o zero; positivo
    enche pra DIREITA (`warm_color`), negativo enche pra ESQUERDA (`cold_color`). O
    caractere central fica marcado mesmo quando t=0, pra sempre dar pra ver onde fica o
    zero."""
    t = max(-1.0, min(1.0, t))
    mid = width // 2
    filled = int(round(abs(t) * mid))
    chars = []
    for i in range(width):
        if t > 0 and mid <= i < mid + filled:
            chars.append(f'{warm_color}█\033[0m')
        elif t < 0 and mid - filled <= i < mid:
            chars.append(f'{cold_color}█\033[0m')
        elif i == mid:
            chars.append('\033[2m│\033[0m')
        else:
            chars.append('\033[2m░\033[0m')
    return ''.join(chars)


def spatial_grids_section(arr, val, sat, gx, gy, prev_val_before, img_peaks, grid=3, cell_w=4):
    """A versao "onde" de cada medidor escalar do RESUMO, todos lado a lado num grid
    espacial (3x3 por padrao) — diferente do resto (que sao listas 1D tipo espectrograma),
    isso e um mapa 2D: mostra ONDE na tela esta o brilho/detalhe/movimento, nao so quanto
    no total. Normaliza cada celula com a MESMA regra do medidor escalar equivalente
    (auto-gain de pico via `img_peaks` pra Bordas/Nitidez/Movimento, escala fixa pra
    Contraste, 0..1 natural pra Brilho/Saturacao/Entropia) — a media dos 9 blocos de cada
    grid fica proxima do numero que o medidor global (RESUMO) mostra pro mesmo frame.
    `prev_val_before` precisa ser o V do frame ANTERIOR capturado ANTES de chamar
    `frame_meter_rows` (que sobrescreve esse estado) — senao o grid de Movimento compara o
    frame com ele mesmo."""
    h, w = val.shape
    gh, gw = gx.shape

    brilho = cell_reduce(lambda y0, y1, x0, x1: val[y0:y1, x0:x1].mean(), h, w, grid)
    sat_c = cell_reduce(lambda y0, y1, x0, x1: sat[y0:y1, x0:x1].mean(), h, w, grid)
    temp_c = cell_reduce(lambda y0, y1, x0, x1: (arr[y0:y1, x0:x1, 0].mean()
                                                  - arr[y0:y1, x0:x1, 2].mean()) / 255.0, h, w, grid)
    contrast_c = cell_reduce(lambda y0, y1, x0, x1: min(1.0, float(val[y0:y1, x0:x1].std()) * 2.5), h, w, grid)
    sharp_raw = cell_reduce(lambda y0, y1, x0, x1: laplacian_variance(val[y0:y1, x0:x1]), h, w, grid)
    sharp_c = np.minimum(1.0, sharp_raw / img_peaks['sharpness'])
    entropy_c = cell_reduce(lambda y0, y1, x0, x1: brightness_entropy(val[y0:y1, x0:x1]), h, w, grid)
    edge_raw = cell_reduce(lambda y0, y1, x0, x1: np.sqrt(gx[y0:y1, x0:x1] ** 2 + gy[y0:y1, x0:x1] ** 2).mean(),
                            gh, gw, grid)
    edge_c = np.minimum(1.0, edge_raw / img_peaks['edge'])
    if prev_val_before is not None and prev_val_before.shape == val.shape:
        motion_raw = cell_reduce(lambda y0, y1, x0, x1: float(np.abs(
            val[y0:y1, x0:x1] - prev_val_before[y0:y1, x0:x1]).mean()), h, w, grid)
    else:
        motion_raw = np.zeros((grid, grid))
    motion_c = np.minimum(1.0, motion_raw / img_peaks['motion'])

    metrics = [('BRILHO', brilho, gray_bg), ('SATURAÇÃO', sat_c, gray_bg), ('TEMP.', temp_c, temp_bg),
               ('CONTRASTE', contrast_c, gray_bg), ('NITIDEZ', sharp_c, gray_bg), ('ENTROPIA', entropy_c, gray_bg),
               ('BORDAS', edge_c, gray_bg), ('MOVIMENTO', motion_c, gray_bg)]

    block_w = grid * cell_w + (grid - 1)  # celulas + os espacos que grid_rows poe entre elas
    # titulo JA com o valor total (ex. "BRILHO 30%"), a barra do total logo abaixo do
    # titulo, e so depois o grid espacial em si — nessa ordem: quanto no total primeiro,
    # onde na tela depois. TEMP. e a unica com sinal de verdade (quente/frio) — em vez da
    # barra 0..1 padrao, usa uma barra CENTRADA em zero (azul p/ frio, esquerda; vermelho
    # p/ quente, direita), igual foi pedido.
    header_parts, bar_parts = [], []
    for name, levels, color_fn in metrics:
        if name == 'TEMP.':
            t = float(np.clip(levels.mean(), -1.0, 1.0))
            label = f'{name} {t:+.2f}'
            bar = bipolar_bar(t, block_w, cold_color=_rgb(90, 150, 255), warm_color=_rgb(255, 90, 90))
        else:
            t = grid_total(levels)
            label = f'{name} {t:.2f}'
            bar = tricolor_bar(int(round(t * block_w)), block_w, base_color=NO_BAND_COLOR)
        header_parts.append(f'{label:^{block_w}}')
        bar_parts.append(bar)
    header = '  '.join(header_parts)
    total_bar_row = '  '.join(bar_parts)
    per_metric_rows = [grid_rows(levels, color_fn, cell_w) for _, levels, color_fn in metrics]
    rows = ['  '.join(pm[r] for pm in per_metric_rows) for r in range(grid)]
    return [header, total_bar_row] + rows


def pick_audio_source(name=None):
    if name:
        return name
    sink = subprocess.check_output(['pactl', 'get-default-sink']).decode().strip()
    return sink + '.monitor'


IMG_TERM_COLS, IMG_TERM_ROWS = 150, 55  # geometria fixa da janela nova de analise de imagem


def open_terminal_window(title):
    """Abre um terminal novo so pra exibir o que a gente escrever num FIFO — devolve o file
    object aberto pra escrita (repassa pro print(..., file=...) de quem for usar). None se
    nao achar terminal/DISPLAY (a funcao chamadora cai pra nao mostrar essa parte, sem travar
    o programa). ponytail: so gnome-terminal (o que tem instalado nessa maquina) — cada
    emulator tem flag de geometria/execucao diferente, suportar todos e trabalho demais pra
    um script pessoal. Troca o comando abaixo se seu ambiente usar outro (konsole, kitty...)."""
    if not shutil.which('gnome-terminal') or not os.environ.get('DISPLAY'):
        print(f'sem gnome-terminal ou $DISPLAY: "{title}" fica desligado')
        return None
    fifo_path = f'/tmp/native_synth_{title.replace(" ", "_")}_{os.getpid()}.fifo'
    os.mkfifo(fifo_path)
    cmd = f"cat '{fifo_path}'; echo; read -p 'terminal encerrado — enter pra fechar'"
    subprocess.Popen(['gnome-terminal', f'--title={title}', '--full-screen',
                       f'--geometry={IMG_TERM_COLS}x{IMG_TERM_ROWS}', '--', 'bash', '-c', cmd])
    stream = open(fifo_path, 'w', buffering=1)  # bloqueia ate o terminal abrir o fifo pra leitura
    os.remove(fifo_path)  # tira o nome do filesystem; o fd em si continua valido pros dois lados
    return stream


def redraw(stream, lines, prev_line_count, term_cols):
    """Desenha `lines` num terminal com redraw incremental (sobe o cursor e reescreve so o
    bloco, sem piscar). `prev_line_count` e uma lista de 1 elemento — estado mutavel entre
    chamadas, um por stream (cada terminal tem o seu). ponytail: "subir cursor N linhas" so
    funciona se nenhuma linha QUEBRAR na tela (janela mais estreita que o conteudo) — senao
    1 linha logica vira 2+ fisicas e o calculo erra, corrompendo o topo do bloco. Se algo
    nao couber em `term_cols`, cai pro clear completo (\033[2J) so nesse frame."""
    if not prev_line_count[0]:
        print('\033[?1049h', end='', file=stream)  # tela alternada, sem sujar o scrollback
    fits = all(visible_len(line) <= term_cols for line in lines)
    if fits and prev_line_count[0]:
        print(f'\033[{prev_line_count[0]}A', end='', file=stream)  # sobe pro topo do bloco anterior
        extra = max(0, prev_line_count[0] - len(lines))
        # \n no final de cada linha (inclusive a ultima) — sem isso o cursor fica EM CIMA da
        # ultima linha, nao embaixo, e o "sobe cursor" erra por 1 toda vez
        out = ''.join('\033[K' + line + '\n' for line in lines)
        out += '\033[K\n' * extra  # bloco novo ficou menor que o anterior — limpa a sobra
        print(out, end='', flush=True, file=stream)
        prev_line_count[0] = len(lines) + extra
    else:
        print('\033[2J\033[H' + '\n'.join(lines), end='', flush=True, file=stream)
        prev_line_count[0] = len(lines)


def close_alt_screen(stream, prev_line_count):
    if prev_line_count[0]:
        print('\033[?1049l', end='', flush=True, file=stream)  # sai da tela alternada


def audio_thread(device, img_stream=None):
    try:
        proc = subprocess.Popen(
            ['parec', '--device=' + device, '--format=s16le', '--rate=44100',
             '--channels=1', '--latency-msec=50'],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
    except FileNotFoundError:
        print('sem audio: "parec" nao encontrado (pacote pulseaudio-utils)')
        return
    print('audio: capturando', device)
    chunk_samples = 1024
    chunk_bytes = chunk_samples * 2
    rate = 44100
    window = np.hanning(chunk_samples)
    freqs = np.fft.rfftfreq(chunk_samples, d=1 / rate)

    def recompute_bins():
        # bass_bins/mid_bins/treble_bins dependem de tuning.BASS_MID_HZ/MID_TREBLE_HZ —
        # precisam ser recalculados toda vez que o tuning.py recarrega
        return (freqs < tuning.BASS_MID_HZ,
                (freqs >= tuning.BASS_MID_HZ) & (freqs < tuning.MID_TREBLE_HZ),
                freqs >= tuning.MID_TREBLE_HZ)

    bass_bins, mid_bins, treble_bins = recompute_bins()
    band_smoothing = band_smoothing_map()  # {chave: SMOOTHING daquela banda}, grave->agudo
    tuning_mtime = os.path.getmtime(TUNING_PATH)
    smooth = {'amp': 0.0, 'bass': 0.0, 'mid': 0.0, 'treble': 0.0, **{k: 0.0 for k in FREQ_BAND_UNIFORM.values()}}
    smoothing_used = dict(smooth)  # ultimo smoothing (attack ou release) aplicado em cada chave
    band_peaks = {name: 1e-6 for name, _, _, _ in FREQ_BANDS}  # auto-gain: teto recente de cada banda
    kick_baseline = 0.0
    kick_env = 0.0
    kick_decay_dynamic = tuning.KICK_DECAY  # ate a 1a batida ter intervalo medido, usa o fixo
    kick_chunk_count = 0
    kick_last_hit_chunk = 0
    monitor_frame = [0]
    prev_line_count = [0]
    prev_line_count_img = [0]
    prev_val = [None]  # frame reduzido (canal V) do throttle anterior — pro medidor de movimento
    prev_dominant = [None]  # cor media (RGB) do throttle anterior — pro medidor de mudanca de cor
    img_peaks = {'edge': 1e-6, 'motion': 1e-6, 'sharpness': 1e-6, 'colorfulness': 1e-6}  # auto-gain
    smooth_spectrum = np.zeros(len(freqs))  # espectrograma piscava: era FFT crua, sem suavizar
    try:
        while running:
            # hot-reload do tuning.py — mesmo esquema do image.frag, so que pro lado Python:
            # olha o mtime, recarrega o modulo, recalcula o que depende dos limiares de Hz
            try:
                m = os.path.getmtime(TUNING_PATH)
                if m != tuning_mtime:
                    tuning_mtime = m
                    importlib.reload(tuning)
                    bass_bins, mid_bins, treble_bins = recompute_bins()
                    band_smoothing = band_smoothing_map()
                    print('tuning.py recarregado')
            except FileNotFoundError:
                pass
            data = read_exact(proc.stdout, chunk_bytes)
            if data is None:
                err = proc.stderr.read().decode(errors='ignore').strip()
                print('audio parou' + (': ' + err if err else ''))
                break
            samples = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
            spectrum = np.abs(np.fft.rfft(samples * window))
            smooth_spectrum = smooth_spectrum * tuning.SMOOTHING + spectrum * (1 - tuning.SMOOTHING)
            bass_raw = float(spectrum[bass_bins].mean())
            mid_raw = float(spectrum[mid_bins].mean())
            treble_raw = float(spectrum[treble_bins].mean())
            amp_raw = float(np.sqrt(np.mean(samples ** 2)))  # RMS do sinal normalizado (-1..1), sem escala
            raw = {
                'amp': min(1.0, amp_raw * 4.0),
                'bass': min(1.0, bass_raw * tuning.BASS_SCALE),
                'mid': min(1.0, mid_raw * tuning.MID_SCALE),
                'treble': min(1.0, treble_raw * tuning.TREBLE_SCALE),
            }
            # faixas finas (Sub-bass..Air) — todo chunk, nao so no throttle do monitor,
            # porque agora controlam uniforms de verdade (u_subbass..u_air). "level" ja
            # vem 0..1 (relativo ao pico ENTRE as 8 bandas, auto-calibrado, sem escala
            # manual por banda) — so falta suavizar igual as outras.
            named_levels = named_band_levels(spectrum, freqs, FREQ_BANDS, band_peaks, tuning.PEAK_DECAY)
            for name, _, level in named_levels:
                raw[FREQ_BAND_UNIFORM[name]] = level
            for k in smooth:
                # release: as 8 bandas finas usam o proprio (grave rapido, agudo estavel);
                # amp/bass/mid/treble classico usa o SMOOTHING global. attack (subindo) e
                # sempre mais rapido que o release, por isso o valor muda sozinho a cada
                # instante em vez de ficar travado num numero fixo por banda.
                release = band_smoothing.get(k, tuning.SMOOTHING)
                attack = release * tuning.ATTACK_RATIO
                s = attack if raw[k] > smooth[k] else release
                smoothing_used[k] = s
                smooth[k] = smooth[k] * s + raw[k] * (1 - s)
                state[k] = smooth[k]

            kick_chunk_count += 1
            # bass_raw (sem teto) em vez de raw['bass'] (clampado em 1.0) — com o clamp, se
            # o grave ficar forte por uns segundos o kick_baseline sobe a ponto do limiar
            # (baseline*THRESHOLD) passar de 1.0, ficando matematicamente impossivel de bater
            kick_baseline = kick_baseline * 0.95 + bass_raw * 0.05
            # aquecimento: so nos primeiros KICK_WARMUP_CHUNKS o baseline ainda nao
            # representa o "chao" de verdade (comeca em 0.0) — sem isso, qualquer som logo
            # no inicio dispara falso positivo. So acontece uma vez, no começo do programa.
            if kick_chunk_count > tuning.KICK_WARMUP_CHUNKS and bass_raw > kick_baseline * tuning.KICK_THRESHOLD:
                # decay adaptativo: mede quantos chunks se passaram desde a ULTIMA batida e
                # recalcula o decay pra o envelope cair ate KICK_FADE_FLOOR nesse intervalo
                # (musica rapida decai rapido, lenta decai devagar) — so depois da 2a batida
                # em diante, a 1a nao tem intervalo pra medir ainda
                interval_chunks = kick_chunk_count - kick_last_hit_chunk
                kick_last_hit_chunk = kick_chunk_count
                if interval_chunks > 1:
                    target_chunks = interval_chunks * tuning.KICK_DECAY_FRACTION
                    raw_decay = tuning.KICK_FADE_FLOOR ** (1.0 / max(target_chunks, 1.0))
                    kick_decay_dynamic = min(tuning.KICK_DECAY_MAX, max(tuning.KICK_DECAY_MIN, raw_decay))
                kick_env = 1.0
            else:
                kick_env *= kick_decay_dynamic
            state['kick'] = kick_env

            # ponytail: monitor pra calibrar as *_SCALE por olho — se o "final" ficar sempre
            # perto de 1.00, o "bruto" mostra o numero real pra escolher a escala certa
            # (SCALE ~= 1 / bruto no pico que voce quer que bata 1.0). so imprime 1x a cada
            # ~230ms (10 chunks de 23ms) pra nao inundar o terminal.
            monitor_frame[0] += 1
            if monitor_frame[0] % 10 == 0:
                # tabela principal: so as 8 bandas finas (ja calculadas acima, todo chunk),
                # do agudo pro grave — simetrica agora (8 bruto x 8 final). bass/mid/treble
                # classico continua rodando e mandando pro shader (u_bass etc.), so nao
                # aparece mais aqui — as 8 bandas finas cobrem o mesmo espectro com mais
                # resolucao.
                merged_colors = {name: color for name, _, _, color in FREQ_BANDS}
                band_entries = list(reversed(named_levels))  # (nome, mag, nivel) x8, agudo->grave
                band_final_meters = [(name, state[FREQ_BAND_UNIFORM[name]]) for name, _, _ in band_entries]
                # amp entra no topo da tabela (nao e banda de frequencia — sem cor propria,
                # NO_BAND_COLOR — mas cabe na mesma estrutura BRUTO/FINAL/SMOOTH/Δ)
                all_entries = [('amp', amp_raw, raw['amp'])] + band_entries
                all_final_meters = [('amp', state['amp'])] + band_final_meters
                meters_header = (f'{"BRUTO":^50}   {"FINAL":^48}   {"SMOOTH":^20}   {"Δ bruto→final":^20}')
                bruto_lines = bruto_rows(all_entries, colors=merged_colors)
                final_lines = final_rows(all_final_meters, colors=merged_colors)
                # dois graficos extra, colados depois do FINAL: o smoothing REALMENTE usado
                # nesse chunk (attack ou release, o que valeu) e a diferenca real entre bruto
                # (cru) e final (suavizado) desse instante — ambos em cinza neutro
                # (NO_BAND_COLOR), sem cor de banda.
                meters_side_by_side = []
                for (b, f), (name, _, level), (_, final_val) in zip(zip(bruto_lines, final_lines),
                                                                      all_entries, all_final_meters):
                    s = smoothing_used[FREQ_BAND_UNIFORM.get(name, name)]  # 'amp' ja e a propria chave
                    smoothing_bar = tricolor_bar(int(round(s * 15)), 15, base_color=NO_BAND_COLOR)
                    smoothing_part = f'{smoothing_bar} {s:.2f}'
                    delta = min(1.0, abs(final_val - level))
                    delta_bar = tricolor_bar(int(round(delta * 15)), 15, base_color=NO_BAND_COLOR)
                    meters_side_by_side.append(f'{b}   {f}   {smoothing_part}   {delta_bar} {delta:.2f}')

                # kick: nao e banda de frequencia (nao tem cor propria, nao tem bruto — so o
                # pulso), entao fica em secao propria, separada da tabela. Sem Δ (nao ha
                # bruto pra comparar).
                kick_header = 'KICK'
                kick_col_header = f'{"":^50}   {"FINAL":^48}   {"DECAY":^20}'
                kick_pad = ' ' * 50 + '   '
                kick_final_part = final_rows([('kick', kick_env)], colors=merged_colors)[0]
                kick_decay_part = (f'{tricolor_bar(int(round(kick_decay_dynamic * 15)), 15, base_color=NO_BAND_COLOR)}'
                                    f' {kick_decay_dynamic:.2f}')
                kick_line = f'{kick_pad}{kick_final_part}   {kick_decay_part}'
                kick_section = [kick_header, kick_col_header, kick_line]

                rel_lines = spectrum_column(smooth_spectrum, freqs)
                db_lines = spectrum_column_db(smooth_spectrum, freqs)
                spectro_header = (f'{"ABSOLUTO (dB real, nao normalizado)":^52}   '
                                   f'{"RELATIVO (% do pico do frame)":^50}')
                spectro_side_by_side = [f'{d}   {r}' for d, r in zip(db_lines, rel_lines)]

                lines = (
                    kick_section
                    + ['', 'FAIXAS DE MIXAGEM', meters_header] + meters_side_by_side
                    + ['', 'ESPECTROGRAMA', spectro_header] + spectro_side_by_side
                )
                term_cols = shutil.get_terminal_size(fallback=(120, 40)).columns
                redraw(sys.stdout, lines, prev_line_count, term_cols)

                # toda analise de imagem sai do dash principal — vai pra janela de terminal
                # propria (aberta uma vez em main()), largura maior aqui ja que nao precisa
                # mais caber espremido do lado de ABSOLUTO/RELATIVO
                if img_stream is not None:
                    arr_small = frame_downsample(state['frame'], WIDTH, HEIGHT)
                    if arr_small is not None:
                        hue, sat, val = rgb_to_hsv_np(arr_small)
                        gx, gy = gradient(val)  # calculado uma vez, usado nos medidores + 2 secoes abaixo
                        dr, dg, db = state['dominant']
                        r255, g255, b255 = int(dr * 255), int(dg * 255), int(db * 255)
                        swatch = f'\033[48;2;{r255};{g255};{b255}m      \033[0m'
                        dominant_line = f'{"Cor dominante":>{LABEL_W}}  {swatch}  RGB({r255},{g255},{b255})'
                        # os 4 espectrogramas ficam LADO A LADO (nao empilhados) pra caber
                        # tudo numa tela so, sem precisar rolar — mesmo esquema do dash
                        # principal (ABSOLUTO/RELATIVO lado a lado). zip_longest porque cada
                        # um tem um numero de faixas diferente; pad_visible alinha a coluna
                        # certo mesmo com os codigos ANSI de cor no meio da string.
                        hue_lines = hue_histogram_rows(hue, sat)
                        bright_lines = brightness_histogram_rows(val)
                        color_lines = frame_spectrum_rows(state['frame'], WIDTH, HEIGHT, width=14)
                        orient_lines = edge_orientation_rows(gx, gy)
                        col_widths = [max(visible_len(l) for l in col)
                                      for col in (hue_lines, bright_lines, color_lines, orient_lines)]
                        headers = ['MATIZ (hue)', 'BRILHO (V)', 'CORES (FFT 2D espacial)', 'ORIENT. BORDA']
                        col_header = '   '.join(f'{h:^{w}}' for h, w in zip(headers, col_widths))
                        rows_4col = [
                            '   '.join(pad_visible(v, w) for v, w in zip(row, col_widths))
                            for row in zip_longest(hue_lines, bright_lines, color_lines, orient_lines, fillvalue='')
                        ]
                        # captura o V do frame anterior ANTES do frame_meter_rows sobrescrever
                        # (ele guarda o V atual em prev_val[0] no final) — senao o grid de
                        # Movimento abaixo compara o frame com ele mesmo
                        prev_val_before = prev_val[0]
                        meter_lines = frame_meter_rows(arr_small, val, sat, gx, gy, prev_val, img_peaks)
                        color_lines_stats = color_stats_rows(arr_small, hue, sat, prev_dominant, img_peaks)
                        grid_lines = spatial_grids_section(arr_small, val, sat, gx, gy, prev_val_before, img_peaks)
                        img_lines = (
                            ['RESUMO', dominant_line] + meter_lines + color_lines_stats
                            + ['', 'ONDE NA TELA (grid 3x3 — mesmos medidores do RESUMO, por regiao)']
                            + grid_lines
                            + ['', 'ANÁLISE ESPACIAL', col_header] + rows_4col
                        )
                        redraw(img_stream, img_lines, prev_line_count_img, IMG_TERM_COLS)
    finally:
        proc.terminate()
        close_alt_screen(sys.stdout, prev_line_count)
        if img_stream is not None:
            close_alt_screen(img_stream, prev_line_count_img)


def dominant_color(frame, w, h):
    """Cor mais frequente do frame — quantiza cada canal pra 32 niveis (5 bits) e conta
    qual combinacao aparece mais. Rapido: e so um unique/count num array de inteiros."""
    arr = frame.reshape(h, w, 3)
    quant = (arr >> 3).astype(np.uint32)  # 0..255 -> 0..31 por canal
    packed = (quant[..., 0] << 10) | (quant[..., 1] << 5) | quant[..., 2]
    vals, counts = np.unique(packed, return_counts=True)
    top = int(vals[np.argmax(counts)])
    r = ((top >> 10) & 31) << 3
    g = ((top >> 5) & 31) << 3
    b = (top & 31) << 3
    return r / 255.0, g / 255.0, b / 255.0


def dominant_color_thread():
    # roda em thread separada, nao no loop de render: um frame 720p pode levar mais de
    # 100ms nesse calculo, o que travaria o fps se rodasse ali. cor dominante muda devagar
    # mesmo, nao precisa recalcular 30x/segundo — um sleep pequeno ja poupa CPU.
    while running:
        try:
            state['dominant'] = dominant_color(state['frame'], WIDTH, HEIGHT)
        except ValueError:
            pass  # frame ainda no tamanho antigo bem no instante de um resize/troca de fonte
        time.sleep(0.1)


def compile_shader(src, kind):
    s = glCreateShader(kind)
    glShaderSource(s, src)
    glCompileShader(s)
    if not glGetShaderiv(s, GL_COMPILE_STATUS):
        raise RuntimeError(glGetShaderInfoLog(s).decode())
    return s


def build_program(frag_src):
    prog = glCreateProgram()
    glAttachShader(prog, compile_shader(VERT_SRC, GL_VERTEX_SHADER))
    glAttachShader(prog, compile_shader(frag_src, GL_FRAGMENT_SHADER))
    glLinkProgram(prog)
    if not glGetProgramiv(prog, GL_LINK_STATUS):
        raise RuntimeError(glGetProgramInfoLog(prog).decode())
    return prog


def main():
    global running, WIDTH, HEIGHT, WIN_W, WIN_H, FRAME_SIZE

    def handle_sigterm(signum, frame):
        # SIGTERM (ex. o watch_synth.sh reiniciando o processo) nao roda blocos "finally"
        # do Python — sem isso, o audio_thread morre no meio da tela alternada e o
        # terminal fica travado nela. So sinaliza; quem limpa e o "while running" de cada
        # thread, no fluxo normal de saida.
        global running
        running = False

    signal.signal(signal.SIGTERM, handle_sigterm)

    parser = argparse.ArgumentParser()
    parser.add_argument('--screen', action='store_true', help='captura a tela em vez da webcam')
    parser.add_argument('--fullscreen', action='store_true', help='janela sem borda, tamanho da tela')
    parser.add_argument('--monitor', metavar='NOME', nargs='?', const='',
                         help='sem borda, fixa num monitor especifico (ex. HDMI-1); implica --fullscreen. '
                              'Sem valor = auto-detecta o monitor secundario')
    parser.add_argument('--source', metavar='NOME', nargs='?', const='',
                         help='no modo --screen, qual monitor capturar (ex. eDP-1) em vez da tela toda. '
                              'Sem valor = auto-detecta o monitor secundario')
    parser.add_argument('--window', metavar='TITULO', nargs='?', const='',
                         help='no modo --screen, captura so uma janela em vez da tela toda. '
                              'Sem valor = clica na janela pra escolher; com titulo, acha por substring (wmctrl)')
    parser.add_argument('--region', action='store_true',
                         help='no modo --screen, arrasta um retangulo pra recortar a regiao exata (mais preciso '
                              'que --window/--source)')
    parser.add_argument('--audio', metavar='SOURCE',
                         help='source de audio do PulseAudio/PipeWire (ver "pactl list short sources"). '
                              'Default = monitor da saida padrao (o som geral do sistema)')
    parser.add_argument('--device', metavar='PATH', default='/dev/video0',
                         help='no modo webcam (sem --screen), qual device v4l2 usar. Default /dev/video0. '
                              'Use uma camera virtual (ex. v4l2loopback + OBS Virtual Camera) pra capturar '
                              'uma janela em fps cheio em vez de --window')
    args = parser.parse_args()
    mode = 'screen' if args.screen else 'webcam'

    screen_size = get_screen_size() if args.fullscreen else None

    capture_region = None
    if mode == 'screen':
        if args.region:
            capture_region = pick_region()
            if capture_region is None:
                return
        elif args.window is not None:
            capture_region = pick_window(args.window if args.window != '' else None)
        elif args.source is not None:
            capture_region = pick_monitor(args.source if args.source != '' else None)
        else:
            sw, sh = screen_size or get_screen_size()
            capture_region = {'name': 'tela toda', 'w': sw, 'h': sh, 'x': 0, 'y': 0}
        if 'id' in capture_region:
            # captura via composite: tamanho tem que bater exato com o que o "import" devolve,
            # sem downscale (ele nao redimensiona) nem clamp de tela (nao usa x,y)
            WIDTH, HEIGHT = capture_region['w'], capture_region['h']
            print(f"fonte: {capture_region['name']} (janela {capture_region['id']}, "
                  f"{WIDTH}x{HEIGHT}, segue mesmo coberta)")
        else:
            capture_region = clamp_region(capture_region)
            WIDTH, HEIGHT = fit(capture_region['w'], capture_region['h'])
            print(f"fonte: {capture_region['name']} "
                  f"({capture_region['w']}x{capture_region['h']}+{capture_region['x']}+{capture_region['y']})")
    elif args.device != '/dev/video0':
        # camera virtual (v4l2loopback/OBS) pode estar numa resolucao diferente do default —
        # pergunta pro device em vez de chutar 640x480
        out = subprocess.check_output(['v4l2-ctl', '--device=' + args.device, '--get-fmt-video']).decode()
        w, h = re.search(r'Width/Height\s*:\s*(\d+)/(\d+)', out).groups()
        WIDTH, HEIGHT = int(w), int(h)
        print(f"fonte: {args.device} ({WIDTH}x{HEIGHT})")
    FRAME_SIZE = WIDTH * HEIGHT * 3
    state['frame'] = np.zeros(FRAME_SIZE, dtype=np.uint8)

    flags = pygame.OPENGL | pygame.DOUBLEBUF
    if args.monitor is not None:
        mon = pick_monitor(args.monitor if args.monitor != '' else None)
        WIN_W, WIN_H = mon['w'], mon['h']
        os.environ['SDL_VIDEO_WINDOW_POS'] = f"{mon['x']},{mon['y']}"
        flags |= pygame.NOFRAME
        print(f"janela fixada em {mon['name']} ({WIN_W}x{WIN_H}+{mon['x']}+{mon['y']})")
    elif args.fullscreen:
        WIN_W, WIN_H = screen_size
        flags |= pygame.FULLSCREEN | pygame.NOFRAME
    else:
        WIN_W, WIN_H = WIDTH, HEIGHT

    pygame.init()
    pygame.display.set_mode((WIN_W, WIN_H), flags)
    pygame.display.set_caption('native_synth — ESC ou fechar a janela pra sair')
    glViewport(0, 0, WIN_W, WIN_H)

    vbo = glGenBuffers(1)
    glBindBuffer(GL_ARRAY_BUFFER, vbo)
    glBufferData(GL_ARRAY_BUFFER, np.array([-1, -1, 3, -1, -1, 3], dtype=np.float32), GL_STATIC_DRAW)

    tex = glGenTextures(1)
    glBindTexture(GL_TEXTURE_2D, tex)
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE)
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE)
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR)

    with open(FRAG_PATH) as f:
        frag_src = f.read()
    frag_mtime = os.path.getmtime(FRAG_PATH)

    uniforms = {}

    def use_program(prog):
        glUseProgram(prog)
        loc = glGetAttribLocation(prog, 'a_pos')
        glEnableVertexAttribArray(loc)
        glVertexAttribPointer(loc, 2, GL_FLOAT, GL_FALSE, 0, None)
        uniforms['res'] = glGetUniformLocation(prog, 'u_resolution')
        uniforms['time'] = glGetUniformLocation(prog, 'u_time')
        uniforms['tex0'] = glGetUniformLocation(prog, 'u_texture_0')
        uniforms['amp'] = glGetUniformLocation(prog, 'u_amp')
        uniforms['bass'] = glGetUniformLocation(prog, 'u_bass')
        uniforms['mid'] = glGetUniformLocation(prog, 'u_mid')
        uniforms['treble'] = glGetUniformLocation(prog, 'u_treble')
        uniforms['kick'] = glGetUniformLocation(prog, 'u_kick')
        uniforms['dominant'] = glGetUniformLocation(prog, 'u_dominant')
        for name in FREQ_BAND_UNIFORM.values():
            uniforms[name] = glGetUniformLocation(prog, 'u_' + name)
        glUniform1i(uniforms['tex0'], 0)

    program = build_program(frag_src)
    use_program(program)

    if capture_region and 'id' in capture_region:
        threading.Thread(target=window_capture_thread, args=(capture_region['id'],), daemon=True).start()
    else:
        threading.Thread(target=video_thread, args=(mode, capture_region, args.device), daemon=True).start()
    img_stream = open_terminal_window('espectrograma de cores — native_synth')
    threading.Thread(target=audio_thread, args=(pick_audio_source(args.audio), img_stream), daemon=True).start()
    threading.Thread(target=dominant_color_thread, daemon=True).start()

    t0 = time.perf_counter()
    clock = pygame.time.Clock()
    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT or (event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE):
                running = False

        # hot reload: mesmo esquema do webcam.html, so que olhando mtime em vez de repollar por HTTP
        try:
            mtime = os.path.getmtime(FRAG_PATH)
            if mtime != frag_mtime:
                frag_mtime = mtime
                with open(FRAG_PATH) as f:
                    new_src = f.read()
                try:
                    new_program = build_program(new_src)
                    glDeleteProgram(program)
                    program = new_program
                    use_program(program)
                    print('shader recarregado')
                except RuntimeError as e:
                    print('erro no shader, mantendo o anterior:\n', e)
        except FileNotFoundError:
            pass

        glActiveTexture(GL_TEXTURE0)
        glBindTexture(GL_TEXTURE_2D, tex)
        glTexImage2D(GL_TEXTURE_2D, 0, GL_RGB, WIDTH, HEIGHT, 0, GL_RGB, GL_UNSIGNED_BYTE, state['frame'])

        glUniform2f(uniforms['res'], WIN_W, WIN_H)
        glUniform1f(uniforms['time'], time.perf_counter() - t0)
        glUniform1f(uniforms['amp'], state['amp'])
        glUniform1f(uniforms['bass'], state['bass'])
        glUniform1f(uniforms['mid'], state['mid'])
        glUniform1f(uniforms['treble'], state['treble'])
        glUniform1f(uniforms['kick'], state['kick'])
        glUniform3f(uniforms['dominant'], *state['dominant'])
        for name in FREQ_BAND_UNIFORM.values():
            glUniform1f(uniforms[name], state[name])

        glClear(GL_COLOR_BUFFER_BIT)
        glDrawArrays(GL_TRIANGLES, 0, 3)
        pygame.display.flip()
        clock.tick(30)

    # da um instante pras threads daemon (audio_thread) notarem running=False e rodarem
    # seu "finally" (ex. sair da tela alternada) antes do processo sumir de baixo delas
    time.sleep(0.15)
    pygame.quit()


if __name__ == '__main__':
    main()
