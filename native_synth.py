#!/usr/bin/env python3
"""Sintese de imagem nativa: webcam ou tela (ffmpeg) + audio do sistema (parec/PulseAudio)
alimentando image.frag numa janela OpenGL, sem navegador nenhum no meio.

Uso: .venv/bin/python native_synth.py [--screen [--source NOME]] [--fullscreen | --monitor [NOME]]
"""
import argparse
import colorsys
import glob
import importlib
import os
import re
import select
import signal
import subprocess
import sys
import threading
import time

import numpy as np
import pygame
from OpenGL.GL import *

import tuning
import dash_server
import dash_data

_HERE = os.path.dirname(os.path.abspath(__file__))
TUNING_PATH = os.path.join(_HERE, 'tuning.py')
# hot-reload por mtime, junto com o tuning.py: editar e salvar aplica na hora, sem re-executar.
# dash_server: para o servidor antigo e sobe um novo (o SSE do browser reconecta sozinho).
# dash_data: so importlib.reload (chamado por dash_data.audio_dash_data, nao por nome fixo).
# native_synth.py em si -> watch_synth.sh (restart do processo).
DASH_SERVER_PATH = os.path.join(_HERE, 'dash_server.py')
DASH_DATA_PATH = os.path.join(_HERE, 'dash_data.py')

# de quantos em quantos chunks de audio (~23ms) o dash (terminal + HTTP) recalcula/redesenha.
# menor = mais rapido, mas a analise de imagem (~16ms) roda dentro do audio_thread e nao pode
# passar do budget do chunk. 3 -> ~14 Hz. 1 seria ~43 Hz e arrisca atrasar a leitura do parec.
DASH_EVERY_N_CHUNKS = 3

WIDTH, HEIGHT = 640, 480  # resolucao do conteudo (textura); recalculada no --screen
WIN_W, WIN_H = WIDTH, HEIGHT  # resolucao da janela; recalculada no --fullscreen
FRAME_SIZE = WIDTH * HEIGHT * 3  # rgb24
FRAG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'image.frag')

MAX_CHANNELS = 8  # teto do array u_chan/u_chan_hit no shader; tuning.CHANNELS pode ter menos

VERT_SRC = """
attribute vec2 a_pos;
void main() { gl_Position = vec4(a_pos, 0.0, 1.0); }
"""

state = {'frame': np.zeros(FRAME_SIZE, dtype=np.uint8), 'amp': 0.0, 'bass': 0.0, 'mid': 0.0, 'treble': 0.0,
         'kick': 0.0, 'dominant': (0.5, 0.5, 0.5),
         # faixas finas de mixagem (Sub-bass..Air) — controlam u_subbass..u_air no shader
         'subbass': 0.0, 'lowmid': 0.0, 'midrange': 0.0, 'highmid': 0.0, 'presence': 0.0,
         'treble_hi': 0.0, 'brilho': 0.0, 'air': 0.0, 'spectrum': [], 'image': {}, 'out_image': {},
         'audio_source': '', 'video': None, 'video_label': '', 'video_id': '', 'output': {},
         # canais por instrumento (ver tuning.CHANNELS) — controlam u_chan/u_chan_hit no shader
         'chan': [0.0] * MAX_CHANNELS, 'chan_hit': [0.0] * MAX_CHANNELS}
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


def resolve_output(cfg):
    """cfg: {'monitor': nome ou '', 'fullscreen': bool, 'w': int, 'h': int} -> (win_w, win_h,
    pos, flags, label). Unifica o que antes era so --monitor/--fullscreen/janela default no
    arranque — agora tambem serve pra reconfigurar ao vivo (barra "saida" no dash)."""
    monitors = get_monitors()
    mon = next((m for m in monitors if m['name'] == cfg.get('monitor')), None) if cfg.get('monitor') else None
    flags = pygame.OPENGL | pygame.DOUBLEBUF
    if cfg.get('fullscreen') and not mon:
        win_w, win_h = get_screen_size()
        pos = (0, 0)
        flags |= pygame.FULLSCREEN | pygame.NOFRAME
        label = 'fullscreen (tela toda)'
    elif mon:
        pos = (mon['x'], mon['y'])
        flags |= pygame.NOFRAME  # sem WM decorando: a posicao (via env var) precisa bater certinho
        if cfg.get('fullscreen'):
            win_w, win_h = mon['w'], mon['h']
            label = f"fullscreen {mon['name']}"
        else:
            win_w = max(160, int(cfg.get('w') or mon['w']))
            win_h = max(120, int(cfg.get('h') or mon['h']))
            label = f"janela {win_w}x{win_h} em {mon['name']}"
    else:
        win_w = max(160, int(cfg.get('w') or WIDTH))
        win_h = max(120, int(cfg.get('h') or HEIGHT))
        pos = (0, 0)
        label = f'janela {win_w}x{win_h}'
    return win_w, win_h, pos, flags, label


