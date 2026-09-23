#!/usr/bin/env python3
"""Sintese de imagem nativa: webcam ou tela (ffmpeg) + audio do sistema (parec/PulseAudio)
alimentando shaders/image.frag numa janela OpenGL, sem navegador nenhum no meio.

Layout: este arquivo + dash_server/dash_data/tuning vivem em src/; os .frag em shaders/
(image.frag + presets/*.frag); dash.html e favicon.png na raiz.

Uso: .venv/bin/python src/native_synth.py [--screen [--source NOME]] [--fullscreen | --monitor [NOME]]
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
DASH_EVERY_N_CHUNKS = 3

WIDTH, HEIGHT = 640, 480  # resolucao do conteudo (textura); recalculada no --screen
WIN_W, WIN_H = WIDTH, HEIGHT  # resolucao da janela; recalculada no --fullscreen
FRAME_SIZE = WIDTH * HEIGHT * 3  # rgb24
SIM_W, SIM_H = WIDTH // 4, HEIGHT // 4  # grade da simulacao de fumaca — Jacobi nao precisa de
# resolucao de tela, so de mais iteracoes; recalculada junto com WIDTH/HEIGHT em main()
FRAG_PATH = os.path.join(SHADERS_DIR, 'image.frag')

MAX_CHANNELS = 8  # teto do array u_chan/u_chan_hit no shader; tuning.CHANNELS pode ter menos


def resolve_shader_path():
    """Caminho absoluto do shader ativo (tuning.SHADER, relativo a shaders/ — 'image.frag'
    ou 'presets/<nome>.frag'). Cai pra image.frag se o escolhido sumiu (preset apagado)."""
    p = os.path.join(SHADERS_DIR, getattr(tuning, 'SHADER', 'image.frag'))
    return p if os.path.isfile(p) else FRAG_PATH


def seed_fx(manifest):
    """Garante uma entrada em state['fx'] pra cada nome do manifest (default = tuning.FX ou
    1.0). Nao mexe em quem ja tem valor — preserva o que o dash/MIDI ja ajustou."""
    saved = getattr(tuning, 'FX', {})
    for name in manifest:
        state['fx'].setdefault(name, float(saved.get(name, 1.0)))

VERT_SRC = """
attribute vec2 a_pos;
void main() { gl_Position = vec4(a_pos, 0.0, 1.0); }
"""

# --- TRANSIÇÕES de mídia (galeria "Transições" no dash). Um arquivo transitions/*.glsl e' so
# uma func `vec4 transition(vec2 uv)` estilo gl-transitions; aqui embrulhamos num harness com
# getFromColor (imagem que SAI) / getToColor (a que ENTRA) / progress, e rodamos num passe FBO
# na troca de midia (ver main()). Cabecalho "// ms: N" = duracao (ausente -> 400).
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
            head = open(path).read(2000)
        except OSError:
            head = ''
        m = re.search(r'//\s*ms:\s*(\d+)', head)
        _trans_ms_cache[key] = int(m.group(1)) if m else 400
    return _trans_ms_cache[key]


def _resolve_transition(v):
    """(caminho_abs, ms) da transicao de ENTRADA da midia `v`, ou (None, 0) = corte seco.
    Item com 'transition' vazio usa tuning.TRANSITION_DEFAULT; 'none' ou arquivo sumido = seco."""
    if not v or v.get('mode') != 'media':
        return (None, 0)
    ms_set = getattr(tuning, 'MEDIA_SET', 'default')
    name = v.get('name', '')
    ent = next((m for m in getattr(tuning, 'MEDIA', [])
                if m.get('name') == name and _media_set_of(m.get('file', '')) == ms_set), None) \
        or next((m for m in getattr(tuning, 'MEDIA', []) if m.get('name') == name), None)
    tn = str((ent or {}).get('transition', '') or '')
    if not tn:
        tn = str(getattr(tuning, 'TRANSITION_DEFAULT', 'none') or 'none')
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
         'kick': 0.0, 'dominant': (0.5, 0.5, 0.5),
         # faixas finas de mixagem (Sub-bass..Air) — controlam u_subbass..u_air no shader
         'subbass': 0.0, 'lowmid': 0.0, 'midrange': 0.0, 'highmid': 0.0, 'presence': 0.0,
         'treble_hi': 0.0, 'brilho': 0.0, 'air': 0.0, 'spectrum': [], 'image': {}, 'out_image': {},
         'audio_source': '', 'video': None, 'video_label': '', 'video_id': '', 'output': {},
         # potenciometros de efeito: 'fx_manifest' = nomes do "// fx:" do shader ativo,
         # 'fx' = nivel 0..1 ao vivo por nome (o dash e, no futuro, o MIDI escrevem aqui).
         'fx': {}, 'fx_manifest': [],
         # canais por instrumento (ver tuning.CHANNELS) — controlam u_chan/u_chan_hit no shader
         'chan': [0.0] * MAX_CHANNELS, 'chan_hit': [0.0] * MAX_CHANNELS,
         # transicao de midia em andamento: None ou {'path','ms','from' (frame A),'t0'} — o
         # video_thread poe na troca, o loop GL roda o passe FBO e limpa quando progress>=1.
         'transition': None}
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

    tex = _mktex(WIDTH, HEIGHT)                 # input de imagem (state['frame']), re-upado por frame
    tex_prev = _mktex(WIDTH, HEIGHT, alloc=True)  # frame de 1 iteracao atras — detecta movimento (fumaca)
    tex_a = _mktex(WIDTH, HEIGHT)               # snapshot da imagem que SAI, durante uma transicao
    fbo_tex = _mktex(WIDTH, HEIGHT, alloc=True) # resultado do passe de transicao -> vira o input do preset
    fbo = glGenFramebuffers(1)
    glBindFramebuffer(GL_FRAMEBUFFER, fbo)
    glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, fbo_tex, 0)
    if glCheckFramebufferStatus(GL_FRAMEBUFFER) != GL_FRAMEBUFFER_COMPLETE:
        print('aviso: FBO de transicao incompleto — transicoes vao aparecer pretas')
    glBindFramebuffer(GL_FRAMEBUFFER, 0)

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
    return (win_w, win_h, pos, label, vbo, tex, tex_prev, tex_a, fbo, fbo_tex,
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


def _fit_vf(fit, src_w=0, src_h=0):
    """-vf pra 'fit' (encaixa, barras pretas) ou 'fill' (preenche, corta) a midia no OUTPUT.
    Corrige o aspecto da JANELA (WIN_W:WIN_H), nao so o da textura WIDTHxHEIGHT: o shader
    depois estica a textura pra janela, entao a correcao antecipa esse esticao. Sem as dims
    da fonte (src_w/h=0) cai no scale-estica simples (comportamento de webcam)."""
    if not (src_w and src_h and WIN_W and WIN_H):
        return f'scale={WIDTH}:{HEIGHT},setsar=1'
    ta = WIDTH / HEIGHT
    r = (src_w / src_h) * ta / (WIN_W / WIN_H)   # aspecto alvo DENTRO da textura
    if fit == 'fit':                              # contain: cabe em WIDTHxHEIGHT, resto preto
        tw, th = (WIDTH, WIDTH / r) if r >= ta else (HEIGHT * r, HEIGHT)
        tw, th = int(round(tw)), int(round(th))
        return f'scale={tw}:{th},pad={WIDTH}:{HEIGHT}:({WIDTH}-{tw})/2:({HEIGHT}-{th})/2:black,setsar=1'
    tw, th = (HEIGHT * r, HEIGHT) if r >= ta else (WIDTH, WIDTH / r)   # cover: enche, corta
    tw, th = max(int(round(tw)), WIDTH), max(int(round(th)), HEIGHT)
    return f'scale={tw}:{th},crop={WIDTH}:{HEIGHT}:({tw}-{WIDTH})/2:({th}-{HEIGHT})/2,setsar=1'


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
        display = os.environ.get('DISPLAY', ':0') + f"+{r['x']},{r['y']}"
        cmd = ['ffmpeg', '-loglevel', 'error', *_FAST_IN, '-f', 'x11grab',
               '-framerate', '30', '-video_size', f"{r['w']}x{r['h']}", '-i', display,
               '-vf', f'scale={WIDTH}:{HEIGHT}', '-pix_fmt', 'rgb24', '-f', 'rawvideo', '-']
    elif v['mode'] == 'media':
        vf = _fit_vf(v.get('fit', 'fill'), *(_probe_dims(v['path']) or (0, 0)))
        if v.get('media_kind') == 'video':  # loop infinito, em tempo real
            cmd = ['ffmpeg', '-loglevel', 'error', *_FAST_IN, '-stream_loop', '-1', '-re',
                   '-i', v['path'], '-vf', vf, '-r', '30', '-pix_fmt', 'rgb24', '-f', 'rawvideo', '-']
        else:                               # imagem parada: repete o mesmo frame a 30 fps
            cmd = ['ffmpeg', '-loglevel', 'error', '-loop', '1', '-framerate', '30',
                   '-i', v['path'], '-vf', vf, '-pix_fmt', 'rgb24', '-f', 'rawvideo', '-']
    else:
        cmd = ['ffmpeg', '-loglevel', 'error', *_FAST_IN, '-f', 'v4l2', '-framerate', '30']
        if v['device'] == '/dev/video0':  # so a webcam de verdade precisa forcar o formato
            cmd += ['-input_format', 'yuyv422']
        cmd += ['-video_size', f'{WIDTH}x{HEIGHT}', '-i', v['device'],
                '-vf', f'scale={WIDTH}:{HEIGHT}', '-pix_fmt', 'rgb24', '-f', 'rawvideo', '-']
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


def _decode_still(v):
    """v = state['video'] de uma imagem -> np.uint8[FRAME_SIZE] (None se falhar). Cacheado por
    (arquivo, fit, tamanho da janela): o -vf depende do aspecto da janela (ver _fit_vf)."""
    key = (v['path'], v.get('fit', 'fill'), WIN_W, WIN_H)
    arr = _still_cache.get(key)
    if arr is None:
        vf = _fit_vf(v.get('fit', 'fill'), *(_probe_dims(v['path']) or (0, 0)))
        try:
            out = subprocess.run(
                ['ffmpeg', '-loglevel', 'error', '-i', v['path'], '-vf', vf, '-frames:v', '1',
                 '-pix_fmt', 'rgb24', '-f', 'rawvideo', '-'],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=15).stdout
        except (subprocess.SubprocessError, OSError):
            out = b''
        if len(out) >= FRAME_SIZE:
            arr = np.frombuffer(out[:FRAME_SIZE], dtype=np.uint8)
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
    for m in getattr(tuning, 'MEDIA', []):
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
            ready = select.select([p.stdout], [], [], 0.2)[0]
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
    items = [m for m in getattr(tuning, 'MEDIA', [])
             if m.get('kind') == 'video' and _media_set_of(m.get('file', '')) == ms]
    items.sort(key=lambda m: m.get('name', '') not in keys)  # False (com tecla) antes de True
    out = []
    for m in items[:cap]:
        p = os.path.join(MEDIA_DIR, m.get('file', ''))
        if os.path.isfile(p):
            out.append((p, {'mode': 'media', 'device': None, 'region': None, 'name': m.get('name', ''),
                            'path': p, 'media_kind': 'video',
                            'fit': 'fit' if m.get('fit') == 'fit' else 'fill'}))
    return out


def _sync_pool():
    """Alinha _pool com _desired_pool() no tamanho de janela atual. Idempotente."""
    win = (WIN_W, WIN_H)
    want = _desired_pool()
    want_paths = {p for p, _ in want}
    for path, e in list(_pool.items()):
        if path not in want_paths or e['win'] != win:
            e['run'] = False
            _pool.pop(path, None)
    for path, v in want:
        if path not in _pool:
            e = {'v': v, 'proc': _spawn_ffmpeg(v), 'frame': None, 'win': win, 'run': True}
            e['thr'] = threading.Thread(target=_pool_reader, args=(e,), daemon=True)
            e['thr'].start()
            _pool[path] = e
            print('video pool +', v['name'])


def _await_first(proc, timeout=2.0):
    """Espera o 1o frame completo de `proc` (ate timeout s). np.uint8[FRAME_SIZE] ou None."""
    end = time.monotonic() + timeout
    while running and time.monotonic() < end:
        if select.select([proc.stdout], [], [], 0.1)[0]:
            f = read_exact(proc.stdout, FRAME_SIZE)
            return np.frombuffer(f, dtype=np.uint8) if f is not None else None
        if proc.poll() is not None:
            return None
    return None


def video_thread(mode, region=None, device='/dev/video0'):
    state['video'] = {'mode': mode, 'device': device, 'region': region}  # fonte da verdade
    state['video_label'] = _video_label(state['video'])
    state['video_id'] = _video_id(state['video'])
    cur = dict(state['video'])
    cur_win = (WIN_W, WIN_H)
    pool_sig = None
    proc = None

    def _pooled(v):
        return bool(v) and v.get('media_kind') == 'video' and v.get('path') in _pool

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
            sig = (getattr(tuning, 'MEDIA_SET', 'default'), (WIN_W, WIN_H),
                   getattr(tuning, 'VIDEO_POOL', 0), getattr(tuning, 'VIDEO_POOL_MAX', 4),
                   tuple(m.get('file', '') for m in getattr(tuning, 'MEDIA', [])
                         if m.get('kind') == 'video'))
            if sig != pool_sig:
                pool_sig = sig
                _sync_pool()

            win_moved = cur.get('mode') == 'media' and (WIN_W, WIN_H) != cur_win

            if state['video'] != cur:
                newcur = dict(state['video'])
                a_frame = state['frame']                      # imagem que SAI, pro passe de transicao
                if _is_still(newcur):                         # imagem: buffer do cache, ~0ms
                    if proc:
                        _kill(proc)
                        proc = None
                    _apply_still(newcur)
                elif _pooled(newcur):                         # video no pool
                    e = _pool.get(newcur['path'])
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
                cur_win = (WIN_W, WIN_H)
                _labels(cur)
                # transicao de ENTRADA dessa midia (ou corte seco) — o loop GL faz o blend
                tpath, tms = _resolve_transition(cur)
                if tpath and a_frame is not None and len(a_frame) == FRAME_SIZE:
                    state['transition'] = {'path': tpath, 'ms': tms, 'from': a_frame, 't0': None}
                print('video: fonte ->', _video_label(cur))
                continue

            if win_moved:                                     # so o -vf mudou (aspecto da janela)
                cur_win = (WIN_W, WIN_H)
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

            if _pooled(cur):                                  # le o frame quente do pool
                e = _pool.get(cur['path'])
                if e is not None and e['frame'] is not None:
                    state['frame'] = e['frame']
                    if proc:                                  # pool esquentou -> larga a fonte-ponte
                        _kill(proc)
                        proc = None
                    time.sleep(0.02)
                elif proc is not None:                        # pool ainda frio: mostra a ponte ao vivo
                    if select.select([proc.stdout], [], [], 0.05)[0]:
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
            if not select.select([proc.stdout], [], [], 0.05)[0]:
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
        for e in list(_pool.values()):
            e['run'] = False
        _pool.clear()


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


def named_band_levels(spectrum, freqs, bands, band_peaks, peak_decay):
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
    if getattr(tuning, 'MEDIA', []):   # UMA fonte generica; qual item toca sai da aba Visuals
        res.append({'kind': 'media', 'id': 'media', 'name': 'Media'})
    return res


def _media_set_of(file):
    """set de um item de MEDIA vem do caminho em 'file' ('<set>/x.png' -> <set>; 'x.png' -> default)."""
    head = os.path.dirname(str(file).replace('\\', '/'))
    return head.split('/')[0] if head else 'default'


def _media_entry(name):
    """item de MEDIA por nome — prefere o do set ativo (nomes so sao unicos DENTRO do set)."""
    items = getattr(tuning, 'MEDIA', [])
    ms = getattr(tuning, 'MEDIA_SET', 'default')
    return (next((m for m in items if m.get('name') == name and _media_set_of(m.get('file', '')) == ms), None)
            or next((m for m in items if m.get('name') == name), None))


def _video_from_id(ident):
    """'webcam:/dev/videoN' | 'screen:<monitor>' | 'media' (item ativo/1o) | 'media:<nome>'
    (item especifico, vindo da aba Visuals / atalho) -> dict state['video']. Sempre escala pra
    WIDTH x HEIGHT atuais (nao muda a resolucao de saida ao vivo)."""
    kind, _, rest = ident.partition(':')
    if kind == 'webcam':
        return {'mode': 'webcam', 'device': rest or '/dev/video0', 'region': None}
    if kind == 'media':
        media = getattr(tuning, 'MEDIA', [])
        if rest:
            m = _media_entry(rest)
        else:  # generico: mantem o item de midia atual, senao o 1o da galeria
            cur = state.get('video') or {}
            m = (_media_entry(cur.get('name')) if cur.get('mode') == 'media' else None) \
                or (media[0] if media else None)
        if m:
            return {'mode': 'media', 'device': None, 'region': None, 'name': m.get('name', ''),
                    'path': os.path.join(MEDIA_DIR, m.get('file', '')),
                    'media_kind': 'video' if m.get('kind') == 'video' else 'image',
                    'fit': 'fit' if m.get('fit') == 'fit' else 'fill'}
        return {'mode': 'webcam', 'device': '/dev/video0', 'region': None}  # sem midia -> webcam
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
    band_release, band_attack, band_peakdecay = band_tweak_maps()  # dinamica por faixa (BAND_*)
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
                    band_release, band_attack, band_peakdecay = band_tweak_maps()
                    # reseed dos potenciometros de efeito a partir do FX gravado. ponytail:
                    # sobrescreve tudo do manifest — sem MIDI ainda, o dash e' a unica outra
                    # fonte e ele acabou de gravar esse mesmo valor. Quando o midi_thread
                    # entrar, pular aqui as chaves com CC bound (ver seam no plano).
                    for n in state['fx_manifest']:
                        state['fx'][n] = float(getattr(tuning, 'FX', {}).get(n, state['fx'].get(n, 1.0)))
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
                'amp': min(1.0, amp_raw * tuning.AMP_SCALE),
                'bass': min(1.0, bass_raw * tuning.BASS_SCALE),
                'mid': min(1.0, mid_raw * tuning.MID_SCALE),
                'treble': min(1.0, treble_raw * tuning.TREBLE_SCALE),
            }
            # faixas finas (Sub-bass..Air) — todo chunk, nao so no throttle do monitor,
            # porque agora controlam uniforms de verdade (u_subbass..u_air). "level" ja
            # vem 0..1 (relativo ao pico ENTRE as 8 bandas, auto-calibrado, sem escala
            # manual por banda) — so falta suavizar igual as outras.
            named_levels = named_band_levels(spectrum, freqs, fine_bands, band_peaks, band_peakdecay)
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


def _use_basic(prog):
    """glUseProgram + liga o unico atributo (a_pos) ao vbo do triangulo cheio de tela — todo
    programa da simulacao de fumaca usa o mesmo VERT_SRC, entao a_pos cai sempre no location 0
    (mesma logica do use_program/use_trans_program, so' que sem uniforms de conteudo pra ler)."""
    glUseProgram(prog)
    loc = glGetAttribLocation(prog, 'a_pos')
    glEnableVertexAttribArray(loc)
    glVertexAttribPointer(loc, 2, GL_FLOAT, GL_FALSE, 0, None)


def _locs(prog, *names):
    return {n: glGetUniformLocation(prog, n) for n in names}


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
    global running, WIDTH, HEIGHT, WIN_W, WIN_H, FRAME_SIZE, SIM_W, SIM_H

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
    SIM_W, SIM_H = max(64, WIDTH // 4), max(48, HEIGHT // 4)
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
    (WIN_W, WIN_H, out_pos, out_mode, vbo, tex, tex_prev, tex_a, fbo, fbo_tex,
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
        'fps_target': 30, 'fps': 0.0,
        'shader': os.path.basename(FRAG_PATH), 'shader_status': 'ok',
        'monitors': monitors,
    }

    shader_path = resolve_shader_path()
    with open(shader_path) as f:
        frag_src = f.read()
    frag_mtime = os.path.getmtime(shader_path)
    state['fx_manifest'] = dash_data.parse_fx_manifest(frag_src)
    seed_fx(state['fx_manifest'])
    state['output']['shader'] = os.path.basename(shader_path)

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
        uniforms['tex_smoke'] = glGetUniformLocation(prog, 'u_texture_smoke')  # densidade da sim de fluido (EFEITO 7 silhueta)
        uniforms['tex_fumaca'] = glGetUniformLocation(prog, 'u_texture_fumaca')  # fumaca procedural (EFEITO 6)
        for name in FREQ_BAND_UNIFORM.values():
            uniforms[name] = glGetUniformLocation(prog, 'u_' + name)
        uniforms['chan'] = [glGetUniformLocation(prog, f'u_chan[{i}]') for i in range(MAX_CHANNELS)]
        uniforms['chan_hit'] = [glGetUniformLocation(prog, f'u_chan_hit[{i}]') for i in range(MAX_CHANNELS)]
        # potenciometros de efeito: um uniform u_fx_<nome> por nome do manifest do shader ativo.
        # nome sem uniform correspondente no GLSL -> loc -1 -> glUniform1f(-1, x) e' no-op.
        uniforms['fx'] = {n: glGetUniformLocation(prog, 'u_fx_' + n) for n in state['fx_manifest']}
        glUniform1i(uniforms['tex0'], 0)
        glUniform1i(uniforms['tex_smoke'], 3)
        glUniform1i(uniforms['tex_fumaca'], 4)

    program = build_program(frag_src)
    use_program(program)
    # cache de programa por arquivo de shader: compila 1x, voltar num shader ja usado e' so
    # glUseProgram (troca em ~0ms). Invalidado por mtime (editou o .frag) e por troca de janela
    # (contexto GL novo). (mtime, program, src, manifest) por caminho.
    prog_cache = {shader_path: (frag_mtime, program, frag_src, state['fx_manifest'])}

    # --- passe de TRANSIÇÃO: programa proprio por arquivo transitions/*.glsl (cache por mtime;
    # None = compilou com erro, nao insiste). uso: ver o bloco "state['transition']" no loop.
    tuni = {}
    trans_cache = {}

    def use_trans_program(prog):
        glUseProgram(prog)
        loc = glGetAttribLocation(prog, 'a_pos')
        glEnableVertexAttribArray(loc)
        glVertexAttribPointer(loc, 2, GL_FLOAT, GL_FALSE, 0, None)
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
            with open(tpath) as tf:
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
    use_program(program)  # volta pro preset — o loop so' re-chama use_program() se o shader mudar
    sim_idx = 0  # ping-pong: sim_vel[sim_idx]/sim_density[sim_idx] = "atual", [1-sim_idx] = escrita
    sim_last_t = [time.perf_counter()]  # p/ calcular o dt real da simulacao (frame a frame)
    fumaca_idx = 0  # ping-pong: fumaca_tex[fumaca_idx] = "atual", [1-fumaca_idx] = escrita
    prev_frame_buf = [state['frame'].copy()]  # frame de 1 iteracao atras, pra detectar movimento

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
            elif event.type == pygame.KEYDOWN:
                # atalhos da aba Visuals: tecla -> shader ou -> midia, SO do set ativo
                # (SHADER_KEYS[SHADER_SET] / MEDIA_KEYS[MEDIA_SET]). dash_server.set_shader /
                # set_input escrevem tuning.py E ja patcham o modulo tuning (mesmo objeto) — o
                # hot-reload do shader abaixo e o video_thread pegam a mudanca no proximo frame.
                kname = pygame.key.name(event.key)
                smap = getattr(tuning, 'SHADER_KEYS', {}).get(getattr(tuning, 'SHADER_SET', 'default'), {})
                mmap = getattr(tuning, 'MEDIA_KEYS', {}).get(getattr(tuning, 'MEDIA_SET', 'default'), {})
                shit = next((s for s, k in smap.items() if k == kname), None)
                mhit = next((n for n, k in mmap.items() if k == kname), None)
                if shit:
                    try:
                        dash_server.set_shader(shit, TUNING_PATH)
                        print(f'tecla {kname!r} -> shader {shit}')
                    except (KeyError, ValueError) as e:
                        print(f'tecla {kname!r}: {e}')
                if mhit:
                    set_input('video', f'media:{mhit}')
                    print(f'tecla {kname!r} -> mídia {mhit}')

        # troca de saida pedida pelo dash (monitor/tela cheia/dimensao, barra "saida" no topo)
        # — reabre a janela e regera vbo/tex/program (contexto GL pode ter sumido -> prog_cache
        # todo invalido, limpa)
        if state['output_req'] != out_cfg:
            out_cfg = dict(state['output_req'])
            (WIN_W, WIN_H, out_pos, out_mode, vbo, tex, tex_prev, tex_a, fbo, fbo_tex,
             sim_vel, sim_density, sim_pressure, sim_vort, sim_div, sim_fbo, fumaca_tex) = open_window(out_cfg)
            program = build_program(frag_src)
            use_program(program)
            sim_progs = build_sim_programs()  # contexto GL novo -> os programas velhos tambem ja eram
            p_fumaca, u_fumaca = build_fumaca_program()
            use_program(program)  # volta pro preset
            prog_cache.clear()
            prog_cache[shader_path] = (frag_mtime, program, frag_src, state.get('fx_manifest', []))
            trans_cache.clear()          # contexto GL novo -> programas de transicao invalidos
            state['transition'] = None   # e o snapshot de A (tex_a) sumiu junto
            state['output'].update(mode=out_mode, window_w=WIN_W, window_h=WIN_H, pos=list(out_pos),
                                    monitor=out_cfg['monitor'], fullscreen=out_cfg['fullscreen'])

        # troca de shader: por CAMINHO (tuning.SHADER, mexido pelo dash/tecla) ou por MTIME
        # (editou o .frag). Cache hit = so glUseProgram, ~0ms; miss = compila e guarda.
        try:
            new_path = resolve_shader_path()
            mtime = os.path.getmtime(new_path)
            if (new_path, mtime) != (shader_path, frag_mtime):
                shader_path, frag_mtime = new_path, mtime
                hit = prog_cache.get(new_path)
                if hit and hit[0] == mtime:
                    _, program, frag_src, manifest = hit
                    state['fx_manifest'] = manifest
                    seed_fx(manifest)
                    use_program(program)
                    state['output']['shader'] = os.path.basename(new_path)
                    state['output']['shader_status'] = 'ok'
                else:
                    with open(new_path) as f:
                        new_src = f.read()
                    try:
                        new_program = build_program(new_src)
                        old = prog_cache.pop(new_path, None)   # versao anterior desse arquivo (editado)
                        if old:
                            glDeleteProgram(old[1])
                        manifest = dash_data.parse_fx_manifest(new_src)
                        prog_cache[new_path] = (mtime, new_program, new_src, manifest)
                        program, frag_src = new_program, new_src
                        state['fx_manifest'] = manifest
                        seed_fx(manifest)
                        use_program(program)  # le state['fx_manifest'] p/ os locs de u_fx_*
                        state['output']['shader'] = os.path.basename(new_path)
                        state['output']['shader_status'] = 'ok'
                        print('shader:', os.path.basename(new_path))
                    except RuntimeError as e:
                        state['output']['shader_status'] = 'erro (mantendo anterior)'
                        print('erro no shader, mantendo o anterior:\n', e)
        except FileNotFoundError:
            pass

        # --- passe de TRANSIÇÃO: se ha uma em andamento, mistura A (tex_a, snapshot) e B (tex,
        # frame vivo) com o .glsl escolhido num FBO -> input_tex. Senao, input_tex = tex (normal).
        tr = state.get('transition')
        input_tex = tex
        if tr:
            if tr['t0'] is None:
                tr['t0'] = time.perf_counter()
                glActiveTexture(GL_TEXTURE1)
                glBindTexture(GL_TEXTURE_2D, tex_a)
                glTexImage2D(GL_TEXTURE_2D, 0, GL_RGB, WIDTH, HEIGHT, 0, GL_RGB, GL_UNSIGNED_BYTE, tr['from'])
            prog_t = trans_program(tr['path'])
            prog = (time.perf_counter() - tr['t0']) / max(0.001, tr['ms'] / 1000.0)
            if prog_t is None or prog >= 1.0:
                state['transition'] = None                # acabou (ou nao compilou) -> corte seco
            else:
                glActiveTexture(GL_TEXTURE0)
                glBindTexture(GL_TEXTURE_2D, tex)         # B = frame vivo
                glTexImage2D(GL_TEXTURE_2D, 0, GL_RGB, WIDTH, HEIGHT, 0, GL_RGB, GL_UNSIGNED_BYTE, state['frame'])
                glActiveTexture(GL_TEXTURE1)
                glBindTexture(GL_TEXTURE_2D, tex_a)       # A = snapshot
                glBindFramebuffer(GL_FRAMEBUFFER, fbo)
                glViewport(0, 0, WIDTH, HEIGHT)
                use_trans_program(prog_t)
                glUniform2f(tuni['res'], WIDTH, HEIGHT)
                glUniform1f(tuni['progress'], min(1.0, max(0.0, prog)))
                glUniform1i(tuni['to'], 0)
                glUniform1i(tuni['from'], 1)
                glClear(GL_COLOR_BUFFER_BIT)
                glDrawArrays(GL_TRIANGLES, 0, 3)
                glBindFramebuffer(GL_FRAMEBUFFER, 0)
                glViewport(0, 0, WIN_W, WIN_H)
                use_program(program)                     # volta pro preset
                input_tex = fbo_tex

        glActiveTexture(GL_TEXTURE0)
        glBindTexture(GL_TEXTURE_2D, input_tex)
        if input_tex == tex:                              # sem transicao: sobe o frame vivo
            glTexImage2D(GL_TEXTURE_2D, 0, GL_RGB, WIDTH, HEIGHT, 0, GL_RGB, GL_UNSIGNED_BYTE, state['frame'])

        # --- passe da FUMACA (Stable Fluids — ver SIM_*_SRC / Caos.frag EFEITO 6): 7 sub-passes
        # numa grade menor (SIM_W x SIM_H). Roda sempre, mesmo se o preset ativo nao usar
        # u_texture_smoke — a grade e' pequena, e' barato.
        glActiveTexture(GL_TEXTURE2)
        glBindTexture(GL_TEXTURE_2D, tex_prev)
        glTexImage2D(GL_TEXTURE_2D, 0, GL_RGB, WIDTH, HEIGHT, 0, GL_RGB, GL_UNSIGNED_BYTE, prev_frame_buf[0])

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
        glViewport(0, 0, WIN_W, WIN_H)
        use_program(program)
        glActiveTexture(GL_TEXTURE0)
        glBindTexture(GL_TEXTURE_2D, input_tex)  # restaura o input do preset (pode ser o fbo_tex da transicao)
        glActiveTexture(GL_TEXTURE3)
        glBindTexture(GL_TEXTURE_2D, dw)         # silhueta (sim de fluido) deste frame -> u_texture_smoke
        glActiveTexture(GL_TEXTURE4)
        glBindTexture(GL_TEXTURE_2D, fw)         # fumaca (procedural) deste frame -> u_texture_fumaca
        prev_frame_buf[0] = state['frame'].copy()
        sim_idx = 1 - sim_idx      # o resultado (vw/dw, fisicamente no slot 1-sim_idx) vira o "atual" no proximo frame
        fumaca_idx = 1 - fumaca_idx

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
        for n, loc in uniforms['fx'].items():
            glUniform1f(loc, state['fx'].get(n, 1.0))

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


def _selfcheck():
    """Sem GL: so o cache de imagem parada. Precisa do ffmpeg (dep do app de qualquer jeito)."""
    import tempfile
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
    for k, val in _keep.items():
        setattr(tuning, k, val) if val is not None else delattr(tuning, k)
    MEDIA_DIR = _md0
    print('native_synth pool self-check ok')

    # --- transicoes: harness, // ms:, e resolucao (item -> default -> none -> arquivo sumido) ---
    w = _wrap_transition('vec4 transition(vec2 uv){ return getToColor(uv); }')
    assert 'getFromColor' in w and 'getToColor' in w and 'void main' in w, w
    global TRANS_DIR
    _td0, TRANS_DIR = TRANS_DIR, tempfile.mkdtemp()
    open(os.path.join(TRANS_DIR, 'fade.glsl'), 'w').write('// ms: 250\nvec4 transition(vec2 uv){return vec4(0.0);}\n')
    assert _transition_ms(os.path.join(TRANS_DIR, 'fade.glsl')) == 250
    _tk = {k: getattr(tuning, k, None) for k in ('MEDIA', 'MEDIA_SET', 'TRANSITION_DEFAULT')}
    tuning.MEDIA = [{'name': 'v', 'file': 'default/v.mp4', 'kind': 'video', 'transition': 'fade.glsl'},
                   {'name': 'w', 'file': 'default/w.mp4', 'kind': 'video', 'transition': ''},
                   {'name': 'z', 'file': 'default/z.mp4', 'kind': 'video', 'transition': 'none'}]
    tuning.MEDIA_SET, tuning.TRANSITION_DEFAULT = 'default', 'fade.glsl'
    assert _resolve_transition({'mode': 'media', 'name': 'v'})[1] == 250            # item aponta
    assert _resolve_transition({'mode': 'media', 'name': 'w'})[1] == 250            # "" -> default
    assert _resolve_transition({'mode': 'media', 'name': 'z'}) == (None, 0)         # "none" -> seco
    tuning.TRANSITION_DEFAULT = 'sumiu.glsl'
    assert _resolve_transition({'mode': 'media', 'name': 'w'}) == (None, 0)         # arquivo sumido
    assert _resolve_transition({'mode': 'webcam'}) == (None, 0)                     # nao-midia
    for k, val in _tk.items():
        setattr(tuning, k, val) if val is not None else delattr(tuning, k)
    TRANS_DIR = _td0
    print('native_synth transitions self-check ok')


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
