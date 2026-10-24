#!/usr/bin/env python3
"""Sintese de imagem nativa: webcam ou tela (ffmpeg) + audio do sistema (parec/PulseAudio)
alimentando shaders/image.frag numa janela OpenGL, sem navegador nenhum no meio.

Layout: este arquivo + dash_server/dash_data/tuning vivem em src/; os .frag em shaders/
(image.frag + presets/*.frag); dash.html e favicon.png na raiz.

Uso: .venv/bin/python src/native_synth.py [--screen [--source NOME]] [--fullscreen | --monitor [NOME]]
"""
import argparse
import collections
import colorsys
import ctypes
import importlib
import math
import os
import re
import signal
import subprocess
import sys
import tempfile
import threading
import time

import numpy as np
# WM_CLASS da janela de saida = a do dash (--class no dash_server) -> uma pilha so' na barra
os.environ.setdefault('SDL_VIDEO_X11_WMCLASS', 'prisma')
import pygame
import OpenGL
# checagem de erro do PyOpenGL = 1 glGetError extra por chamada (~25% de cada uma, centenas por frame).
# Erro de compilacao de shader nao depende disso (glGetShaderiv). PRISMA_GL_CHECK=1 religa pra depurar.
OpenGL.ERROR_CHECKING = bool(os.environ.get('PRISMA_GL_CHECK'))
from OpenGL.GL import *

import tuning
import dash_server
import dash_data
import plat   # Linux x Windows: monitores, captura, audio, pipes (ver plat.py)
import luzes  # refletores/fitas LED (Art-Net) seguindo a saida + o som
import ritmo  # BPM/fase (TAP, troca no compasso) + tom da musica (cor do tom)

plat.init_process()   # Windows: DPI-aware (pixel fisico; senao o pixel map nao e' 1:1)

_HERE = os.path.dirname(os.path.abspath(__file__))          # src/
_ROOT = os.path.dirname(_HERE)                              # raiz do repo
SHADERS_DIR = os.path.join(_ROOT, 'shaders')               # image.frag + presets/*.frag
MEDIA_DIR = os.path.join(_ROOT, 'media')                    # galeria da aba Visuais (imgs/videos)
TRANS_DIR = os.path.join(_ROOT, 'transitions')             # galeria "Transições": *.glsl
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
DASH_EVERY_N_CHUNKS = 2   # analise de imagem pro dash a cada 2 chunks de audio (~21 Hz)

WIDTH, HEIGHT = 640, 480  # resolucao do conteudo (textura); recalculada no --screen
WIN_W, WIN_H = WIDTH, HEIGHT  # resolucao da janela; recalculada no --fullscreen
# CANVAS = o contorno das TELAS do palco fisico (tuning.SCREENS, dash v2 > Saida; ver _stage) ou,
# com o PIXEL MAP ligado (telao), o RASTER dele inteiro; encaixado na janela com barras. FIT_W:FIT_H =
# o aspecto que o 'fit' das fontes mira (o do canvas; sem telas, o da janela) — recalculado a cada frame
FIT_W, FIT_H = WIN_W, WIN_H
# MISTURA (texturas das camadas, u_resolution dos shaders da pilha) = a janela
CMP_W, CMP_H = WIN_W, WIN_H
FRAME_SIZE = WIDTH * HEIGHT * 3  # rgb24
SIM_W, SIM_H = WIDTH // 4, HEIGHT // 4  # grade da simulacao de fumaca — Jacobi nao precisa de
# resolucao de tela, so de mais iteracoes; recalculada junto com WIDTH/HEIGHT em main()
FRAG_PATH = os.path.join(SHADERS_DIR, 'image.frag')

MAX_CHANNELS = 8  # teto do array u_chan/u_chan_hit no shader; tuning.CHANNELS pode ter menos


VERT_SRC = """
attribute vec2 a_pos;
void main() { gl_Position = vec4(a_pos, 0.0, 1.0); }
"""

# --- TRANSIÇÕES entre SETS (galeria "Transições" no dash). Um arquivo transitions/*.glsl e' so
# uma func `vec4 transition(vec2 uv)` estilo gl-transitions; aqui embrulhamos num harness com
# getFromColor (imagem FINAL que sai, capturada da tela) / getToColor (o set novo) / progress,
# e rodamos como o ultimo passe do frame na troca de set (ver main()). Cabecalho "// ms: N" =
# duracao (ausente -> 400).
_TRANS_HEAD = """\
#ifdef GL_ES
precision highp float;
#endif
uniform vec2 u_resolution;
uniform float u_progress;
uniform sampler2D u_from;
uniform sampler2D u_to;
#define progress u_progress
vec4 getFromColor(vec2 uv) { return texture2D(u_from, uv); }
vec4 getToColor(vec2 uv) { return texture2D(u_to, uv); }
"""
_TRANS_TAIL = "\nvoid main() { gl_FragColor = transition(gl_FragCoord.xy / u_resolution.xy); }\n"
_trans_ms_cache = {}


def _wrap_transition(src):
    return _TRANS_HEAD + "\n" + src + _TRANS_TAIL


def _transition_ms(path):
    try:
        key = (path, os.path.getmtime(path))
    except OSError:
        return 400
    if key not in _trans_ms_cache:
        try:
            head = open(path, encoding='utf-8').read(2000)
        except OSError:
            head = ''
        m = re.search(r'//\s*ms:\s*(\d+)', head)
        _trans_ms_cache[key] = int(m.group(1)) if m else 400
    return _trans_ms_cache[key]


def _resolve_transition(tn):
    """(caminho_abs, ms) da transicao `tn` ('<x>.glsl'), ou (None, 0) = corte seco ('none',
    vazio ou arquivo sumido). Quem resolve '' -> TRANSITION_DEFAULT e' dash_server.scene_transition_name."""
    tn = str(tn or 'none')
    if tn == 'none':
        return (None, 0)
    p = os.path.join(TRANS_DIR, os.path.basename(tn))
    return (p, _transition_ms(p)) if os.path.isfile(p) else (None, 0)

# --- FUMAÇA (EFEITO 6 do Caos.frag): simulação de fluido de verdade — Stable Fluids
# (Jos Stam, "Real-Time Fluid Dynamics for Games", 1999) + confinamento de vorticidade
# (Fedkiw/Stam, pra repor o detalhe turbulento que a advecção discretizada apaga sozinha).
# Roda numa GRADE PRÓPRIA menor que o conteúdo (SIM_W x SIM_H — Jacobi não precisa de
# resolução de tela, só de mais iterações; ver main()) em 7 passes por frame:
#   1. ADVECT_VEL   — velocidade se advecta por si mesma (semi-Lagrangiana) + empuxo (a
#                      densidade guia: mais densa/"quente" perto da fonte sobe mais rápido)
#                      + impulso onde o vídeo real tem movimento (frame atual x anterior)
#   2. VORTICITY    — rotacional da velocidade (curl escalar em 2D)
#   3. CONFINEMENT  — soma de volta o giro que a advecção discreta amortece sozinha
#   4. DIVERGENCE   — quanto a velocidade "nasce/some" em cada célula (devia ser 0: fluido
#                      incompressível)
#   5. PRESSURE     — resolve ∇²p = ∇·u por relaxação de Jacobi (PRESSURE_ITERS iterações,
#                      ping-pong) pra achar a pressão que cancela essa divergência
#   6. PROJECT      — tira o gradiente de pressão da velocidade -> campo sem divergência
#   7. ADVECT_DENS  — densidade (o que a gente VÊ) se advecta pelo campo final + injeção de
#                      movimento + decaimento
# Resultado (densidade 0..1 em .r) disponível pra QUALQUER preset via
# `uniform sampler2D u_texture_smoke;` (ver Caos.frag) — o preset nem sabe que tem um
# solver de Navier-Stokes por trás, só lê uma textura.
_SIM_HEAD = """
#ifdef GL_ES
precision highp float;
#endif
uniform vec2 u_res;
"""

SIM_ADVECT_VEL_SRC = _SIM_HEAD + """
uniform float u_dt;
uniform sampler2D u_vel;          // velocidade do frame anterior
uniform sampler2D u_density;      // densidade do frame anterior (guia o empuxo)
uniform sampler2D u_texture_0;    // frame de video atual (full-res)
uniform sampler2D u_texture_prev; // frame de video anterior

float random(vec2 p) { return fract(sin(dot(p, vec2(12.9898, 78.233))) * 43758.5453); }

void main() {
    vec2 uv = gl_FragCoord.xy / u_res;
    vec2 vel = texture2D(u_vel, uv).xy;

    // ADVECCAO SEMI-LAGRANGIANA (Stam): em vez de empurrar a grade pra frente (instavel),
    // pergunta "de onde essa particula veio ha um instante?" e le a velocidade de la
    vec2 back_uv = uv - vel * u_dt;
    vec2 advected = texture2D(u_vel, back_uv).xy;

    // EMPUXO: densidade = proxy de "calor" perto da fonte -> acelera pra cima (+y na
    // convencao de tela do Caos.frag). decai sozinha conforme sobe, como esfriar subindo.
    float density = texture2D(u_density, uv).r;
    advected.y += 1.4 * density * u_dt; // <- edita aqui: forca do empuxo

    // IMPULSO: onde o video tem movimento de verdade, a fonte "sopra" ar
    vec3 cur = texture2D(u_texture_0, uv).rgb;
    vec3 prev = texture2D(u_texture_prev, uv).rgb;
    float motion = clamp(length(cur - prev) * 3.0, 0.0, 1.0); // <- edita aqui: sensibilidade
    vec2 jitter = vec2(random(uv + u_dt) - 0.5, random(uv * 1.7 + u_dt) - 0.5);
    advected += (jitter * 0.6 + vec2(0.0, 0.8)) * motion * u_dt; // <- edita aqui: forca do sopro

    gl_FragColor = vec4(advected, 0.0, 1.0);
}
"""

SIM_VORTICITY_SRC = _SIM_HEAD + """
uniform sampler2D u_vel;

void main() {
    vec2 uv = gl_FragCoord.xy / u_res;
    vec2 texel = 1.0 / u_res;
    float vx1 = texture2D(u_vel, uv + vec2(0.0, texel.y)).x;
    float vx2 = texture2D(u_vel, uv - vec2(0.0, texel.y)).x;
    float vy1 = texture2D(u_vel, uv + vec2(texel.x, 0.0)).y;
    float vy2 = texture2D(u_vel, uv - vec2(texel.x, 0.0)).y;
    float curl = (vy1 - vy2) - (vx1 - vx2); // rotacional 2D (escalar)
    gl_FragColor = vec4(curl, 0.0, 0.0, 1.0);
}
"""

SIM_CONFINEMENT_SRC = _SIM_HEAD + """
uniform float u_dt;
uniform sampler2D u_vel;
uniform sampler2D u_vorticity;

void main() {
    vec2 uv = gl_FragCoord.xy / u_res;
    vec2 texel = 1.0 / u_res;
    float cL = texture2D(u_vorticity, uv - vec2(texel.x, 0.0)).x;
    float cR = texture2D(u_vorticity, uv + vec2(texel.x, 0.0)).x;
    float cB = texture2D(u_vorticity, uv - vec2(0.0, texel.y)).x;
    float cT = texture2D(u_vorticity, uv + vec2(0.0, texel.y)).x;
    float cC = texture2D(u_vorticity, uv).x;

    // gradiente da MAGNITUDE da vorticidade -> aponta pro centro de cada redemoinho
    vec2 grad = 0.5 * vec2(abs(cR) - abs(cL), abs(cT) - abs(cB));
    vec2 n = grad / (length(grad) + 1e-5);

    // forca de confinamento (Fedkiw/Stam): repoe o detalhe turbulento que a advecao
    // discreta apaga sozinha — sem isso a fumaca fica "lisa demais" depois de alguns frames
    vec2 force = 6.0 * u_dt * vec2(n.y * cC, -n.x * cC); // <- edita aqui: 6.0 = forca do confinamento

    vec2 vel = texture2D(u_vel, uv).xy + force;
    gl_FragColor = vec4(vel, 0.0, 1.0);
}
"""

SIM_DIVERGENCE_SRC = _SIM_HEAD + """
uniform sampler2D u_vel;

void main() {
    vec2 uv = gl_FragCoord.xy / u_res;
    vec2 texel = 1.0 / u_res;
    float L = texture2D(u_vel, uv - vec2(texel.x, 0.0)).x;
    float R = texture2D(u_vel, uv + vec2(texel.x, 0.0)).x;
    float B = texture2D(u_vel, uv - vec2(0.0, texel.y)).y;
    float T = texture2D(u_vel, uv + vec2(0.0, texel.y)).y;
    float div = 0.5 * ((R - L) + (T - B));
    gl_FragColor = vec4(div, 0.0, 0.0, 1.0);
}
"""

SIM_PRESSURE_SRC = _SIM_HEAD + """
uniform sampler2D u_pressure;
uniform sampler2D u_divergence;

void main() {
    vec2 uv = gl_FragCoord.xy / u_res;
    vec2 texel = 1.0 / u_res;
    float L = texture2D(u_pressure, uv - vec2(texel.x, 0.0)).x;
    float R = texture2D(u_pressure, uv + vec2(texel.x, 0.0)).x;
    float B = texture2D(u_pressure, uv - vec2(0.0, texel.y)).x;
    float T = texture2D(u_pressure, uv + vec2(0.0, texel.y)).x;
    float div = texture2D(u_divergence, uv).x;
    float p = (L + R + B + T - div) * 0.25; // relaxacao de Jacobi pra ∇²p = ∇·u
    gl_FragColor = vec4(p, 0.0, 0.0, 1.0);
}
"""

SIM_PROJECT_SRC = _SIM_HEAD + """
uniform sampler2D u_vel;
uniform sampler2D u_pressure;

void main() {
    vec2 uv = gl_FragCoord.xy / u_res;
    vec2 texel = 1.0 / u_res;
    float L = texture2D(u_pressure, uv - vec2(texel.x, 0.0)).x;
    float R = texture2D(u_pressure, uv + vec2(texel.x, 0.0)).x;
    float B = texture2D(u_pressure, uv - vec2(0.0, texel.y)).x;
    float T = texture2D(u_pressure, uv + vec2(0.0, texel.y)).x;
    vec2 vel = texture2D(u_vel, uv).xy - 0.5 * vec2(R - L, T - B); // projeta pra campo sem divergencia
    gl_FragColor = vec4(vel, 0.0, 1.0);
}
"""

SIM_ADVECT_DENS_SRC = _SIM_HEAD + """
uniform float u_dt;
uniform sampler2D u_vel;
uniform sampler2D u_density;
uniform sampler2D u_texture_0;
uniform sampler2D u_texture_prev;

void main() {
    vec2 uv = gl_FragCoord.xy / u_res;
    vec2 vel = texture2D(u_vel, uv).xy;
    vec2 back_uv = uv - vel * u_dt;
    float old = texture2D(u_density, back_uv).r;

    vec3 cur = texture2D(u_texture_0, uv).rgb;
    vec3 prev = texture2D(u_texture_prev, uv).rgb;
    float motion = clamp(length(cur - prev) * 3.0, 0.0, 1.0); // <- edita aqui: sensibilidade

    float density = clamp(old * 0.985 + motion * 0.6, 0.0, 1.0); // <- edita aqui: decaimento / injecao
    gl_FragColor = vec4(density, density, density, 1.0);
}
"""

PRESSURE_ITERS = 20  # <- edita aqui: mais = fumaca "gruda" menos, mas cada um custa 1 passe

# --- FUMAÇA "de verdade" (EFEITO 6 do Caos.frag / Fumaca.frag). A sim de fluido acima
# (Stable Fluids) virou o EFEITO 7 "SILHUETA" — interessante mas nao parece fumaca (grade
# baixa + confinamento de vorticidade forte = blobs grandes, nao fibras finas).
# Essa aqui e' proceduralizada: motion (frame atual x anterior) decide ONDE nasce densidade;
# a FORMA de como ela se move usa "turbulence" (tecnica classica de fogo/fumaca/fluido em
# shader 2D barato — ver GM Shaders "Xor", mini.gmshaders.com/p/turbulence): desloca a
# posicao de LEITURA com senos cuja fase e' a propria posicao girada por uma matriz de
# rotacao que acumula giro a cada iteracao (frequencia sobe, amplitude cai — como fBm, so
# que deformando coordenada em vez de somar ruido). Sozinha, sem ruido aleatorio nenhum, ja
# da o jeito "puxado"/fibroso que curl noise generico nao dava. + difusao (4 vizinhos) +
# decaimento nao-uniforme (esse sim usa ruido, so pra variar quanto tempo cada "fio" dura).
# Roda numa unica textura, na resolucao do CONTEUDO (1 passe so' — ver p_fumaca/u_fumaca em main()).
SMOKE_SRC = """
#ifdef GL_ES
precision mediump float;
#endif
uniform vec2 u_resolution;
uniform float u_time;
uniform sampler2D u_texture_0;    // frame atual
uniform sampler2D u_texture_prev; // frame de 1 iteracao atras (mesma fonte)
uniform sampler2D u_smoke_prev;   // buffer de fumaca do frame anterior (ping-pong)

float random(vec2 p) { return fract(sin(dot(p, vec2(12.9898, 78.233))) * 43758.5453); }

// so' pro decaimento nao-uniforme (passo 3) — a advecao em si usa turbulence(), nao isso
float vnoise(vec2 p) {
    vec2 i = floor(p);
    vec2 f = fract(p);
    float a = random(i), b = random(i + vec2(1.0, 0.0));
    float c = random(i + vec2(0.0, 1.0)), d = random(i + vec2(1.0, 1.0));
    vec2 u = f * f * (3.0 - 2.0 * f);
    return mix(a, b, u.x) + (c - a) * u.y * (1.0 - u.x) + (d - b) * u.x * u.y;
}

void main() {
    vec2 uv = gl_FragCoord.xy / u_resolution;
    vec2 texel = 1.0 / u_resolution;

    // 1) MOVIMENTO: diferenca de cor entre o frame atual e o anterior = objeto se mexendo ali
    vec3 cur = texture2D(u_texture_0, uv).rgb;
    vec3 prev = texture2D(u_texture_prev, uv).rgb;
    float motion = clamp(length(cur - prev) * 3.0, 0.0, 1.0); // <- edita aqui: sensibilidade

    // 2) ADVECCAO por TURBULENCIA — 5 iteracoes de "seno com fase = posicao girada":
    float local = texture2D(u_smoke_prev, uv).r; // densidade aqui ANTES de deslocar, so pra guiar a subida
    vec2 tp = uv * 3.0 + u_time * 0.1;
    float freq = 2.0;
    mat2 rot = mat2(0.6, -0.8, 0.8, 0.6);
    vec2 turb = vec2(0.0);
    for (int i = 0; i < 5; i++) {                  // <- edita aqui: mais iteracoes = mais fibra fina (mais caro)
        float phase = freq * (rot * tp).y + 0.4 * u_time + float(i);
        turb += rot[0] * sin(phase) / freq;
        rot *= mat2(0.6, -0.8, 0.8, 0.6);
        freq *= 1.4;
    }
    vec2 wind = turb * 0.025;                      // <- edita aqui: 0.025 = forca da turbulencia
    wind.y += 0.004 + 0.012 * local;                // <- edita aqui: fumaca densa (perto da fonte) sobe mais rapido

    // difusao: mistura o centro com 4 vizinhos -> a fumaca dissolve/amacia em vez de ficar
    // com cara de ruido estatico (sem isso cada "fio" fica com borda dura)
    float old = texture2D(u_smoke_prev, uv + wind).r * 0.4
              + texture2D(u_smoke_prev, uv + wind + vec2(texel.x, 0.0)).r * 0.15
              + texture2D(u_smoke_prev, uv + wind - vec2(texel.x, 0.0)).r * 0.15
              + texture2D(u_smoke_prev, uv + wind + vec2(0.0, texel.y)).r * 0.15
              + texture2D(u_smoke_prev, uv + wind - vec2(0.0, texel.y)).r * 0.15;

    // 3) DECAIMENTO NAO-UNIFORME: um ruido lento e grande decide quais "fios" de fumaca
    // duram mais e quais dissipam rapido — sem isso tudo desbota junto e parece um filtro
    // de video, nao fumaca de verdade
    float clump = vnoise(uv * 2.0 - u_time * 0.03);
    float decay = mix(0.945, 0.975, clump);              // <- edita aqui: 0.945 dissipa rapido .. 0.975 dura mais
    float density = clamp(old * decay + motion * 0.5, 0.0, 1.0); // <- edita aqui: 0.5 = injecao no movimento

    gl_FragColor = vec4(density, density, density, 1.0);
}
"""

state = {'frame': np.zeros(FRAME_SIZE, dtype=np.uint8), 'amp': 0.0, 'bass': 0.0, 'mid': 0.0, 'treble': 0.0,
         'kick': 0.0, 'beats': 0.0, 'build': 0.0, 'dominant': (0.5, 0.5, 0.5),
         # ritmo.py: u_bpm, posicao na batida/compasso (0..1, calculada no render) e o TOM (matiz da cor
         # do tom, menor 0/1, confianca 0..1)
         'bpm': 0.0, 'beat': 0.0, 'bar': 0.0, 'key_hue': 0.0, 'key_minor': 0.0, 'key_conf': 0.0,
         'bpos': 0.0,   # batidas desde o '1', continuo (relogio dos LFOs do dash v4; sem tempo = 120 BPM)
         # faixas finas de mixagem (Sub-bass..Air) — controlam u_subbass..u_air no shader
         'subbass': 0.0, 'lowmid': 0.0, 'midrange': 0.0, 'highmid': 0.0, 'presence': 0.0,
         'treble_hi': 0.0, 'brilho': 0.0, 'air': 0.0, 'spectrum': [], 'image': {}, 'out_image': {}, 'bounce_busy': [],
         'audio_source': '', 'video': None, 'video_label': '', 'video_id': '', 'output': {},
         # canais por instrumento (ver tuning.CHANNELS) — controlam u_chan/u_chan_hit no shader
         'chan': [0.0] * MAX_CHANNELS, 'chan_hit': [0.0] * MAX_CHANNELS,
         # transicao de midia em andamento: None ou {'path','ms','from' (frame A),'t0'} — o
         # video_thread poe na troca, o loop GL roda o passe FBO e limpa quando progress>=1.
         'transition': None}
running = True


def get_screen_size():
    return plat.screen_size()


def get_monitors(virtual=True):
    """Nome, w, h, x, y, primario de cada saida conectada (ordem do xrandr) + o telao VIRTUAL do
    simulador (src/telao_sim.py aberto; virtual=True, a direita da tela — dash_data.virtual_outputs).
    virtual=False = so' as reais (captura de tela)."""
    monitors = plat.monitors()
    if virtual:
        right = max((m['x'] + m['w'] for m in monitors), default=0)   # o telao virtual comeca a direita
        monitors += [{k: v[k] for k in ('name', 'w', 'h', 'x', 'y', 'primary', 'virtual')}
                     for v in dash_data.virtual_outputs(right)]
    return monitors


def pick_monitor(name=None, virtual=False):
    monitors = get_monitors(virtual)
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
        if cfg.get('fullscreen') and mon.get('virtual'):   # telao do simulador: so' o tamanho (o WM
            win_w, win_h = mon['w'], mon['h']             # puxa uma tira pra tela; o resto fica fora)
            label = f"telão virtual {mon['name']}"
        elif cfg.get('fullscreen'):
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


def _wm_fullscreen():
    """Pede tela cheia ao gerenciador de janelas (_NET_WM_STATE_FULLSCREEN): so' NOFRAME no
    tamanho do monitor fica ATRAS da barra de tarefas do Cinnamon; com o estado fullscreen a
    saida cobre a barra, como o --kiosk fazia no dash. Sem wmctrl: fica como antes."""
    wid = pygame.display.get_wm_info().get('window')
    if not wid:
        return
    pygame.event.pump()   # janela mapeada antes do pedido
    try:
        subprocess.run(['wmctrl', '-i', '-r', hex(wid), '-b', 'add,fullscreen'],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2)
    except (OSError, subprocess.TimeoutExpired):
        pass


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
    try:  # icone do PRISMA na barra (antes do set_mode; sem ele fica a cobra do pygame)
        pygame.display.set_icon(pygame.image.load(os.path.join(_ROOT, 'favicon.png')))
    except (pygame.error, FileNotFoundError):
        pass
    if os.environ.get('PRISMA_HIDDEN'):   # testes: renderiza igual, mas a janela nunca aparece na tela
        flags |= pygame.HIDDEN
    pygame.display.set_mode((win_w, win_h), flags)
    pygame.display.set_caption('PRISMA! · saída')
    if cfg.get('fullscreen') and not label.startswith('telão virtual'):   # WM encolheria pro monitor real
        _wm_fullscreen()
    glViewport(0, 0, win_w, win_h)

    vbo = glGenBuffers(1)
    glBindBuffer(GL_ARRAY_BUFFER, vbo)
    glBufferData(GL_ARRAY_BUFFER, np.array([-1, -1, 3, -1, -1, 3], dtype=np.float32), GL_STATIC_DRAW)

    def _mktex(w, h, alloc=False, float_fmt=False):
        t = glGenTextures(1)
        glBindTexture(GL_TEXTURE_2D, t)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR)
        if float_fmt:
            # RGBA32F: velocidade/pressao/divergencia/vorticidade da sim precisam de valor
            # negativo + precisao pro Jacobi convergir sem serrilhar (8 bits nao da conta)
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
            glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA32F, w, h, 0, GL_RGBA, GL_FLOAT, None)
        elif alloc:
            glTexImage2D(GL_TEXTURE_2D, 0, GL_RGB, w, h, 0, GL_RGB, GL_UNSIGNED_BYTE, None)
        return t

    tex = _mktex(WIDTH, HEIGHT, alloc=True)     # mistura das fontes (CPU), glTexSubImage2D so' quando muda
    tex_prev = _mktex(WIDTH, HEIGHT, alloc=True)  # frame de 1 iteracao atras — detecta movimento (fumaca)

    # campos da SIMULACAO DE FUMACA (Stable Fluids — ver SIM_*_SRC): velocidade/pressao numa
    # grade menor (SIM_W x SIM_H), tudo ping-pong exceto vorticidade/divergencia (recalculadas
    # do zero a cada frame, nao precisam persistir). 1 FBO so, reaproveitado pelos 7 passes.
    sim_vel = [_mktex(SIM_W, SIM_H, float_fmt=True), _mktex(SIM_W, SIM_H, float_fmt=True)]
    sim_density = [_mktex(SIM_W, SIM_H, alloc=True), _mktex(SIM_W, SIM_H, alloc=True)]
    sim_pressure = [_mktex(SIM_W, SIM_H, float_fmt=True), _mktex(SIM_W, SIM_H, float_fmt=True)]
    sim_vort = _mktex(SIM_W, SIM_H, float_fmt=True)
    sim_div = _mktex(SIM_W, SIM_H, float_fmt=True)
    sim_fbo = glGenFramebuffers(1)

    # par ping-pong da FUMAÇA procedural (ver SMOKE_SRC) — resolucao do conteudo, 1 passe so'
    fumaca_tex = [_mktex(WIDTH, HEIGHT, alloc=True), _mktex(WIDTH, HEIGHT, alloc=True)]

    print(f'saida: {label} ({win_w}x{win_h}+{pos[0]}+{pos[1]})')
    return (win_w, win_h, pos, label, vbo, tex, tex_prev,
            sim_vel, sim_density, sim_pressure, sim_vort, sim_div, sim_fbo, fumaca_tex)


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


_dims_cache = {}


def _probe_dims(path):
    """(largura, altura) do 1o stream de video de `path` via ffprobe; None se falhar. Cacheado."""
    if path not in _dims_cache:
        try:
            out = subprocess.check_output(
                ['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries',
                 'stream=width,height', '-of', 'csv=p=0:s=x', path],
                stderr=subprocess.DEVNULL, timeout=5).decode().strip()
            w, h = (int(x) for x in out.split('x')[:2])
            _dims_cache[path] = (w, h) if w and h else None
        except (subprocess.SubprocessError, ValueError, OSError):
            _dims_cache[path] = None
    return _dims_cache[path]


# --- REBATE (item de MEDIA com "bounce": true): o video passa inteiro pra frente, depois inteiro
# de tras pra frente, em loop — e desacelera perto de cada virada (fim da ida / comeco da volta,
# e o mesmo na volta->ida) pra quina nao ficar seca. Pre-renderiza UMA vez (ffmpeg: reverse +
# setpts com rampa + framerate blend pra suavizar a camera lenta) num cache fora de media/, e o
# resto do pipeline (loop -stream_loop, pool, _fit_vf) toca esse arquivo sem saber de nada.
# ponytail: o filtro reverse segura o clipe inteiro na RAM (reduzido a <=640px, ~0.35-0.46 MB
# por frame) -> teto BOUNCE_MAX_S; video mais longo toca normal. Upgrade: reverter em pedacos.
BOUNCE_RAMP_S = 0.8    # duracao (s de video original) da desaceleracao antes/depois de cada virada
BOUNCE_SLOW = 0.5      # velocidade na virada (1 = normal): 0.5 = 2x mais lento no ponto de rebate
BOUNCE_MAX_S = 60
BOUNCE_DIR = os.path.join(os.environ.get('XDG_CACHE_HOME') or os.path.expanduser('~/.cache'),
                          'prisma', 'bounce')
_bounce_jobs = {}  # caminho do original -> 'busy' | 'fail'
_media_procs = {}  # caminho do original -> {Popen} tocando ele agora (pra trocar pro rebate pronto)