def open_window(cfg):
    """Abre (ou REABRE) a janela de saida a partir de resolve_output(cfg). pygame.display.quit()
    + init() de novo e o mesmo truque que o --monitor original usava no arranque (SDL so le
    SDL_VIDEO_WINDOW_POS na criacao da janela) — aqui repetido pra poder trocar de monitor/
    tamanho/fullscreen AO VIVO, sem reiniciar o processo. Devolve vbo/tex NOVOS de proposito:
    ponytail — o driver pode ou nao preservar o contexto GL numa troca dessas; em vez de tentar
    adivinhar, o chamador SEMPRE regera vbo/tex/program depois (ver main()). Se o contexto
    velho sobreviveu, os objetos antigos so ficam sem uso (vazamento pequeno, so quando o
    usuario troca a saida pelo dash — nao por frame; upgrade se um dia isso incomodar)."""
    win_w, win_h, pos, flags, label = resolve_output(cfg)
    os.environ.pop('SDL_VIDEO_WINDOW_POS', None)
    if flags & pygame.NOFRAME:
        os.environ['SDL_VIDEO_WINDOW_POS'] = f'{pos[0]},{pos[1]}'
    if pygame.display.get_init():
        pygame.display.quit()
    pygame.display.init()
    pygame.display.set_mode((win_w, win_h), flags)
    pygame.display.set_caption('native_synth — ESC ou fechar a janela pra sair')
    glViewport(0, 0, win_w, win_h)

    vbo = glGenBuffers(1)
    glBindBuffer(GL_ARRAY_BUFFER, vbo)
    glBufferData(GL_ARRAY_BUFFER, np.array([-1, -1, 3, -1, -1, 3], dtype=np.float32), GL_STATIC_DRAW)

    tex = glGenTextures(1)
    glBindTexture(GL_TEXTURE_2D, tex)
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE)
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE)
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR)

    print(f'saida: {label} ({win_w}x{win_h}+{pos[0]}+{pos[1]})')
    return win_w, win_h, pos, label, vbo, tex


def set_output(cfg):
    """cfg: {'monitor','fullscreen','w','h'} — o dash escreve aqui (aba Video, barra "saida");
    quem realmente reabre a janela e o main thread (dono do contexto GL), no proximo frame,
    quando ve state['output_req'] diferente do que esta aplicado agora (ver main())."""
    state['output_req'] = {
        'monitor': str(cfg.get('monitor') or ''),
        'fullscreen': bool(cfg.get('fullscreen')),
        'w': int(cfg.get('w') or 0) or WIDTH,
        'h': int(cfg.get('h') or 0) or HEIGHT,
    }


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


def _spawn_ffmpeg(v):
    """v = state['video'] = {'mode':'webcam'|'screen', 'device':.., 'region':..}. Sempre escala
    pra WIDTH x HEIGHT fixos (nao mexe nos globais ao vivo — trocar de fonte pelo dash mantem a
    resolucao de saida; pra aspect certo de tela, reinicie com --screen)."""
    if v['mode'] == 'screen':
        r = v['region']
        display = os.environ.get('DISPLAY', ':0') + f"+{r['x']},{r['y']}"
        cmd = ['ffmpeg', '-loglevel', 'error', '-f', 'x11grab', '-framerate', '30',
               '-video_size', f"{r['w']}x{r['h']}", '-i', display,
               '-vf', f'scale={WIDTH}:{HEIGHT}', '-pix_fmt', 'rgb24', '-f', 'rawvideo', '-']
    else:
        cmd = ['ffmpeg', '-loglevel', 'error', '-f', 'v4l2', '-framerate', '30']
        if v['device'] == '/dev/video0':  # so a webcam de verdade precisa forcar o formato
            cmd += ['-input_format', 'yuyv422']
        cmd += ['-video_size', f'{WIDTH}x{HEIGHT}', '-i', v['device'],
                '-vf', f'scale={WIDTH}:{HEIGHT}', '-pix_fmt', 'rgb24', '-f', 'rawvideo', '-']
    return subprocess.Popen(cmd, stdout=subprocess.PIPE)


