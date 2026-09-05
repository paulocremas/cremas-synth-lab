# synth — GLSL puro & SuperCollider, da base

## Objetivo
Aprender síntese de sinal de baixo nível em dois domínios com o mesmo vocabulário
(oscilador, frequência, fase, ruído, filtro, feedback):

- **SuperCollider** (`sclang`/`scsynth`) — síntese de áudio; sinal = onda sonora (amplitude × tempo).
- **GLSL puro** — síntese de imagem na GPU; sinal = onda de cor/luz (valor × posição de pixel, por frame).

Entender cada ferramenta isolada primeiro, comparar onde o vocabulário se repete, só depois compor
(visual reagindo a áudio, ou os dois lado a lado).

## Estado do ambiente (2026-09-04)
- **SuperCollider** 3.13.0 (`sclang` + `scsynth`), sem SuperDirt/Tidal — synth cru.
- **GLSL**: VS Code `circledev.glsl-canvas` (preview WebGL, uniforms `u_time`/`u_resolution`/`u_mouse`,
  modelo Shadertoy) + `slevesque.shader`. `check.frag` = smoke-test do pipeline.
- **`native_synth.py`** (Python + PyOpenGL): captura webcam/tela (`ffmpeg`) + áudio do sistema
  (`parec`/PulseAudio), faz FFT do áudio (bass/mid/treble + 8 faixas Sub-bass…Air + kick) e
  alimenta `image.frag` via uniforms em tempo real. Threads de captura reiniciáveis ao vivo
  (troca de fonte pelo dashboard); a janela de saída também (ver "saída de vídeo" abaixo).
- **Canais por instrumento**: `tuning.CHANNELS` — lista de tamanho livre (até 8, add/remove
  pelo dash, sem pré-definir). Paralelo às 8 faixas de frequência, não as substitui. Cada canal
  pode ter uma source do PulseAudio (stem isolado) e uma "saída" — uma variável existente
  (kick/amp/bass/mid/treble/uma das 8 faixas) que ele passa a alimentar enquanto a source
  estiver ligada; sem source, a variável original (FFT do mix) segue intocada. Detalhe técnico
  completo (uniforms, endpoints): [fluxo técnico navegável](https://paulocremas.github.io/cremas-synth-lab/#uniforms).
- **Saída de vídeo ao vivo**: monitor / dimensão / tela cheia mudam pela barra "saída" no topo
  do dash, sem reiniciar o processo — não é mais só via `--monitor`/`--fullscreen` na CLI
  (que continuam valendo como valor inicial). Lembra o tamanho de antes do fullscreen.
- **Dashboard HTML** (substituiu os dashes de terminal): `dash_server.py` (HTTP+SSE stdlib) +
  `dash_data.py` (funções puras) + `dash.html`. Abre 1 aba só ("PRISMA!"), com tabs "Source Audio" /
  "Source Image" / "Output Image" / "Output Lights" no header (troca a seção visível; as duas
  últimas ainda placeholder); shift+click numa tab abre ela em janela própria
  (`?panel=audio` / `?panel=image`), sincronizadas ao vivo. Regula tudo ao vivo, grava em `tuning.py`: knobs,
  ranges das 8 faixas (com toggle `BANDS_ENABLED` e overlap), canais, fonte de áudio/vídeo,
  saída de vídeo. Sincronização entre abas/janelas usa um guard por TEMPO (`TOUCH_MS` em
  `dash.html`), não por foco — foco sozinho não prova edição em andamento (um `<select>` pode
  ficar focado bem depois do dropdown fechar); se algum campo parecer "travado" sem atualizar,
  é esse o mecanismo a olhar.
- **Hot-reload por mtime** (edita/salva/aplica, sem restart): `image.frag`, `tuning.py`,
  `dash_server.py`, `dash_data.py`, `dash.html`. Só o `native_synth.py` em si precisa de restart
  (`watch_synth.sh` faz automático).
- Arquivos e os dois fluxos (técnico / macro): [README.md](README.md).
- **Fluxo técnico navegável**: <https://paulocremas.github.io/cremas-synth-lab/> — fonte `docs/index.html`.
  Ao editar esse arquivo, respeitar os sistemas já montados (cada um tem comentário no próprio HTML):
  glossário `GLOSS` fonte-da-verdade + `linkify` automático; cores por região + linhagem de dado;
  possibilidades em `<details>` retraído; eixo status (`.maybe` cinza) separado da cor de região.
  O bloco "Visualização" do diagrama agora é o **Dashboard** (HTTP, bidirecional — lê o `state` e
  grava no `tuning.py`), não mais terminal/somente-leitura.

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