def _bounce_path(path):
    """arquivo de cache do rebate de `path` — muda se o original ou os parametros mudarem."""
    import hashlib
    st = os.stat(path)
    key = f'{os.path.abspath(path)}|{st.st_mtime_ns}|{st.st_size}|{BOUNCE_RAMP_S}|{BOUNCE_SLOW}|v1'
    return os.path.join(BOUNCE_DIR, hashlib.sha1(key.encode()).hexdigest()[:16] + '.mp4')


def _ease_pts(dur):
    """expressao do setpts: tempo de saida em funcao do tempo T do video. Rampa de R segundos em
    cada ponta; dentro dela o custo por segundo de video (1/velocidade) sobe linear de 1 ate
    1/BOUNCE_SLOW na virada -> tempo = integral = termo quadratico. Meio = velocidade normal."""
    r = min(BOUNCE_RAMP_S, dur / 3)
    c = 1 / BOUNCE_SLOW - 1
    a = r + c * r / 2                     # tempo gasto na rampa inicial
    e = dur - r                           # onde comeca a rampa final
    return (f"'if(lt(T,{r}),T+{c}*(T-T*T/(2*{r})),"
            f"if(lt(T,{e}),{a}+T-{r},"
            f"{a}+{e - r}+(T-{e})+{c}*(T-{e})*(T-{e})/(2*{r})))/TB'")


def _render_bounce(path, out):
    try:
        dur = float(subprocess.check_output(
            ['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', path],
            stderr=subprocess.DEVNULL, timeout=10).decode().strip())
        if not 0.3 < dur <= BOUNCE_MAX_S:
            raise ValueError(f'duracao {dur:.1f}s fora de (0.3, {BOUNCE_MAX_S}]s')
        ease = _ease_pts(dur)
        graph = ('[0:v]fps=30,scale=640:640:force_original_aspect_ratio=decrease:force_divisible_by=2,'
                 'setsar=1,split[a][b];'
                 f'[b]reverse,setpts=PTS-STARTPTS,setpts={ease}[rv];'
                 f'[a]setpts=PTS-STARTPTS,setpts={ease}[fw];'
                 '[fw][rv]concat=n=2:v=1:a=0,framerate=fps=30[out]')
        os.makedirs(BOUNCE_DIR, exist_ok=True)
        tmp = out + '.part.mp4'
        subprocess.run(['ffmpeg', '-y', '-loglevel', 'error', '-i', path, '-filter_complex', graph,
                        '-map', '[out]', '-an', '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '18',
                        '-pix_fmt', 'yuv420p', tmp], check=True, timeout=600)
        os.replace(tmp, out)
        _bounce_jobs.pop(path, None)
        print('rebate pronto:', os.path.basename(path))
        for p in list(_media_procs.get(path, ())):  # quem toca o original morre -> respawna no rebate
            p.terminate()
    except (subprocess.SubprocessError, ValueError, OSError) as ex:
        _bounce_jobs[path] = 'fail'
        print(f'rebate falhou ({os.path.basename(path)}): {ex} — tocando normal')
    finally:
        state['bounce_busy'] = [p for p, s in _bounce_jobs.items() if s == 'busy']


def _bounce_source(path):
    """caminho a tocar pra um item com rebate: o cache se pronto; senao dispara o render (1x, em
    thread) e devolve o original enquanto isso."""
    try:
        out = _bounce_path(path)
    except OSError:
        return path
    if os.path.isfile(out):
        return out
    if path not in _bounce_jobs:
        _bounce_jobs[path] = 'busy'
        state['bounce_busy'] = [p for p, s in _bounce_jobs.items() if s == 'busy']
        print('rebate: preparando', os.path.basename(path), '...')
        threading.Thread(target=_render_bounce, args=(path, out), daemon=True).start()
    return path


MAX_SCREENS = 16   # = tamanho dos u_sa[]/u_sb[] do LAYER_BLEND_SRC e das linhas de u_poly


def _shape_in(t, bounds):
    """Tela (x, y, w, h, rot, poly — dash_data.screen_axes) -> no canvas (0..1, origem em cima;
    bounds = (x0, y0, W, H) do canvas, nas mesmas unidades): (bbox, o, ex, ey, poly). Ponto da tela
    (u, v) = o + u*ex + v*ey; poly = [(u, v)] ou None. Erro de campo = ValueError/KeyError."""
    x0, y0, W, H = bounds
    b = dash_data.screen_bbox(t)
    o, ex, ey = dash_data.screen_axes(t)
    return (((b[0] - x0) / W, (b[1] - y0) / H, (b[2] - b[0]) / W, (b[3] - b[1]) / H),
            ((o[0] - x0) / W, (o[1] - y0) / H), (ex[0] / W, ex[1] / H), (ey[0] / W, ey[1] / H), dash_data.screen_poly(t))


def _raster(pm):
    """(w, h) do PIXEL_MAP ligado e valido, senao None."""
    try:
        if isinstance(pm, dict) and pm.get('on') and int(pm['w']) >= 16 and int(pm['h']) >= 16:
            return int(pm['w']), int(pm['h'])
    except (KeyError, TypeError, ValueError):
        pass
    return None


def _valid_screens(screens):
    """tuning.SCREENS -> [(t, bbox, w, h, pw, ph)] das telas com x/y/w/h validos (ate MAX_SCREENS).
    A ORDEM daqui = a das shapes do _stage, dos blocos do _out_blocks e das linhas de u_poly."""
    scr = []
    for t in screens or []:
        try:
            x, y, w, h = (float(t[k]) for k in ('x', 'y', 'w', 'h'))
            pw, ph = int(t.get('pw') or 0), int(t.get('ph') or 0)
            if w > 0 and h > 0:
                scr.append((t, dash_data.screen_bbox(t), w, h, pw, ph))
        except (KeyError, TypeError, ValueError, AttributeError):
            continue
    return scr[:MAX_SCREENS]


MAX_CANVAS_PX = 3840 * 2160   # canvas MAPEADO (pixel map) = a mistura: acima disso a densidade cai junto


def _stage(screens, win_w, win_h, max_px=None):
    """Canvas e telas -> (cw, ch, shapes). shapes = cada tela no canvas (_shape_in); com telas, a
    camada so' aparece dentro delas (fora = preto). O canvas e' SEMPRE o palco fisico (tuning.SCREENS =
    [{name, x, y, w, h (metros, origem em cima a esquerda), pw, ph, rot, poly}]): o retangulo que
    envolve o contorno de todas, com os vaos entre elas, na MAIOR densidade (px/m) entre elas (ate
    8192; max_px = teto de area, a densidade cai por igual). Com o PIXEL MAP ligado esse canvas vira a
    mistura e cada tela e' copiada dele pro bloco dela no raster (_out_blocks, OUTPUT_MAP_SRC) — como o
    input map x output map do Resolume / stage x feed do disguise. Sem telas: o canvas e' a janela."""
    scr = _valid_screens(screens)
    if not scr:
        return win_w, win_h, []
    x0, y0 = min(t[1][0] for t in scr), min(t[1][1] for t in scr)
    W = max(t[1][2] for t in scr) - x0
    H = max(t[1][3] for t in scr) - y0
    dens = max(max(t[4] / t[2], t[5] / t[3]) for t in scr) or 100.0
    k = min(dens, 8192 / W, 8192 / H)
    if max_px:
        k = min(k, math.sqrt(max_px / (W * H)))
    return (max(16, int(round(W * k))), max(16, int(round(H * k))),
            [_shape_in(t[0], (x0, y0, W, H)) for t in scr])


def _out_blocks(screens, pm):
    """PIXEL MAP (tuning.PIXEL_MAP = {on, w, h}: o TELAO, que o computador ve como UMA resolucao — os
    gabinetes e o espaco entre eles estao na processadora) -> None (desligado/invalido/sem blocos) ou
    (rw, rh, blocos), blocos alinhados com as shapes do _stage: (ox, oy, fw, fh, q) em px do raster
    (origem em cima; fw x fh = o que o bloco ocupa, pw x ph deitado se q e' impar) ou None (tela fora
    do raster). q = orot / 90: o painel entra GIRADO no raster (gabinete deitado na processadora)."""
    rr = _raster(pm)
    if not rr:
        return None
    out = []
    for t, *_ in _valid_screens(screens):
        try:
            ox, oy, pw, ph = (int(t[k]) for k in ('ox', 'oy', 'pw', 'ph'))
            q = int(round(float(t.get('orot') or 0) / 90.0)) % 4
            out.append(((ox, oy, ph, pw, q) if q % 2 else (ox, oy, pw, ph, q)) if pw > 0 and ph > 0 else None)
        except (KeyError, TypeError, ValueError, AttributeError):
            out.append(None)
    return (rr[0], rr[1], out) if any(out) else None


def _map_uniforms(shapes, blocks):
    """Telas + blocos -> (u_ba, u_bb, u_bc) do OUTPUT_MAP_SRC, um vec4 por tela (fora do raster = zeros)."""
    ba, bb, bc = [], [], []
    for (_, o, ex, ey, poly), b in zip(shapes, blocks):
        ba.append(b[:4] if b else (0, 0, 0, 0))
        bb.append((o[0], o[1], ex[0], ex[1]))
        bc.append((ey[0], ey[1], b[4] if b else 0, len(poly or ())))
    return [np.array(x, np.float32).ravel() for x in (ba, bb, bc)]


POLY_TEX_W = dash_data.MAX_POLY   # textura dos poligonos: POLY_TEX_W x MAX_SCREENS, linha i = tela i


def _poly_tex(shapes):
    """Poligonos das telas -> RGBA8 (MAX_SCREENS, POLY_TEX_W, 4): u e v em 16 bits (alto, baixo)
    cada — a textura u_poly que inShape (POLY_GLSL) le. Tela sem poly = linha zerada (nao e' lida)."""
    a = np.zeros((MAX_SCREENS, POLY_TEX_W, 4), np.uint8)
    for i, sh in enumerate(shapes[:MAX_SCREENS]):
        for j, (u, v) in enumerate((sh[4] or [])[:POLY_TEX_W]):
            qu, qv = int(round(u * 65535)), int(round(v * 65535))
            a[i, j] = (qu >> 8, qu & 255, qv >> 8, qv & 255)
    return a


def _mod_value(v, m, levels):
    """Knob com ♪ (entrada['mod'][knob] = {b: faixas, lo, hi}, dash v2): o som anda de lo (silencio)
    a hi (faixa no maximo), pela faixa marcada MAIS forte (levels = state: as 8 faixas + 'kick').
    Sem lo/hi (formato velho) = do valor do knob `v` ate 1. Sem ♪ = `v`."""
    if not m or not m.get('b'):
        return v
    lo, hi = m.get('lo', v), m.get('hi', 1.0)
    lv = lambda b: dash_data.lfo(m.get('lfo'), levels.get('bpos', 0.0)) if b == 'lfo' else levels.get(b, 0.0)
    return lo + (hi - lo) * min(1.0, max(lv(b) for b in m['b']))


AUTO_LO, AUTO_HI = 0.04, 0.92   # auto-nivel: pra onde vao os percentis 2% e 98% da luminancia da fonte
AUTO_GAIN = (0.6, 3.0)          # teto do ganho (escuro demais nao vira ruido gritando; claro demais desce)


def _auto_levels(frame, w, h, prev=None, k=1.0):
    """AUTO-NIVEL de uma fonte crua (np.uint8 rgb24 w x h): (ganho, deslocamento) que leva os percentis
    2%/98% da luminancia pra AUTO_LO/AUTO_HI — camera trocada / luz do palco mudou = a imagem que entra
    nos efeitos continua na mesma faixa. k = quanto anda do anterior `prev` pro novo (suavizacao)."""
    a = np.asarray(frame, np.uint8).reshape(h, w, 3)[::16, ::16].astype(np.float32) / 255.0
    lum = a[..., 0] * 0.299 + a[..., 1] * 0.587 + a[..., 2] * 0.114
    lo, hi = np.percentile(lum, (2, 98))
    g = min(AUTO_GAIN[1], max(AUTO_GAIN[0], (AUTO_HI - AUTO_LO) / max(1e-3, hi - lo)))
    new = (g, AUTO_LO - lo * g)
    if prev is None:
        return new
    return tuple(p + (n - p) * k for p, n in zip(prev, new))


class Limiter:
    """PROTECAO DA SAIDA (tuning.LIMITS = {'on', 'bright', 'flash'}): ganho 0..1 que o loop GL aplica no
    MASTER. step(t, luma) a cada frame com a luminancia MEDIA da saida ja' limitada (0..1); a conta usa
    o nivel SEM o ganho (luma / g), entao nao oscila. Brilho: media acima do teto -> ganho = teto/nivel.
    Anti-estrobo (WCAG 2.3.1): inversoes claro<->escuro de >= FLASH_STEP no ultimo segundo; mais de 3
    flashes/s (6 inversoes) -> ganho FLASH_GAIN ate 1 s depois de parar. Desce rapido, sobe devagar."""
    FLASH_STEP, FLASH_GAIN, HOLD_S, ATTACK_S, RELEASE_S = 0.10, 0.35, 1.0, 0.05, 1.0

    def __init__(self):
        self.g, self.ext, self.dir, self.flips, self.flash_t, self.t = 1.0, None, 0, collections.deque(), -1e9, None
        self.why = ''

    def step(self, t, luma, bright=1.0, flash=True):
        raw = luma / max(self.g, 0.05)                    # o que sairia sem a protecao
        if self.ext is None:
            self.ext = raw
        d = raw - self.ext
        if (self.dir >= 0 and d <= -self.FLASH_STEP) or (self.dir <= 0 and d >= self.FLASH_STEP):
            if self.dir != 0:
                self.flips.append(t)                       # inverteu: mais meio flash
            self.dir, self.ext = (1 if d > 0 else -1), raw
        elif (self.dir > 0 and raw > self.ext) or (self.dir < 0 and raw < self.ext) or self.dir == 0:
            self.ext = raw if self.dir != 0 else self.ext   # segue o extremo na mesma direcao
        while self.flips and t - self.flips[0] > 1.0:
            self.flips.popleft()
        if flash and len(self.flips) > 6:
            self.flash_t = t
        target, self.why = 1.0, ''
        if flash and t - self.flash_t < self.HOLD_S:
            target, self.why = self.FLASH_GAIN, 'flash'
        if bright < 1.0 and raw > bright and bright / raw < target:
            target, self.why = bright / raw, 'brilho'
        dt = 0.0 if self.t is None else max(0.0, t - self.t)
        self.t = t
        tau = self.ATTACK_S if target < self.g else self.RELEASE_S
        self.g += (target - self.g) * (1.0 - math.exp(-dt / tau)) if dt else 0.0
        return self.g


def _smooth(store, key, target, k, frame, start=None):
    """Valor que DESLIZA ate `target` (um polo: anda a fracao k por frame) — knob do MIDI (128 passos)
    e do dash (25 Hz) viram movimento continuo, sem degrau. store = {key: [valor, frame do ultimo uso]}.
    Chave nova comeca em `start` (opacidade: 0 = entra com fade) ou ja' no alvo."""
    e = store.get(key)
    if e is None:
        e = store[key] = [target if start is None else start, frame]
    v = target if k >= 1.0 else e[0] + (target - e[0]) * k
    if abs(target - v) < 1e-4:
        v = target
    e[0], e[1] = v, frame
    return v


def _blend_scr(shapes):
    """Telas pro LAYER_BLEND_SRC: por tela (sa, sb) = a conta INVERSA (canvas -> painel): (u, v) =
    [[sa.z, sa.w], [sb.x, sb.y]] * (c - sa.xy); sb.z = pontos do poligono (0 = painel inteiro)."""
    out = []
    for _, o, ex, ey, poly in shapes:
        det = ex[0] * ey[1] - ey[0] * ex[1] or 1e-9
        out.append(((o[0], o[1], ey[1] / det, -ey[0] / det), (-ex[1] / det, ex[0] / det, len(poly or ()), 0.0)))
    return out


def _canvas_box(win_w, win_h, cw, ch):
    """Onde o canvas cw x ch cai na janela, ENCAIXADO (barras pretas no que sobra), em uv da
    janela com origem EMBAIXO (gl_FragCoord / u_res): (x, y, w, h)."""
    if not (win_w and win_h and cw and ch):
        return (0.0, 0.0, 1.0, 1.0)
    k = (cw / ch) / (win_w / win_h)
    return ((1 - k) / 2, 0.0, k, 1.0) if k < 1 else (0.0, (1 - 1 / k) / 2, 1.0, 1 / k)


def _rect_uv(rect, box):
    """rect de um canal (OVERLAYS[i]['rect'] = [x, y, w, h] no canvas, 0..1, origem EM CIMA como
    no dash; ausente = canvas inteiro) -> uv da janela (origem embaixo) dentro de `box`."""
    x, y, w, h = rect if rect and len(rect) == 4 else (0.0, 0.0, 1.0, 1.0)
    bx, by, bw, bh = box
    return (bx + x * bw, by + (1 - y - h) * bh, max(1e-4, w * bw), max(1e-4, h * bh))


def _fit_vf(fit, src_w=0, src_h=0, pad='black'):
    """-vf de uma fonte (camera, tela ou midia) no OUTPUT: 'fill' (preencher) = ESTICA pra
    cobrir a saida inteira (pode distorcer); 'fit' = ENCAIXA inteira sem distorcer, com margens
    pretas. O 'fit' corrige o aspecto do CANVAS (FIT_W:FIT_H; sem canvas = a janela), nao so o da
    textura WIDTHxHEIGHT: a saida depois estica a textura pro canvas, entao a correcao antecipa
    esse esticao (objeto redimensionado fora do aspecto do canvas estica junto). Sem as
    dims da fonte (src_w/h=0) cai no estica."""
    if fit != 'fit' or not (src_w and src_h and FIT_W and FIT_H):
        return f'scale={WIDTH}:{HEIGHT},setsar=1'
    ta = WIDTH / HEIGHT
    r = (src_w / src_h) * ta / (FIT_W / FIT_H)   # aspecto alvo DENTRO da textura
    tw, th = (WIDTH, WIDTH / r) if r >= ta else (HEIGHT * r, HEIGHT)
    tw, th = int(round(tw)), int(round(th))
    return f'scale={tw}:{th},pad={WIDTH}:{HEIGHT}:({WIDTH}-{tw})/2:({HEIGHT}-{th})/2:{pad},setsar=1'


# opcao 2: -fflags nobuffer corta a fila interna do ffmpeg (menos latencia ate o 1o frame no
# pipe). Nao mexe em -probesize/-analyzeduration: zerar faz o h264 comecar a decodificar sem
# frame de referencia -> "co located POCs unavailable" e uns frames corrompidos na entrada.
_FAST_IN = ['-fflags', 'nobuffer']


def _spawn_ffmpeg(v):
    """v = state['video'] = {'mode':'webcam'|'screen'|'media', ...}. Sempre escala pra WIDTH x
    HEIGHT fixos (nao mexe nos globais ao vivo — trocar de fonte pelo dash mantem a resolucao
    de saida; pra aspect certo de tela, reinicie com --screen). stderr descartado: 'fonte
    morta' a gente detecta por poll/timeout, e o teardown do pool cospe broken-pipe a toa."""
    if v['mode'] == 'screen':
        r = v['region']
        cmd = ['ffmpeg', '-loglevel', 'error', *_FAST_IN, *plat.screen_input_args(r),
               '-vf', _fit_vf(v.get('fit', 'fill'), r['w'], r['h']), '-pix_fmt', 'rgb24', '-f', 'rawvideo', '-']
    elif v['mode'] == 'media':
        vf = _fit_vf(v.get('fit', 'fill'), *(_probe_dims(v['path']) or (0, 0)))
        if v.get('media_kind') == 'video':  # loop infinito, em tempo real
            src = _bounce_source(v['path']) if v.get('bounce') else v['path']
            hw, vf = plat.hw_decode(src, vf)   # GPU decodifica + escala quando da
            cmd = ['ffmpeg', '-loglevel', 'error', *_FAST_IN, '-stream_loop', '-1', '-re', *hw,
                   '-i', src, '-map', '0:v:0', '-vf', vf, '-r', '30', '-pix_fmt', 'rgb24', '-f', 'rawvideo', '-']
            if v.get('audio') and plat.IS_WIN:   # sem pass_fds no Windows: 2o ffmpeg so' pro audio
                p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
                p.audio_proc = subprocess.Popen(
                    ['ffmpeg', '-loglevel', 'error', '-stream_loop', '-1', '-re', '-i', src, '-map', '0:a:0',
                     '-ac', '1', '-ar', '44100', '-f', 's16le', '-'], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
                p.audio = p.audio_proc.stdout
                return p
            if v.get('audio'):  # fonte de audio (🔊 na mesa): 2a saida, PCM no pipe p.audio
                rfd, wfd = os.pipe()
                cmd += ['-map', '0:a:0', '-ac', '1', '-ar', '44100', '-f', 's16le', f'pipe:{wfd}']
                p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, pass_fds=(wfd,))
                os.close(wfd)
                p.audio = os.fdopen(rfd, 'rb')
                return p
            p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            if src == v['path'] and v.get('bounce'):  # rebate ainda renderizando: lembra do proc
                procs = _media_procs.setdefault(v['path'], set())
                procs.difference_update({q for q in procs if q.poll() is not None})
                procs.add(p)
                if _bounce_jobs.get(v['path']) != 'busy':  # ficou pronto nesse meio-tempo
                    p.terminate()
            return p
        else:                               # imagem parada: repete o mesmo frame a 30 fps
            cmd = ['ffmpeg', '-loglevel', 'error', '-loop', '1', '-framerate', '30',
                   '-i', v['path'], '-vf', vf, '-pix_fmt', 'rgb24', '-f', 'rawvideo', '-']
    else:
        cmd = ['ffmpeg', '-loglevel', 'error', *_FAST_IN, *plat.cam_input_args(v['device'], WIDTH, HEIGHT),
               '-vf', _fit_vf(v.get('fit', 'fill'), WIDTH, HEIGHT), '-pix_fmt', 'rgb24', '-f', 'rawvideo', '-']
    return subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)


