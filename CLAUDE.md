# synth — GLSL puro & SuperCollider, da base

## Objetivo
Aprender síntese de sinal de baixo nível em dois domínios com o mesmo vocabulário
(oscilador, frequência, fase, ruído, filtro, feedback):

- **SuperCollider** (`sclang`/`scsynth`) — síntese de áudio; sinal = onda sonora (amplitude × tempo).
- **GLSL puro** — síntese de imagem na GPU; sinal = onda de cor/luz (valor × posição de pixel, por frame).

Entender cada ferramenta isolada primeiro, comparar onde o vocabulário se repete, só depois compor
(visual reagindo a áudio, ou os dois lado a lado).

## Estado do ambiente (2026-08-29)
- **SuperCollider** 3.13.0 (`sclang` + `scsynth`), sem SuperDirt/Tidal — synth cru.
- **GLSL**: VS Code `circledev.glsl-canvas` (preview WebGL, uniforms `u_time`/`u_resolution`/`u_mouse`,
  modelo Shadertoy) + `slevesque.shader`. `check.frag` = smoke-test do pipeline.
- **`native_synth.py`** (Python + PyOpenGL, sem navegador): captura webcam/tela (`ffmpeg`) + áudio do
  sistema (`parec`/PulseAudio), faz FFT do áudio (bass/mid/treble + 8 faixas Sub-bass…Air + kick) e
  alimenta `image.frag` via uniforms em tempo real. `tuning.py` = constantes de calibração com
  hot-reload por mtime (edita, salva, aplica na hora). Também roda análise de imagem do frame de
  entrada (brilho, cor dominante, saturação, nitidez, bordas, movimento…) num dashboard
  `gnome-terminal` à parte.
- Arquivos e os dois fluxos (técnico / macro): [README.md](README.md).
- **Fluxo técnico navegável**: <https://paulocremas.github.io/cremas-synth-lab/> — fonte `docs/index.html`.
  Ao editar esse arquivo, respeitar os sistemas já montados (cada um tem comentário no próprio HTML):
  glossário `GLOSS` fonte-da-verdade + `linkify` automático; cores por região + linhagem de dado;
  possibilidades em `<details>` retraído; eixo status (`.maybe` cinza) separado da cor de região.

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

Currículos-fonte: [The Book of Shaders](https://thebookofshaders.com/) ·
[tutoriais Fieldsteel](https://github.com/elifieldsteel/SuperCollider-Tutorials).
Índice comentado de cada capítulo/tutorial (o que ensina de fato): [MAPA.md](MAPA.md).

| Fase | SuperCollider | GLSL (Book of Shaders) |
|---|---|---|
| 0 · navegação da ferramenta | tutoriais 1–5 | cap. 00–08 |
| 1 · oscilador / frequência / fase | `SinOsc` básico | cap. 05 (shaping functions) |
| 1 · ruído | `LFNoise` / `WhiteNoise` | cap. 10–11 (random, noise) |
| 1 · padrões / repetição | tutorial 10 (Pbind/Pseq/Prand) | cap. 09 (`fract()`/módulo) |
| 1 · filtro | `LPF` / `HPF` / `RLPF` | cap. 17–18 (kernel convolution, filters) |
| 1 · feedback | tutorial 20 (`LocalIn`/`LocalOut`, live input) | — fora do livro; ver Fase 3 |
| 2 · avançado (isolado) | 21–23, 25–26 (FM, wavetable, granular) | cap. 13–14 (fBm, fractals) |
| 3 · fusão | RMS/amplitude → OSC → uniform | uniform de áudio movendo o shader |

**Fase 3 já implementada fora de ordem** em `native_synth.py` (com `parec`/numpy no lugar de
SC→OSC). O caminho SC→OSC→shader continua de pé como comparação de abordagem.

## Primeiro exercício (Fase 1, oscilador)
- SC — ouvir uma frequência: `{SinOsc.ar(440, 0, 0.2)}.play;`
- GLSL — ver uma frequência (em `check.frag`): `gl_FragColor = vec4(vec3(sin(u_time * 4.0) * 0.5 + 0.5), 1.0);`
- Comparar o que "frequência" significa em cada um: ciclos por segundo no ouvido vs. na tela.