def _kill(proc):
    """Mata o ffmpeg E ESPERA sair — v4l2 e exclusivo, sem isso o proximo ffmpeg pega
    'Device or resource busy' e a webcam nao volta."""
    proc.terminate()
    try:
        proc.wait(timeout=1.5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


def _video_label(v):
    if not v:
        return ''
    return v['device'] if v['mode'] == 'webcam' else f"tela: {(v.get('region') or {}).get('name', '')}"


def video_thread(mode, region=None, device='/dev/video0'):
    state['video'] = {'mode': mode, 'device': device, 'region': region}  # fonte da verdade
    state['video_label'] = _video_label(state['video'])
    state['video_id'] = _video_id(state['video'])
    cur = dict(state['video'])
    proc = _spawn_ffmpeg(cur)
    try:
        while running:
            if state['video'] != cur:  # troca pedida pelo dash (set_input substitui o dict inteiro)
                _kill(proc)
                cur = dict(state['video'])
                state['video_label'] = _video_label(cur)
                state['video_id'] = _video_id(cur)
                proc = _spawn_ffmpeg(cur)
                print('video: fonte ->', _video_label(cur))
                continue
            # select com timeout: se o ffmpeg atual travar sem produzir frame (fonte ruim,
            # ex. /dev/video1 que nao e camera), o loop ainda re-checa a troca a cada 0.25s
            # em vez de ficar preso pra sempre num read bloqueante — era por isso que a
            # webcam "nao voltava".
            if not select.select([proc.stdout], [], [], 0.25)[0]:
                if proc.poll() is not None:          # ffmpeg saiu — respawna a mesma fonte
                    time.sleep(0.3)
                    proc = _spawn_ffmpeg(cur)
                continue
            frame = read_exact(proc.stdout, FRAME_SIZE)
            if frame is None:
                if not running:
                    break
                time.sleep(0.3)  # fonte caiu — tenta de novo, sem matar a thread
                _kill(proc)
                proc = _spawn_ffmpeg(cur)
                continue
            state['frame'] = np.frombuffer(frame, dtype=np.uint8)
    finally:
        _kill(proc)


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


# nomes das 8 faixas de mixagem finas, grave->agudo. As cores vivem em dash_data.FREQ_BAND_RGB
# (so o lado web usa cor); aqui so precisamos de nome + os cortes em Hz.
FREQ_BAND_NAMES = ['Sub-bass', 'Low-mid', 'Midrange', 'High-mid',
                   'Presence', 'Treble', 'Brilliance', 'Air']

# nome de exibicao -> chave de uniform valida no GLSL (sem hifen/maiuscula; "Treble" vira
# "treble_hi" pra nao colidir com o u_treble do bass/mid/treble classico)
FREQ_BAND_UNIFORM = {
    'Sub-bass': 'subbass', 'Low-mid': 'lowmid', 'Midrange': 'midrange',
    'High-mid': 'highmid', 'Presence': 'presence', 'Treble': 'treble_hi',
    'Brilliance': 'brilho', 'Air': 'air',
}
FINE_BAND_KEYS = set(FREQ_BAND_UNIFORM.values())  # pro gate do tuning.BANDS_ENABLED

def chan_cfg(slot):
    """tuning.CHANNELS[slot] com fallback a {} pra slot fora do tamanho atual da lista
    (lista e de tamanho livre agora — add/remove pelo dash, sem slot fixo pre-definido)."""
    chs = tuning.CHANNELS
    return chs[slot] if slot < len(chs) else {}


def freq_bands():
    """[(nome, lo_hz, hi_hz)] das 8 faixas, direto de tuning.FREQ_BAND_HZ (range por faixa).
    Reconstruido a cada reload do tuning.py — e como a secao "Ranges das faixas" do dash mexe
    nas faixas ao vivo. As faixas podem se sobrepor ou deixar buraco (tuning.HZ_OVERLAP);
    named_band_levels lida com qualquer (lo, hi), inclusive sobreposto/vazio."""
    return [(name, float(lo), float(hi))
            for name, (lo, hi) in zip(FREQ_BAND_NAMES, tuning.FREQ_BAND_HZ)]


def band_smoothing_map():
    """{chave de uniform: SMOOTHING daquela banda}, interpolado linear entre
    tuning.SMOOTHING_MIN (Sub-bass, indice 0) e tuning.SMOOTHING_MAX (Air, ultimo indice),
    seguindo a ordem grave->agudo. Recalcula toda vez que chamada — chamar de novo apos um
    reload do tuning.py pra pegar os valores atualizados."""
    n = len(FREQ_BAND_NAMES)
    span = tuning.SMOOTHING_MAX - tuning.SMOOTHING_MIN
    return {FREQ_BAND_UNIFORM[name]: tuning.SMOOTHING_MIN + (i / (n - 1)) * span
            for i, name in enumerate(FREQ_BAND_NAMES)}


def named_band_levels(spectrum, freqs, bands, band_peaks, peak_decay):
    """Pra cada (nome, lo, hi) em `bands` (de freq_bands()): magnitude bruta (fallback de bin
    mais proximo pra faixa mais estreita que a resolucao da FFT) e nivel relativo ao PICO
    RECENTE DA PROPRIA banda — nao ao pico entre as bandas. Isso importa porque uma banda
    estruturalmente mais forte (ex. Sub-bass) ficaria travada perto de 1.0 so por ser mais
    alta que as demais. `band_peaks` (dict {nome: pico}) e mantido pelo chamador entre
    chunks: sobe na hora com um pico novo, decai devagar por `peak_decay` — auto-gain sem
    escala manual."""
    out = []
    for name, lo, hi in bands:
        mask = (freqs >= lo) & (freqs < hi)
        if mask.any():
            mag = spectrum[mask].mean()
        else:
            mid = (lo + min(hi, freqs[-1])) / 2  # `hi` pode ser infinito (ultima banda)
            mag = spectrum[np.argmin(np.abs(freqs - mid))]
        band_peaks[name] = max(mag, band_peaks[name] * peak_decay, 1e-6)
        out.append((name, mag, min(1.0, mag / band_peaks[name])))
    return out


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


def image_dash_data(arr, hue, sat, val, gx, gy, frame, w, h, dominant, peaks, prev_val, prev_mean, grid=3):
    """Fonte unica de verdade do dash de imagem: dict de numeros (resumo escalar + grid 3x3
    por metrica + 4 histogramas). `peaks` (auto-gain), `prev_val` e `prev_mean` (deltas de
    movimento/cor) sao estado mutavel entre chamadas."""
    # --- resumo escalar ---
    hw = val.shape[1] // 2
    sym_diff = float(np.abs(val[:, :hw] - val[:, val.shape[1] - hw:][:, ::-1]).mean())
    symmetry = max(0.0, 1.0 - sym_diff * 4.0)

    peaks['sharpness'] = max(laplacian_variance(val), peaks['sharpness'] * tuning.PEAK_DECAY, 1e-6)
    peaks['edge'] = max(float(np.sqrt(gx ** 2 + gy ** 2).mean()), peaks['edge'] * tuning.PEAK_DECAY, 1e-6)
    motion_raw = (float(np.abs(val - prev_val[0]).mean())
                  if prev_val[0] is not None and prev_val[0].shape == val.shape else 0.0)
    peaks['motion'] = max(motion_raw, peaks['motion'] * tuning.PEAK_DECAY, 1e-6)
    prev_before = prev_val[0]
    prev_val[0] = val

    over = float((val > 0.95).mean())
    under = float((val < 0.05).mean())
    rr, gg, bb = arr[..., 0].ravel(), arr[..., 1].ravel(), arr[..., 2].ravel()
    with np.errstate(invalid='ignore'):
        corr_rg = float(np.nan_to_num(np.corrcoef(rr, gg)[0, 1]))
        corr_rb = float(np.nan_to_num(np.corrcoef(rr, bb)[0, 1]))
        corr_gb = float(np.nan_to_num(np.corrcoef(gg, bb)[0, 1]))
    yy, xx = np.indices(val.shape)
    tot = float(val.sum()) + 1e-9
    cx = float((xx * val).sum()) / tot / max(1, val.shape[1] - 1)
    cy = float((yy * val).sum()) / tot / max(1, val.shape[0] - 1)

    cf_raw = colorfulness(arr)
    peaks['colorfulness'] = max(cf_raw, peaks['colorfulness'] * tuning.PEAK_DECAY, 1e-6)
    cf_level = min(1.0, cf_raw / peaks['colorfulness'])
    mr, mg, mb = (int(round(c)) for c in arr.mean(axis=(0, 1)))
    total_px = arr.shape[0] * arr.shape[1]
    n_uni = unique_colors(arr)
    cur_mean = np.array([mr, mg, mb], dtype=np.float32)
    color_change = (min(1.0, float(np.linalg.norm(cur_mean - prev_mean[0])) / (255.0 * np.sqrt(3)))
                    if prev_mean[0] is not None else 0.0)
    prev_mean[0] = cur_mean
    warm = hue_range_fraction(hue, sat)

    # --- grids 3x3 por metrica (brilho/saturacao/temp/contraste/nitidez/entropia/bordas/movimento) ---
    vh, vw = val.shape
    gh, gw = gx.shape
    brilho = cell_reduce(lambda y0, y1, x0, x1: val[y0:y1, x0:x1].mean(), vh, vw, grid)
    sat_c = cell_reduce(lambda y0, y1, x0, x1: sat[y0:y1, x0:x1].mean(), vh, vw, grid)
    temp_c = cell_reduce(lambda y0, y1, x0, x1: (arr[y0:y1, x0:x1, 0].mean()
                                                  - arr[y0:y1, x0:x1, 2].mean()) / 255.0, vh, vw, grid)
    contrast_c = cell_reduce(lambda y0, y1, x0, x1: min(1.0, float(val[y0:y1, x0:x1].std()) * 2.5), vh, vw, grid)
    sharp_c = np.minimum(1.0, cell_reduce(lambda y0, y1, x0, x1: laplacian_variance(val[y0:y1, x0:x1]),
                                          vh, vw, grid) / peaks['sharpness'])
    entropy_c = cell_reduce(lambda y0, y1, x0, x1: brightness_entropy(val[y0:y1, x0:x1]), vh, vw, grid)
    edge_c = np.minimum(1.0, cell_reduce(lambda y0, y1, x0, x1: np.sqrt(
        gx[y0:y1, x0:x1] ** 2 + gy[y0:y1, x0:x1] ** 2).mean(), gh, gw, grid) / peaks['edge'])
    if prev_before is not None and prev_before.shape == val.shape:
        motion_c = np.minimum(1.0, cell_reduce(lambda y0, y1, x0, x1: float(np.abs(
            val[y0:y1, x0:x1] - prev_before[y0:y1, x0:x1]).mean()), vh, vw, grid) / peaks['motion'])
    else:
        motion_c = np.zeros((grid, grid))

    def _grid(name, cells, bipolar=False):
        total = (float(np.clip(cells.mean(), -1.0, 1.0)) if bipolar
                 else float(np.clip(np.abs(cells).mean(), 0.0, 1.0)))
        return {'name': name, 'bipolar': bipolar, 'total': round(total, 3),
                'cells': [[round(float(v), 3) for v in row] for row in cells]}

    grids = [_grid('BRILHO', brilho), _grid('SATURAÇÃO', sat_c), _grid('TEMP.', temp_c, True),
             _grid('CONTRASTE', contrast_c), _grid('NITIDEZ', sharp_c), _grid('ENTROPIA', entropy_c),
             _grid('BORDAS', edge_c), _grid('MOVIMENTO', motion_c)]

    # --- histogramas ---
    hc, he = np.histogram(hue.ravel(), bins=12, range=(0.0, 1.0), weights=sat.ravel())
    hcent = (he[:-1] + he[1:]) / 2
    hue_hist = [{'deg': int(round(cn * 360)), 'level': round(float(c / (hc.max() + 1e-9)), 3),
                 'rgb': [int(v * 255) for v in colorsys.hsv_to_rgb(cn, 1.0, 1.0)]}
                for c, cn in zip(hc, hcent)]

    bc, be = np.histogram(val.ravel(), bins=16, range=(0.0, 1.0))
    bcent = (be[:-1] + be[1:]) / 2
    bright_hist = [{'gray': int(cn * 255), 'level': round(float(c / (bc.max() + 1e-9)), 3)}
                   for c, cn in reversed(list(zip(bc, bcent)))]  # claro em cima

    color_spectrum = [{'radius': int(rad), 'r': round(float(lr), 3), 'g': round(float(lg), 3),
                       'b': round(float(lb), 3)}
                      for rad, lr, lg, lb in frame_color_spectrum(frame, w, h)]

    ang = np.degrees(np.arctan2(gy, gx)) % 180.0
    oc, oe = np.histogram(ang.ravel(), bins=9, range=(0.0, 180.0),
                          weights=np.sqrt(gx ** 2 + gy ** 2).ravel())
    ocent = (oe[:-1] + oe[1:]) / 2
    edge_orient = [{'deg': int(round(cn)), 'level': round(float(c / (oc.max() + 1e-9)), 3),
                    'rgb': [int(v * 255) for v in colorsys.hsv_to_rgb(cn / 180.0, 0.8, 1.0)]}
                   for c, cn in zip(oc, ocent)]

    return {
        'dominant': [int(dominant[0] * 255), int(dominant[1] * 255), int(dominant[2] * 255)],
        'summary': {
            'symmetry': round(symmetry, 3), 'overexposed': round(over, 3), 'underexposed': round(under, 3),
            'corr_rg': round(corr_rg, 3), 'corr_rb': round(corr_rb, 3), 'corr_gb': round(corr_gb, 3),
            'cx': round(cx, 3), 'cy': round(cy, 3), 'mean_rgb': [mr, mg, mb],
            'colorfulness': round(cf_level, 3), 'palette_unique': n_uni, 'palette_total': total_px,
            'palette_level': round(min(1.0, n_uni / total_px), 3),
            'color_change': round(color_change, 3), 'warm': round(warm, 3),
        },
        'grids': grids, 'hue_hist': hue_hist, 'bright_hist': bright_hist,
        'color_spectrum': color_spectrum, 'edge_orient': edge_orient,
    }


def pick_audio_source(name=None):
    if name:
        return name
    sink = subprocess.check_output(['pactl', 'get-default-sink']).decode().strip()
    return sink + '.monitor'


# --- troca de entrada pelo dashboard: enumerar + aplicar (dash_server chama via callbacks) ---

def _list_audio_sources():
    try:
        out = subprocess.check_output(['pactl', 'list', 'short', 'sources'], text=True)
    except (FileNotFoundError, subprocess.CalledProcessError):
        return []
    res = []
    for line in out.splitlines():
        parts = line.split('\t')
        if len(parts) >= 2:
            name = parts[1]
            short = (name.replace('alsa_output.', '').replace('alsa_input.', '')
                     .replace('.monitor', ' (monitor)'))
            res.append({'id': name, 'name': short})
    return res


def _list_video_inputs():
    res = [{'kind': 'webcam', 'id': f'webcam:{d}', 'name': d}
           for d in sorted(glob.glob('/dev/video*'))]
    try:
        for m in get_monitors():
            res.append({'kind': 'screen', 'id': f"screen:{m['name']}",
                        'name': f"tela {m['name']} {m['w']}x{m['h']}" + (' *' if m['primary'] else '')})
    except Exception:
        pass
    return res


def _video_from_id(ident):
    """'webcam:/dev/videoN' ou 'screen:<monitor>' -> dict state['video']. Sempre escala pra
    WIDTH x HEIGHT atuais (nao muda a resolucao de saida ao vivo)."""
    kind, _, rest = ident.partition(':')
    if kind == 'webcam':
        return {'mode': 'webcam', 'device': rest or '/dev/video0', 'region': None}
    try:
        m = pick_monitor(rest or None)
    except SystemExit:
        m = None
    if m:
        r = {'name': m['name'], 'w': m['w'], 'h': m['h'], 'x': m['x'], 'y': m['y']}
    else:
        sw, sh = get_screen_size()
        r = {'name': 'tela toda', 'w': sw, 'h': sh, 'x': 0, 'y': 0}
    return {'mode': 'screen', 'device': None, 'region': r}


def _video_id(v):
    """dict state['video'] -> id no formato das opcoes ('webcam:/dev/videoN' | 'screen:<nome>')."""
    if not v:
        return ''
    return (f"webcam:{v['device']}" if v.get('mode') == 'webcam'
            else f"screen:{(v.get('region') or {}).get('name', '')}")


def list_inputs():
    return {'audio': _list_audio_sources(), 'video': _list_video_inputs(),
            'current': {'audio': state.get('audio_source', ''),
                        'video': state.get('video_id') or _video_id(state.get('video'))}}


def set_input(kind, ident):
    if kind == 'audio':
        state['audio_source'] = ident
    elif kind == 'video':
        state['video'] = _video_from_id(ident)  # video_thread ve o dict novo e re-spawna o ffmpeg
        state['video_id'] = ident               # id "canonico" pro dash sincronizar os selects
    else:
        raise ValueError(f'kind desconhecido: {kind}')


def _spawn_parec(device):
    return subprocess.Popen(
        ['parec', '--device=' + device, '--format=s16le', '--rate=44100',
         '--channels=1', '--latency-msec=50'],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )


def audio_thread(device):
    state['audio_source'] = device  # fonte da verdade a partir daqui (o dash troca via set_input)
    try:
        proc = _spawn_parec(device)
    except FileNotFoundError:
        print('sem audio: "parec" nao encontrado (pacote pulseaudio-utils)')
        return
    cur_src = device
    print('audio: capturando', device)
    chunk_samples = 1024
    chunk_bytes = chunk_samples * 2
    rate = 44100
    window = np.hanning(chunk_samples)
    freqs = np.fft.rfftfreq(chunk_samples, d=1 / rate)

    def recompute_bins():
        # bass_bins/mid_bins/treble_bins dependem de tuning.BASS_MID_HZ/MID_TREBLE_HZ e as 8
        # faixas finas dos cortes tuning.HZ_* — recalcula tudo quando o tuning.py recarrega
        return ((freqs < tuning.BASS_MID_HZ,
                 (freqs >= tuning.BASS_MID_HZ) & (freqs < tuning.MID_TREBLE_HZ),
                 freqs >= tuning.MID_TREBLE_HZ), freq_bands())

    (bass_bins, mid_bins, treble_bins), fine_bands = recompute_bins()
    band_smoothing = band_smoothing_map()  # {chave: SMOOTHING daquela banda}, grave->agudo
    tuning_mtime = os.path.getmtime(TUNING_PATH)
    dash_server_mtime = os.path.getmtime(DASH_SERVER_PATH)
    dash_data_mtime = os.path.getmtime(DASH_DATA_PATH)
    smooth = {'amp': 0.0, 'bass': 0.0, 'mid': 0.0, 'treble': 0.0, **{k: 0.0 for k in FREQ_BAND_UNIFORM.values()}}
    smoothing_used = dict(smooth)  # ultimo smoothing (attack ou release) aplicado em cada chave
    band_peaks = {name: 1e-6 for name, _, _ in fine_bands}  # auto-gain: teto recente de cada banda
    kick_baseline = 0.0
    kick_env = 0.0
    kick_decay_dynamic = tuning.KICK_DECAY  # ate a 1a batida ter intervalo medido, usa o fixo
    kick_chunk_count = 0
    kick_last_hit_chunk = 0
    monitor_frame = [0]
    # estado entre throttles pro image_dash_data (auto-gain de pico + deltas de movimento/cor)
    html_img = {'peaks': {'edge': 1e-6, 'motion': 1e-6, 'sharpness': 1e-6, 'colorfulness': 1e-6},
                'prev_val': [None], 'prev_mean': [None]}
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
                    (bass_bins, mid_bins, treble_bins), fine_bands = recompute_bins()
                    band_smoothing = band_smoothing_map()
                    print('tuning.py recarregado')
                m = os.path.getmtime(DASH_SERVER_PATH)
                if m != dash_server_mtime:
                    dash_server_mtime = m
                    vm, old_srv = dash_server._cfg.get('video_mode', ''), dash_server._cfg.get('srv')
                    try:
                        importlib.reload(dash_server)
                    except Exception as e:
                        print(f'dash_server.py com erro, mantendo o anterior:\n{e}')
                    else:
                        if old_srv is not None:
                            old_srv.shutdown()
                            old_srv.server_close()
                        dash_server.start(state, tuning, TUNING_PATH, lambda: running,
                                          audio_source=device, video_mode=vm, open_browser=False,
                                          on_inputs=list_inputs, on_set_input=set_input,
                                          on_set_output=set_output)
                        print('dash_server.py recarregado')
                m = os.path.getmtime(DASH_DATA_PATH)
                if m != dash_data_mtime:
                    dash_data_mtime = m
                    try:
                        importlib.reload(dash_data)
                        print('dash_data.py recarregado')
                    except Exception as e:
                        print(f'dash_data.py com erro:\n{e}')
            except FileNotFoundError:
                pass
            if state['audio_source'] != cur_src:  # troca pedida pelo dash
                _kill(proc)
                cur_src = state['audio_source']
                proc = _spawn_parec(cur_src)
                print('audio: fonte ->', cur_src)
                continue
            data = read_exact(proc.stdout, chunk_bytes)
            if data is None:
                if not running:
                    break
                err = proc.stderr.read().decode(errors='ignore').strip()
                print('audio parou' + (': ' + err if err else '') + ' — retomando ' + cur_src)
                time.sleep(0.5)
                _kill(proc)
                proc = _spawn_parec(cur_src)
                continue
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
            named_levels = named_band_levels(spectrum, freqs, fine_bands, band_peaks, tuning.PEAK_DECAY)
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
                # BANDS_ENABLED=0 so silencia o que alimenta o shader/dash ("final"); smooth[k]
                # continua calculado (auto-gain/attack-release nao perdem o fio quando reativa)
                state[k] = smooth[k] if (k not in FINE_BAND_KEYS or tuning.BANDS_ENABLED) else 0.0

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

            # canal com "output" escolhido E "src" bound SUBSTITUI a variavel (kick = onset,
            # o resto = nivel) por cima do que acabou de ser calculado acima. Sem src, a
            # variavel original fica como esta — nao ha fallback implicito por nome mais.
            for slot, ch in enumerate(tuning.CHANNELS[:MAX_CHANNELS]):
                out = ch.get('output')
                if out and ch.get('src'):
                    state[out] = state['chan_hit'][slot] if out == 'kick' else state['chan'][slot]

            # so recalcula/redesenha o dash a cada DASH_EVERY_N_CHUNKS chunks (~14 Hz) — o
            # resto do loop e a leitura crua do parec, que nao pode atrasar.
            monitor_frame[0] += 1
            if monitor_frame[0] % DASH_EVERY_N_CHUNKS == 0:
                # audio_dash_data() / image_dash_data() montam os dicts de numeros que o
                # dash HTML (dash_server -> /events) renderiza. Nao ha mais dash de terminal.
                bands_raw = [(name, mag, lvl, state[FREQ_BAND_UNIFORM[name]],
                              smoothing_used[FREQ_BAND_UNIFORM[name]])
                             for name, mag, lvl in named_levels]  # grave->agudo (ordem freq_bands())
                state['audio_dash'] = dash_data.audio_dash_data(
                    bands_raw, amp_raw, raw['amp'], state['amp'], smoothing_used['amp'],
                    kick_env, kick_decay_dynamic, smooth_spectrum, freqs,
                    band_lohi=[(lo, hi) for _, lo, hi in fine_bands])  # tint + cinza nos buracos

                arr_s = frame_downsample(state['frame'], WIDTH, HEIGHT)
                if arr_s is not None:
                    hue_s, sat_s, val_s = rgb_to_hsv_np(arr_s)
                    gx_s, gy_s = gradient(val_s)
                    state['image'] = image_dash_data(arr_s, hue_s, sat_s, val_s, gx_s, gy_s,
                                                     state['frame'], WIDTH, HEIGHT, state['dominant'],
                                                     html_img['peaks'], html_img['prev_val'],
                                                     html_img['prev_mean'])
    finally:
        _kill(proc)


def channel_thread(slot):
    """Um canal por INSTRUMENTO (stem isolado), nao por Hz — ver tuning.CHANNELS (lista de
    tamanho livre, add/remove pelo dash; slot alem do tamanho atual = so nao existe ainda,
    thread fica ociosa). Sem "src", sem parec/CPU: state['chan'][slot] fica 0 e a variavel de
    "output" (se houver) NAO e mexida — o calculo original continua valendo. So liga quando
    uma source e escolhida no dash (aba Audio -> Canais); troca ou volta a "" com o mesmo
    esquema de respawn ao vivo do audio_thread principal. Analise leve de proposito (nao e FFT
    de 8 faixas por stem, so faz sentido pra 1 instrumento): RMS suavizado (SMOOTHING) + o
    mesmo detector de batida baseline/limiar do kick (KICK_THRESHOLD/KICK_DECAY), agora sobre
    o RMS full-band em vez do grave — um stem isolado ja e "so" aquele instrumento."""
    chunk_samples = 1024
    chunk_bytes = chunk_samples * 2
    proc, cur_src = None, None
    baseline = env = smooth = 0.0
    while running:
        src = chan_cfg(slot).get('src') or ''
        if src != cur_src:
            if proc:
                _kill(proc)
            proc = _spawn_parec(src) if src else None
            cur_src = src
            baseline = env = smooth = 0.0
            if not src:
                state['chan'][slot] = state['chan_hit'][slot] = 0.0  # audio_thread assume nesse frame
        if not proc:
            time.sleep(0.2)
            continue
        data = read_exact(proc.stdout, chunk_bytes)
        if data is None:
            if not running:
                break
            time.sleep(0.3)
            _kill(proc)
            proc = _spawn_parec(cur_src) if cur_src else None
            continue
        samples = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
        amp_raw = float(np.sqrt(np.mean(samples ** 2)))
        smooth = smooth * tuning.SMOOTHING + min(1.0, amp_raw * 4.0) * (1 - tuning.SMOOTHING)
        state['chan'][slot] = smooth
        baseline = baseline * 0.95 + amp_raw * 0.05
        env = 1.0 if amp_raw > baseline * tuning.KICK_THRESHOLD else env * tuning.KICK_DECAY
        state['chan_hit'][slot] = env
    if proc:
        _kill(proc)


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

    # config inicial da saida a partir dos argumentos de linha de comando — mesma forma que
    # set_output()/o dash usam pra pedir uma troca ao vivo (ver resolve_output/open_window)
    out_cfg = {'monitor': '', 'fullscreen': False, 'w': WIDTH, 'h': HEIGHT}
    if args.monitor is not None:
        mon = pick_monitor(args.monitor if args.monitor != '' else None)
        out_cfg = {'monitor': mon['name'], 'fullscreen': True, 'w': mon['w'], 'h': mon['h']}
    elif args.fullscreen:
        out_cfg = {'monitor': '', 'fullscreen': True, 'w': 0, 'h': 0}

    pygame.init()
    WIN_W, WIN_H, out_pos, out_mode, vbo, tex = open_window(out_cfg)
    state['output_req'] = dict(out_cfg)  # o que o dash pode reescrever; comeca igual ao que abriu

    # detalhes da SAIDA pro dashboard (onde/tamanho a imagem sintetizada aparece)
    try:
        monitors = get_monitors()
    except Exception:
        monitors = []
    state['output'] = {
        'content_w': WIDTH, 'content_h': HEIGHT,   # resolucao do render (textura)
        'window_w': WIN_W, 'window_h': WIN_H,      # resolucao da janela de saida
        'mode': out_mode, 'pos': list(out_pos),
        'monitor': out_cfg['monitor'], 'fullscreen': out_cfg['fullscreen'],
        'fps_target': 30, 'fps': 0.0,
        'shader': os.path.basename(FRAG_PATH), 'shader_status': 'ok',
        'monitors': monitors,
    }

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
        uniforms['chan'] = [glGetUniformLocation(prog, f'u_chan[{i}]') for i in range(MAX_CHANNELS)]
        uniforms['chan_hit'] = [glGetUniformLocation(prog, f'u_chan_hit[{i}]') for i in range(MAX_CHANNELS)]
        glUniform1i(uniforms['tex0'], 0)

    program = build_program(frag_src)
    use_program(program)

    if capture_region and 'id' in capture_region:
        threading.Thread(target=window_capture_thread, args=(capture_region['id'],), daemon=True).start()
    else:
        threading.Thread(target=video_thread, args=(mode, capture_region, args.device), daemon=True).start()
    audio_src = pick_audio_source(args.audio)
    threading.Thread(target=audio_thread, args=(audio_src,), daemon=True).start()
    for slot in range(MAX_CHANNELS):
        threading.Thread(target=channel_thread, args=(slot,), daemon=True).start()
    threading.Thread(target=dominant_color_thread, daemon=True).start()
    dash_server.start(state, tuning, TUNING_PATH, lambda: running,
                      audio_source=audio_src, video_mode='screen' if args.screen else 'webcam',
                      on_inputs=list_inputs, on_set_input=set_input, on_set_output=set_output)

    t0 = time.perf_counter()
    clock = pygame.time.Clock()
    frame_n = 0
    # estado entre throttles pro image_dash_data do OUTPUT (auto-gain/motion separados do
    # Source Image — ver tuning.OUT_ANALYSIS_ENABLED). OUT_ANALYSIS_EVERY_N_FRAMES=6 a 30fps
    # e' ~5Hz: de sobra pros medidores (nao precisam de mais que isso), barato o bastante pra
    # nao derrubar o fps do glReadPixels (ele trava esperando a GPU acabar de desenhar).
    OUT_ANALYSIS_EVERY_N_FRAMES = 6
    out_img = {'peaks': {'edge': 1e-6, 'motion': 1e-6, 'sharpness': 1e-6, 'colorfulness': 1e-6},
               'prev_val': [None], 'prev_mean': [None]}
    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT or (event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE):
                running = False

        # troca de saida pedida pelo dash (monitor/tela cheia/dimensao, barra "saida" no topo)
        # — reabre a janela e regera vbo/tex/program (ver open_window: pode ou nao ter perdido
        # o contexto GL, regera de qualquer jeito pra nao arriscar)
        if state['output_req'] != out_cfg:
            out_cfg = dict(state['output_req'])
            WIN_W, WIN_H, out_pos, out_mode, vbo, tex = open_window(out_cfg)
            program = build_program(frag_src)
            use_program(program)
            state['output'].update(mode=out_mode, window_w=WIN_W, window_h=WIN_H, pos=list(out_pos),
                                    monitor=out_cfg['monitor'], fullscreen=out_cfg['fullscreen'])

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
                    frag_src = new_src  # se a saida trocar de janela depois, recompila ISSO, nao o original
                    use_program(program)
                    state['output']['shader_status'] = 'ok'
                    print('shader recarregado')
                except RuntimeError as e:
                    state['output']['shader_status'] = 'erro (mantendo anterior)'
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
        for i in range(MAX_CHANNELS):
            glUniform1f(uniforms['chan'][i], state['chan'][i])
            glUniform1f(uniforms['chan_hit'][i], state['chan_hit'][i])

        glClear(GL_COLOR_BUFFER_BIT)
        glDrawArrays(GL_TRIANGLES, 0, 3)

        # Output Image (ver CLAUDE.md): mesmos medidores do Source Image, so que na imagem
        # JA sintetizada — precisa ler antes do flip trocar o buffer. So' quando ligado
        # (checkbox "calcular" na tab) e throttled, senao o glReadPixels (sincrono, espera
        # a GPU) derruba o fps sozinho.
        if tuning.OUT_ANALYSIS_ENABLED and frame_n % OUT_ANALYSIS_EVERY_N_FRAMES == 0:
            out_buf = glReadPixels(0, 0, WIN_W, WIN_H, GL_RGB, GL_UNSIGNED_BYTE)
            # OpenGL le de baixo pra cima (origem no canto inferior-esquerdo) — inverte de
            # volta pra topo->baixo, senao os grids 3x3 (e o cy do resumo) saem de cabeca
            # pra baixo comparado ao que a tela mostra e ao Source Image (ffmpeg, topo->baixo).
            out_frame = np.ascontiguousarray(
                np.frombuffer(out_buf, dtype=np.uint8).reshape(WIN_H, WIN_W, 3)[::-1]).reshape(-1)
            arr_s = frame_downsample(out_frame, WIN_W, WIN_H)
            if arr_s is not None:
                hue_s, sat_s, val_s = rgb_to_hsv_np(arr_s)
                gx_s, gy_s = gradient(val_s)
                out_dom = dominant_color(arr_s.astype(np.uint8), arr_s.shape[1], arr_s.shape[0])
                state['out_image'] = image_dash_data(arr_s, hue_s, sat_s, val_s, gx_s, gy_s,
                                                      out_frame, WIN_W, WIN_H, out_dom,
                                                      out_img['peaks'], out_img['prev_val'],
                                                      out_img['prev_mean'])

        pygame.display.flip()
        clock.tick(30)
        frame_n += 1
        if frame_n % 15 == 0:
            state['output']['fps'] = round(clock.get_fps(), 1)

    # da um instante pras threads daemon (audio_thread) notarem running=False e rodarem
    # seu "finally" (ex. sair da tela alternada) antes do processo sumir de baixo delas
    time.sleep(0.15)
    pygame.quit()


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        pass
    finally:
        dash_server.stop()  # fecha o socket ja -> o dash detecta a queda e mostra "encerrado"