def _kill(proc):
    """Mata o ffmpeg E ESPERA sair — v4l2 e exclusivo, sem isso o proximo ffmpeg pega
    'Device or resource busy' e a webcam nao volta."""
    proc.terminate()
    try:
        proc.wait(timeout=1.5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
    ap = getattr(proc, 'audio_proc', None)   # Windows: o ffmpeg separado do audio
    if ap:
        ap.kill()
    a = getattr(proc, 'audio', None)   # pipe de audio do video-fonte-de-audio
    if a:
        try:
            a.close()
        except OSError:
            pass


def _video_label(v):
    if not v:
        return ''
    if v['mode'] == 'media':
        return f"mídia: {v.get('name', '')}"
    return v['device'] if v['mode'] == 'webcam' else f"tela: {(v.get('region') or {}).get('name', '')}"


# --- imagens paradas: decodifica UMA vez pro buffer RGB e guarda. Trocar entre imagens ja
# vistas vira uma troca de ponteiro (~0ms) em vez de matar+respawnar o ffmpeg (~200-500ms), e
# nao deixa um ffmpeg rodando a 30 fps so pra repetir o mesmo frame.
# ponytail: cache sem teto — vive so enquanto o processo vive; ~0.9 MB por (arquivo, fit,
# tamanho de janela). Dezenas de imagens x 2-3 tamanhos = poucos MB. Poe um LRU se crescer.
_still_cache = {}
_still_alpha = {}   # mesma chave -> alpha (np.uint8[FRAME_SIZE], replicado em RGB); ausente = opaca


def _decode_still(v):
    """v = state['video'] de uma imagem -> np.uint8[FRAME_SIZE] rgb (None se falhar). Cacheado por
    (arquivo, fit, tamanho da janela): o -vf depende do aspecto da janela (ver _fit_vf). Decodifica
    em RGBA: se a imagem tem transparencia (PNG/WebP/GIF), o alpha vai pro _still_alpha e a saida
    mistura por pixel (as margens do 'fit' tambem ficam transparentes)."""
    key = (v['path'], v.get('fit', 'fill'), FIT_W, FIT_H)
    arr = _still_cache.get(key)
    if arr is None:
        vf = 'format=rgba,' + _fit_vf(v.get('fit', 'fill'), *(_probe_dims(v['path']) or (0, 0)), pad='black@0')
        try:
            out = subprocess.run(
                ['ffmpeg', '-loglevel', 'error', '-i', v['path'], '-vf', vf, '-frames:v', '1',
                 '-pix_fmt', 'rgba', '-f', 'rawvideo', '-'],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=15).stdout
        except (subprocess.SubprocessError, OSError):
            out = b''
        n = WIDTH * HEIGHT * 4
        if len(out) >= n:
            px = np.frombuffer(out[:n], dtype=np.uint8).reshape(-1, 4)
            arr = np.ascontiguousarray(px[:, :3]).reshape(-1)
            if px[:, 3].min() < 255:
                _still_alpha[key] = np.repeat(px[:, 3], 3)
            else:
                _still_alpha.pop(key, None)
            _still_cache[key] = arr
    return arr


def _is_still(v):
    return bool(v) and v.get('mode') == 'media' and v.get('media_kind') != 'video'


def _apply_still(v):
    arr = _decode_still(v)
    if arr is not None:
        state['frame'] = arr


def prewarm_media():
    """Thread daemon no start: decodifica toda imagem da galeria pro _still_cache (1a troca ja
    instantanea) e aquece _probe_dims dos videos — senao o 1o _sync_pool trava o video_thread
    num ffprobe frio por video, e o 1o video da sessao congela ate esquentar."""
    for m in dash_server.media_items(MEDIA_DIR):
        p = os.path.join(MEDIA_DIR, m.get('file', ''))
        if not os.path.isfile(p):
            continue
        if m.get('kind') == 'video':
            _probe_dims(p)
        else:
            _decode_still({'path': p, 'fit': 'fit' if m.get('fit') == 'fit' else 'fill'})


# --- opcao 3: POOL de video quente. Um ffmpeg -re por VIDEO do set de midia ativo, cada um
# lido por uma thread que so guarda o ultimo frame completo (e['frame']). Trocar de video =
# apontar pro e['frame'] do outro -> ~0ms. Preco: N decodes h264 simultaneos de CPU/RAM.
# tuning.VIDEO_POOL liga/desliga; VIDEO_POOL_MAX limita N. Respawna tudo quando a janela muda
# de tamanho (o -vf depende do aspecto — ver _fit_vf) ou o set/lista de video muda.
_pool = {}  # path -> {'v', 'proc', 'thr', 'frame', 'win', 'run'}


def _pool_reader(e):
    while e['run'] and running:
        p = e['proc']
        try:
            ready = plat.readable(p.stdout, 0.2)
        except (ValueError, OSError):
            break
        if not ready:
            if p.poll() is not None and e['run'] and running:
                time.sleep(0.3)
                e['proc'] = _spawn_ffmpeg(e['v'])
            continue
        f = read_exact(p.stdout, FRAME_SIZE)
        if f is not None:
            e['frame'] = np.frombuffer(f, dtype=np.uint8)
            e['t'] = time.monotonic()   # saude (_stale_sources): fonte parada = frame velho
            p.nframes = getattr(p, 'nframes', 0) + 1   # relogio do video (-r 30) pro audio_thread alinhar
        elif e['run'] and running:
            time.sleep(0.3)
            _kill(p)
            e['proc'] = _spawn_ffmpeg(e['v'])
    _kill(e['proc'])


def _desired_pool():
    """[(path, v-dict)] dos videos do set de midia ativo — com tecla primeiro, ate VIDEO_POOL_MAX."""
    if not getattr(tuning, 'VIDEO_POOL', 0):
        return []
    ms = getattr(tuning, 'MEDIA_SET', 'default')
    cap = max(0, int(getattr(tuning, 'VIDEO_POOL_MAX', 4)))
    keys = getattr(tuning, 'MEDIA_KEYS', {}).get(ms, {})
    items = [m for m in dash_server.media_items(MEDIA_DIR)
             if m.get('kind') == 'video' and _media_set_of(m.get('file', '')) == ms]
    items.sort(key=lambda m: m.get('name', '') not in keys)  # False (com tecla) antes de True
    out = []
    for m in items[:cap]:
        p = os.path.join(MEDIA_DIR, m.get('file', ''))
        if os.path.isfile(p):
            out.append((p, _media_v(m)))
    return out


def _sync_pool():
    """Alinha _pool com _desired_pool() no tamanho de janela atual. Idempotente."""
    win = (FIT_W, FIT_H)
    want = _desired_pool()
    want_paths = {p for p, _ in want}
    for path, e in list(_pool.items()):
        if path not in want_paths or e['win'] != win or e['v'] != dict(want)[path]:
            e['run'] = False
            _pool.pop(path, None)
    for path, v in want:
        if path not in _pool:
            e = {'v': v, 'proc': _spawn_ffmpeg(v), 'frame': None, 'win': win, 'run': True, 't': time.monotonic()}
            e['thr'] = threading.Thread(target=_pool_reader, args=(e,), daemon=True)
            e['thr'].start()
            _pool[path] = e
            print('video pool +', v['name'])


# --- CAMADAS (overlay): state['overlays'] = [{file, opacity}] de baixo pra cima (dash grava;
# ver dash_server.set_overlays). Cada camada precisa de um frame vivo: video usa o do pool se
# estiver la, senao ganha um ffmpeg proprio aqui (_ovl, mesmo _pool_reader); imagem usa o
# _still_cache (aquecido aqui, fora do loop GL). _composite mistura tudo por cima da fonte
# atual no loop GL, antes do shader/transicao/analise — nenhum deles sabe que ha camadas.
# Camada tambem pode ser uma FONTE VIVA (id 'webcam:/dev/videoN' | 'screen:<monitor>', marcada
# na lista "Fonte de imagem"): ganha um ffmpeg proprio em _ovl (chave = o id), SEMPRE — a saida
# nunca le state['frame'] (esse segue a fonte SELECIONADA, que troca a cada clique na mesa). Se a
# selecionada e' uma camada viva, o video_thread copia o frame do _ovl em vez de abrir o device
# de novo (v4l2 e' exclusivo: abrir 2x da "busy").
_ovl = {}  # path (ou id de fonte viva) -> entry igual a do _pool (so video fora do pool)


def _is_live(key):
    return isinstance(key, str) and key.startswith(('webcam:', 'screen:'))


def _chkey(o):
    """chave do CANAL (igual dash_server._chkey): 'file', ou 'file#N' pra 2a+ vez da mesma fonte."""
    d = o.get('dup')
    return f"{o.get('file', '')}#{d}" if d else o.get('file', '')


def _ins_tex(r, key, lane_out, tap_tex, dflt):
    """Textura de uma entrada B/C: '@id' = saida do modulo id (tap), 'fb' = a propria raia 1 frame atras,
    outra raia = a saida dela; sem ligacao / ainda sem saida guardada = dflt (a fonte)."""
    if r and r.startswith('@'):
        return tap_tex.get(r[1:], dflt)
    return lane_out.get(key if r == 'fb' else r, dflt)


def _post_items(o, bindings):
    """MODIFICADORES PARALELOS da peca o: ids em o['post'] -> itens da pilha dash_server.POST_KEY, na ordem,
    so' os ligados. O mesmo id em varias pecas = UM modificador (mesmos knobs) atendendo todas."""
    store = {x.get('id'): x for x in ((bindings or {}).get(dash_server.POST_KEY) or {}).get('shaders') or () if x.get('id')}
    return [store[i] for i in o.get('post') or () if i in store and not store[i].get('off')]


def _graph_wants(bindings, overlays):
    """O que precisa RODAR ou ficar GUARDADO porque alguem le (dash v4: ramo, entrada B, feedback).
    -> (lanes, taps, need): lanes = canais cuja SAIDA alguem le ('ins' = outra raia; 'fb' = a propria) ->
    lane_out; taps = ids de modulos cuja saida alguem le (fileira '@id' no ar, 'ins' '@id') -> tap_tex;
    need = canais lidos por OUTRO ou com um tap dentro: rodam mesmo a 0% ou desligados (sem ir pra saida)."""
    rows = [_chkey(o) for o in overlays or []]
    src_of = {_chkey(o): str(o['file'])[1:] for o in overlays or [] if str(o.get('file') or '').startswith('@')}
    row_of, lanes, taps, need = {}, set(), set(), set()
    for k in rows:
        for o in ((bindings or {}).get(k) or {}).get('shaders') or []:
            if o.get('id'):
                row_of[o['id']] = k
            if o.get('off'):
                continue
            for r in o.get('ins') or ():
                if r == 'fb':
                    lanes.add(k)
                elif r.startswith('@'):
                    taps.add(r[1:])
                elif r != 'src':
                    lanes.add(r)
                    need.add(r)
    vis = {_chkey(o) for o in overlays or [] if not o.get('off') and float(o.get('opacity', 1.0) or 0) > 0}
    grow = True
    while grow:   # fileira '@' que roda -> o tap dela; tap -> a fileira que tem o modulo (que entao roda)
        grow = False
        for k in vis | need:
            t = src_of.get(k)
            if t and t not in taps:
                taps.add(t)
                grow = True
        for t in taps:
            r = row_of.get(t)
            if r and r not in need:
                need.add(r)
                grow = True
    return lanes, taps, need


def _overlay_items(chans=False, scene=None):
    """[(item de MEDIA | id de fonte viva, opacidade)] das camadas validas, de baixo pra cima.
    So' as disponiveis no set ativo (state['pool']['sources']; ausente = todas). chans=True
    acrescenta a chave do canal (a mesma fonte pode vir 2x, cada canal com a sua pilha).
    scene = {overlays, pool} de OUTRA cena (a que sai numa transicao); None = a ativa."""
    ms = getattr(tuning, 'MEDIA_SET', 'default')
    by_file = {m.get('file', ''): m for m in dash_server.media_items(MEDIA_DIR)}
    sc = scene if scene is not None else state
    avail = (sc.get('pool') or {}).get('sources')
    need = _graph_wants(sc.get('bindings'), sc.get('overlays'))[2]
    out = []
    for o in sc.get('overlays') or []:
        f = o.get('file') or ''
        on = not o.get('off') and (avail is None or f in avail or f.startswith('@'))
        if not on and _chkey(o) not in need:   # desligada mas lida por outra (ramo/entrada B): roda a 0%
            continue
        a = float(o.get('opacity', 1.0)) if on else 0.0
        ck = (_chkey(o),) if chans else ()
        if _is_live(f) or f.startswith('@'):   # '@id' = fileira que nasce da saida do modulo id (dash v4)
            out.append((f, a) + ck)
            continue
        m = by_file.get(f)
        if m and _media_set_of(m.get('file', '')) == ms and \
                os.path.isfile(os.path.join(MEDIA_DIR, m.get('file', ''))):
            out.append((m, a) + ck)
    return out


def _sync_overlays():
    """Alinha _ovl com as camadas atuais (idempotente) e aquece o cache das imagens."""
    win = (FIT_W, FIT_H)
    want = {}
    apath = _audio_media()
    fr = state.get('scene_from')          # cena que SAI numa transicao: as fontes dela seguem abertas
    cu = state.get('scene_cue_sc')        # PROXIMA cena (preview): as fontes dela ja' abrem (aquecimento)
    for m, _ in _overlay_items() + (_overlay_items(scene=fr) if fr else []) + (_overlay_items(scene=cu) if cu else []):
        if isinstance(m, str) and m.startswith('@'):   # ramo: le um modulo, nao abre nada
            continue
        if _is_live(m):
            want[m] = _ovl[m]['v'] if m in _ovl and _ovl[m]['v'].get('fit') == _live_fit(m) \
                else _video_from_id(m)
            continue
        v = _media_v(m)
        if v['media_kind'] == 'video':
            if v['path'] == apath:          # fonte de audio: ffmpeg proprio (com o pipe de audio)
                want[v['path']] = dict(v, audio=True)
            elif v['path'] not in _pool:
                want[v['path']] = v
        else:
            _decode_still(v)                  # ~100ms na 1a vez; depois e' cache
    for path, e in list(_ovl.items()):
        if path not in want or e['win'] != win or e['v'] != want[path]:
            e['run'] = False
            _ovl.pop(path, None)
    for path, v in want.items():
        if path not in _ovl:
            e = {'v': v, 'proc': _spawn_ffmpeg(v), 'frame': None, 'win': win, 'run': True, 't': time.monotonic()}
            e['thr'] = threading.Thread(target=_pool_reader, args=(e,), daemon=True)
            e['thr'].start()
            _ovl[path] = e
            print('camada +', _video_label(v))
    state['audio_media'] = apath if apath in _ovl else None   # audio_thread troca de fonte ao ver isso


SRC_STALE_S = 2.0   # fonte da mistura sem frame novo por isso = parada (saude no dash)


def _stale_sources():
    """Rotulos das fontes de video NA MISTURA (camera/tela/video) sem frame novo ha SRC_STALE_S —
    camera desplugada, ffmpeg morto. Imagem parada nao entra (nao tem leitor)."""
    now, out = time.monotonic(), []
    for m, a, _ in _overlay_items(chans=True):
        if a <= 0 or (isinstance(m, str) and m.startswith('@')):
            continue
        e = _ovl.get(m) if _is_live(m) else (_pool.get(_media_v(m)['path']) or _ovl.get(_media_v(m)['path']))
        if e and 'v' in e and now - e.get('t', now) > SRC_STALE_S:
            lab = _video_label(e['v']) or str(m)
            if lab not in out:
                out.append(lab)
    return out


_alpha_now = {}   # chave do canal -> alpha do frame atual (np.uint8[FRAME_SIZE], replicado em RGB) | None


def _source_frames(scene=None, alpha=None):
    """[(chave, opacidade, frame)] das fontes MARCADAS com frame pronto, de baixo pra cima.
    chave = a do CANAL (OVERLAYS/BINDINGS: id da fonte viva ou file da midia, '#N' se repetida).
    Deixa em _alpha_now (ou no dict `alpha`) a transparencia de cada canal (imagem com alpha; None =
    opaca). scene = outra cena ({overlays, pool}: a que sai numa transicao)."""
    out = []
    alpha = _alpha_now if alpha is None else alpha
    alpha.clear()
    sc = scene if scene is not None else state
    need = _graph_wants(sc.get('bindings'), sc.get('overlays'))[2]
    for m, a, ck in _overlay_items(chans=True, scene=scene):
        if a <= 0 and ck not in need:          # a 0% so' roda quem outro le (ramo, entrada B)
            continue
        if isinstance(m, str) and m.startswith('@'):   # ramo: o "frame" e' a textura do tap (loop GL)
            out.append((ck, a, None))
            continue
        if _is_live(m):
            e = _ovl.get(m)
            f = e['frame'] if e else None
            if f is None or len(f) != FRAME_SIZE:
                continue
            out.append((ck, a, f))
        else:
            f = _overlay_frame(m)
            if f is not None:
                out.append((ck, a, f))
                alpha[ck] = _overlay_alpha(m)
    return out


def _preview_frame(which, key='', max_w=320):
    """Pixels crus REDUZIDOS pro dash v2 desenhar num canvas (GET /frame) — sem JPEG/ffmpeg,
    por isso da pra atualizar a ~15 fps. which: 'cv' = o canvas do palco (idem, state['cv_want']), 'out' = a saida (lida pequena na GPU pelo loop GL,
    so' enquanto alguem pede — ver state['out_want']), 'sel' = a fonte selecionada (state['frame']),
    'src' = um canal da mesa (key: fonte viva ou arquivo de midia, '#N' ignorado).
    Devolve (bytes rgb24, w, h) | None."""
    if which == 'steps':                       # dash v4: o sinal DEPOIS de cada modulo do canal key (empilhadas)
        state['steps_want'] = (key, time.time())
        st = state.get('steps_small') or {}
        if st.get('key') != key or not st.get('img'):
            return None
        w, h = next(iter(st['img'].values()))[1:]
        blank = bytes(w * h * 3)
        return b''.join(x[0] if x and x[1:] == (w, h) else blank for x in (st['img'].get(j) for j in range(st['n']))), w, h * st['n']
    if which == 'try':                         # dash v4: previa FORA DO AR da versao key (0..3) de um canal
        tr = state.get('try')
        if not tr:
            return None
        tr['t'] = time.time()                  # quem le mantem a previa viva
        try:
            return (state.get('try_small') or {}).get(int(key or 0))
        except ValueError:
            return None
    if which == 'cue':                         # PREVIEW da proxima cena (loop GL, so' enquanto pedida)
        state['cue_want'] = time.time()
        return state.get('cue_small') if state.get('scene_cue_sc') else None
    if which == 'lightmap':                    # foto base do mapeamento das luzes (light_scan_thread)
        return state.get('light_map')
    if which == 'out':
        state['out_want'] = time.time()
        return state.get('out_small')
    if which == 'cv':                          # o CANVAS do palco pronto (com telao: antes do raster)
        state['cv_want'] = time.time()
        return state.get('cv_small')
    if which == 'fx':                          # canal da mesa DEPOIS da pilha de efeitos (key = chave do canal)
        state.setdefault('fx_want', {})[key] = time.time()
        return (state.get('fx_small') or {}).get(key)
    if which == 'mask':                        # ASSUNTO do canal: magenta (--subj) no preto (dash: mix-blend screen)
        state.setdefault('mask_want', {})[key] = time.time()
        m = subject_mask.get(re.sub(r'#\d+$', '', key or ''))
        if m is None:
            return None
        lo, hi = _subject_params((state.get('bindings') or {}).get(key))
        s = np.clip((m / 255.0 - lo) / (hi - lo), 0, 1)
        s = s * s * (3 - 2 * s)                    # = smoothstep do shader
        a = (s[..., None] * np.array([228, 108, 255])).astype(np.uint8)
        return np.ascontiguousarray(a).tobytes(), SUBJECT_DET, SUBJECT_DET
    if which == 'comp':                        # mistura crua das fontes NO AR (so' opacidade/alpha, sem efeitos)
        f = state.get('frame_comp')
        if f is None:
            f = state.get('frame')
    elif which == 'sel':
        f = state.get('frame')
    else:
        base = re.sub(r'#\d+$', '', key or '')
        if _is_live(base):
            e = _ovl.get(base)
            f = e['frame'] if e else (state.get('frame') if base == state.get('video_id') else None)
        else:
            m = next((x for x in dash_server.media_items(MEDIA_DIR) if x.get('file') == base), None)
            try:
                f = _overlay_frame(m) if m else None
            except (KeyError, TypeError, ValueError):
                f = None
    if f is None or len(f) != FRAME_SIZE:
        return None
    s = max(1, -(-WIDTH // max_w))                 # stride inteiro: barato, sem interpolar
    a = np.asarray(f, dtype=np.uint8).reshape(HEIGHT, WIDTH, 3)[::s, ::s]
    return np.ascontiguousarray(a).tobytes(), a.shape[1], a.shape[0]


def _thumb_frame(key):
    """Frame atual de uma fonte viva (rgb24, WIDTH x HEIGHT) pra miniatura do dash; None se ela
    nao esta sendo capturada agora (desligada / ffmpeg ainda subindo)."""
    e = _ovl.get(key)
    f = e['frame'] if e else (state.get('frame') if key == state.get('video_id') else None)
    return (bytes(f), WIDTH, HEIGHT) if f is not None and len(f) == FRAME_SIZE else None


def _composite(frames):
    """Mistura na CPU das fontes marcadas (preto + cada uma por cima com a opacidade dela) — so'
    pra analise de imagem / fumaca / cor dominante. A SAIDA e' feita na GPU (ver main).
    A ULTIMA fonte opaca (opacidade 1, sem alpha) cobre as de baixo: comeca dela — com 1 fonte so'
    devolve o proprio frame (era ~3 ms por frame novo pra dar o mesmo resultado)."""
    frames = [x for x in frames if x[2] is not None]   # ramo ('@id') so' existe na GPU
    base, rest = None, frames
    for i, (k, a, f) in enumerate(frames):
        if a >= 1.0 and _alpha_now.get(k) is None:
            base, rest = f, frames[i + 1:]
    if base is not None and not rest:
        return base
    out = np.zeros(FRAME_SIZE, np.uint16) if base is None else base.astype(np.uint16)
    for k, a, f in rest:
        a8 = int(round(min(1.0, a) * 256))
        al = _alpha_now.get(k)
        if al is not None:                           # imagem com transparencia: peso por pixel
            a8 = (al.astype(np.uint16) * a8) // 255
        out = (out * (256 - a8) + f * np.uint16(1) * a8) >> 8
    return out.astype(np.uint8)


def _overlay_alpha(m):
    """alpha de uma camada de MIDIA (so imagem com transparencia; None = opaca)."""
    v = _media_v(m)
    return None if v['media_kind'] == 'video' else _still_alpha.get((v['path'], v['fit'], FIT_W, FIT_H))


def _overlay_frame(m):
    """frame atual de uma camada de MIDIA (None = ainda esquentando: pula esse frame)."""
    v = _media_v(m)
    if v['media_kind'] == 'video':
        e = _ovl.get(v['path']) or _pool.get(v['path'])
        f = e['frame'] if e else None
    else:
        f = _still_cache.get((v['path'], v['fit'], FIT_W, FIT_H))
    return f if f is not None and len(f) == FRAME_SIZE else None


def _await_first(proc, timeout=2.0):
    """Espera o 1o frame completo de `proc` (ate timeout s). np.uint8[FRAME_SIZE] ou None."""
    end = time.monotonic() + timeout
    while running and time.monotonic() < end:
        if plat.readable(proc.stdout, 0.1):
            f = read_exact(proc.stdout, FRAME_SIZE)
            return np.frombuffer(f, dtype=np.uint8) if f is not None else None
        if proc.poll() is not None:
            return None
    return None


def video_thread(mode, region=None, device=None):
    device = device or plat.default_cam()
    state['video'] = {'mode': mode, 'device': device, 'region': region}  # fonte da verdade
    state['video_label'] = _video_label(state['video'])
    state['video_id'] = _video_id(state['video'])
    cur = dict(state['video'])
    cur_win = (FIT_W, FIT_H)
    pool_sig = None
    ovl_sig = None
    proc = None

    def _feed(v):
        """entry que ja decodifica `v` (video no pool, ou camada viva no _ovl) | None."""
        if not v:
            return None
        if v.get('mode') in ('webcam', 'screen'):
            return _ovl.get(_video_id(v))
        if v.get('media_kind') != 'video':
            return None
        return _pool.get(v.get('path')) or _ovl.get(v.get('path'))

    def _pooled(v):
        return _feed(v) is not None

    def _labels(v):
        state['video_label'] = _video_label(v)
        state['video_id'] = _video_id(v)

    if _is_still(cur):
        _apply_still(cur)
    elif not _pooled(cur):
        proc = _spawn_ffmpeg(cur)

    try:
        while running:
            # pool: reconstroi quando muda set / lista de video / tamanho de janela / os flags
            sig = (getattr(tuning, 'MEDIA_SET', 'default'), (FIT_W, FIT_H),
                   getattr(tuning, 'VIDEO_POOL', 0), getattr(tuning, 'VIDEO_POOL_MAX', 4),
                   tuple((m.get('file', ''), m.get('fit'), bool(m.get('bounce')))
                         for m in dash_server.media_items(MEDIA_DIR) if m.get('kind') == 'video'))
            if sig != pool_sig:
                pool_sig = sig
                _sync_pool()
            # camadas: depois do pool (video que ja esta no pool nao ganha ffmpeg proprio)
            osig = (sig, state.get('video_id'), tuple((o.get('file', ''), o.get('off', 0), o.get('audio', 0)) for o in state.get('overlays') or []),
                    tuple(sorted((getattr(tuning, 'SOURCE_FIT', None) or {}).items())),
                    tuple((state.get('pool') or {}).get('sources') or ()))
            if osig != ovl_sig:
                ovl_sig = osig
                # a selecionada virou camada viva: solta o device antes de o _ovl abrir (v4l2 busy)
                if proc and cur.get('mode') == 'webcam' and \
                        _video_id(cur) in {m for m, _ in _overlay_items() if _is_live(m)}:
                    _kill(proc)
                    proc = None
                _sync_overlays()

            win_moved = (cur.get('mode') == 'media' or cur.get('fit') == 'fit') and (FIT_W, FIT_H) != cur_win

            if state['video'] != cur:
                newcur = dict(state['video'])
                if _is_still(newcur):                         # imagem: buffer do cache, ~0ms
                    if proc:
                        _kill(proc)
                        proc = None
                    _apply_still(newcur)
                elif _pooled(newcur):                         # video no pool / camada viva
                    e = _feed(newcur)
                    if e is not None and e['frame'] is not None and proc:
                        _kill(proc)                           # pool ja quente: troca seca ~0ms
                        proc = None
                    # pool ainda frio (1o video da sessao): mantem `proc` (fonte antiga) vivo
                    # como ponte pra tela nao congelar ate o pool_reader entregar o 1o frame
                else:                                         # opcao 1: sobe o novo, espera 1 frame,
                    newproc = _spawn_ffmpeg(newcur)           # so entao mata o antigo (sem piscar)
                    first = _await_first(newproc)
                    if proc:
                        _kill(proc)
                    proc = newproc
                    if first is not None:
                        state['frame'] = first
                cur = newcur
                cur_win = (FIT_W, FIT_H)
                _labels(cur)
                print('video: fonte ->', _video_label(cur))
                continue

            if win_moved:                                     # so o -vf mudou (aspecto da janela)
                cur_win = (FIT_W, FIT_H)
                if _is_still(cur):
                    _apply_still(cur)
                elif _pooled(cur):
                    pass                                     # _sync_pool ja respawnou com o -vf novo
                elif proc:
                    newproc = _spawn_ffmpeg(cur)
                    first = _await_first(newproc)
                    _kill(proc)
                    proc = newproc
                    if first is not None:
                        state['frame'] = first
                continue

            if _pooled(cur):                                  # le o frame quente do pool/_ovl
                e = _feed(cur)
                if e is not None and e['frame'] is not None:
                    state['frame'] = e['frame']
                    if proc:                                  # pool esquentou -> larga a fonte-ponte
                        _kill(proc)
                        proc = None
                    time.sleep(0.02)
                elif proc is not None:                        # pool ainda frio: mostra a ponte ao vivo
                    if plat.readable(proc.stdout, 0.05):
                        f = read_exact(proc.stdout, FRAME_SIZE)
                        if f is not None:
                            state['frame'] = np.frombuffer(f, dtype=np.uint8)
                    elif proc.poll() is not None:
                        _kill(proc)
                        proc = None
                else:
                    time.sleep(0.02)
                continue

            if proc is None:
                if _is_still(cur):                            # imagem parada: nada a ler
                    time.sleep(0.03)
                    continue
                proc = _spawn_ffmpeg(cur)                     # ex.: pool desligado com video ativo
                continue

            # select com timeout curto: re-checa a troca de fonte a cada 50ms e nao trava se o
            # ffmpeg atual parar de produzir frame (fonte ruim, ex. /dev/video1 que nao e camera).
            if not plat.readable(proc.stdout, 0.05):
                if proc.poll() is not None:                   # ffmpeg saiu — respawna a mesma fonte
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
        if proc:
            _kill(proc)
        for e in list(_pool.values()) + list(_ovl.values()):
            e['run'] = False
        _pool.clear()
        _ovl.clear()


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


def band_tweak_maps():
    """3 dicts pro loop de suavizacao, lidos das listas por-faixa do tuning.py (popup da
    faixa no dash). Recalcula toda vez — chamar de novo apos reload do tuning.py.
      release, attack: {chave de suavizacao -> valor}. As 8 faixas finas (chave = uniform
        GLSL) usam tuning.BAND_SMOOTHING / BAND_ATTACK (uma entrada por faixa); 'amp' usa
        tuning.AMP_SMOOTHING / AMP_ATTACK_RATIO; 'bass'/'mid'/'treble' caem no SMOOTHING /
        ATTACK_RATIO global (via .get() no chamador).
      peakdecay: {NOME DE EXIBICAO -> tuning.BAND_PEAK_DECAY[i]} — named_band_levels indexa
        band_peaks por nome de exibicao, nao por uniform."""
    release = {'amp': tuning.AMP_SMOOTHING}
    attack = {'amp': tuning.AMP_ATTACK_RATIO}
    peakdecay = {}
    for i, name in enumerate(FREQ_BAND_NAMES):
        release[FREQ_BAND_UNIFORM[name]] = tuning.BAND_SMOOTHING[i]
        attack[FREQ_BAND_UNIFORM[name]] = tuning.BAND_ATTACK[i]
        peakdecay[name] = tuning.BAND_PEAK_DECAY[i]
    return release, attack, peakdecay


BAND_LONG_DECAY = 0.99995   # pico de LONGO prazo por faixa (~5 min de meia-vida a ~43 chunks/s)


def named_band_levels(spectrum, freqs, bands, band_peaks, peak_decay, band_long=None):
    """Pra cada (nome, lo, hi) em `bands` (de freq_bands()): magnitude bruta (fallback de bin
    mais proximo pra faixa mais estreita que a resolucao da FFT) e nivel relativo ao PICO
    RECENTE DA PROPRIA banda — nao ao pico entre as bandas. Isso importa porque uma banda
    estruturalmente mais forte (ex. Sub-bass) ficaria travada perto de 1.0 so por ser mais
    alta que as demais. `band_peaks` (dict {nome: pico}) e mantido pelo chamador entre
    chunks: sobe na hora com um pico novo, decai devagar por `peak_decay[nome]` (fator por
    faixa, tuning.BAND_PEAK_DECAY) — auto-gain sem escala manual."""
    out = []
    for name, lo, hi in bands:
        mask = (freqs >= lo) & (freqs < hi)
        if mask.any():
            mag = spectrum[mask].mean()
        else:
            mid = (lo + min(hi, freqs[-1])) / 2  # `hi` pode ser infinito (ultima banda)
            mag = spectrum[np.argmin(np.abs(freqs - mid))]
        band_peaks[name] = max(mag, band_peaks[name] * peak_decay[name], 1e-6)
        ceil = band_peaks[name]
        if band_long is not None:   # PISO: o teto nunca cai abaixo de BAND_FLOOR do pico de longo prazo — senao,
            # minutos sem agudo e o teto do Air desce ate o CHIADO dele, que passa a acender como se tocasse
            band_long[name] = max(mag, band_long.get(name, 1e-6) * BAND_LONG_DECAY, 1e-6)
            ceil = max(ceil, getattr(tuning, 'BAND_FLOOR', 0.25) * band_long[name])
        out.append((name, mag, min(1.0, mag / ceil)))
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
    return plat.default_audio()


# --- troca de entrada pelo dashboard: enumerar + aplicar (dash_server chama via callbacks) ---

def _list_audio_sources():
    if plat.IS_WIN:
        try:
            return plat.list_audio()
        except (FileNotFoundError, OSError):
            return []
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
    res = [{'kind': 'webcam', 'id': f'webcam:{d}', 'name': d} for d in plat.list_cams()]
    try:
        for m in get_monitors(virtual=False):
            res.append({'kind': 'screen', 'id': f"screen:{m['name']}",
                        'name': f"tela {m['name']} {m['w']}x{m['h']}" + (' *' if m['primary'] else '')})
    except Exception:
        pass
    if dash_server.media_items(MEDIA_DIR):   # UMA fonte generica; qual item toca sai da aba Visuals
        res.append({'kind': 'media', 'id': 'media', 'name': 'Media'})
    return res


def _media_set_of(file):
    """set de um item de MEDIA vem do caminho em 'file' ('<set>/x.png' -> <set>; 'x.png' -> default)."""
    head = os.path.dirname(str(file).replace('\\', '/'))
    return head.split('/')[0] if head else 'default'


def _media_v(m):
    """item de MEDIA -> dict state['video'] (mesmo formato pra fonte principal, pool e camadas)."""
    video = m.get('kind') == 'video'
    return {'mode': 'media', 'device': None, 'region': None, 'name': m.get('name', ''),
            'path': os.path.join(MEDIA_DIR, m.get('file', '')),
            'media_kind': 'video' if video else 'image',
            'fit': 'fit' if m.get('fit') == 'fit' else 'fill',
            'bounce': video and bool(m.get('bounce'))}


_has_audio_cache = {}


def _has_audio(path):
    """o arquivo tem trilha de audio? (ffprobe, cache por mtime)"""
    try:
        mt = os.path.getmtime(path)
    except OSError:
        return False
    hit = _has_audio_cache.get(path)
    if hit and hit[0] == mt:
        return hit[1]
    try:
        out = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'a', '-show_entries',
                              'stream=index', '-of', 'csv=p=0', path],
                             capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.TimeoutExpired):
        out = ''
    _has_audio_cache[path] = (mt, bool(out.strip()))
    return bool(out.strip())


def _audio_media():
    """path do video marcado 🔊 na mesa (`audio: 1` na entrada de OVERLAYS) — ele SUBSTITUI a
    fonte do PulseAudio enquanto estiver na saida. None = sem (ou canal desligado / fora do pool /
    rebate / sem trilha de audio): volta pro PulseAudio. TESTE: o audio vem de uma 2a saida do
    mesmo ffmpeg do video (p.audio) e o audio_thread alinha pelos frames (p.nframes)."""
    avail = (state.get('pool') or {}).get('sources')
    for o in state.get('overlays') or []:
        if not o.get('audio'):
            continue
        if o.get('off') or (avail is not None and o.get('file') not in avail):
            return None
        m = next((x for x in dash_server.media_items(MEDIA_DIR) if x.get('file') == o.get('file')), None)
        if not m or m.get('kind') != 'video' or m.get('bounce'):
            return None
        p = os.path.join(MEDIA_DIR, m.get('file', ''))
        return p if os.path.isfile(p) and _has_audio(p) else None
    return None


def _media_entry(name):
    """item de MEDIA por nome — prefere o do set ativo (nomes so sao unicos DENTRO do set)."""
    items = dash_server.media_items(MEDIA_DIR)
    ms = getattr(tuning, 'MEDIA_SET', 'default')
    return (next((m for m in items if m.get('name') == name and _media_set_of(m.get('file', '')) == ms), None)
            or next((m for m in items if m.get('name') == name), None))


def _live_fit(ident):
    """'fill' (estica, padrao) | 'fit' (encaixa com margens) de uma camera/tela: tuning.SOURCE_FIT
    (o dash grava; midia guarda o dela no proprio item de MEDIA)."""
    return 'fit' if (getattr(tuning, 'SOURCE_FIT', None) or {}).get(ident) == 'fit' else 'fill'


def _video_from_id(ident):
    """'webcam:/dev/videoN' | 'screen:<monitor>' | 'media' (item ativo/1o) | 'media:<nome>'
    (item especifico, vindo da aba Visuals / atalho) -> dict state['video']. Sempre escala pra
    WIDTH x HEIGHT atuais (nao muda a resolucao de saida ao vivo)."""
    kind, _, rest = ident.partition(':')
    if kind == 'webcam':
        dev = rest or plat.default_cam()
        return {'mode': 'webcam', 'device': dev, 'region': None, 'fit': _live_fit('webcam:' + dev)}
    if kind == 'media':
        media = dash_server.media_items(MEDIA_DIR)
        if rest:
            m = _media_entry(rest)
        else:  # generico: mantem o item de midia atual, senao o 1o da galeria
            cur = state.get('video') or {}
            m = (_media_entry(cur.get('name')) if cur.get('mode') == 'media' else None) \
                or (media[0] if media else None)
        if m:
            return _media_v(m)
        return {'mode': 'webcam', 'device': plat.default_cam(), 'region': None}  # sem midia -> webcam
    try:
        m = pick_monitor(rest or None)
    except SystemExit:
        m = None
    if m:
        r = {'name': m['name'], 'w': m['w'], 'h': m['h'], 'x': m['x'], 'y': m['y']}
    else:
        sw, sh = get_screen_size()
        r = {'name': 'tela toda', 'w': sw, 'h': sh, 'x': 0, 'y': 0}
    return {'mode': 'screen', 'device': None, 'region': r, 'fit': _live_fit(ident)}


def _video_id(v):
    """dict state['video'] -> id da opcao do dropdown ('webcam:..' | 'screen:..' | 'media').
    Midia colapsa pra 'media' generico — qual item toca e' escolha da aba Visuals, nao do
    dropdown; state['video']['name'] guarda qual e'."""
    if not v:
        return ''
    if v.get('mode') == 'media':
        return 'media'
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
        state['video_id'] = _video_id(state['video'])  # canonico p/ o dropdown ('media:foo' -> 'media')
    else:
        raise ValueError(f'kind desconhecido: {kind}')


def _spawn_parec(device):
    return plat.spawn_audio(device)   # parec (Linux) | loopback WASAPI (Windows) — ver plat.py


def _parec_err(p):
    try:
        p.errf.seek(0)
        return p.errf.read()[-400:].decode(errors='ignore').strip()
    except (AttributeError, OSError, ValueError):
        return ''


PAREC_STALL_S = 2.0   # parec vivo mas sem mandar nada por isso = travado -> reinicia (sink suspenso, soluco do PipeWire)


def _spawn_pacat():
    """toca o audio do video-fonte-de-audio (o mesmo trecho ja alinhado que a analise ve)."""
    return plat.spawn_player()


def audio_thread(device):
    state['audio_source'] = device  # fonte da verdade a partir daqui (o dash troca via set_input)
    try:
        proc = _spawn_parec(device)
    except FileNotFoundError:
        print('sem audio: ' + ('PyAudioWPatch nao instalado' if plat.IS_WIN else '"parec" nao encontrado (pacote pulseaudio-utils)'))
        return
    cur_src = device
    stall_t = 0.0                    # desde quando o parec nao manda nada (vigia, ver PAREC_STALL_S)
    cur_media, listen = None, None   # video-fonte-de-audio (path) e o pacat que o toca
    mstream, mbuf, mread = None, collections.deque(), 0
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
    band_release, band_attack, band_peakdecay = band_tweak_maps()  # dinamica por faixa (BAND_*)
    tuning_mtime = os.path.getmtime(TUNING_PATH)
    dash_server_mtime = os.path.getmtime(DASH_SERVER_PATH)
    dash_data_mtime = os.path.getmtime(DASH_DATA_PATH)
    smooth = {'amp': 0.0, 'bass': 0.0, 'mid': 0.0, 'treble': 0.0, **{k: 0.0 for k in FREQ_BAND_UNIFORM.values()}}
    smoothing_used = dict(smooth)  # ultimo smoothing (attack ou release) aplicado em cada chave
    band_peaks = {name: 1e-6 for name, _, _ in fine_bands}  # auto-gain: teto recente de cada banda
    band_long = {}   # pico de longo prazo (piso do teto: faixa vazia nao amplifica o proprio ruido)
    kick_baseline = 0.0
    kick_env = 0.0
    kick_decay_dynamic = tuning.KICK_DECAY  # ate a 1a batida ter intervalo medido, usa o fixo
    kick_chunk_count = 0
    kick_last_hit_chunk = 0
    amp_slow = 0.0   # media do amp nos ultimos ~10 s (referencia do crescendo, u_build)
    monitor_frame = [0]
    # estado entre throttles pro image_dash_data (auto-gain de pico + deltas de movimento/cor)
    html_img = {'peaks': {'edge': 1e-6, 'motion': 1e-6, 'sharpness': 1e-6, 'colorfulness': 1e-6},
                'prev_val': [None], 'prev_mean': [None]}
    smooth_spectrum = np.zeros(len(freqs))  # espectrograma piscava: era FFT crua, sem suavizar
    tempo, key = ritmo.Tempo(rate / chunk_samples), ritmo.Key(rate)   # BPM/fase e tom (ritmo.py)
    state['tempo_obj'] = tempo              # o render le a fase daqui (tempo.phase) a cada frame
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
                    band_release, band_attack, band_peakdecay = band_tweak_maps()
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
                                          on_set_output=set_output, on_thumb=_thumb_frame,
                                          on_frame=_preview_frame)
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
            media = state.get('audio_media')
            extra = []                       # chunks ANTERIORES do mesmo lote (video): so' pro ritmo/tom
            if media != cur_media:  # video 🔊 na mesa substitui o PulseAudio (e volta quando sai)
                cur_media = media
                for k in band_peaks:  # auto-gain nao herda o teto da fonte anterior
                    band_peaks[k] = 1e-6
                band_long.clear()
                kick_baseline = 0.0
                if media:
                    if proc:
                        _kill(proc)
                        proc = None
                    mstream, mbuf = None, collections.deque()
                    print('audio: fonte -> midia', os.path.basename(media))
                else:
                    if listen:
                        _kill(listen)
                        listen = None
                    cur_src = state['audio_source']
                    proc = _spawn_parec(cur_src)
                    print('audio: fonte ->', cur_src)
                continue
            if media:
                data = None
                e = _ovl.get(media)
                vp = e['proc'] if e else None
                st = getattr(vp, 'audio', None)
                if st is None:
                    time.sleep(0.02)
                    continue
                if st is not mstream:          # ffmpeg (re)nasceu: relogios zerados
                    mstream, mbuf, mread = st, collections.deque(), 0
                try:
                    chunk = read_exact(st, chunk_bytes)
                except (ValueError, OSError):
                    chunk = None
                if chunk is None:
                    time.sleep(0.05)
                    continue
                mbuf.append((mread, chunk))
                mread += chunk_samples
                # o audio sai do ffmpeg ~1 s antes do frame correspondente (decode de video demora
                # pra arrancar): so analisa/toca o trecho que o video (frames/30) ja alcancou
                vt = getattr(vp, 'nframes', 0) * rate / 30
                ready = []
                while mbuf and (mbuf[0][0] + chunk_samples <= vt or len(mbuf) > 400):
                    ready.append(mbuf.popleft()[1])
                if not ready:
                    continue
                if getattr(tuning, 'MEDIA_AUDIO_LISTEN', 1):
                    if listen is None or listen.poll() is not None:
                        listen = _spawn_pacat()
                    if listen:
                        try:
                            listen.stdin.write(b''.join(ready))
                            listen.stdin.flush()
                        except (BrokenPipeError, OSError, ValueError):
                            _kill(listen)
                            listen = None
                elif listen:
                    _kill(listen)
                    listen = None
                data = ready[-1]                   # niveis: o mais novo basta
                extra = ready[:-1]                 # ritmo/tom: TODOS (pular chunk = pular batida: 120 lia 90)
                state['audio_t'] = time.monotonic()
            else:
                if state['audio_source'] != cur_src:  # troca pedida pelo dash
                    _kill(proc)
                    cur_src = state['audio_source']
                    proc = _spawn_parec(cur_src)
                    print('audio: fonte ->', cur_src)
                    continue
                # VIGIA: le so' quando ha dado (select). Sem nada por PAREC_STALL_S = travado:
                # reinicia. Enquanto espera, o loop volta pro topo (reload do tuning.py segue vivo)
                # e os medidores caem pra zero em vez de congelar no ultimo valor.
                if not plat.readable(proc.stdout, 0.25):
                    stall_t = stall_t or time.monotonic()
                    if time.monotonic() - stall_t >= PAREC_STALL_S:
                        print(f'audio: sem dados ha {PAREC_STALL_S:.0f}s — reiniciando o parec ({cur_src})')
                        _kill(proc)
                        proc = _spawn_parec(cur_src)
                        stall_t = time.monotonic()
                    data = bytes(chunk_bytes)          # silencio: os medidores descem em vez de travar
                else:
                    stall_t = 0.0
                    data = read_exact(proc.stdout, chunk_bytes)
                    state['audio_t'] = time.monotonic()   # saude do dash: audio_age
                    if data is not None:
                        state.pop('audio_err', None)
                if data is None:
                    if not running:
                        break
                    err = _parec_err(proc)
                    print('audio parou' + (': ' + err if err else '') + ' — retomando ' + cur_src)
                    state['audio_err'] = err or 'a captura fechou sem dizer o motivo'   # dash: saude > audio (Windows nao tem terminal)
                    time.sleep(0.5)
                    _kill(proc)
                    proc = _spawn_parec(cur_src)
                    continue
            samples = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
            spectrum = np.abs(np.fft.rfft(samples * window))
            now_m = time.monotonic()
            for tt in state.pop('tap_q', None) or ():      # TAP do dash/MIDI (dash_server /tap)
                tempo.tap(tt)
            if state.pop('tempo_auto', False):
                tempo.auto()
            dt_c = chunk_samples / rate
            for j, ch in enumerate(extra):     # lote do video: cada chunk no instante dele, em ordem
                xs = np.frombuffer(ch, dtype=np.int16).astype(np.float32) / 32768.0
                tempo.update(now_m - (len(extra) - j) * dt_c, np.abs(np.fft.rfft(xs * window)))
                key.push(xs)
            tempo.update(now_m, spectrum)
            key.push(samples)
            state['bpm'] = round(tempo.bpm, 2)
            km = str(getattr(tuning, 'KEY_COLORS', 'quintas') or 'quintas')
            if key.tonic >= 0:
                state['key_hue'], state['key_minor'], state['key_conf'] = ritmo.key_hue(key.tonic, key.minor, km), float(key.minor), key.conf
            state['tempo'] = {'bpm': round(tempo.bpm, 1), 'conf': round(tempo.conf, 2), 'manual': int(tempo.manual),
                              'key': key.name(), 'key_conf': round(key.conf, 2), 'key_rgb': list(ritmo.key_rgb(key.tonic, key.minor, km))}
            smooth_spectrum = smooth_spectrum * tuning.SMOOTHING + spectrum * (1 - tuning.SMOOTHING)
            bass_raw = float(spectrum[bass_bins].mean())
            mid_raw = float(spectrum[mid_bins].mean())
            treble_raw = float(spectrum[treble_bins].mean())
            amp_raw = float(np.sqrt(np.mean(samples ** 2)))  # RMS do sinal normalizado (-1..1), sem escala
            raw = {
                'amp': min(1.0, amp_raw * tuning.AMP_SCALE),
                'bass': min(1.0, bass_raw * tuning.BASS_SCALE),
                'mid': min(1.0, mid_raw * tuning.MID_SCALE),
                'treble': min(1.0, treble_raw * tuning.TREBLE_SCALE),
            }
            # faixas finas (Sub-bass..Air) — todo chunk, nao so no throttle do monitor,
            # porque agora controlam uniforms de verdade (u_subbass..u_air). "level" ja
            # vem 0..1 (relativo ao pico ENTRE as 8 bandas, auto-calibrado, sem escala
            # manual por banda) — so falta suavizar igual as outras.
            named_levels = named_band_levels(spectrum, freqs, fine_bands, band_peaks, band_peakdecay, band_long)
            # faixas DESLIGADAS no dash (botao na coluna, tuning.BANDS_OFF: nomes + 'kick') = 0 pro shader/♪
            off = {FREQ_BAND_UNIFORM.get(n, n) for n in getattr(tuning, 'BANDS_OFF', None) or ()}
            for name, _, level in named_levels:
                raw[FREQ_BAND_UNIFORM[name]] = level
            for k in smooth:
                # release/attack POR FAIXA: cada uma das 8 finas tem o seu (popup da faixa),
                # 'amp' tem o AMP_*, bass/mid/treble caem no SMOOTHING/ATTACK_RATIO global.
                # attack (subindo) = release*ratio, sempre mais rapido — por isso o "smooth"
                # na tela muda sozinho em vez de travar num numero fixo.
                release = band_release.get(k, tuning.SMOOTHING)
                attack = release * band_attack.get(k, tuning.ATTACK_RATIO)
                s = attack if raw[k] > smooth[k] else release
                smoothing_used[k] = s
                smooth[k] = smooth[k] * s + raw[k] * (1 - s)
                # BANDS_ENABLED=0 so silencia o que alimenta o shader/dash ("final"); smooth[k]
                # continua calculado (auto-gain/attack-release nao perdem o fio quando reativa)
                state[k] = smooth[k] if (k not in FINE_BAND_KEYS or tuning.BANDS_ENABLED) and k not in off else 0.0

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
                if 'kick' not in off:
                    state['beats'] += 1.0   # u_beats: contador de batidas (shader da 1 passo por batida)
            else:
                kick_env *= kick_decay_dynamic
            state['kick'] = 0.0 if 'kick' in off else kick_env
            # u_build (0..1) = CRESCENDO, a memoria que o shader nao tem: sobe devagar (~20 s ate 1)
            # enquanto o som segura perto da media dos ultimos ~10 s e cai rapido (~1.5 s) quando a
            # musica baixa (break/silencio). Efeito que "vai crescendo" le daqui.
            amp_slow = amp_slow * 0.998 + state['amp'] * 0.002
            if state['amp'] > max(0.03, amp_slow * 0.9):
                state['build'] = min(1.0, state['build'] + 1 / 900)
            else:
                state['build'] = max(0.0, state['build'] - 1 / 65)

            # canal com "output" escolhido E "src" bound SUBSTITUI a variavel (kick = onset,
            # o resto = nivel) por cima do que acabou de ser calculado acima. Sem src, a
            # variavel original fica como esta — nao ha fallback implicito por nome mais.
            for slot, ch in enumerate(tuning.CHANNELS[:MAX_CHANNELS]):
                out = ch.get('output')
                if out and ch.get('src'):
                    state[out] = state['chan_hit'][slot] if out == 'kick' else state['chan'][slot]

            # audio do dash a CADA chunk (~43 Hz, barato — o dash anima a 60 fps em cima disso);
            # a analise de imagem (cara) so a cada DASH_EVERY_N_CHUNKS (~14 Hz). O resto do loop
            # e a leitura crua do parec, que nao pode atrasar.
            monitor_frame[0] += 1
            if True:
                # audio_dash_data() / image_dash_data() montam os dicts de numeros que o
                # dash HTML (dash_server -> /events) renderiza. Nao ha mais dash de terminal.
                bands_raw = [(name, mag, lvl, state[FREQ_BAND_UNIFORM[name]],
                              smoothing_used[FREQ_BAND_UNIFORM[name]])
                             for name, mag, lvl in named_levels]  # grave->agudo (ordem freq_bands())
                state['audio_dash'] = dash_data.audio_dash_data(
                    bands_raw, amp_raw, raw['amp'], state['amp'], smoothing_used['amp'],
                    state['kick'], kick_decay_dynamic, smooth_spectrum, freqs,
                    band_lohi=[(lo, hi) for _, lo, hi in fine_bands])  # tint + cinza nos buracos

                arr_s = frame_downsample(state.get('frame_comp', state['frame']), WIDTH, HEIGHT) \
                    if monitor_frame[0] % DASH_EVERY_N_CHUNKS == 0 else None
                if arr_s is not None:
                    hue_s, sat_s, val_s = rgb_to_hsv_np(arr_s)
                    gx_s, gy_s = gradient(val_s)
                    state['image'] = image_dash_data(arr_s, hue_s, sat_s, val_s, gx_s, gy_s,
                                                     state.get('frame_comp', state['frame']), WIDTH, HEIGHT, state['dominant'],
                                                     html_img['peaks'], html_img['prev_val'],
                                                     html_img['prev_mean'])
                    for k_, v_ in dash_data.img_mod_levels(state['image']).items():   # knob modulado pela IMAGEM
                        state[k_] = state.get(k_, 0.0) * 0.5 + v_ * 0.5          # ponytail: ~14 Hz, meia suavizacao
    finally:
        for q in (proc, listen):
            if q:
                _kill(q)


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
        smooth = smooth * tuning.SMOOTHING + min(1.0, amp_raw * tuning.AMP_SCALE) * (1 - tuning.SMOOTHING)
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
            state['dominant'] = dominant_color(state.get('frame_comp', state['frame']), WIDTH, HEIGHT)
        except ValueError:
            pass  # frame ainda no tamanho antigo bem no instante de um resize/troca de fonte
        time.sleep(0.1)


