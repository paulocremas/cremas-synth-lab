# synth — GLSL puro & SuperCollider, da base

## Objetivo
Aprender síntese de sinal de baixo nível em dois domínios com o mesmo vocabulário
(oscilador, frequência, fase, ruído, filtro, feedback): **SuperCollider** (áudio: amplitude × tempo)
e **GLSL puro** (imagem na GPU: cor × posição de pixel, por frame). Cada ferramenta isolada
primeiro, depois comparar, só então compor.

## Estado do ambiente (2026-09-25)
- **SuperCollider** 3.13.0 cru (sem SuperDirt/Tidal). **GLSL**: VS Code `circledev.glsl-canvas`
  (modelo Shadertoy) + `slevesque.shader`; `shaders/check.frag` = smoke-test.
- **`src/native_synth.py`** (PyOpenGL): fontes de imagem (câmera/tela/mídia via `ffmpeg`) + áudio
  (`parec`, FFT → bass/mid/treble, 8 faixas, kick) → pilha de shaders por fonte → janela de saída.
  `dash_server.py` (HTTP+SSE stdlib) + `dash_data.py` (funções puras) + `dash.html` (v1, `/`) e
  `dash2.html` (v2 ao vivo, `/v2`). Arquivos e fluxos: [README.md](README.md).
- **App empacotado (`prisma`)**: `dist/prisma/prisma` roda uma **cópia** em `~/.local/share/prisma/`
  (dados reais do usuário: `tuning.py`, shaders, transições, mídia). Mudou código → copiar
  `src/native_synth.py`, `dash_server.py`, `dash_data.py`, `dash.html`, `dash2.html` (e shader
  interno tipo `calibrar.frag`) pra `dist/prisma/` **e** `~/.local/share/prisma/` (o launcher
  recopia de `dist/` a cada abertura; `dash2.html` só entra sozinho após rebuild). Config ao vivo =
  `~/.local/share/prisma/src/tuning.py`.
- **Hot-reload por mtime**: `.frag`, `transitions/*.glsl`, `tuning.py`, `dash_server.py`,
  `dash_data.py`, `dash*.html` (`html_mtime`/`html2_mtime`). **`native_synth.py` só reabrindo.**

## Armadilhas / convenções
- `dash_server` grava o `tuning.py` via `_write_atomic` **e** patcha o módulo `tuning` na hora (mesmo
  objeto do native). O reload por mtime do native roda no loop de áudio, que pode ficar parado —
  setter novo tem que patchar o módulo, senão o dash "volta pro lugar".
- `None` nunca vai pro `tuning.py` (`_scene_with` tira o campo); flags são `1`, não `True` (blocos
  saem via `json.dumps`).
- Sincronização entre abas = guard por TEMPO (`TOUCH_MS`), não por foco. Campo "travado" → olhar isso.
- Testes que gravam no `tuning.py` usam arquivo temporário (`tuning_path` / `_cfg['tuning_path']`).
- Set (scene) ativo **é** o estado vivo e auto-salva (`save_active_scene`); trocar = `request_scene`
  → loop GL aplica no fim do frame (`apply_scene`, `_applying`) + transição de entrada.
- Seleção (`/select`) não mexe na saída: fonte viva tem ffmpeg próprio em `_ovl`; v4l2 é exclusivo,
  por isso o `video_thread` copia de lá (`_feed`).
- Canal `file#N` = mesma fonte 2× (`_chkey`/`_base_key`); pilha por canal em `BINDINGS`, endereçada
  pela POSIÇÃO. Fora do `pool` some da mesa/saída mas fica lembrado.
- 60 fps (`tuning.OUTPUT_FPS`): textura por fonte (`src_tex`) e mistura CPU (`comp_last`) só refazem
  quando o frame é OUTRO objeto — comparar por `is`, guardando o próprio frame.
- Calibração (`calibrar.frag`, `OUTPUT_GRADE`) é o último passe; `master` → `u_dim` (0 = neutro,
  vale com a calibração desligada). O `from` da transição é guardado antes dela.
- Prévias do dash v2: `GET /frame?which=out|sel|comp|src` (rgb24 cru, `_preview_frame`); saída lida
  pequena por blit (`out_pv`, só enquanto pedida — `out_want`). Áudio: vigia `PAREC_STALL_S`.
- Dash v2: decisões no comentário do topo do `dash2.html` (modo Palco `.ed`, `knob()`/`fader()`,
  MIDI `CTRL[id]`, costura das faixas `seamOf`/`moveSeam`, `METERS` a 60 fps). localStorage
  `mixKeys`/`fxPick` é compartilhado com a v1.

## Testes
`.venv/bin/python src/dash_server.py` e `.venv/bin/python src/native_synth.py --selfcheck` (venv).

## Docs
- Fluxo técnico navegável: <https://paulocremas.github.io/cremas-synth-lab/> (`docs/index.html`).
  Respeitar os sistemas do arquivo: glossário `GLOSS` + `linkify`, cores por região + linhagem,
  possibilidades em `<details>` retraído, status `.maybe` separado da cor.
- [MAPA.md](MAPA.md) = índice comentado dos currículos (material de estudo).

## Vocabulário compartilhado (onda / sinal)

| Conceito | SuperCollider | GLSL |
|---|---|---|
| Oscilador | `SinOsc`, `Saw`, `Pulse` | `sin()`/`fract()` numa shaping function |
| Frequência | `.freq` do UGen | quantas repetições do padrão cabem na tela |
| Fase | `.phase` | offset dentro do `sin()`/`fract()` |
| Amplitude | `.mul`, envelope (`EnvGen`) | brilho/intensidade da cor |
| Ruído | `LFNoise`, `WhiteNoise` | `random()`, Perlin `noise()` |
| Filtro | `LPF`/`HPF`/`RLPF` | blur, kernel convolution |
| Feedback | `LocalIn`/`LocalOut`, delay | pingpong buffer, reaction-diffusion |
| Taxa de amostragem | sample rate (44.1kHz, no tempo) | resolução/frame rate (no espaço) |

## Plano de estudo
Fontes: [The Book of Shaders](https://thebookofshaders.com/) ·
[tutoriais Fieldsteel](https://github.com/elifieldsteel/SuperCollider-Tutorials).

| Fase | SuperCollider | GLSL (Book of Shaders) |
|---|---|---|
| 0 · navegação | tutoriais 1–5 | cap. 00–08 |
| 1 · oscilador / frequência / fase | `SinOsc` | cap. 05 (shaping functions) |
| 1 · ruído | `LFNoise` / `WhiteNoise` | cap. 10–11 |
| 1 · padrões | tutorial 10 (Pbind/Pseq/Prand) | cap. 09 (`fract()`) |
| 1 · filtro | `LPF` / `HPF` / `RLPF` | cap. 17–18 |
| 1 · feedback | tutorial 20 (`LocalIn`/`LocalOut`) | fora do livro; ver Fase 3 |
| 2 · avançado | 21–23, 25–26 (FM, wavetable, granular) | cap. 13–14 (fBm, fractals) |
| 3 · fusão | RMS → OSC → uniform | uniform de áudio movendo o shader |

Fase 3 já implementada fora de ordem no `native_synth.py` (`parec`/numpy no lugar de SC→OSC);
SC→OSC→shader segue como comparação. Primeiro exercício: `{SinOsc.ar(440, 0, 0.2)}.play;` vs.
`gl_FragColor = vec4(vec3(sin(u_time * 4.0) * 0.5 + 0.5), 1.0);` no `check.frag`.