# OLHOS: deteccao de rosto (YuNet, cv2.FaceDetectorYN) numa thread, como a cor dominante. So'
# roda pras fontes cujo shader pede u_eyes (o loop GL poe eyes_want[chave] = (instante, frame)).
# Resultado por chave em state['eyes'] = (lx, ly, rx, ry, on): olhos em uv 0..1 da FONTE com
# origem EM CIMA (o mesmo `st` dos presets), on = 0..1 (some devagar quando perde o rosto).
# Sem cv2 (ex. app empacotado sem ele) ou sem o modelo = on fica 0 e o shader nao desenha.
EYES_MODEL = os.path.join(_ROOT, 'models', 'face_detection_yunet_2023mar.onnx')
EYES_DET_W = 320        # largura em que a deteccao roda (frame reduzido; mais = mais lento)
EYES_SMOOTH = 0.5       # 0..1, quanto a posicao nova pesa por deteccao (menos = mais liso, mais atraso)
eyes_want = {}


def eyes_thread():
    try:
        import cv2
        det = cv2.FaceDetectorYN.create(EYES_MODEL, '', (EYES_DET_W, EYES_DET_W), 0.6)
    except Exception as e:
        print('olhos: deteccao desligada ->', e)
        return
    while running:
        now = time.time()
        want = {k: f for k, (t, f) in list(eyes_want.items()) if now - t < 1.0}
        if not want:
            time.sleep(0.2)
            continue
        eyes = dict(state.get('eyes') or {})
        for k, f in want.items():
            prev = eyes.get(k)
            hit = None
            if len(f) == FRAME_SIZE:
                dh = max(1, round(HEIGHT * EYES_DET_W / WIDTH))
                img = cv2.resize(f.reshape(HEIGHT, WIDTH, 3), (EYES_DET_W, dh))
                det.setInputSize((EYES_DET_W, dh))
                _n, faces = det.detect(cv2.cvtColor(img, cv2.COLOR_RGB2BGR))
                if faces is not None and len(faces):
                    fc = max(faces, key=lambda r: r[2] * r[3])   # maior rosto
                    # landmarks YuNet: [4:6] olho direito (da pessoa = esquerda da imagem), [6:8] esquerdo
                    ax, ay, bx, by = fc[4] / EYES_DET_W, fc[5] / dh, fc[6] / EYES_DET_W, fc[7] / dh
                    hit = (ax, ay, bx, by) if ax <= bx else (bx, by, ax, ay)   # l = o da esquerda da imagem
            if hit:
                if prev and prev[4] > 0:
                    s = EYES_SMOOTH
                    hit = tuple(p + (h - p) * s for p, h in zip(prev[:4], hit))
                eyes[k] = (*hit, 1.0)
            elif prev:
                eyes[k] = (*prev[:4], max(0.0, prev[4] - 0.15))   # perdeu: some em ~0.5s
        state['eyes'] = eyes
        time.sleep(0.03)


# ASSUNTO ("selecionar assunto" do Lightroom): mascara do objeto saliente (U^2-Net-p, cv2.dnn)
# numa thread, como os olhos. So' roda pras fontes com item da pilha em region assunto/fundo (ou
# com a previa da mascara aberta): o loop GL poe subject_want[fonte base] = (instante, frame).
# Resultado em subject_mask[fonte base] = uint8 SUBJECT_DET x SUBJECT_DET, origem em cima, 0..255
# = chance de ser assunto (quadrada: a uv estica de volta). Limiar/borda (BINDINGS[canal]['mask'])
# ficam no shader de mistura. Sem cv2/modelo = sem mascara: efeito no assunto nao aparece.
SUBJECT_MODEL = os.path.join(_ROOT, 'models', 'u2netp.onnx')
SUBJECT_DET = 192       # lado da entrada da rede: 192 ~110 ms, 320 ~380 ms (12 nucleos)
SUBJECT_SMOOTH = 0.6    # 0..1, peso da mascara nova (menos = treme menos, mais atraso)
SUBJECT_TH, SUBJECT_SOFT = 0.5, 0.15   # padrao do limiar / meia-largura da borda (dash: ajustar mascara)
subject_want, subject_mask = {}, {}


def subject_thread():
    try:
        import cv2
        net = cv2.dnn.readNetFromONNX(SUBJECT_MODEL)
    except Exception as e:
        print('assunto: deteccao desligada ->', e)
        return
    while running:
        now = time.time()
        want = {k: f for k, (t, f) in list(subject_want.items()) if now - t < 1.0}
        for k in [k for k in subject_mask if k not in want]:
            subject_mask.pop(k, None)
        if not want:
            time.sleep(0.2)
            continue
        for k, f in want.items():
            if len(f) != FRAME_SIZE:
                continue
            # normalizacao do U^2-Net (ImageNet); std dos 3 canais ~igual -> 1 escala so'
            blob = cv2.dnn.blobFromImage(np.asarray(f, np.uint8).reshape(HEIGHT, WIDTH, 3), 1 / (255 * 0.226),
                                         (SUBJECT_DET, SUBJECT_DET), (123.7, 116.3, 103.5))
            net.setInput(blob)
            m = net.forward()[0, 0]
            prev = subject_mask.get(k)
            if prev is not None:
                m = prev / 255.0 + (m - prev / 255.0) * SUBJECT_SMOOTH
            subject_mask[k] = (np.clip(m, 0, 1) * 255).astype(np.uint8)
        time.sleep(0.01)


# MAPEAMENTO DAS LUZES pela camera (sem rider; dash > Luzes > mapear): luzes.scan acende canal a canal
# por Art-Net e compara fotos de uma fonte VIVA. Enquanto roda o telao fica preto (g_dim no loop GL) e o
# envio normal das luzes para. Resultado em state['light_scan']['result'] + a foto base em state['light_map'].
LIGHT_SCAN_W = 160     # largura da foto analisada (manchas de luz nao precisam de mais)


def light_scan_thread(req):
    key = req.get('src') or next((k for k in _ovl if _is_live(k)), '')
    host = str(req.get('host') or (getattr(tuning, 'LIGHTS', None) or {}).get('host') or '255.255.255.255')
    settle = min(2.0, max(0.05, float(req.get('settle', 0.25))))
    st = state['light_scan']
    tx = luzes.Sender()

    def cam():
        e = _ovl.get(key)
        return e['frame'] if e else state.get('frame')

    def grab():
        time.sleep(settle)               # o aparelho acender + a camera expor
        for _ in range(2):               # 2 frames NOVOS depois disso (o 1o pode ter comecado antes)
            f0, end = cam(), time.monotonic() + 1.0
            while cam() is f0 and time.monotonic() < end and running:
                time.sleep(0.005)
        f = cam()
        if f is None or len(f) != FRAME_SIZE:
            raise RuntimeError('a camera parou de mandar imagem')
        s_ = max(1, WIDTH // LIGHT_SCAN_W)
        return np.asarray(f, np.uint8).reshape(HEIGHT, WIDTH, 3)[::s_, ::s_]

    def prog(fr, txt):
        st.update(prog=round(fr, 3), txt=txt)
    try:
        if cam() is None:
            raise RuntimeError('nenhuma câmera no ar: ponha uma câmera na mesa')
        unis = [int(u) for u in (req.get('unis') or [0])][:8]
        res = luzes.scan(lambda u, d: tx.send({(host, u): d}), grab, unis=unis,
                         n=min(512, max(1, int(req.get('n', 128)))), progress=prog,
                         stop=lambda: bool(state.pop('light_scan_stop', False)) or not running)
        if res is None:
            st.update(run=0, txt='parado')
            return
        for f in res['fixtures']:
            if host != '255.255.255.255':
                f['host'] = host
        b = np.ascontiguousarray(res['base'])
        state['light_map'] = (b.tobytes(), b.shape[1], b.shape[0])
        st.update(run=0, prog=1.0, txt=f"{len(res['fixtures'])} aparelho(s)", result=res['fixtures'], src=key)
    except Exception as e:
        st.update(run=0, txt='erro', err=str(e))
        print('luzes: mapeamento ->', e)


def _subject_params(b):
    """(limiar - borda, limiar + borda) do smoothstep da mascara; b = BINDINGS[canal]."""
    mk = (b or {}).get('mask') or {}
    th, soft = float(mk.get('th', SUBJECT_TH)), max(0.01, float(mk.get('soft', SUBJECT_SOFT)))
    return th - soft, th + soft


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
    glBindAttribLocation(prog, 0, 'a_pos')   # a_pos sempre no 0: _use_basic nao pergunta por frame
    glLinkProgram(prog)
    if not glGetProgramiv(prog, GL_LINK_STATUS):
        raise RuntimeError(glGetProgramInfoLog(prog).decode())
    return prog


def _use_basic(prog):
    """glUseProgram + liga o unico atributo (a_pos) ao vbo do triangulo cheio de tela — todo
    programa da simulacao de fumaca usa o mesmo VERT_SRC, entao a_pos cai sempre no location 0
    (mesma logica do use_program/use_trans_program, so' que sem uniforms de conteudo pra ler)."""
    glUseProgram(prog)
    glEnableVertexAttribArray(0)   # build_program fixa a_pos no 0
    glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 0, None)


def _locs(prog, *names):
    return {n: glGetUniformLocation(prog, n) for n in names}


_STATE_U = ('amp', 'bass', 'mid', 'treble', 'kick', 'build', 'bpm', 'beat', 'bar', 'key_hue', 'key_minor',
            'key_conf') + tuple(FREQ_BAND_UNIFORM.values())


def _prog_locs(prog, manifest):
    """Locations de um programa da pilha, perguntadas UMA vez (eram ~45 glGetUniformLocation por
    camada por frame). Uniform que o shader nao declara fica fora das listas (nem chama glUniform).
    Fixa tambem as unidades de textura (estado do programa: basta 1x)."""
    g = lambda n: glGetUniformLocation(prog, n)
    u = {k: g(n) for k, n in (('res', 'u_resolution'), ('time', 'u_time'), ('beats', 'u_beats'),
                              ('dominant', 'u_dominant'), ('eyes', 'u_eyes'), ('eyes_on', 'u_eyes_on'),
                              ('test', 'u_test'), ('dim', 'u_dim'))}
    u['state'] = [(l, k) for k in _STATE_U if (l := g('u_' + k)) >= 0]
    u['chan'] = [(l, k, i) for k in ('chan', 'chan_hit') for i in range(MAX_CHANNELS) if (l := g(f'u_{k}[{i}]')) >= 0]
    # potenciometros: u_fx_<nome> do manifest {nome: padrao} -> [(nome, loc, padrao)]
    u['fx'] = [(n, l, d) for n, d in manifest.items() if (l := g('u_fx_' + n)) >= 0]
    smoke, fumaca = g('u_texture_smoke'), g('u_texture_fumaca')
    u['sim'] = smoke >= 0 or fumaca >= 0     # so' quem le roda a sim de fluido/fumaca (main)
    # ENTRADAS do modulo (item com in: 'chain'): u_texture_0 = a corrente; u_texture_1/2 = outras raias
    # (item 'ins'); u_texture_src = a fonte crua do canal, sempre
    u['ins'] = [g(f'u_texture_{i + 1}') for i in range(len(INS_UNITS))]
    u['src'] = g('u_texture_src')
    glUseProgram(prog)
    for l, unit in ((g('u_texture_0'), 0), (smoke, 3), (fumaca, 4), (u['src'], SRC_UNIT), *zip(u['ins'], INS_UNITS)):
        if l >= 0:
            glUniform1i(l, unit)
    return u


def build_sim_programs():
    """Compila os 7 programas da simulacao de fumaca (ver SIM_*_SRC) e fixa o mapeamento de
    texture units de cada um (glUniform1i so precisa ser setado 1x por programa). Chamada no
    arranque E toda vez que a janela reabre (contexto GL novo invalida os programas velhos —
    mesma razao que o 'program' do preset e' reconstruido em open_window/main())."""
    p = build_program(SIM_ADVECT_VEL_SRC)
    _use_basic(p)
    u = _locs(p, 'u_res', 'u_dt', 'u_vel', 'u_density', 'u_texture_0', 'u_texture_prev')
    glUniform1i(u['u_vel'], 0); glUniform1i(u['u_density'], 1)
    glUniform1i(u['u_texture_0'], 2); glUniform1i(u['u_texture_prev'], 3)
    adv = (p, u)

    p = build_program(SIM_VORTICITY_SRC)
    _use_basic(p)
    u = _locs(p, 'u_res', 'u_vel')
    glUniform1i(u['u_vel'], 0)
    vort = (p, u)

    p = build_program(SIM_CONFINEMENT_SRC)
    _use_basic(p)
    u = _locs(p, 'u_res', 'u_dt', 'u_vel', 'u_vorticity')
    glUniform1i(u['u_vel'], 0); glUniform1i(u['u_vorticity'], 1)
    conf = (p, u)

    p = build_program(SIM_DIVERGENCE_SRC)
    _use_basic(p)
    u = _locs(p, 'u_res', 'u_vel')
    glUniform1i(u['u_vel'], 0)
    div = (p, u)

    p = build_program(SIM_PRESSURE_SRC)
    _use_basic(p)
    u = _locs(p, 'u_res', 'u_pressure', 'u_divergence')
    glUniform1i(u['u_pressure'], 0); glUniform1i(u['u_divergence'], 1)
    pres = (p, u)

    p = build_program(SIM_PROJECT_SRC)
    _use_basic(p)
    u = _locs(p, 'u_res', 'u_vel', 'u_pressure')
    glUniform1i(u['u_vel'], 0); glUniform1i(u['u_pressure'], 1)
    proj = (p, u)

    p = build_program(SIM_ADVECT_DENS_SRC)
    _use_basic(p)
    u = _locs(p, 'u_res', 'u_dt', 'u_vel', 'u_density', 'u_texture_0', 'u_texture_prev')
    glUniform1i(u['u_vel'], 0); glUniform1i(u['u_density'], 1)
    glUniform1i(u['u_texture_0'], 2); glUniform1i(u['u_texture_prev'], 3)
    dens = (p, u)

    return {'adv': adv, 'vort': vort, 'conf': conf, 'div': div, 'pres': pres, 'proj': proj, 'dens': dens}


# TELA COM FORMA LIVRE (dash_data.screen_axes): o painel (l = u, v 0..1, origem em cima) esta' aceso
# dentro do retangulo e, se a tela tem poligono (n >= 3 pontos, linha `row` de u_poly; _poly_tex),
# dentro dele (par-impar). Entra no LAYER_BLEND_SRC.
POLY_GLSL = """
uniform sampler2D u_poly;
vec2 polyPt(float row, int j) {
    vec4 t = texture2D(u_poly, vec2((float(j) + 0.5) / %(W)d.0, (row + 0.5) / %(H)d.0));
    return vec2(dot(t.rg, vec2(65280.0, 255.0)), dot(t.ba, vec2(65280.0, 255.0))) / 65535.0;
}
bool inShape(float row, float n, vec2 l) {
    if (any(lessThan(l, vec2(0.0))) || any(greaterThan(l, vec2(1.0)))) return false;
    if (n < 3.0) return true;
    bool ins = false;
    vec2 b = polyPt(row, int(n) - 1);
    for (int j = 0; j < %(W)d; j++) {
        if (float(j) >= n) break;
        vec2 a = polyPt(row, j);
        if ((a.y > l.y) != (b.y > l.y) && l.x < (b.x - a.x) * (l.y - a.y) / (b.y - a.y) + a.x) ins = !ins;
        b = a;
    }
    return ins;
}
""" % {'W': POLY_TEX_W, 'H': MAX_SCREENS}


# --- MISTURA DAS CAMADAS DE SHADER (ver layer_program no main): cada camada e' desenhada numa
# textura propria e misturada com o acumulado (base) aqui, com opacidade u_a e modo u_mode —
# indice de dash_server.LAYER_BLENDS: 0 normal, 1 soma, 2 tela, 3 multiplicar, 4 clarear.
# Modo 0 com a=1 = copia simples de u_layer (blit final na tela; com u_flip, a fonte crua).
# u_rect/u_clip/u_sa/u_sb: so' a entrada da FONTE na saida usa (objeto no canvas, recortado nas
# telas, _blend_scr); o resto passa FULL_UV e u_nscr = 0.
LAYER_BLEND_SRC = """
#ifdef GL_ES
precision mediump float;
#endif
uniform vec2 u_res;
uniform sampler2D u_base;
uniform sampler2D u_layer;
uniform float u_a;
uniform int u_mode;
uniform int u_flip;   // 1 = u_layer e' a fonte CRUA (textura topo->baixo, como os presets leem)
uniform sampler2D u_mask;   // alpha da fonte (imagem com transparencia), topo->baixo como a crua
uniform int u_use_mask;     // 1 = alpha da fonte; 2 = so' no ASSUNTO, 3 = so' no FUNDO (u_mask = subject_mask)
uniform vec2 u_mth;         // assunto: smoothstep(x, y) da mascara (limiar -/+ borda)
uniform vec4 u_rect;   // onde u_layer entra na tela (uv da janela, origem embaixo): x, y, w, h
uniform vec4 u_clip;   // o CANVAS na janela: fora dele a camada nao aparece (barras ficam na base)
uniform int u_nscr;    // telas do palco: com telas, a camada so' aparece DENTRO delas (forma livre)
uniform vec4 u_sa[16];
uniform vec4 u_sb[16];
uniform vec2 u_lv;     // AUTO-NIVEL da fonte crua (u_flip = 1): l * ganho + deslocamento (padrao 1, 0)
""" + POLY_GLSL + """
void main() {
    vec2 uv = gl_FragCoord.xy / u_res;
    vec2 lu = (uv - u_rect.xy) / u_rect.zw;
    float a = u_a;
    if (any(lessThan(lu, vec2(0.0))) || any(greaterThan(lu, vec2(1.0))) ||
        any(lessThan(uv, u_clip.xy)) || any(greaterThan(uv, u_clip.xy + u_clip.zw))) a = 0.0;
    if (u_nscr > 0) {
        vec2 cu = (uv - u_clip.xy) / u_clip.zw;
        vec2 c = vec2(cu.x, 1.0 - cu.y);   // no canvas, origem em cima
        float in_ = 0.0;
        for (int i = 0; i < 16; i++) {
            if (i >= u_nscr) break;
            vec4 sa = u_sa[i], sb = u_sb[i];
            vec2 d = c - sa.xy;
            if (inShape(float(i), sb.z, vec2(dot(sa.zw, d), dot(sb.xy, d)))) in_ = 1.0;
        }
        a *= in_;
    }
    if (u_use_mask == 1) a *= texture2D(u_mask, vec2(lu.x, 1.0 - lu.y)).r;
    else if (u_use_mask >= 2) {
        float s = smoothstep(u_mth.x, u_mth.y, texture2D(u_mask, vec2(lu.x, 1.0 - lu.y)).r);
        a *= u_use_mask == 2 ? s : 1.0 - s;
    }
    vec3 b = texture2D(u_base, uv).rgb;
    vec4 lt = texture2D(u_layer, u_flip == 1 ? vec2(lu.x, 1.0 - lu.y) : lu);
    vec3 l = lt.rgb;
    if (u_flip == 1) l = clamp(l * u_lv.x + u_lv.y, 0.0, 1.0);
    else a *= lt.a;   // peca que desenha so' uma parte (alfa = cobertura): o resto deixa passar o de baixo
    vec3 m = l;
    if (u_mode == 1) m = min(b + l, 1.0);
    else if (u_mode == 2) m = 1.0 - (1.0 - b) * (1.0 - l);
    else if (u_mode == 3) m = b * l;
    else if (u_mode == 4) m = max(b, l);
    gl_FragColor = vec4(mix(b, m, a), 1.0);
}
"""
LAYER_BLEND_UNIT_BASE, LAYER_BLEND_UNIT_LAYER, LAYER_BLEND_UNIT_MASK = 5, 6, 7   # fora das do preset (0..4)
POLY_UNIT = 8   # u_poly (_poly_tex) do LAYER_BLEND_SRC
FULL_UV = (0.0, 0.0, 1.0, 1.0)


def build_layer_blend_program():
    p = build_program(LAYER_BLEND_SRC)
    _use_basic(p)
    u = _locs(p, 'u_res', 'u_base', 'u_layer', 'u_a', 'u_mode', 'u_flip', 'u_mask', 'u_use_mask', 'u_mth', 'u_rect', 'u_clip', 'u_nscr', 'u_sa', 'u_sb', 'u_poly', 'u_lv')
    glUniform2f(u['u_lv'], 1.0, 0.0)
    glUniform1i(u['u_base'], LAYER_BLEND_UNIT_BASE)
    glUniform1i(u['u_poly'], POLY_UNIT)
    glUniform1i(u['u_layer'], LAYER_BLEND_UNIT_LAYER)
    glUniform1i(u['u_mask'], LAYER_BLEND_UNIT_MASK)
    glUniform1i(u['u_use_mask'], 0)
    glUniform4f(u['u_rect'], *FULL_UV)
    glUniform4f(u['u_clip'], *FULL_UV)
    glUniform1i(u['u_nscr'], 0)
    return p, u


# --- PIXEL MAP / OUTPUT MAP (ultimo passe, so' com telao: _out_blocks): a janela E' o raster da
# processadora (u_box: o raster u_rast encaixado na janela; janela = raster -> 1:1); cada pixel dentro de um bloco (u_ba: ox, oy, fw, fh em px, origem em cima) vira o (u, v)
# do painel (girado u_bc.z quartos de volta: gabinete deitado), cai fora se sai do poligono (inShape) e
# busca a cor no CANVAS do palco em o + u*ex + v*ey (u_bb, u_bc.xy). Fora dos blocos = preto.
OUTPUT_MAP_SRC = """
#ifdef GL_ES
precision mediump float;
#endif
uniform vec2 u_res;
uniform vec4 u_box;
uniform vec2 u_rast;
uniform sampler2D u_canvas;
uniform int u_nblk;
uniform vec4 u_ba[16];
uniform vec4 u_bb[16];
uniform vec4 u_bc[16];
""" + POLY_GLSL + """
void main() {
    vec2 r = (gl_FragCoord.xy / u_res - u_box.xy) / u_box.zw;
    vec2 p = vec2(r.x, 1.0 - r.y) * u_rast;   // px do raster, origem em cima
    vec3 col = vec3(0.0);
    for (int i = 0; i < 16; i++) {
        if (i >= u_nblk) break;
        vec4 a = u_ba[i], b = u_bb[i], c = u_bc[i];
        if (a.z <= 0.0) continue;
        vec2 l = (p - a.xy) / a.zw;
        if (any(lessThan(l, vec2(0.0))) || any(greaterThan(l, vec2(1.0)))) continue;
        vec2 uv = l;
        if (c.z > 2.5) uv = vec2(1.0 - l.y, l.x);
        else if (c.z > 1.5) uv = 1.0 - l;
        else if (c.z > 0.5) uv = vec2(l.y, 1.0 - l.x);
        if (!inShape(float(i), c.w, uv)) continue;
        vec2 q = b.xy + uv.x * b.zw + uv.y * c.xy;
        col = texture2D(u_canvas, vec2(q.x, 1.0 - q.y)).rgb;
    }
    gl_FragColor = vec4(col, 1.0);
}
"""
OUTPUT_MAP_UNIT = 9   # u_canvas (a textura `canvas` dos layer targets)
INS_UNITS, SRC_UNIT = (10, 11), 12   # u_texture_1/2 (outras raias) e u_texture_src (fonte crua) dos modulos


def build_output_map_program():
    p = build_program(OUTPUT_MAP_SRC)
    _use_basic(p)
    u = _locs(p, 'u_res', 'u_box', 'u_rast', 'u_canvas', 'u_nblk', 'u_ba', 'u_bb', 'u_bc', 'u_poly')
    glUniform1i(u['u_canvas'], OUTPUT_MAP_UNIT)
    glUniform1i(u['u_poly'], POLY_UNIT)
    return p, u


def make_layer_targets(w, h):
    """1 FBO + 11 texturas do tamanho da MISTURA (a janela; com telao, o canvas do palco): out[0]/out[1]
    (a saida acumulada, ping-pong), src[0]/src[1] (o resultado da fonte da vez, ping-pong), layer (o
    shader da vez), canvas (a imagem final do palco antes do OUTPUT_MAP; linear: o bloco reamostra) e
    old[0]/old[1] (a mistura da cena que SAI, desenhada viva durante a transicao) e cue[0]/cue[1] (a
    PROXIMA cena, so' quando a previa dela e' pedida). Recriado quando o
    tamanho muda (main)."""
    texs = glGenTextures(13)
    for t in texs:
        glBindTexture(GL_TEXTURE_2D, t)
        filt = GL_LINEAR if t in (texs[7], texs[11]) else GL_NEAREST
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, filt)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, filt)
        rgba = t in (texs[4], texs[12])   # 'layer' = saida da peca: o ALFA dela e' cobertura (padrao ATOMO: traco/gerador)
        glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA if rgba else GL_RGB, w, h, 0, GL_RGBA if rgba else GL_RGB, GL_UNSIGNED_BYTE, None)
    return {'size': (w, h), 'fbo': glGenFramebuffers(1), 'out': [texs[0], texs[1]],
            'src': [texs[2], texs[3]], 'layer': texs[4], 'old': [texs[5], texs[8]], 'cue': [texs[9], texs[10]],
            'mask': texs[6],   # alpha da fonte da vez (WIDTH x HEIGHT, re-upado quando ela tem)
            'canvas': texs[7],
            'chain': texs[11],   # a CORRENTE virada topo->baixo (como os presets leem u_texture_0)
            'layer2': texs[12]}  # par da 'layer' pros MODIFICADORES PARALELOS (_post_items)


def build_fumaca_program():
    """Programa da FUMAÇA procedural (ver SMOKE_SRC) — 1 programa so', sem sub-passes."""
    p = build_program(SMOKE_SRC)
    _use_basic(p)
    u = _locs(p, 'u_resolution', 'u_time', 'u_texture_0', 'u_texture_prev', 'u_smoke_prev')
    glUniform1i(u['u_texture_0'], 0)
    glUniform1i(u['u_texture_prev'], 1)
    glUniform1i(u['u_smoke_prev'], 2)
    return p, u


def main():
    global running, WIDTH, HEIGHT, WIN_W, WIN_H, FIT_W, FIT_H, CMP_W, CMP_H, FRAME_SIZE, SIM_W, SIM_H

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
    parser.add_argument('--device', metavar='PATH', default=None,
                         help='no modo webcam (sem --screen), qual device v4l2 usar. Default /dev/video0. '
                              'Use uma camera virtual (ex. v4l2loopback + OBS Virtual Camera) pra capturar '
                              'uma janela em fps cheio em vez de --window')
    args = parser.parse_args()
    mode = 'screen' if args.screen else 'webcam'
    if plat.IS_WIN and (args.region or args.window is not None):
        raise SystemExit('--region/--window ainda so no Linux; use --source NOME (DISPLAY1...) ou a mesa do dash')

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
    elif args.device and args.device != '/dev/video0' and not plat.IS_WIN:
        # camera virtual (v4l2loopback/OBS) pode estar numa resolucao diferente do default —
        # pergunta pro device em vez de chutar 640x480
        out = subprocess.check_output(['v4l2-ctl', '--device=' + args.device, '--get-fmt-video']).decode()
        w, h = re.search(r'Width/Height\s*:\s*(\d+)/(\d+)', out).groups()
        WIDTH, HEIGHT = int(w), int(h)
        print(f"fonte: {args.device} ({WIDTH}x{HEIGHT})")
    FRAME_SIZE = WIDTH * HEIGHT * 3
    SIM_W, SIM_H = max(64, WIDTH // 4), max(48, HEIGHT // 4)
    state['frame'] = np.zeros(FRAME_SIZE, dtype=np.uint8)

    # config inicial da saida a partir dos argumentos de linha de comando — mesma forma que
    # set_output()/o dash usam pra pedir uma troca ao vivo (ver resolve_output/open_window)
    out_cfg = {'monitor': '', 'fullscreen': False, 'w': WIDTH, 'h': HEIGHT}
    if args.monitor is not None:
        mon = pick_monitor(args.monitor if args.monitor != '' else None, virtual=True)
        out_cfg = {'monitor': mon['name'], 'fullscreen': True, 'w': mon['w'], 'h': mon['h']}
    elif args.fullscreen:
        out_cfg = {'monitor': '', 'fullscreen': True, 'w': 0, 'h': 0}

    pygame.init()
    (WIN_W, WIN_H, out_pos, out_mode, vbo, tex, tex_prev,
     sim_vel, sim_density, sim_pressure, sim_vort, sim_div, sim_fbo, fumaca_tex) = open_window(out_cfg)
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
        'fps_target': int(getattr(tuning, 'OUTPUT_FPS', 60) or 60), 'fps': 0.0,
        'shader': os.path.basename(FRAG_PATH), 'shader_status': 'ok',
        'monitors': monitors,
    }

    # SAIDA = fontes marcadas (OVERLAYS) + a pilha de shaders de cada uma (BINDINGS) — gravadas
    # pelo dash (aba Visuals > Sets); depois o dash e' quem mexe no vivo
    if 'overlays' not in state:
        state['overlays'] = dash_server._norm_overlays(getattr(tuning, 'OVERLAYS', []))
    if 'bindings' not in state:
        state['bindings'] = dash_server._norm_bindings(getattr(tuning, 'BINDINGS', {}))
    for i, x in enumerate((list(getattr(tuning, 'MACROS', None) or []) + [0.0] * 4)[:4]):   # faders M1..M4
        state[f'm{i + 1}'] = float(x)

    uniforms = {}
    sim_want = [False]   # algum shader no ar le u_texture_smoke/_fumaca (frame anterior) -> roda a sim

    def use_program(h):
        """h = prog_cache[...]: liga o programa e aponta `uniforms` pras locations dele (_prog_locs)."""
        _use_basic(h[1])
        uniforms.clear()
        uniforms.update(h[4])
        if h[4]['sim']:
            sim_want[0] = True

    # cache de programa por arquivo de shader: compila 1x, voltar num shader ja usado e' so
    # glUseProgram. Invalidado por mtime (editou o .frag = hot-reload) e por troca de janela
    # (contexto GL novo). (mtime, program, src, manifest, locations) por caminho absoluto.
    prog_cache = {}

    # --- programa de um shader da pilha de uma fonte (state['bindings'][fonte]['shaders']):
    # prog_cache (compila 1x, hot-reload por mtime); erro de compilacao = shader pulado (lembra o
    # mtime, nao insiste) e aparece em state['output']['shader_status'].
    layer_bad = {}

    def layer_program(rel):
        lp = os.path.join(SHADERS_DIR, rel)
        try:
            mt = os.path.getmtime(lp)
        except OSError:
            return None
        hit = prog_cache.get(lp)
        if hit and hit[0] == mt:
            return hit
        if layer_bad.get(lp) == mt:
            return None
        try:
            with open(lp, encoding='utf-8') as lf:
                src = lf.read()
            prog = build_program(src)
        except (RuntimeError, OSError) as e:
            print('erro no shader', rel, '->\n', e)
            state['output']['shader_status'] = f'erro em {os.path.basename(rel)}'
            state['output']['shader_error'] = f'{rel}\n{e}'[:2000]   # detalhe no clique da saude (dash v2)
            layer_bad[lp] = mt
            return None
        if hit:
            glDeleteProgram(hit[1])
        manifest = dash_data.parse_fx_defaults(src)
        prog_cache[lp] = (mt, prog, src, manifest, _prog_locs(prog, manifest))
        state['output']['shader_status'] = 'ok'
        state['output'].pop('shader_error', None)
        return prog_cache[lp]

    blend_prog, blend_u = build_layer_blend_program()
    map_prog, map_u = build_output_map_program()
    ltargets = [None]   # make_layer_targets(...) sob demanda (camada ativa ou transicao de set)
    poly_tex = [None, None]   # textura dos poligonos das telas (_poly_tex) + o que ela tem
    lane_out = {}   # canal -> saida da raia (topo->baixo), so' das que algum modulo le ('ins'; 'fb' = a propria)
    tap_tex = {}    # id do modulo -> saida dele (topo->baixo), so' dos que alguem le (ramo '@id', 'ins' '@id'; dash v4)
    live_taps = [set()]   # taps que a cena AO VIVO pede (o resto e' apagado no fim do frame)

    def layer_targets():
        if not ltargets[0] or ltargets[0]['size'] != (CMP_W, CMP_H):
            if ltargets[0]:
                glDeleteFramebuffers(1, [ltargets[0]['fbo']])
                glDeleteTextures([t for k in ('out', 'src', 'old', 'cue') for t in ltargets[0][k]] +
                                 [ltargets[0][k] for k in ('layer', 'layer2', 'mask', 'canvas', 'chain')])
            if lane_out:
                glDeleteTextures(list(lane_out.values()))
                lane_out.clear()
            if tap_tex:
                glDeleteTextures(list(tap_tex.values()))
                tap_tex.clear()
            ltargets[0] = make_layer_targets(CMP_W, CMP_H)
        return ltargets[0]

    # troca de SET (dash_server.request_scene / tecla -> state['scene_pending']): aplicada no FIM
    # de um frame. Durante a transicao (scene_tr) as DUAS cenas sao desenhadas vivas (render_mix: a
    # nova em lt['out'], a que sai em lt['old'] com os dados guardados em scene_tr['old']) e o ultimo
    # passe mistura as duas com o .glsl de entrada do set. Transicao 'none'/sumida = corte seco.
    scene_tr = None

    # --- passe de TRANSIÇÃO: programa proprio por arquivo transitions/*.glsl (cache por mtime;
    # None = compilou com erro, nao insiste). uso: troca de SET (bloco "scene_pending" no loop).
    tuni = {}
    trans_cache = {}

    def use_trans_program(prog):
        _use_basic(prog)
        tuni['res'] = glGetUniformLocation(prog, 'u_resolution')
        tuni['progress'] = glGetUniformLocation(prog, 'u_progress')
        tuni['from'] = glGetUniformLocation(prog, 'u_from')
        tuni['to'] = glGetUniformLocation(prog, 'u_to')

    def trans_program(tpath):
        try:
            mt = os.path.getmtime(tpath)
        except OSError:
            return None
        hit = trans_cache.get(tpath)
        if hit and hit[0] == mt:
            return hit[1]
        try:
            with open(tpath, encoding='utf-8') as tf:
                prog = build_program(_wrap_transition(tf.read()))
        except (RuntimeError, OSError) as e:
            print('erro na transicao', os.path.basename(tpath), '->\n', e)
            trans_cache[tpath] = (mt, None)
            return None
        old = trans_cache.pop(tpath, None)
        if old and old[1]:
            glDeleteProgram(old[1])
        trans_cache[tpath] = (mt, prog)
        return prog

    # --- passe da SILHUETA (sim de fluido, 7 programas fixos — ver build_sim_programs()/SIM_*_SRC)
    # e da FUMAÇA (procedural, 1 programa — ver build_fumaca_program()/SMOKE_SRC). Infra interna,
    # nao presets do usuario, sem hot-reload.
    sim_progs = build_sim_programs()
    p_fumaca, u_fumaca = build_fumaca_program()
    sim_idx = 0  # ping-pong: sim_vel[sim_idx]/sim_density[sim_idx] = "atual", [1-sim_idx] = escrita
    sim_last_t = [time.perf_counter()]  # p/ calcular o dt real da simulacao (frame a frame)
    fumaca_idx = 0  # ping-pong: fumaca_tex[fumaca_idx] = "atual", [1-fumaca_idx] = escrita
    prev_frame_buf = [state['frame'].copy()]  # frame de 1 iteracao atras, pra detectar movimento
    tex_fresh = [False]   # `tex`/`tex_prev` tem a mistura atual (a sim parada nao as atualiza)
    sm_store, sm_last = {}, [0.0]   # suavizacao dos parametros (_smooth): valores atuais + relogio
    auto_lv = {}                    # auto-nivel por canal: [(ganho, deslocamento), frame que gerou]

    if capture_region and 'id' in capture_region:
        threading.Thread(target=window_capture_thread, args=(capture_region['id'],), daemon=True).start()
    else:
        threading.Thread(target=video_thread, args=(mode, capture_region, args.device), daemon=True).start()
    threading.Thread(target=prewarm_media, daemon=True).start()  # aquece _still_cache + _probe_dims dos videos
    audio_src = pick_audio_source(args.audio)
    threading.Thread(target=audio_thread, args=(audio_src,), daemon=True).start()
    for slot in range(MAX_CHANNELS):
        threading.Thread(target=channel_thread, args=(slot,), daemon=True).start()
    threading.Thread(target=dominant_color_thread, daemon=True).start()
    threading.Thread(target=eyes_thread, daemon=True).start()
    threading.Thread(target=subject_thread, daemon=True).start()
    dash_server.start(state, tuning, TUNING_PATH, lambda: running,
                      audio_source=audio_src, video_mode='screen' if args.screen else 'webcam',
                      on_inputs=list_inputs, on_set_input=set_input, on_set_output=set_output,
                      on_thumb=_thumb_frame, on_frame=_preview_frame)
    state['gl_running'] = True   # dash_server.request_scene passa a deixar a troca pro loop (fim do frame)
    if getattr(tuning, 'SCENE', None):   # abre no set ativo (sem transicao)
        state['scene_pending'] = {'name': tuning.SCENE, 'transition': False}

    t0 = time.perf_counter()
    clock = pygame.time.Clock()
    frame_n = 0
    # estado entre throttles pro image_dash_data do OUTPUT (auto-gain/motion separados do
    # Source Image — ver tuning.OUT_ANALYSIS_ENABLED). OUT_ANALYSIS_EVERY_N_FRAMES=6 a 30fps
    # e' ~5Hz: de sobra pros medidores (nao precisam de mais que isso), barato o bastante pra
    # nao derrubar o fps do glReadPixels (ele trava esperando a GPU acabar de desenhar).
    # SAIDA pro dash: a imagem final e' reduzida NA GPU (blit pra um FBO de OUT_PV_W px) e so' essa
    # versao pequena e' lida (glReadPixels trava esperando a GPU — lendo 320 px em vez da janela
    # inteira o custo cai ~20x). Le a OUT_PREVIEW_HZ enquanto alguem pede (/frame?which=out, dash
    # v2) ou com a analise ligada; a analise (medidores do Output Image) roda a OUT_ANALYSIS_HZ
    # em cima da mesma leitura. Tudo por TEMPO (o fps da saida muda ao vivo, tuning.OUTPUT_FPS).
    CV_PV_MAX = 480       # previa do canvas: o lado maior (canvas do palco costuma ser bem largo)
    OUT_ANALYSIS_HZ = 10
    OUT_PREVIEW_HZ = 15
    OUT_PV_W = 320
    out_an_t = [0.0]
    out_pv_t = [0.0]
    out_pv = {'fbo': None, 'tex': None, 'wh': None}
    cv_pv = {'fbo': None, 'tex': None, 'wh': None, 't': 0.0}   # previa do CANVAS do palco (/frame?which=cv)
    LIGHT_PV_W = 64   # LUZES: o canvas pronto lido nesse tamanho (a cor de uma zona nao precisa de mais)
    lt_pv = {'fbo': None, 'tex': None, 'wh': None, 't': 0.0, 'prev': {}, 'tx': None}
    lim_pv = {'fbo': None, 'tex': None, 'wh': None}   # PROTECAO: leitura minuscula da saida (Limiter)
    cue_pv = {'fbo': None, 'tex': None, 'wh': None}   # PREVIEW da proxima cena (/frame?which=cue)
    step_pv = {'fbo': None, 'tex': None, 'wh': None, 't': 0.0}   # dash v4: miniatura de cada modulo do canal pedido
    try_pv = {'fbo': None, 'tex': None, 'wh': None, 'i': 0}      # dash v4: previa FORA DO AR (versoes de um canal)
    STEP_PV_HZ, STEP_PV_W = 8, 160
    limiter, lim_g = Limiter(), [1.0]
    # previa de cada FONTE JA COM OS EFEITOS (canvas do Palco v2: GET /frame?which=fx): a textura
    # da fonte depois da pilha (lt['src']) reduzida por blit, so' das pedidas (state['fx_want'])
    FX_PV_HZ, FX_PV_W = 10, 240
    fx_pv = {'fbo': None, 'tex': None, 'wh': None, 't': {}}
    # leitura ASSINCRONA das previas: glReadPixels pra um PBO (volta na hora, a copia corre na GPU) e
    # o resultado e' pego na PROXIMA leitura do mesmo key (~1/HZ depois, ja pronto). O glReadPixels
    # direto parava a CPU ate a GPU acabar o frame inteiro, a cada previa (CPU e GPU em fila, nao juntas).
    pbos = {}   # key -> [2 PBOs, qual recebe agora, [(w, h) que cada um tem]]

    def read_async(key, pw, ph):
        """READ framebuffer ligado (pw x ph) -> PBO; devolve a leitura ANTERIOR desse key como
        np.uint8 (h, w, 3) topo->baixo, ou None na 1a."""
        e = pbos.get(key)
        if e is None:
            e = pbos[key] = [glGenBuffers(2), 0, [None, None]]
        b, i, wh = e
        out = None
        try:
            glBindBuffer(GL_PIXEL_PACK_BUFFER, int(b[i]))
            if wh[i] != (pw, ph):
                glBufferData(GL_PIXEL_PACK_BUFFER, pw * ph * 3, None, GL_STREAM_READ)
            glPixelStorei(GL_PACK_ALIGNMENT, 1)
            glReadPixels(0, 0, pw, ph, GL_RGB, GL_UNSIGNED_BYTE, ctypes.c_void_p(0))
            wh[i] = (pw, ph)
            if wh[1 - i]:
                w2, h2 = wh[1 - i]
                glBindBuffer(GL_PIXEL_PACK_BUFFER, int(b[1 - i]))
                p = glMapBuffer(GL_PIXEL_PACK_BUFFER, GL_READ_ONLY)
                if p:
                    out = np.frombuffer(ctypes.string_at(p, w2 * h2 * 3), np.uint8).reshape(h2, w2, 3)[::-1]
                glUnmapBuffer(GL_PIXEL_PACK_BUFFER)
            e[1] = 1 - i
        finally:
            glBindBuffer(GL_PIXEL_PACK_BUFFER, 0)   # senao um glReadPixels comum depois escreve no PBO
        return out

    def pv_grab(pv, key, sr, pw, ph):
        """Previa pequena pro dash: blit da regiao sr (x0, y0, x1, y1) do READ framebuffer JA ligado ->
        FBO pw x ph da previa `pv` (reduz na GPU) -> read_async(key)."""
        if pv['wh'] != (pw, ph):
            if pv['fbo'] is None:
                pv['fbo'], pv['tex'] = glGenFramebuffers(1), glGenTextures(1)
            glBindTexture(GL_TEXTURE_2D, pv['tex'])
            glTexImage2D(GL_TEXTURE_2D, 0, GL_RGB, pw, ph, 0, GL_RGB, GL_UNSIGNED_BYTE, None)
            glBindFramebuffer(GL_DRAW_FRAMEBUFFER, pv['fbo'])   # DRAW: nao solta o READ que o chamador ligou
            glFramebufferTexture2D(GL_DRAW_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, pv['tex'], 0)
            pv['wh'] = (pw, ph)
        glBindFramebuffer(GL_DRAW_FRAMEBUFFER, pv['fbo'])
        glBlitFramebuffer(*sr, 0, 0, pw, ph, GL_COLOR_BUFFER_BIT, GL_LINEAR)
        glBindFramebuffer(GL_READ_FRAMEBUFFER, pv['fbo'])
        return read_async(key, pw, ph)
    # textura POR FONTE: so' sobe (glTexSubImage2D) quando o frame da fonte e' OUTRO objeto —
    # camera/video chegam a ~30 fps, a saida roda a 60: sem isso metade dos uploads e' repetida.
    # Guarda o proprio frame (nao id()) pra o endereco nao ser reusado por outro array.
    src_tex = {}          # chave do canal -> [textura, frame subido]
    subj_tex = {}         # fonte base -> [textura, mascara subida] (subject_thread)
    comp_last = [None, None]   # [assinatura das fontes da mistura na CPU, frame_in]
    out_img = {'peaks': {'edge': 1e-6, 'motion': 1e-6, 'sharpness': 1e-6, 'colorfulness': 1e-6},
               'prev_val': [None], 'prev_mean': [None]}
    esc_t = []   # instantes dos ultimos Esc: 3 em ESC_QUIT_S fecha o app (no dash: POST /quit)
    ESC_QUIT_S = 1.2
    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN and event.key in (pygame.K_ESCAPE, pygame.K_F11):
                # Esc SAI da tela cheia (1 Esc so nao fecha: era o gesto natural e derrubava o
                # show); 3x Esc seguidos fecha o app. F11 alterna. Mesmo caminho do dash (output_req)
                if event.key == pygame.K_ESCAPE:
                    now = time.monotonic()
                    esc_t = [t for t in esc_t if now - t < ESC_QUIT_S] + [now]
                    if len(esc_t) >= 3:
                        running = False
                        break
                if event.key == pygame.K_F11 or out_cfg.get('fullscreen'):
                    fs = not out_cfg.get('fullscreen')
                    set_output({**out_cfg, 'fullscreen': fs, **({} if fs else {'w': 0, 'h': 0})})   # janela = tamanho padrao
            elif event.type == pygame.KEYDOWN:
                # atalho de SET (campo 'key' de tuning.SCENES): pede a troca; ela e' aplicada
                # no fim deste frame (bloco "scene_pending" antes do flip), com transicao
                kname = pygame.key.name(event.key)
                hit = next((sc['name'] for sc in getattr(tuning, 'SCENES', None) or []
                            if sc.get('key') and sc.get('key') == kname), None)
                if hit:
                    state['scene_pending'] = {'name': hit, 'transition': True}
                    print(f'tecla {kname!r} -> set {hit}')

        # troca de saida pedida pelo dash (monitor/tela cheia/dimensao, barra "saida" no topo)
        # — reabre a janela e regera vbo/tex/program (contexto GL pode ter sumido -> prog_cache
        # todo invalido, limpa)
        if state['output_req'] != out_cfg:
            out_cfg = dict(state['output_req'])
            (WIN_W, WIN_H, out_pos, out_mode, vbo, tex, tex_prev,
             sim_vel, sim_density, sim_pressure, sim_vort, sim_div, sim_fbo, fumaca_tex) = open_window(out_cfg)
            sim_progs = build_sim_programs()  # contexto GL novo -> os programas velhos tambem ja eram
            p_fumaca, u_fumaca = build_fumaca_program()
            prog_cache.clear()
            trans_cache.clear()          # contexto GL novo -> programas de transicao invalidos
            layer_bad.clear()            # camadas de shader recompilam no proximo frame
            blend_prog, blend_u = build_layer_blend_program()
            map_prog, map_u = build_output_map_program()
            ltargets[0] = None           # FBO/texturas das camadas eram do contexto velho
            poly_tex[:] = [None, None]   # idem a dos poligonos
            src_tex.clear()              # texturas por fonte idem (sem glDelete: o contexto ja foi)
            lane_out.clear()
            tap_tex.clear()
            out_pv.update(fbo=None, tex=None, wh=None)   # FBO da previa da saida idem (nome velho = textura de outro)
            cv_pv.update(fbo=None, tex=None, wh=None)
            fx_pv.update(fbo=None, tex=None, wh=None)
            lt_pv.update(fbo=None, tex=None, wh=None)
            lim_pv.update(fbo=None, tex=None, wh=None)
            cue_pv.update(fbo=None, tex=None, wh=None)
            step_pv.update(fbo=None, tex=None, wh=None)
            try_pv.update(fbo=None, tex=None, wh=None)
            pbos.clear()                 # PBOs das previas idem
            comp_last[0] = None          # forca re-subir a mistura na `tex` nova
            scene_tr = None              # as texturas da transicao eram do contexto velho
            state.pop('scene_from', None)
            state['output'].update(mode=out_mode, window_w=WIN_W, window_h=WIN_H, pos=list(out_pos),
                                    monitor=out_cfg['monitor'], fullscreen=out_cfg['fullscreen'])

        # CANVAS = o palco (telas em metros, com os vaos). Sem telao: encaixado na janela (barras).
        # Com telao (pixel map com blocos): a mistura E' o canvas, no tamanho dele, e o ultimo passe
        # (OUTPUT_MAP_SRC) copia cada tela pro bloco dela no raster = a janela.
        scr_ = getattr(tuning, 'SCREENS', None)
        omap = _out_blocks(scr_, getattr(tuning, 'PIXEL_MAP', None))
        FIT_W, FIT_H, scr_rects = _stage(scr_, WIN_W, WIN_H, MAX_CANVAS_PX if omap else None)   # o 'fit' mira o canvas
        CMP_W, CMP_H = (FIT_W, FIT_H) if omap else (WIN_W, WIN_H)
        state['output']['canvas'] = [FIT_W, FIT_H]
        state['output']['comp'] = [CMP_W, CMP_H]
        state['output']['map'] = [omap[0], omap[1], sum(1 for b in omap[2] if b)] if omap else None   # telao: raster + blocos
        src_frames = _source_frames()             # fontes MARCADAS com frame pronto (a saida)
        # mistura na CPU (so' pra fumaca / analise / cor dominante): refeita so' se alguma fonte
        # trouxe frame novo (ou mudou opacidade/alpha/ordem). Igual = mesma tex/tex_prev de antes,
        # e o "frame anterior" da deteccao de movimento nao anda (senao a 60 fps com fonte a 30
        # o movimento zeraria em frames alternados).
        comp_sig = [(k, a, f, _alpha_now.get(k)) for k, a, f in src_frames]
        prev_sig = comp_last[0]
        comp_changed = prev_sig is None or len(prev_sig) != len(comp_sig) or any(
            x[0] != y[0] or x[1] != y[1] or x[2] is not y[2] or x[3] is not y[3] for x, y in zip(prev_sig, comp_sig))
        if comp_changed:
            frame_in = _composite(src_frames)
            comp_last[0], comp_last[1] = comp_sig, frame_in
        else:
            frame_in = comp_last[1]
        state['frame_comp'] = frame_in
        # SIM DE FLUIDO + FUMACA so' com algum shader no ar que le u_texture_smoke/_fumaca (sim_want,
        # visto no frame anterior): sao ~27 passes + 1 na resolucao do conteudo por frame. Parada, a
        # sim congela onde estava; `tex`/`tex_prev` re-sobem quando ela volta (tex_fresh).
        run_sim, sim_want[0] = sim_want[0], False
        if not run_sim and comp_changed:
            tex_fresh[0] = False
        if run_sim:
            up = comp_changed or not tex_fresh[0]
            tex_fresh[0] = True
            glActiveTexture(GL_TEXTURE0)
            glBindTexture(GL_TEXTURE_2D, tex)
            if up:
                glTexSubImage2D(GL_TEXTURE_2D, 0, 0, 0, WIDTH, HEIGHT, GL_RGB, GL_UNSIGNED_BYTE, frame_in)

            # --- passe da FUMACA (Stable Fluids — ver SIM_*_SRC / Caos.frag EFEITO 6): 7 sub-passes
            # numa grade menor (SIM_W x SIM_H).
            glActiveTexture(GL_TEXTURE2)
            glBindTexture(GL_TEXTURE_2D, tex_prev)
            if up:
                glTexSubImage2D(GL_TEXTURE_2D, 0, 0, 0, WIDTH, HEIGHT, GL_RGB, GL_UNSIGNED_BYTE, prev_frame_buf[0])

            sim_now = time.perf_counter()
            sim_dt = min(0.05, max(0.0, sim_now - sim_last_t[0]))
            sim_last_t[0] = sim_now

            glBindFramebuffer(GL_FRAMEBUFFER, sim_fbo)
            glViewport(0, 0, SIM_W, SIM_H)

            vr, vw = sim_vel[sim_idx], sim_vel[1 - sim_idx]
            dr, dw = sim_density[sim_idx], sim_density[1 - sim_idx]

            # 1) ADVECT_VEL: velocidade se advecta por si mesma + empuxo (dr) + impulso do movimento
            prog, u = sim_progs['adv']
            glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, vw, 0)
            glUseProgram(prog)
            glUniform2f(u['u_res'], SIM_W, SIM_H)
            glUniform1f(u['u_dt'], sim_dt)
            glActiveTexture(GL_TEXTURE0); glBindTexture(GL_TEXTURE_2D, vr)
            glActiveTexture(GL_TEXTURE1); glBindTexture(GL_TEXTURE_2D, dr)
            glActiveTexture(GL_TEXTURE2); glBindTexture(GL_TEXTURE_2D, tex)
            glActiveTexture(GL_TEXTURE3); glBindTexture(GL_TEXTURE_2D, tex_prev)
            glDrawArrays(GL_TRIANGLES, 0, 3)

            # 2) VORTICITY: rotacional de vw
            prog, u = sim_progs['vort']
            glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, sim_vort, 0)
            glUseProgram(prog)
            glUniform2f(u['u_res'], SIM_W, SIM_H)
            glActiveTexture(GL_TEXTURE0); glBindTexture(GL_TEXTURE_2D, vw)
            glDrawArrays(GL_TRIANGLES, 0, 3)

            # 3) CONFINEMENT: soma a forca de confinamento em vw -> escreve no OUTRO slot (vr, ja
            # consumido no passo 1, vira scratch) e troca os apelidos: vw passa a ser o resultado
            prog, u = sim_progs['conf']
            glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, vr, 0)
            glUseProgram(prog)
            glUniform2f(u['u_res'], SIM_W, SIM_H)
            glUniform1f(u['u_dt'], sim_dt)
            glActiveTexture(GL_TEXTURE0); glBindTexture(GL_TEXTURE_2D, vw)
            glActiveTexture(GL_TEXTURE1); glBindTexture(GL_TEXTURE_2D, sim_vort)
            glDrawArrays(GL_TRIANGLES, 0, 3)
            vw, vr = vr, vw

            # 4) DIVERGENCE de vw
            prog, u = sim_progs['div']
            glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, sim_div, 0)
            glUseProgram(prog)
            glUniform2f(u['u_res'], SIM_W, SIM_H)
            glActiveTexture(GL_TEXTURE0); glBindTexture(GL_TEXTURE_2D, vw)
            glDrawArrays(GL_TRIANGLES, 0, 3)

            # 5) PRESSURE: Jacobi, PRESSURE_ITERS vezes, p^(0) = 0 (nao herda do frame anterior —
            # mais previsivel). ping-pong local entre os 2 slots de sim_pressure.
            prog, u = sim_progs['pres']
            pr, pw = sim_pressure[0], sim_pressure[1]
            glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, pr, 0)
            glClear(GL_COLOR_BUFFER_BIT)
            glUseProgram(prog)
            glUniform2f(u['u_res'], SIM_W, SIM_H)
            for _ in range(PRESSURE_ITERS):
                glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, pw, 0)
                glActiveTexture(GL_TEXTURE0); glBindTexture(GL_TEXTURE_2D, pr)
                glActiveTexture(GL_TEXTURE1); glBindTexture(GL_TEXTURE_2D, sim_div)
                glDrawArrays(GL_TRIANGLES, 0, 3)
                pr, pw = pw, pr

            # 6) PROJECT: tira o gradiente de pressao de vw -> campo sem divergencia
            prog, u = sim_progs['proj']
            glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, vr, 0)
            glUseProgram(prog)
            glUniform2f(u['u_res'], SIM_W, SIM_H)
            glActiveTexture(GL_TEXTURE0); glBindTexture(GL_TEXTURE_2D, vw)
            glActiveTexture(GL_TEXTURE1); glBindTexture(GL_TEXTURE_2D, pr)
            glDrawArrays(GL_TRIANGLES, 0, 3)
            vw, vr = vr, vw  # vw = velocidade final (sem divergencia) deste frame

            # 7) ADVECT_DENS: densidade se advecta pelo campo final + injecao de movimento + decaimento
            prog, u = sim_progs['dens']
            glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, dw, 0)
            glUseProgram(prog)
            glUniform2f(u['u_res'], SIM_W, SIM_H)
            glUniform1f(u['u_dt'], sim_dt)
            glActiveTexture(GL_TEXTURE0); glBindTexture(GL_TEXTURE_2D, vw)
            glActiveTexture(GL_TEXTURE1); glBindTexture(GL_TEXTURE_2D, dr)
            glActiveTexture(GL_TEXTURE2); glBindTexture(GL_TEXTURE_2D, tex)
            glActiveTexture(GL_TEXTURE3); glBindTexture(GL_TEXTURE_2D, tex_prev)
            glDrawArrays(GL_TRIANGLES, 0, 3)

            # --- passe da FUMAÇA procedural (ver SMOKE_SRC): 1 passe so', na resolucao do
            # conteudo (nao da grade da sim de fluido acima). Roda no mesmo FBO reaproveitado.
            fr, fw = fumaca_tex[fumaca_idx], fumaca_tex[1 - fumaca_idx]
            glViewport(0, 0, WIDTH, HEIGHT)
            glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, fw, 0)
            glUseProgram(p_fumaca)
            glUniform2f(u_fumaca['u_resolution'], WIDTH, HEIGHT)
            glUniform1f(u_fumaca['u_time'], time.perf_counter() - t0)
            glActiveTexture(GL_TEXTURE0); glBindTexture(GL_TEXTURE_2D, tex)
            glActiveTexture(GL_TEXTURE1); glBindTexture(GL_TEXTURE_2D, tex_prev)
            glActiveTexture(GL_TEXTURE2); glBindTexture(GL_TEXTURE_2D, fr)
            glDrawArrays(GL_TRIANGLES, 0, 3)

            glBindFramebuffer(GL_FRAMEBUFFER, 0)
            sim_idx = 1 - sim_idx      # o resultado (vw/dw, fisicamente no slot 1-sim_idx) vira o "atual"
            fumaca_idx = 1 - fumaca_idx
        glViewport(0, 0, CMP_W, CMP_H)             # a mistura; o que desenha na janela volta pra WIN_W x WIN_H
        glActiveTexture(GL_TEXTURE3)
        glBindTexture(GL_TEXTURE_2D, sim_density[sim_idx])   # silhueta (sim de fluido) deste frame -> u_texture_smoke
        glActiveTexture(GL_TEXTURE4)
        glBindTexture(GL_TEXTURE_2D, fumaca_tex[fumaca_idx])  # fumaca (procedural) deste frame -> u_texture_fumaca
        if comp_changed:
            prev_frame_buf[0] = frame_in.copy()

        now_t = time.perf_counter() - t0
        tp_ = state.get('tempo_obj')            # posicao na batida/compasso NESTE frame (lisa, sem degrau do audio)
        if tp_:
            state['beat'], state['bar'] = tp_.phase(time.monotonic())
        bp_ = tp_.pos(time.monotonic()) if tp_ else None
        state['bpos'] = bp_ if bp_ is not None else now_t * 2.0   # relogio dos LFOs: sem tempo detectado, 120 BPM
        # SUAVIZACAO (tuning.PARAM_SMOOTH_MS, ~80 ms): knobs, opacidades, liga/desliga e intensidade
        # deslizam ate o valor novo em vez de pular. O som (♪/kick) NAO passa por aqui (ja' tem attack/
        # release proprio; suavizar de novo so' atrasaria a reacao). Master/blackout tambem nao (seguranca).
        sm_dt = now_t - sm_last[0]
        sm_last[0] = now_t
        tau = max(0.0, float(getattr(tuning, 'PARAM_SMOOTH_MS', 80) or 0)) / 1000.0
        if scene_tr:   # MORPH: na transicao os parametros da cena nova andam do valor antigo ao novo nela toda
            tau = max(tau, scene_tr['ms'] / 3000.0)    # (~95% do caminho no fim: 3 constantes de tempo)
        k_sm = 1.0 if tau <= 0 else 1.0 - math.exp(-max(0.0, sm_dt) / tau)
        if frame_n % 300 == 0:   # chave que sumiu (efeito tirado, cena trocada) nao fica pra sempre
            for k_ in [k_ for k_, e_ in sm_store.items() if frame_n - e_[1] > 300]:
                del sm_store[k_]
        smv = lambda key, v, start=None: _smooth(sm_store, key, v, k_sm, frame_n, start)
        # INTENSIDADE DOS EFEITOS (fader EFEITOS no topo do dash = OUTPUT_GRADE.fxamt): multiplica a
        # opacidade de TODO efeito da pilha; 0 = so' as fontes cruas (a mistura/telas/calibracao seguem)
        fx_amt = min(1.0, max(0.0, float((getattr(tuning, 'OUTPUT_GRADE', None) or {}).get('fxamt', 1.0))))

        def set_uniforms(fx, mod=None, sk=None):
            glUniform2f(uniforms['res'], CMP_W, CMP_H)
            glUniform1f(uniforms['time'], now_t)
            glUniform1f(uniforms['beats'], state['beats'] % 4096.0)   # float32 do GL: nao deixa crescer sem fim
            glUniform3f(uniforms['dominant'], *state['dominant'])
            for loc, k in uniforms['state']:          # amp/bass/.../kick/build + as 8 faixas (as que o shader le)
                glUniform1f(loc, state[k])
            for loc, k, i in uniforms['chan']:        # u_chan[i] / u_chan_hit[i]
                glUniform1f(loc, state[k][i])
            mod = mod or {}
            for n, loc, d in uniforms['fx']:   # sk = chave da suavizacao (None = valor cru)
                v = fx.get(n, d)
                glUniform1f(loc, _mod_value(smv(sk + (n,), v) if sk else v, mod.get(n), state))

        # --- SAIDA: so' as fontes MARCADAS (src_frames, de baixo pra cima), cada uma pela SUA
        # pilha (state['bindings'][fonte]): a fonte crua -> cada shader marcado desenha com ela de
        # u_texture_0 (forcas u_fx_* daquele par fonte/shader) e mistura por cima (opacidade +
        # modo, LAYER_BLEND_SRC) -> o resultado entra na saida com a opacidade + modo da fonte. Saida
        # comeca preta. No fim: saida -> tela (copia, ou transicao de set misturando com a que sai).
        if scene_tr and time.perf_counter() - scene_tr['t0'] >= scene_tr['ms'] / 1000.0:
            scene_tr = None
            state.pop('scene_from', None)               # fontes so' da cena que saiu podem fechar
        lt = layer_targets()

        def blend_into(dst, base, layer, a, mode, flip=0, mask=0, rect=FULL_UV, clip=FULL_UV, scr=(), mth=(0.0, 1.0), lv=(1.0, 0.0)):
            glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, dst, 0)
            _use_basic(blend_prog)
            glUniform2f(blend_u['u_lv'], *lv)
            glUniform2f(blend_u['u_mth'], *mth)
            glUniform2f(blend_u['u_res'], CMP_W, CMP_H)
            glUniform4f(blend_u['u_rect'], *rect)
            glUniform4f(blend_u['u_clip'], *clip)
            glUniform1i(blend_u['u_nscr'], len(scr))
            if scr:
                glUniform4fv(blend_u['u_sa'], len(scr), np.array([q[0] for q in scr], np.float32).ravel())
                glUniform4fv(blend_u['u_sb'], len(scr), np.array([q[1] for q in scr], np.float32).ravel())
            glUniform1f(blend_u['u_a'], a)
            glUniform1i(blend_u['u_mode'], mode)
            glUniform1i(blend_u['u_flip'], flip)
            glUniform1i(blend_u['u_use_mask'], mask)
            glActiveTexture(GL_TEXTURE0 + LAYER_BLEND_UNIT_BASE)
            glBindTexture(GL_TEXTURE_2D, base)
            glActiveTexture(GL_TEXTURE0 + LAYER_BLEND_UNIT_LAYER)
            glBindTexture(GL_TEXTURE_2D, layer)
            glDrawArrays(GL_TRIANGLES, 0, 3)

        cbox = FULL_UV if omap else _canvas_box(WIN_W, WIN_H, FIT_W, FIT_H)   # canvas encaixado na janela (barras fora; telao: a mistura e' o canvas)
        scr_uv = _blend_scr(scr_rects)                  # telas (forma livre): fora delas fica preto
        poly_sig = [sh[4] for sh in scr_rects]          # poligonos -> u_poly (so' re-sobe se mudou)
        if poly_tex[0] is None or poly_tex[1] != poly_sig:
            if poly_tex[0] is None:
                poly_tex[0] = glGenTextures(1)
            glActiveTexture(GL_TEXTURE0 + POLY_UNIT)
            glBindTexture(GL_TEXTURE_2D, poly_tex[0])
            for pn, pv in ((GL_TEXTURE_MIN_FILTER, GL_NEAREST), (GL_TEXTURE_MAG_FILTER, GL_NEAREST),
                           (GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE), (GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE)):
                glTexParameteri(GL_TEXTURE_2D, pn, pv)
            glPixelStorei(GL_UNPACK_ALIGNMENT, 1)
            glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, POLY_TEX_W, MAX_SCREENS, 0, GL_RGBA, GL_UNSIGNED_BYTE, _poly_tex(scr_rects))
            poly_tex[1] = poly_sig
        glActiveTexture(GL_TEXTURE0 + POLY_UNIT)
        glBindTexture(GL_TEXTURE_2D, poly_tex[0])
        # TRANSICAO VIVA: a cena que SAI (scene_tr['old'] = overlays/bindings/pool/grade dela) continua
        # sendo desenhada, com as fontes dela ainda abertas (state['scene_from'] -> _sync_overlays) —
        # a transicao mistura DUAS imagens em movimento, nao uma foto congelada.
        old = scene_tr.get('old') if scene_tr else None
        old_alpha = {}
        old_frames = _source_frames(old, old_alpha) if old else []
        # PREVIEW da PROXIMA cena (state['scene_cue_sc']): so' enquanto o dash pede (/frame?which=cue), a cada
        # 3 frames (~20 Hz basta pra uma previa) — custa uma mistura extra so' nesses frames
        cue = state.get('scene_cue_sc') if time.time() - state.get('cue_want', 0) < 1.5 and frame_n % 3 == 0 else None
        cue_alpha = {}
        cue_frames = _source_frames(cue, cue_alpha) if cue else []
        keep = {x[0] for x in src_frames} | {x[0] for x in old_frames} | {x[0] for x in cue_frames}
        for k in [k for k in src_tex if k not in keep]:
            glDeleteTextures([src_tex.pop(k)[0]])       # canal saiu da saida: libera a textura
            e = pbos.pop('fx:' + k, None)                # e os PBOs da previa com efeitos dele
            if e:
                glDeleteBuffers(2, e[0])
        for k in [k for k in lane_out if k not in keep]:
            glDeleteTextures([lane_out.pop(k)])

        def src_texture(key, frame):
            """textura da fonte crua do canal (1 por chave; so' re-sobe se o frame e' OUTRO objeto)."""
            glActiveTexture(GL_TEXTURE0)                 # a fonte crua -> u_texture_0 dos shaders
            st_ = src_tex.get(key)
            if st_ is None:
                st_ = src_tex[key] = [glGenTextures(1), None]
                glBindTexture(GL_TEXTURE_2D, st_[0])
                for pn, pv in ((GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE), (GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE),
                               (GL_TEXTURE_MIN_FILTER, GL_LINEAR), (GL_TEXTURE_MAG_FILTER, GL_LINEAR)):
                    glTexParameteri(GL_TEXTURE_2D, pn, pv)
                glTexImage2D(GL_TEXTURE_2D, 0, GL_RGB, WIDTH, HEIGHT, 0, GL_RGB, GL_UNSIGNED_BYTE, frame)
                st_[1] = frame
            else:
                glBindTexture(GL_TEXTURE_2D, st_[0])
                if st_[1] is not frame:
                    glTexSubImage2D(GL_TEXTURE_2D, 0, 0, 0, WIDTH, HEIGHT, GL_RGB, GL_UNSIGNED_BYTE, frame)
                    st_[1] = frame
            return st_[0]

        def copy_flip(store, k, tex):
            """saida (orientacao GL) -> store[k], virada topo->baixo como a fonte crua (quem le e' um shader)."""
            if k not in store:
                store[k] = t = glGenTextures(1)
                glBindTexture(GL_TEXTURE_2D, t)
                for pn, pv in ((GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE), (GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE),
                               (GL_TEXTURE_MIN_FILTER, GL_LINEAR), (GL_TEXTURE_MAG_FILTER, GL_LINEAR)):
                    glTexParameteri(GL_TEXTURE_2D, pn, pv)
                glTexImage2D(GL_TEXTURE_2D, 0, GL_RGB, CMP_W, CMP_H, 0, GL_RGB, GL_UNSIGNED_BYTE, None)
            blend_into(store[k], tex, tex, 1.0, 0, flip=1)

        def render_mix(pair, sc, frames, alpha, live):
            """MISTURA de uma cena -> uma das texturas de `pair` (ping-pong), que e' devolvida: cada fonte
            pela pilha dela, a imagem da cena e a calibracao por tela. sc = {overlays, bindings, pool,
            grade}. live=False = a cena que SAI numa transicao: valores crus (sem suavizacao), sem previas."""
            sv = smv if live else (lambda key, v, start=None: v)
            glBindFramebuffer(GL_FRAMEBUFFER, lt['fbo'])
            glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, pair[0], 0)
            glClear(GL_COLOR_BUFFER_BIT)
            oi = 0
            bindings = sc.get('bindings') or {}
            sh_avail = (sc.get('pool') or {}).get('shaders')   # disponiveis no set (None = todos)
            src_blend = {_chkey(o): o.get('blend') for o in sc.get('overlays') or []}
            src_rect = {_chkey(o): o.get('rect') for o in sc.get('overlays') or []}
            src_auto = {_chkey(o) for o in sc.get('overlays') or [] if o.get('auto')}
            # raias que algum modulo le (ins): a saida delas fica guardada (lane_out); modulos que alguem le (ramo
            # '@id', ins '@id'): a saida deles fica em tap_tex. Lida mais acima na mesa / 'fb' (a propria) = a do
            # frame anterior — o atraso de 1 frame do feedback (LocalIn/LocalOut)
            lane_want, tap_want, _ = _graph_wants(bindings, sc.get('overlays')) if live else (set(), set(), set())
            if live:
                live_taps[0] = tap_want
            sw = state.get('steps_want')            # dash v4: miniatura de cada modulo desse canal (so' enquanto pedida)
            step_key = sw[0] if live and sw and time.time() - sw[1] < 1.5 and \
                time.perf_counter() - step_pv['t'] >= 1.0 / STEP_PV_HZ else None

            def after_module(key, oj, o, tex):
                """depois de cada modulo (rodou ou nao): guarda o tap (ramo) e a miniatura do passo (dash v4)."""
                if live and o.get('id') in tap_want:
                    copy_flip(tap_tex, o['id'], tex)
                if key == step_key:
                    pw = min(STEP_PV_W, CMP_W)
                    glBindFramebuffer(GL_READ_FRAMEBUFFER, lt['fbo'])
                    glFramebufferTexture2D(GL_READ_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, tex, 0)
                    a_ = pv_grab(step_pv, f'st:{oj}', (0, 0, CMP_W, CMP_H), pw, max(2, int(round(pw * CMP_H / max(1, CMP_W)))))
                    if a_ is not None:
                        steps_img[oj] = (a_.tobytes(), a_.shape[1], a_.shape[0])
                    glBindFramebuffer(GL_FRAMEBUFFER, lt['fbo'])

            for key, src_a, frame in frames:
                if frame is None:                       # RAMO (fileira '@id'): a fonte e' a saida do modulo id
                    ftex = tap_tex.get(re.sub(r'#\d+$', '', key)[1:])
                    if not ftex:                        # o modulo ainda nao rodou (ou sumiu): fica de fora
                        continue
                else:
                    ftex = src_texture(key, frame)
                si = 0
                lv = (1.0, 0.0)
                steps_img = dict((state.get('steps_small') or {}).get('img') or {}) \
                    if key == step_key and (state.get('steps_small') or {}).get('key') == key else {}
                if key in src_auto and frame is not None:   # AUTO-NIVEL: recalcula so' com frame NOVO (~30 Hz), ~1.5 s de suavizacao
                    e = auto_lv.get(key)
                    if e is None or e[1] is not frame:
                        auto_lv[key] = e = [_auto_levels(frame, WIDTH, HEIGHT, e[0] if e else None, 0.03), frame]
                    lv = e[0]
                blend_into(lt['src'][0], ftex, ftex, 1.0, 0, flip=1, lv=lv)
                b = bindings.get(key) or {}
                # ASSUNTO: pilha com region (ou previa da mascara aberta) -> pede a mascara dessa fonte
                bk = re.sub(r'#\d+$', '', key)
                if frame is not None and (any(o.get('region') for o in b.get('shaders') or []) or
                                          time.time() - (state.get('mask_want') or {}).get(key, 0) < 1.5):
                    subject_want[bk] = (time.time(), frame)
                sjm, sjt = subject_mask.get(bk), subj_tex.get(bk)
                if sjm is not None and (sjt is None or sjt[1] is not sjm):
                    if sjt is None:
                        sjt = subj_tex[bk] = [glGenTextures(1), None]
                    glActiveTexture(GL_TEXTURE0 + LAYER_BLEND_UNIT_MASK)
                    glBindTexture(GL_TEXTURE_2D, sjt[0])
                    for pn, pv in ((GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE), (GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE),
                                   (GL_TEXTURE_MIN_FILTER, GL_LINEAR), (GL_TEXTURE_MAG_FILTER, GL_LINEAR)):
                        glTexParameteri(GL_TEXTURE_2D, pn, pv)
                    glPixelStorei(GL_UNPACK_ALIGNMENT, 1)
                    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGB, SUBJECT_DET, SUBJECT_DET, 0, GL_RGB, GL_UNSIGNED_BYTE,
                                 np.repeat(sjm[..., None], 3, axis=2))
                    sjt[1] = sjm
                elif sjm is None:
                    sjt = None
                for oj, o in enumerate(b.get('shaders') or []):
                    a = min(1.0, float(o.get('opacity', 0)))
                    if o.get('off') or (sh_avail is not None and o['file'] not in sh_avail):
                        a = 0
                    rg = o.get('region')
                    if rg == 'subject' and sjt is None:     # sem mascara (ainda): assunto vazio
                        a = 0
                    sk = ('fx', key, oj, o['file']) if live else None   # suavizacao: liga/desliga/opacidade viram fade
                    a = sv(sk, a * fx_amt, 0.0)
                    if o.get('kick'):                       # kick no efeito: opacidade x kick (batida = 1, decai ate 0)
                        a *= state['kick']
                    h = layer_program(o['file']) if a > 0.002 else None
                    if not h:                               # nao desenha: a corrente passa direto (o tap tambem)
                        after_module(key, oj, o, lt['src'][si])
                        continue
                    chain = o.get('in') != 'src'           # le o resultado dos de antes; so' 'src' le a fonte crua (antes: sem 'in' = crua,
                                                            # e a ultima peca cobria todas)
                    if chain:                               # (sem 'in' = pilha antiga: le a fonte crua)
                        blend_into(lt['chain'], lt['src'][si], lt['src'][si], 1.0, 0, flip=1)
                    glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, lt['layer'], 0)
                    use_program(h)
                    set_uniforms(o['fx'] if isinstance(o.get('fx'), dict)   # forcas da ENTRADA (mesmo .frag pode vir 2x)
                                 else (b.get('fx') or {}).get(o['file']) or {}, o.get('mod'), sk)
                    if uniforms['eyes'] >= 0:                   # shader usa olhos -> pede deteccao dessa fonte
                        if frame is not None:
                            eyes_want[key] = (time.time(), frame)
                        ey = (state.get('eyes') or {}).get(key) or (0.0, 0.0, 0.0, 0.0, 0.0)
                        glUniform4f(uniforms['eyes'], *ey[:4])
                        glUniform1f(uniforms['eyes_on'], ey[4])
                    ins = o.get('ins') or ()
                    for i, (unit, loc) in enumerate(zip(INS_UNITS, uniforms['ins'])):
                        if loc >= 0:                        # sem ligacao / raia sem saida guardada ainda = a fonte
                            r = ins[i] if i < len(ins) else None
                            glActiveTexture(GL_TEXTURE0 + unit)
                            glBindTexture(GL_TEXTURE_2D, _ins_tex(r, key, lane_out, tap_tex, ftex))
                    if uniforms['src'] >= 0:
                        glActiveTexture(GL_TEXTURE0 + SRC_UNIT)
                        glBindTexture(GL_TEXTURE_2D, ftex)
                    glActiveTexture(GL_TEXTURE0)
                    glBindTexture(GL_TEXTURE_2D, lt['chain'] if chain else ftex)
                    glClear(GL_COLOR_BUFFER_BIT)
                    glDrawArrays(GL_TRIANGLES, 0, 3)
                    cur_l = lt['layer']
                    for pm in _post_items(o, bindings):   # MODIFICADOR PARALELO: age so' na saida DESTA peca
                        ph = layer_program(pm['file'])
                        if not ph:
                            continue
                        alt = lt['layer2'] if cur_l == lt['layer'] else lt['layer']
                        lw_, lh_ = lt['size']
                        glBindFramebuffer(GL_FRAMEBUFFER, lt['fbo'])   # 1) camada (com o ALFA do efeito) -> alt
                        glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, cur_l, 0)
                        glBindTexture(GL_TEXTURE_2D, alt)
                        glCopyTexSubImage2D(GL_TEXTURE_2D, 0, 0, 0, 0, 0, lw_, lh_)
                        blend_into(lt['chain'], cur_l, cur_l, 1.0, 0, flip=1)   # 2) a cor dela topo->baixo (como o atomo le)
                        glBindFramebuffer(GL_FRAMEBUFFER, lt['fbo'])   # 3) o modificador pinta SO' a cor; o alfa fica o do efeito
                        glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, alt, 0)
                        use_program(ph)
                        set_uniforms(pm.get('fx') or {}, pm.get('mod'), ('post', key, oj, pm.get('id')) if live else None)
                        glActiveTexture(GL_TEXTURE0)
                        glBindTexture(GL_TEXTURE_2D, lt['chain'])
                        glColorMask(GL_TRUE, GL_TRUE, GL_TRUE, GL_FALSE)
                        glDrawArrays(GL_TRIANGLES, 0, 3)
                        glColorMask(GL_TRUE, GL_TRUE, GL_TRUE, GL_TRUE)
                        cur_l = alt
                    mode = dash_server.LAYER_BLENDS.index(o['blend']) if o.get('blend') in dash_server.LAYER_BLENDS else 0
                    um = 0
                    if rg and sjt is not None:              # so' dentro (2) / fora (3) do assunto
                        glActiveTexture(GL_TEXTURE0 + LAYER_BLEND_UNIT_MASK)
                        glBindTexture(GL_TEXTURE_2D, sjt[0])
                        um = 2 if rg == 'subject' else 3
                    blend_into(lt['src'][1 - si], lt['src'][si], cur_l, a, mode, mask=um, mth=_subject_params(b))
                    si = 1 - si
                    after_module(key, oj, o, lt['src'][si])
                if key == step_key:
                    state['steps_small'] = {'key': key, 'n': len(b.get('shaders') or []), 'img': steps_img}
                    step_pv['t'] = time.perf_counter()
                if key in lane_want:                        # saida da raia, virada topo->baixo, pra quem le (ins)
                    copy_flip(lane_out, key, lt['src'][si])
                fx_want = state.get('fx_want') or {}
                if live and time.time() - fx_want.get(key, 0) < 1.5 and time.perf_counter() - fx_pv['t'].get(key, 0) >= 1.0 / FX_PV_HZ:
                    fx_pv['t'][key] = time.perf_counter()
                    try:
                        pw = min(FX_PV_W, CMP_W)
                        ph = max(2, int(round(pw * CMP_H / max(1, CMP_W))))
                        glBindFramebuffer(GL_READ_FRAMEBUFFER, lt['fbo'])
                        glFramebufferTexture2D(GL_READ_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, lt['src'][si], 0)
                        a = pv_grab(fx_pv, 'fx:' + key, (0, 0, CMP_W, CMP_H), pw, ph)
                        if a is not None:
                            state.setdefault('fx_small', {})[key] = (a.tobytes(), a.shape[1], a.shape[0])
                    except Exception as e:                  # sem blit: fica sem previa com efeito (o dash cai na crua)
                        if not fx_pv.get('warned'):
                            print('previa com efeitos indisponivel ->', e)
                            fx_pv['warned'] = True
                    glBindFramebuffer(GL_FRAMEBUFFER, lt['fbo'])
                sm = src_blend.get(key)                     # modo da FONTE sobre as de baixo (normal = cobre)
                sm = dash_server.LAYER_BLENDS.index(sm) if sm in dash_server.LAYER_BLENDS else 0
                al = alpha.get(key)                         # imagem com transparencia: so' onde e' opaca
                if al is not None:
                    glActiveTexture(GL_TEXTURE0 + LAYER_BLEND_UNIT_MASK)
                    glBindTexture(GL_TEXTURE_2D, lt['mask'])
                    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR)
                    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
                    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGB, WIDTH, HEIGHT, 0, GL_RGB, GL_UNSIGNED_BYTE, al)
                a_out = sv(('src', key) if live else None, min(1.0, src_a), 0.0)
                if a_out > 0.002:                           # a 0% (so' lida por outra fileira) nao entra na saida
                    blend_into(pair[1 - oi], pair[oi], lt['src'][si], a_out, sm,
                               mask=int(al is not None), rect=_rect_uv(src_rect.get(key), cbox), clip=cbox, scr=scr_uv)
                    oi = 1 - oi
            # IMAGEM DA CENA (campo 'grade' do set; knobs no Palco do v2): o mesmo calibrar.frag na MISTURA
            # da cena -> antes da transicao (cada cena cruza com a sua) e da calibracao do telao. Neutro = sem passe.
            sg = sc.get('grade') or {}
            sfx = (sg.get('fx') or {}) if sg.get('on', 1) else {}
            sgh = layer_program(dash_server.GRADE_FRAG) if sfx else None
            if sgh and any(abs(float(sfx.get(n, d)) - d) > 1e-4 for n, d in sgh[3].items()):
                glBindFramebuffer(GL_FRAMEBUFFER, lt['fbo'])
                glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, pair[1 - oi], 0)
                use_program(sgh)
                set_uniforms(sfx, sk=('sg',) if live else None)
                glUniform1i(uniforms['test'], 0)
                glUniform1f(uniforms['dim'], 0.0)
                glActiveTexture(GL_TEXTURE0)
                glBindTexture(GL_TEXTURE_2D, pair[oi])
                glClear(GL_COLOR_BUFFER_BIT)
                glDrawArrays(GL_TRIANGLES, 0, 3)
                oi = 1 - oi
            # CALIBRACAO POR TELA (SCREENS[i]['grade'], dash v2 > Saida): igualar paineis diferentes.
            # calibrar.frag na mistura inteira -> 'layer', e o blend so' deixa passar DENTRO da tela i
            # (forma livre). As telas antes dela vao pra longe (sa.xy = 1e6) so' pra manter o indice i =
            # a linha dela no u_poly. Antes da transicao (fixa por tela, os 2 lados ja' saem calibrados).
            if scr_rects:
                for i, t in enumerate(_valid_screens(scr_)):
                    tfx = t[0].get('grade') or {}
                    th = layer_program(dash_server.GRADE_FRAG) if tfx else None
                    if not th or i >= len(scr_uv):
                        continue
                    glBindFramebuffer(GL_FRAMEBUFFER, lt['fbo'])
                    glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, lt['layer'], 0)
                    use_program(th)
                    set_uniforms(tfx, sk=('scr', i) if live else None)
                    glUniform1i(uniforms['test'], 0)
                    glUniform1f(uniforms['dim'], 0.0)
                    glActiveTexture(GL_TEXTURE0)
                    glBindTexture(GL_TEXTURE_2D, pair[oi])
                    glClear(GL_COLOR_BUFFER_BIT)
                    glDrawArrays(GL_TRIANGLES, 0, 3)
                    far = ((1e6, 1e6, 1.0, 0.0), (0.0, 1.0, 0.0, 0.0))
                    blend_into(pair[1 - oi], pair[oi], lt['layer'], 1.0, 0, clip=cbox, scr=[far] * i + [scr_uv[i]])
                    oi = 1 - oi
            return pair[oi]

        mixed = render_mix(lt['out'], {'overlays': state.get('overlays'), 'bindings': state.get('bindings'),
                                       'pool': state.get('pool'), 'grade': getattr(tuning, 'SCENE_GRADE', None)},
                           src_frames, _alpha_now, True)
        for t_ in [t_ for t_ in tap_tex if t_ not in live_taps[0]]:   # modulo que ninguem mais le: solta o tap
            glDeleteTextures([tap_tex.pop(t_)])
        mixed_from = render_mix(lt['old'], old, old_frames, old_alpha, False) if old else None
        if cue:
            try:
                ctex = render_mix(lt['cue'], cue, cue_frames, cue_alpha, False)
                glBindFramebuffer(GL_READ_FRAMEBUFFER, lt['fbo'])
                glFramebufferTexture2D(GL_READ_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, ctex, 0)
                pw = min(FX_PV_W, CMP_W)
                a = pv_grab(cue_pv, 'cue', (0, 0, CMP_W, CMP_H), pw, max(2, int(round(pw * CMP_H / max(1, CMP_W)))))
                if a is not None:
                    state['cue_small'] = (a.tobytes(), a.shape[1], a.shape[0])
            except Exception as e:
                if cue_pv.get('err') != str(e):
                    print('previa da proxima cena ->', e)
                    cue_pv['err'] = str(e)
            glBindFramebuffer(GL_FRAMEBUFFER, lt['fbo'])
        # PREVIA FORA DO AR (dash v4, POST /try): versoes da pilha de UM canal, uma por frame (rodizio), no par
        # lt['cue'] (fora dos frames da previa da proxima cena); a saida nao muda. So' enquanto alguem le.
        tr = state.get('try')
        if tr and tr.get('v') and time.time() - tr.get('t', 0) < 1.5:
            if not cue:
                try:
                    i = try_pv['i'] = (try_pv['i'] + 1) % len(tr['v'])
                    row = next((o for o in state.get('overlays') or [] if _chkey(o) == tr['key']), None)
                    if row:
                        tsc = {'overlays': [dict({k: v for k, v in row.items() if k not in ('rect', 'blend', 'off')}, opacity=1.0)],
                               'bindings': dict(state.get('bindings') or {}, **{tr['key']: tr['v'][i]}), 'pool': None, 'grade': None}
                        t_alpha = {}
                        ttex = render_mix(lt['cue'], tsc, _source_frames(tsc, t_alpha), t_alpha, False)
                        glBindFramebuffer(GL_READ_FRAMEBUFFER, lt['fbo'])
                        glFramebufferTexture2D(GL_READ_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, ttex, 0)
                        pw = min(FX_PV_W, CMP_W)
                        a = pv_grab(try_pv, f'try:{i}', (0, 0, CMP_W, CMP_H), pw, max(2, int(round(pw * CMP_H / max(1, CMP_W)))))
                        if a is not None:
                            state.setdefault('try_small', {})[i] = (a.tobytes(), a.shape[1], a.shape[0])
                except Exception as e:
                    if try_pv.get('err') != str(e):
                        print('previa fora do ar ->', e)
                        try_pv['err'] = str(e)
                glBindFramebuffer(GL_FRAMEBUFFER, lt['fbo'])
        elif state.get('try_small'):
            state.pop('try_small', None)
        # CALIBRACAO DA SAIDA (tuning.OUTPUT_GRADE, shaders/calibrar.frag): ligada e fora do
        # neutro (ou no padrao de teste) -> a imagem final (copia ou transicao) vai pra textura
        # `final` e o calibrar.frag a desenha na tela. Neutro = caminho de sempre, sem passe extra.
        # MASTER (dash v2, grade['master'] < 1) forca o passe mesmo com a calibracao desligada
        # (ai com os knobs no neutro); vira u_dim = 1 - master no calibrar.frag.
        grade = getattr(tuning, 'OUTPUT_GRADE', None) or {}
        g_on = bool(grade.get('on', 1))
        g_dim = 1.0 - min(1.0, max(0.0, float(grade.get('master', 1.0)))) * lim_g[0]   # x protecao (Limiter)
        if (state.get('light_scan') or {}).get('run'):   # mapeando as luzes: telao preto (a camera so' ve o rig)
            g_dim = 1.0
        g_test = g_on and bool(grade.get('test'))
        gh = layer_program(dash_server.GRADE_FRAG) if (g_on or g_dim > 1e-4) else None
        gfx = (grade.get('fx') or {}) if g_on else {}
        if gh and not (g_test or g_dim > 1e-4 or any(abs(float(gfx.get(n, d)) - d) > 1e-4
                                                     for n, d in gh[3].items())):
            gh = None
        # calibrada: a transicao fica em textura e a calibracao desenha na tela. `final` = a imagem
        # ANTES da calibracao.
        # com telao, "a tela" desses passes e' a textura `canvas` (o palco pronto) e o OUTPUT_MAP a
        # desenha no raster no fim
        def to_screen():
            if omap:
                glBindFramebuffer(GL_FRAMEBUFFER, lt['fbo'])
                glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, lt['canvas'], 0)
            else:
                glBindFramebuffer(GL_FRAMEBUFFER, 0)

        final = mixed
        if scene_tr and gh:
            glBindFramebuffer(GL_FRAMEBUFFER, lt['fbo'])
            glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, lt['layer'], 0)
            final = lt['layer']
        else:
            to_screen()
        if scene_tr:                                    # transicao de set: a cena que sai (VIVA) -> a nova
            use_trans_program(scene_tr['prog'])
            glUniform2f(tuni['res'], CMP_W, CMP_H)
            glUniform1f(tuni['progress'], min(1.0, (time.perf_counter() - scene_tr['t0'])
                                              / max(0.001, scene_tr['ms'] / 1000.0)))
            glUniform1i(tuni['from'], LAYER_BLEND_UNIT_BASE)
            glUniform1i(tuni['to'], LAYER_BLEND_UNIT_LAYER)
            glActiveTexture(GL_TEXTURE0 + LAYER_BLEND_UNIT_BASE)
            glBindTexture(GL_TEXTURE_2D, mixed_from if mixed_from is not None else mixed)
            glActiveTexture(GL_TEXTURE0 + LAYER_BLEND_UNIT_LAYER)
            glBindTexture(GL_TEXTURE_2D, mixed)
            glClear(GL_COLOR_BUFFER_BIT)
            glDrawArrays(GL_TRIANGLES, 0, 3)
        elif not gh:                                    # copia (modo 0, a=1) a saida pra tela
            glClear(GL_COLOR_BUFFER_BIT)
            _use_basic(blend_prog)
            glUniform2f(blend_u['u_res'], CMP_W, CMP_H)
            glUniform1f(blend_u['u_a'], 1.0)
            glUniform1i(blend_u['u_mode'], 0)
            glUniform1i(blend_u['u_flip'], 0)
            glUniform1i(blend_u['u_use_mask'], 0)
            glUniform4f(blend_u['u_rect'], *FULL_UV)
            glUniform4f(blend_u['u_clip'], *FULL_UV)
            glUniform1i(blend_u['u_nscr'], 0)
            glActiveTexture(GL_TEXTURE0 + LAYER_BLEND_UNIT_BASE)
            glBindTexture(GL_TEXTURE_2D, mixed)
            glActiveTexture(GL_TEXTURE0 + LAYER_BLEND_UNIT_LAYER)
            glBindTexture(GL_TEXTURE_2D, mixed)
            glDrawArrays(GL_TRIANGLES, 0, 3)
        if gh:                                          # final -> calibrar.frag -> tela
            to_screen()
            use_program(gh)
            set_uniforms(gfx, sk=('og',))
            glUniform1i(uniforms['test'], int(g_test))
            glUniform1f(uniforms['dim'], g_dim)
            glActiveTexture(GL_TEXTURE0)
            glBindTexture(GL_TEXTURE_2D, final)
            glClear(GL_COLOR_BUFFER_BIT)
            glDrawArrays(GL_TRIANGLES, 0, 3)
        if omap:                                        # OUTPUT MAP: palco pronto -> blocos do raster (a janela)
            glBindFramebuffer(GL_FRAMEBUFFER, 0)
            glViewport(0, 0, WIN_W, WIN_H)
            glClear(GL_COLOR_BUFFER_BIT)
            _use_basic(map_prog)
            ba, bb, bc = _map_uniforms(scr_rects, omap[2])
            glUniform2f(map_u['u_res'], WIN_W, WIN_H)
            glUniform4f(map_u['u_box'], *_canvas_box(WIN_W, WIN_H, omap[0], omap[1]))
            glUniform2f(map_u['u_rast'], omap[0], omap[1])
            glUniform1i(map_u['u_nblk'], len(scr_rects))
            glUniform4fv(map_u['u_ba'], len(scr_rects), ba)
            glUniform4fv(map_u['u_bb'], len(scr_rects), bb)
            glUniform4fv(map_u['u_bc'], len(scr_rects), bc)
            glActiveTexture(GL_TEXTURE0 + POLY_UNIT)
            glBindTexture(GL_TEXTURE_2D, poly_tex[0])
            glActiveTexture(GL_TEXTURE0 + OUTPUT_MAP_UNIT)
            glBindTexture(GL_TEXTURE_2D, lt['canvas'])
            glDrawArrays(GL_TRIANGLES, 0, 3)
        glActiveTexture(GL_TEXTURE0)
        state['output']['shader'] = f'{len(src_frames)} fonte(s)'

        # Output Image (ver CLAUDE.md): mesmos medidores do Source Image, so que na imagem
        # JA sintetizada — precisa ler antes do flip trocar o buffer. So' quando ligado
        # (checkbox "calcular" na tab) e throttled, senao o glReadPixels (sincrono, espera
        # a GPU) derruba o fps sozinho.
        t_pv = time.perf_counter()
        want_pv = time.time() - state.get('out_want', 0) < 1.5
        if (tuning.OUT_ANALYSIS_ENABLED or want_pv) and t_pv - out_pv_t[0] >= 1.0 / OUT_PREVIEW_HZ:
            out_pv_t[0] = t_pv
            pw = OUT_PV_W if WIN_W > OUT_PV_W else WIN_W
            ph = max(2, int(round(pw * WIN_H / max(1, WIN_W))))
            small = None
            try:
                glBindFramebuffer(GL_READ_FRAMEBUFFER, 0)
                small = pv_grab(out_pv, 'out', (0, 0, WIN_W, WIN_H), pw, ph)
            except Exception as e:                      # sem blit/PBO (driver velho): le inteira e reduz
                if not out_pv.get('warned'):
                    print('previa da saida: blit indisponivel, lendo a janela inteira ->', e)
                    out_pv['warned'] = True
                out_pv['wh'] = None
                glBindFramebuffer(GL_FRAMEBUFFER, 0)
                buf = glReadPixels(0, 0, WIN_W, WIN_H, GL_RGB, GL_UNSIGNED_BYTE)
                st_ = max(1, -(-WIN_W // OUT_PV_W))
                # OpenGL le de baixo pra cima — inverte pra topo->baixo (igual ao Source Image / ffmpeg)
                small = np.frombuffer(buf, dtype=np.uint8).reshape(WIN_H, WIN_W, 3)[::st_, ::st_][::-1]
            glBindFramebuffer(GL_FRAMEBUFFER, 0)
            if small is not None:
                small = np.ascontiguousarray(small)
                sh_, sw_ = small.shape[:2]
                state['out_small'] = (small.tobytes(), sw_, sh_)
            if small is not None and tuning.OUT_ANALYSIS_ENABLED and t_pv - out_an_t[0] >= 1.0 / OUT_ANALYSIS_HZ:
                out_an_t[0] = t_pv
                out_frame = small.reshape(-1)
                arr_s = frame_downsample(out_frame, sw_, sh_)
                if arr_s is not None:
                    hue_s, sat_s, val_s = rgb_to_hsv_np(arr_s)
                    gx_s, gy_s = gradient(val_s)
                    out_dom = dominant_color(arr_s.astype(np.uint8), arr_s.shape[1], arr_s.shape[0])
                    state['out_image'] = image_dash_data(arr_s, hue_s, sat_s, val_s, gx_s, gy_s,
                                                          out_frame, sw_, sh_, out_dom,
                                                          out_img['peaks'], out_img['prev_val'],
                                                          out_img['prev_mean'])

        def read_canvas():
            """liga o READ framebuffer no CANVAS pronto (o palco, sem o raster) e devolve a regiao (x0, y0,
            x1, y1): com telao a textura `canvas`; sem, a janela no retangulo do canvas (sem as barras)."""
            if omap:
                glBindFramebuffer(GL_READ_FRAMEBUFFER, lt['fbo'])
                glFramebufferTexture2D(GL_READ_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, lt['canvas'], 0)
                return (0, 0, CMP_W, CMP_H)
            glBindFramebuffer(GL_READ_FRAMEBUFFER, 0)
            return (int(round(cbox[0] * WIN_W)), int(round(cbox[1] * WIN_H)),
                    int(round((cbox[0] + cbox[2]) * WIN_W)), int(round((cbox[1] + cbox[3]) * WIN_H)))

        # PROTECAO DA SAIDA (Limiter; tuning.LIMITS): a saida pronta a 16 px, TODO frame (leitura async =
        # quase de graca) -> luminancia media -> ganho do proximo frame (no master: g_dim). Estrobo/brilho.
        lim = getattr(tuning, 'LIMITS', None) or {}
        if lim.get('on', 1):
            try:
                pw = 16
                img = pv_grab(lim_pv, 'lim', read_canvas(), pw, max(2, int(round(pw * FIT_H / max(1, FIT_W)))))
                if img is not None:
                    luma = float((img[..., 0] * 0.2126 + img[..., 1] * 0.7152 + img[..., 2] * 0.0722).mean()) / 255.0
                    lim_g[0] = limiter.step(time.monotonic(), luma, float(lim.get('bright', 1.0)), bool(lim.get('flash', 1)))
            except Exception as e:
                if lim_pv.get('err') != str(e):
                    print('protecao da saida ->', e)
                    lim_pv['err'] = str(e)
            glBindFramebuffer(GL_FRAMEBUFFER, 0)
        else:
            lim_g[0], limiter.why = 1.0, ''
        state['limit'] = {'g': round(lim_g[0], 2), 'why': limiter.why if lim_g[0] < 0.98 else ''}

        # PREVIA DO CANVAS (vista Palco do dash: cada tela mostra a regiao dela): o palco pronto, sem o
        # raster — com telao a textura `canvas`; sem, a janela no retangulo do canvas (sem as barras)
        if time.time() - state.get('cv_want', 0) < 1.5 and t_pv - cv_pv['t'] >= 1.0 / OUT_PREVIEW_HZ:
            cv_pv['t'] = t_pv
            try:
                k = min(1.0, CV_PV_MAX / max(1, FIT_W, FIT_H))
                pw, ph = max(2, int(round(FIT_W * k))), max(2, int(round(FIT_H * k)))
                sr = read_canvas()
                a = pv_grab(cv_pv, 'cv', sr, pw, ph)
                if a is not None:
                    state['cv_small'] = (a.tobytes(), a.shape[1], a.shape[0])
            except Exception as e:                      # sem blit: o Palco fica sem previa
                if not cv_pv.get('warned'):
                    print('previa do canvas indisponivel ->', e)
                    cv_pv['warned'] = True
            glBindFramebuffer(GL_FRAMEBUFFER, 0)

        # LUZES (tuning.LIGHTS, ver luzes.py): o canvas pronto (= o da previa cv) pequeno -> cor de cada
        # zona -> brilho pelo som (♪, mesmo _mod_value dos knobs) x master -> Art-Net a LIGHTS['fps']
        lcfg = getattr(tuning, 'LIGHTS', None) or {}
        req = state.pop('light_scan_req', None)
        if req and not (state.get('light_scan') or {}).get('run'):
            state['light_scan'] = {'run': 1, 'prog': 0.0, 'txt': 'começando'}
            threading.Thread(target=light_scan_thread, args=(req,), daemon=True).start()
        if lcfg.get('on') and lcfg.get('fixtures') and not (state.get('light_scan') or {}).get('run') and t_pv - lt_pv['t'] >= 1.0 / max(1, min(60, int(lcfg.get('fps', 40)))):
            lt_pv['t'] = t_pv
            try:
                pw = min(LIGHT_PV_W, FIT_W)
                ph = max(2, int(round(pw * FIT_H / max(1, FIT_W))))
                sr = read_canvas()
                img = pv_grab(lt_pv, 'luz', sr, pw, ph)
                if img is not None:
                    lt_pv['tx'] = lt_pv['tx'] or luzes.Sender()
                    unis = luzes.dmx_frame(img, lcfg['fixtures'], lambda fx: _mod_value(1.0, fx.get('mod'), state),
                                           lt_pv['prev'], master=1.0 - g_dim, host=str(lcfg.get('host') or '255.255.255.255'),
                                           key_rgb=(state.get('tempo') or {}).get('key_rgb'))
                    lt_pv['tx'].send(unis)
                    state['lights_live'] = [[int(c) for c in (lt_pv['prev'].get(i) or [(0, 0, 0)])[0]]
                                            for i in range(len(lcfg['fixtures']))]   # 1a cor de cada aparelho (dash)
            except Exception as e:                      # config torta / sem rede: o video nao para por causa da luz
                if lt_pv.get('err') != str(e):
                    print('luzes ->', e)
                    lt_pv['err'] = str(e)
            glBindFramebuffer(GL_FRAMEBUFFER, 0)

        # TROCA QUANTIZADA (tuning.SCENE_QUANT = 'beat' | 'bar'; '' = na hora): o pedido espera a proxima
        # batida/'1' do compasso (ritmo.Tempo); sem tempo detectado, troca na hora. Pedido novo substitui.
        pend = state.get('scene_pending')
        if pend and pend.get('transition') and tp_ and 'at' not in pend:
            pend['at'] = tp_.next_boundary(time.monotonic(), str(getattr(tuning, 'SCENE_QUANT', '') or ''))
        if pend and pend.get('at') and time.monotonic() < pend['at']:
            pend = None                         # ainda nao chegou a batida
        elif pend and state.get('scene_pending') is pend:
            state.pop('scene_pending', None)
        if pend:
            # a cena que SAI segue viva na transicao (render_mix com os dados dela + fontes abertas).
            # ponytail: trocar NO MEIO de uma transicao larga a cena que ja' saia (corte nela); encadear
            # 3 cenas = guardar uma lista de 'old' em vez de uma
            old_sc = {'overlays': state.get('overlays'), 'bindings': state.get('bindings'), 'pool': state.get('pool'),
                      'grade': getattr(tuning, 'SCENE_GRADE', None)} if pend.get('transition') else None
            try:
                dash_server.apply_scene(pend['name'], defer=True)   # memoria agora; disco numa thread (sem perder frame)
                print('set ->', pend['name'])
            except (KeyError, ValueError, OSError) as e:
                print('set: nao aplicou', pend.get('name'), '->', e)
            else:
                tpath, tms = _resolve_transition(dash_server.scene_transition_name(pend['name'])) \
                    if pend.get('transition') else (None, 0)
                nb = float(getattr(tuning, 'TRANS_BEATS', 0) or 0)   # duracao em BATIDAS (0 = o ms do .glsl)
                if tpath and nb > 0 and state.get('bpm'):
                    tms = nb * 60000.0 / state['bpm']
                prog_t = trans_program(tpath) if tpath else None
                scene_tr = {'prog': prog_t, 'ms': tms, 't0': time.perf_counter(), 'old': old_sc} if prog_t and old_sc else None
                if scene_tr:
                    state['scene_from'] = old_sc        # _sync_overlays mantem as fontes dela abertas

        pygame.display.flip()
        try:
            fps_t = max(10, min(240, int(getattr(tuning, 'OUTPUT_FPS', 60) or 60)))
        except (TypeError, ValueError):
            fps_t = 60
        clock.tick(fps_t)
        frame_n += 1
        if frame_n % 15 == 0:
            state['output']['fps'] = round(clock.get_fps(), 1)
            state['output']['fps_target'] = fps_t
            # dims originais da midia ativa (botao "tamanho da mídia" no dash). So le o cache:
            # _probe_dims ja rodou quando a midia abriu; ffprobe aqui travaria o render.
            v = state['video']
            dims = _dims_cache.get(v['path']) if v and v.get('mode') == 'media' else None
            state['output']['media_dims'] = list(dims) if dims else None
            at = state.get('audio_t')
            state['health'] = {'audio_age': round(time.monotonic() - at, 1) if at else None,
                               'audio_err': state.get('audio_err'), 'stale': _stale_sources()}

    # da um instante pras threads daemon (audio_thread) notarem running=False e rodarem
    # seu "finally" (ex. sair da tela alternada) antes do processo sumir de baixo delas
    time.sleep(0.15)
    pygame.quit()


def _selfcheck():
    """Sem GL: so o cache de imagem parada. Precisa do ffmpeg (dep do app de qualquer jeito)."""
    import tempfile
    # canvas encaixado na janela: 16:9 numa janela 4:3 = barras em cima/embaixo; 4:3 em 16:9 = dos lados
    ok = lambda a, b: all(abs(x - y) < 1e-6 for x, y in zip(a, b))
    assert ok(_canvas_box(1600, 900, 1920, 1080), FULL_UV)
    assert ok(_canvas_box(800, 600, 1600, 900), (0, 0.125, 1, 0.75))
    assert ok(_canvas_box(1600, 900, 800, 600), (0.125, 0, 0.75, 1))
    assert ok(_rect_uv(None, (0.125, 0, 0.75, 1)), (0.125, 0, 0.75, 1))
    # telas: portal = 2 colunas 1x4 m (256x1024) + faixa 4x1 m (1024x256) em cima -> canvas 4x5 m
    arco = [{'x': 0, 'y': 1, 'w': 1, 'h': 4, 'pw': 256, 'ph': 1024}, {'x': 3, 'y': 1, 'w': 1, 'h': 4, 'pw': 256, 'ph': 1024},
            {'x': 0, 'y': 0, 'w': 4, 'h': 1, 'pw': 1024, 'ph': 256}, {'x': 'ruim'}]
    cw, ch, rs = _stage(arco, 800, 600)
    assert (cw, ch) == (1024, 1280) and len(rs) == 3, (cw, ch, rs)
    assert ok(rs[1][0], (0.75, 0.2, 0.25, 0.8)) and ok(rs[2][0], (0, 0, 1, 0.2))
    assert ok(rs[2][1] + rs[2][2] + rs[2][3], (0, 0, 1, 0, 0, 0.2)) and rs[2][4] is None
    # forma livre: faixa 4x1 girada 90 graus = coluna 1x4 (canvas = o contorno girado); triangulo
    rr = _stage([dict(arco[2], rot=90)], 800, 600)[2]
    assert ok(rr[0][0], (0, 0, 1, 1)) and ok(rr[0][1], (1, 0)) and ok(rr[0][2], (0, 1)) and ok(rr[0][3], (-1, 0)), rr
    sa, sb = _blend_scr(rr)[0]                       # inversa: canto de cima a direita do canvas = (u, v) (0, 0)
    assert ok(sa, (1, 0, 0, 1)) and ok(sb, (-1, 0, 0, 0)), (sa, sb)
    tri = [dict(arco[2], poly=[[0, 1], [0.5, 0], [1, 1]])]
    pt = _poly_tex(_stage(tri, 800, 600)[2])
    assert pt.shape == (16, 32, 4) and tuple(pt[0, 1]) == (128, 0, 0, 0) and not pt[1].any()
    assert _blend_scr(_stage(tri, 800, 600)[2])[0][1][2] == 3
    assert _stage([], 800, 600) == (800, 600, [])   # sem telas: canvas = janela
    # TELAO (pixel map ligado): o canvas continua o PALCO; cada tela com ox/oy vira um bloco do raster
    # (pw x ph; orot = deitado: ocupa ph x pw), alinhado com as shapes do _stage; sem ox/oy = fora
    blocos = [dict(arco[0], ox=0, oy=0, rot=30), dict(arco[2], ox=256, oy=0, orot=90, poly=[[0, 0], [1, 0], [0, 1]]), arco[1], {'x': 'ruim'}]
    pm = {'on': 1, 'w': 1920, 'h': 1080}
    assert _raster({'on': 0, 'w': 1920, 'h': 1080}) is None and _raster({'on': 1, 'w': 8, 'h': 8}) is None
    assert _stage(blocos, 800, 600)[:2] == _stage(blocos, 800, 600, MAX_CANVAS_PX)[:2] != (1920, 1080)   # canvas = palco
    rw, rh, bl = _out_blocks(blocos, pm)
    assert (rw, rh) == (1920, 1080) and bl == [(0, 0, 256, 1024, 0), (256, 0, 256, 1024, 1), None], bl
    assert _out_blocks(blocos, dict(pm, on=0)) is None and _out_blocks([arco[1]], pm) is None   # desligado / sem blocos
    ba, bb, bc = _map_uniforms(_stage(blocos, 800, 600)[2], bl)
    assert ba.shape == (12,) and tuple(ba[4:8]) == (256, 0, 256, 1024) and not ba[8:].any()
    assert tuple(bc[4:8])[2:] == (1, 3) and bc[3] == 0                    # quartos de giro, pontos do poligono
    cw, ch, _ = _stage([{'x': 0, 'y': 0, 'w': 10, 'h': 1, 'pw': 8000, 'ph': 800}], 800, 600, 1000 * 100)
    assert (cw, ch) == (1000, 100), (cw, ch)                              # teto de area: a densidade cai por igual
    assert ok(_rect_uv([0.5, 0, 0.5, 0.5], FULL_UV), (0.5, 0.5, 0.5, 0.5))   # canto de CIMA a direita
    p = os.path.join(tempfile.mkdtemp(), 't.png')
    subprocess.run(['ffmpeg', '-loglevel', 'error', '-f', 'lavfi', '-i', 'color=c=red:s=320x240',
                    '-frames:v', '1', p], check=True)
    v = {'path': p, 'fit': 'fill'}
    a = _decode_still(v)
    assert a is not None and a.shape == (FRAME_SIZE,), a
    assert _decode_still(v) is a, 'segundo decode nao veio do cache'
    assert int(a[0]) > 200 and int(a[1]) < 60 and int(a[2]) < 60, a[:3].tolist()  # vermelho
    os.remove(p)
    print('native_synth still-cache self-check ok')

    # --- pool: filtra video do set ativo, tecla primeiro, respeita VIDEO_POOL / _MAX ---
    global MEDIA_DIR
    _md0, MEDIA_DIR = MEDIA_DIR, tempfile.mkdtemp()
    os.makedirs(os.path.join(MEDIA_DIR, 'S1'))
    for n in ('a.mp4', 'b.mp4', 'c.mp4', 'd.mp4', 'e.png'):
        open(os.path.join(MEDIA_DIR, 'S1', n), 'wb').write(b'')
    _keep = {k: getattr(tuning, k, None) for k in
             ('MEDIA', 'MEDIA_SET', 'MEDIA_KEYS', 'VIDEO_POOL', 'VIDEO_POOL_MAX')}
    tuning.MEDIA = [{'name': 'a', 'file': 'S1/a.mp4', 'kind': 'video'},
                   {'name': 'b', 'file': 'S1/b.mp4', 'kind': 'video'},
                   {'name': 'c', 'file': 'S1/c.mp4', 'kind': 'video'},
                   {'name': 'd', 'file': 'S1/d.mp4', 'kind': 'video'},
                   {'name': 'e', 'file': 'S1/e.png', 'kind': 'image'},   # imagem -> fora do pool
                   {'name': 'x', 'file': 'S2/x.mp4', 'kind': 'video'}]   # outro set -> fora
    tuning.MEDIA_SET, tuning.MEDIA_KEYS = 'S1', {'S1': {'c': '7'}}
    tuning.VIDEO_POOL, tuning.VIDEO_POOL_MAX = 1, 3
    got = [os.path.basename(pp) for pp, _ in _desired_pool()]
    assert got == ['c.mp4', 'a.mp4', 'b.mp4'], got   # tecla 1o, resto em ordem, cap 3
    tuning.VIDEO_POOL = 0
    assert _desired_pool() == [], 'VIDEO_POOL=0 nao esvaziou o pool'
    open(os.path.join(MEDIA_DIR, 'S1', 'solta.mp4'), 'wb').write(b'')   # na pasta, fora de MEDIA (como a galeria mostra)
    _ov, _pl = state.get('overlays'), state.get('pool')
    state['overlays'], state['pool'] = [{'file': 'S1/solta.mp4', 'opacity': 1.0}], None
    it = _overlay_items()
    assert it and it[0][0]['kind'] == 'video', ('midia solta posta na mesa tem que entrar na mistura', it)
    state['overlays'], state['pool'] = _ov, _pl
    for k, val in _keep.items():
        setattr(tuning, k, val) if val is not None else delattr(tuning, k)
    MEDIA_DIR = _md0
    print('native_synth pool self-check ok')

    # --- transicoes: harness, // ms:, e resolucao (arquivo -> none -> arquivo sumido) ---
    w = _wrap_transition('vec4 transition(vec2 uv){ return getToColor(uv); }')
    assert 'getFromColor' in w and 'getToColor' in w and 'void main' in w, w
    global TRANS_DIR
    _td0, TRANS_DIR = TRANS_DIR, tempfile.mkdtemp()
    open(os.path.join(TRANS_DIR, 'fade.glsl'), 'w', encoding='utf-8').write('// ms: 250\nvec4 transition(vec2 uv){return vec4(0.0);}\n')
    assert _transition_ms(os.path.join(TRANS_DIR, 'fade.glsl')) == 250
    _tk = {k: getattr(tuning, k, None) for k in ('MEDIA', 'MEDIA_SET', 'TRANSITION_DEFAULT')}
    assert _resolve_transition('fade.glsl')[1] == 250
    assert _resolve_transition('none') == (None, 0) and _resolve_transition('') == (None, 0)
    assert _resolve_transition('sumiu.glsl') == (None, 0)                           # arquivo sumido
    assert _resolve_transition('../fade.glsl')[0] == os.path.join(TRANS_DIR, 'fade.glsl')  # basename: sem sair da pasta
    for k, val in _tk.items():
        setattr(tuning, k, val) if val is not None else delattr(tuning, k)
    TRANS_DIR = _td0
    print('native_synth transitions self-check ok')

    # --- camadas: ordem de baixo pra cima, opacidade, set ativo, camada fria pulada ---
    _md0, MEDIA_DIR = MEDIA_DIR, tempfile.mkdtemp()
    os.makedirs(os.path.join(MEDIA_DIR, 'default'))
    os.makedirs(os.path.join(MEDIA_DIR, 'S2'))
    for f in ('default/a.png', 'default/b.png', 'default/v.mp4', 'S2/c.png'):
        open(os.path.join(MEDIA_DIR, f), 'wb').write(b'x')
    _tk = {k: getattr(tuning, k, None) for k in ('MEDIA', 'MEDIA_SET')}
    tuning.MEDIA = [{'name': 'a', 'file': 'default/a.png', 'kind': 'image'},
                   {'name': 'b', 'file': 'default/b.png', 'kind': 'image'},
                   {'name': 'v', 'file': 'default/v.mp4', 'kind': 'video'},
                   {'name': 'c', 'file': 'S2/c.png', 'kind': 'image'}]
    tuning.MEDIA_SET = 'default'
    key = lambda f: (os.path.join(MEDIA_DIR, f), 'fill', FIT_W, FIT_H)
    _still_cache[key('default/a.png')] = np.full(FRAME_SIZE, 200, np.uint8)
    _still_cache[key('default/b.png')] = np.full(FRAME_SIZE, 0, np.uint8)
    _still_cache[key('S2/c.png')] = np.full(FRAME_SIZE, 255, np.uint8)
    comp = lambda: _composite(_source_frames())
    state['overlays'] = []
    assert _source_frames() == [] and int(comp().max()) == 0, 'nada marcado = preto'
    state['overlays'] = [{'file': 'default/a.png', 'opacity': 0.5}]
    assert abs(int(comp()[0]) - 100) <= 1, comp()[0]                             # 0 -> 200 a 50%
    assert [k for k, _, _ in _source_frames()] == ['default/a.png']
    state['overlays'] = [{'file': 'default/a.png', 'opacity': 1.0}, {'file': 'default/b.png', 'opacity': 0.5}]
    assert abs(int(comp()[0]) - 100) <= 1, comp()[0]                             # a cobre; b (0) a 50% por cima
    state['overlays'] = [{'file': 'default/b.png', 'opacity': 0.5}, {'file': 'default/a.png', 'opacity': 1.0}]
    assert int(comp()[0]) == 200, 'ordem: a ultima marcada fica por cima'
    state['overlays'] = [{'file': 'S2/c.png', 'opacity': 1.0}, {'file': 'default/v.mp4', 'opacity': 1.0}]
    assert _source_frames() == [], 'camada de outro set / video sem frame ainda devia ser pulada'
    # fonte viva: sempre o frame do _ovl — a selecionada (state['frame']) nao mexe na saida
    _f0, _v0 = state.get('frame'), state.get('video_id')
    state['frame'] = np.full(FRAME_SIZE, 50, np.uint8); state['video_id'] = 'webcam:/dev/video9'
    _ovl['webcam:/dev/video9'] = {'frame': np.full(FRAME_SIZE, 200, np.uint8)}
    state['overlays'] = [{'file': 'webcam:/dev/video9', 'opacity': 0.5}]
    assert _overlay_items() == [('webcam:/dev/video9', 0.5)], _overlay_items()
    assert abs(int(comp()[0]) - 100) <= 1, comp()[0]
    _ovl.pop('webcam:/dev/video9')
    assert _source_frames() == [], 'selecionada sem _ovl nao devia vazar state[frame] na saida'
    state['overlays'] = [{'file': 'screen:HDMI-9', 'opacity': 1.0}]
    assert _source_frames() == [], 'tela sem ffmpeg ainda devia ser pulada'
    _ovl['screen:HDMI-9'] = {'frame': np.zeros(FRAME_SIZE, np.uint8)}
    assert [k for k, _, _ in _source_frames()] == ['screen:HDMI-9'] and int(comp()[0]) == 0
    state['pool'] = {'sources': ['default/a.png']}                               # fora do set = fora da saida
    state['overlays'] = [{'file': 'screen:HDMI-9', 'opacity': 1.0}, {'file': 'default/a.png', 'opacity': 1.0}]
    assert [k for k, _, _ in _source_frames()] == ['default/a.png'], _source_frames()
    state.pop('pool')
    state['overlays'] = [{'file': 'screen:HDMI-9', 'opacity': 1.0, 'off': 1}]  # desligada = fora da saida
    assert _source_frames() == [], _source_frames()
    ka = key('default/a.png')                    # imagem com transparencia: pesa so' onde e' opaca
    _still_alpha[ka] = np.zeros(FRAME_SIZE, np.uint8)
    state['overlays'] = [{'file': 'default/a.png', 'opacity': 1.0}]
    assert int(comp()[0]) == 0, 'alpha 0 devia deixar ver o de baixo (preto)'
    _still_alpha.pop(ka)
    state['overlays'] = [{'file': 'default/a.png', 'opacity': 1.0}, {'file': 'default/a.png', 'opacity': 1.0, 'dup': 2}]
    assert [k for k, _, _ in _source_frames()] == ['default/a.png', 'default/a.png#2'], 'mesma fonte 2x = 2 canais'
    _ovl.pop('screen:HDMI-9'); state['frame'], state['video_id'] = _f0, _v0
    for k, val in _tk.items():
        setattr(tuning, k, val) if val is not None else delattr(tuning, k)
    for f in ('default/a.png', 'default/b.png', 'S2/c.png'):
        _still_cache.pop(key(f), None)
    state['overlays'] = []
    MEDIA_DIR = _md0
    print('native_synth overlay self-check ok')
    lv = {'subbass': 0.5, 'air': 0.9, 'kick': 0.0}
    assert _mod_value(0.3, None, lv) == 0.3, '♪ desligado = o knob'
    assert abs(_mod_value(0.3, {'b': ['subbass'], 'lo': 0.2, 'hi': 0.6}, lv) - 0.4) < 1e-9, '♪ = lo + (hi-lo) * nivel'
    assert abs(_mod_value(0.3, {'b': ['subbass', 'air'], 'lo': 1.0, 'hi': 0.0}, lv) - 0.1) < 1e-9, '♪ mais forte vale; hi<lo inverte'
    assert abs(_mod_value(0.5, {'b': ['kick']}, lv) - 0.5) < 1e-9, '♪ formato velho = do knob ate 1'
    assert abs(_mod_value(0.0, {'b': ['m1'], 'lo': 0.2, 'hi': 0.8}, {'m1': 0.5}) - 0.5) < 1e-9, 'macro = fonte do ♪'
    near = lambda a, b: abs(a - b) < 1e-9
    assert near(_mod_value(0.0, {'b': ['lfo'], 'lo': 0.2, 'hi': 0.6, 'lfo': {'f': 'saw', 'r': 4}}, {'bpos': 2.0}), 0.4), 'lfo: serra no meio'
    assert near(_mod_value(0.0, {'b': ['lfo', 'kick'], 'lo': 0, 'hi': 1, 'lfo': {'f': 'sq', 'r': 4}}, {'bpos': 3.0, 'kick': 0.7}), 0.7), \
        'lfo + kick: vale o mais forte'
    assert near(_mod_value(0.0, {'b': ['mov'], 'lo': 0.0, 'hi': 0.5}, {'mov': 0.6}), 0.3), 'imagem (mov) = fonte do ♪'
    fq, bd, dc = np.array([100.0, 10000.0]), [('Air', 5000.0, 20000.0)], {'Air': 0.999}
    pk, lg = {'Air': 1e-6}, {}
    for _ in range(200):
        named_band_levels(np.array([0.0, 1.0]), fq, bd, pk, dc, lg)          # agudo de verdade
    for _ in range(13000):                                                    # ~5 min so' de chiado
        lv_air = named_band_levels(np.array([0.0, 0.02]), fq, bd, pk, dc, lg)[0][2]
    assert lv_air < 0.3, ('faixa vazia nao pode acender com o proprio chiado', lv_air)
    pk2 = {'Air': 1e-6}
    for _ in range(13000):
        lv_old = named_band_levels(np.array([0.0, 0.02]), fq, bd, pk2, dc)[0][2]
    assert lv_old > 0.9, 'sem piso (chamada antiga) = o comportamento de antes'
    print('native_synth mod self-check ok')
    # --- dash v4: quem le quem (ramo, entrada B, feedback) ---
    bnd = {'cam': {'shaders': [{'file': 'a.frag', 'id': 'k1'}, {'file': 'b.frag', 'id': 'k2', 'ins': ['fb']}]},
           'vid': {'shaders': [{'file': 'm.frag', 'ins': ['cam', '@k1']}]},
           '@k2': {'shaders': [{'file': 'c.frag'}]}}
    gw = _graph_wants(bnd, [{'file': 'cam', 'opacity': 1.0}, {'file': '@k2', 'opacity': 0.5}])
    assert gw == ({'cam'}, {'k2'}, {'cam'}), gw
    assert _graph_wants(bnd, [{'file': 'cam', 'opacity': 0.0}, {'file': '@k2', 'opacity': 0.7}]) == ({'cam'}, {'k2'}, {'cam'}), \
        'ramo no ar: a fileira mae roda mesmo a 0%'
    assert _graph_wants(bnd, [{'file': 'cam', 'opacity': 1}, {'file': '@k2', 'opacity': 0}]) == ({'cam'}, set(), set()), \
        'ramo a 0% que ninguem le: sem tap'
    assert _graph_wants(bnd, [{'file': 'cam', 'off': 1}, {'file': 'vid'}]) == ({'cam'}, {'k1'}, {'cam'}), \
        'entrada B (raia + tap) faz a desligada rodar'
    assert _graph_wants({}, []) == (set(), set(), set())
    _f0 = state.get('frame')
    _ovl['webcam:/dev/video9'] = {'frame': np.full(FRAME_SIZE, 200, np.uint8)}
    state['bindings'] = {'webcam:/dev/video9': {'shaders': [{'file': 'a.frag', 'id': 'k1'}]}}
    state['overlays'] = [{'file': 'webcam:/dev/video9', 'opacity': 0.0}, {'file': '@k1', 'opacity': 1.0}]
    sf = _source_frames()
    assert [(k, a, f is None) for k, a, f in sf] == [('webcam:/dev/video9', 0.0, False), ('@k1', 1.0, True)], sf
    assert int(_composite(sf).max()) == 0, 'a 0% e o ramo (so GPU) nao entram na mistura da CPU'
    state['overlays'] = [{'file': 'webcam:/dev/video9', 'opacity': 1.0, 'off': 1}, {'file': '@k1', 'opacity': 1.0, 'dup': 2}]
    assert [(m, a, k) for m, a, k in _overlay_items(chans=True)] == [('webcam:/dev/video9', 0.0, 'webcam:/dev/video9'),
                                                                     ('@k1', 1.0, '@k1#2')], 'desligada mas lida: entra a 0%'
    assert _stale_sources() == [], 'ramo nao e fonte parada'
    state['overlays'] = [{'file': '@k1', 'opacity': 1.0}]
    assert [k for k, _, _ in _source_frames()] == ['@k1'], 'ramo cuja mae nem esta na mesa: o loop GL pula (sem tap)'
    _ovl.pop('webcam:/dev/video9')
    state['overlays'], state['bindings'], state['frame'] = [], {}, _f0
    # miniaturas por passo (empilhadas, buraco = preto) e previa fora do ar
    state['steps_small'] = {'key': 'cam', 'n': 3, 'img': {0: (b'\x01' * 12, 2, 2), 2: (b'\x02' * 12, 2, 2)}}
    assert _preview_frame('steps', 'cam') == (b'\x01' * 12 + bytes(12) + b'\x02' * 12, 2, 6) and state['steps_want'][0] == 'cam'
    assert _preview_frame('steps', 'vid') is None
    state['try'], state['try_small'] = {'key': 'cam', 'v': [{}, {}], 't': 0.0}, {1: (b'xyz', 1, 1)}
    assert _preview_frame('try', '1') == (b'xyz', 1, 1) and state['try']['t'] > 0 and _preview_frame('try', '0') is None
    state.pop('try'), state.pop('try_small'), state.pop('steps_small'), state.pop('steps_want')
    assert _ins_tex('@m1', 'cam', {'cam': 1}, {'m1': 7}, 0) == 7 and _ins_tex('@x', 'cam', {}, {}, 0) == 0
    assert _ins_tex('fb', 'cam', {'cam': 1}, {}, 0) == 1 and _ins_tex('vid', 'cam', {'vid': 2}, {}, 0) == 2 and _ins_tex(None, 'cam', {}, {}, 9) == 9
    pb = {dash_server.POST_KEY: {'shaders': [{'file': 'M.frag', 'id': 'm1'}, {'file': 'N.frag', 'id': 'm2', 'off': 1}]}}
    assert [x['id'] for x in _post_items({'post': ['m2', 'm1', 'zz']}, pb)] == ['m1'], 'post: ligados, na ordem, id que sumiu sai'
    assert _post_items({}, pb) == [] and _post_items({'post': ['m1']}, {}) == []
    print('native_synth graph (v4) self-check ok')
    rng = np.random.default_rng(1)
    fa, fb = (rng.integers(0, 256, FRAME_SIZE, dtype=np.uint8) for _ in range(2))

    def slow(frames):   # a conta de antes (preto + cada uma por cima), sem o atalho da opaca
        out = np.zeros(FRAME_SIZE, np.uint16)
        for _k, a, f in frames:
            a8 = int(round(min(1.0, a) * 256))
            out = (out * (256 - a8) + f * np.uint16(1) * a8) >> 8
        return out.astype(np.uint8)
    _alpha_now.clear()
    for fr in ([('a', 1.0, fa)], [('a', 0.4, fa)], [('a', 1.0, fa), ('b', 0.5, fb)], [('a', 0.5, fa), ('b', 1.0, fb)],
               [('a', 0.3, fa), ('b', 1.0, fb), ('c', 0.7, fa)]):
        assert np.array_equal(_composite(fr), slow(fr)), [(k, a) for k, a, _ in fr]
    assert _composite([('a', 1.0, fa)]) is fa, 'fonte opaca sozinha = o proprio frame, sem copia'
    print('native_synth composite self-check ok')
    st_ = {}
    assert _smooth(st_, 'a', 1.0, 0.5, 0, start=0.0) == 0.5, 'chave nova com start: anda a partir dele'
    assert _smooth(st_, 'a', 1.0, 0.5, 1) == 0.75 and _smooth(st_, 'b', 0.3, 0.5, 1) == 0.3, 'sem start = ja no alvo'
    assert _smooth(st_, 'a', 0.2, 1.0, 2) == 0.2, 'k=1 (suavizacao desligada) = pula'
    for f in range(3, 200):
        v = _smooth(st_, 'a', 0.9, 0.2, f)
    assert v == 0.9, 'chega exatamente no alvo (sem ficar rastejando pra sempre)'
    print('native_synth smooth self-check ok')
    # protecao: estrobo a 8 Hz (preto/branco) e' contido; pulso a 1 Hz passa; imagem clara com teto 0.6 desce
    L = Limiter()
    for f in range(120):                               # 2 s a 60 fps, estrobo 8 Hz
        t = f / 60
        g = L.step(t, (1.0 if int(t * 16) % 2 else 0.0) * L.g)
    assert L.why == 'flash' and g < 0.45, (L.why, g)
    L = Limiter()
    for f in range(180):                               # 3 s, pulso a 1 Hz (2 inversoes/s) = permitido
        t = f / 60
        g = L.step(t, (1.0 if int(t * 2) % 2 else 0.2) * L.g)
    assert L.why == '' and g > 0.95, (L.why, g)
    L = Limiter()
    for f in range(120):
        g = L.step(f / 60, 0.9 * L.g, bright=0.6)
    assert L.why == 'brilho' and abs(0.9 * g - 0.6) < 0.03, (L.why, g)
    print('native_synth limiter self-check ok')
    # auto-nivel: imagem escura (faixa 0.1..0.3) e clara (0.6..0.95) saem na MESMA faixa depois do ajuste
    for lo_, hi_ in ((0.15, 0.45), (0.6, 0.95)):
        ramp = np.tile(np.linspace(lo_, hi_, 640), (480, 1))       # degrade na horizontal, 640x480
        fr = (np.repeat(ramp[..., None], 3, 2) * 255).astype(np.uint8)
        g_, o_ = _auto_levels(fr, 640, 480)
        a2, b2 = lo_ * g_ + o_, hi_ * g_ + o_                         # pontas: um pouco alem de LO/HI (percentis 2/98)
        assert abs(a2 - AUTO_LO) < 0.05 and abs(b2 - AUTO_HI) < 0.05, (lo_, hi_, a2, b2)
    assert _auto_levels(fr, 640, 480, (1.0, 0.0), 0.0) == (1.0, 0.0), 'k=0 = fica onde estava'
    dark = (np.full((480, 640, 3), 0.1) * 255).astype(np.uint8); dark[:, ::2] += 20
    assert _auto_levels(dark, 640, 480)[0] == AUTO_GAIN[1], 'quase preto: ganho para no teto (ruido nao grita)'
    print('native_synth auto-levels self-check ok')


if __name__ == '__main__':
    if '--selfcheck' in sys.argv:
        _selfcheck()
        sys.exit(0)
    try:
        main()
    except KeyboardInterrupt:
        pass
    finally:
        dash_server.stop()  # fecha o socket ja -> o dash detecta a queda e mostra "encerrado"
