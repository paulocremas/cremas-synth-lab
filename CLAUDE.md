# synth — GLSL puro & SuperCollider, da base

## Objetivo
Aprender síntese de sinal de baixo nível em dois domínios com o mesmo vocabulário
(oscilador, frequência, fase, ruído, filtro, feedback):

- **SuperCollider** (`sclang`/`scsynth`) — síntese de áudio; sinal = onda sonora (amplitude × tempo).
- **GLSL puro** — síntese de imagem na GPU; sinal = onda de cor/luz (valor × posição de pixel, por frame).

Entender cada ferramenta isolada primeiro, comparar onde o vocabulário se repete, só depois compor
(visual reagindo a áudio, ou os dois lado a lado).

## Estado do ambiente (2026-09-09)
- **SuperCollider** 3.13.0 (`sclang` + `scsynth`), sem SuperDirt/Tidal — synth cru.
- **GLSL**: VS Code `circledev.glsl-canvas` (preview WebGL, uniforms `u_time`/`u_resolution`/`u_mouse`,
  modelo Shadertoy) + `slevesque.shader`. `shaders/check.frag` = smoke-test do pipeline.
- **`src/native_synth.py`** (Python + PyOpenGL): captura webcam/tela (`ffmpeg`) + áudio do sistema
  (`parec`/PulseAudio), faz FFT do áudio (bass/mid/treble + 8 faixas Sub-bass…Air + kick) e
  alimenta `shaders/image.frag` via uniforms em tempo real. Threads de captura reiniciáveis ao vivo
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
- **Layout dos arquivos**: `src/` = os 4 módulos Python (`native_synth.py`, `dash_server.py`,
  `dash_data.py`, `tuning.py`); `shaders/` = `image.frag` (base) + `check.frag` (fora do pipeline)
  + `presets/<set>/*.frag`; `media/` = `<set>/*` (imagens/vídeos, gitignored); `dash.html`,
  `favicon.png`, `docs/`, `watch_synth.sh` na raiz. `native_synth.py` resolve `../shaders/`,
  `../media/` e `../dash.html` por caminho relativo ao próprio arquivo — roda de qualquer cwd.
- **Aba "Visuals"** (era "Effects") — seções: galeria de **mídia**, galeria de **transições**,
  galeria de **shaders**, potenciômetros de **fx**. Mídia e shaders têm no topo uma **barra de
  set**: `<select>` + `+ set` + `🗑 set` (transições ainda não têm sets).
  - **Mídia** = imagens/vídeos locais que viram o **input de imagem** no lugar da webcam/tela
    (vídeo em loop, `ffmpeg -loop 1` / `-stream_loop -1`). Entram como `mode:'media'` em
    `state['video']`; no dropdown de imagem do topo do dash são **uma** fonte só, "Media" (qual
    item toca sai da aba / de uma tecla, não do dropdown). Por item: um upload (`+ imagem ou
    vídeo`, kind pela extensão), checkbox **preencher/encaixar** (`fit` `fill`|`fit`), engrenagem
    renomear/excluir/tecla. `fit`/`fill` é **ciente do aspecto da janela**: `_probe_dims` (ffprobe,
    cacheado) + `_fit_vf` pré-distorcem o `-vf` do ffmpeg pra que, depois do shader esticar a
    textura 640×480 pra `WIN_W×WIN_H`, a imagem fique sem distorção (barras no eixo curto / corte
    no longo). `video_thread` respawna a mídia quando a janela muda de tamanho.
    **Rebate** (só vídeo, checkbox por item → `"bounce": 1` no item de `MEDIA`; `1`, não `True`,
    porque o bloco é escrito via `json.dumps`): ida inteira + volta inteira em loop, desacelerando
    perto de cada virada (`BOUNCE_RAMP_S`/`BOUNCE_SLOW` no topo do bloco de rebate em
    `native_synth.py`). Pré-renderizado 1x pelo ffmpeg (`reverse` + `setpts` com rampa +
    `framerate` blend) em `~/.cache/prisma/bounce/` — o resto do pipeline toca esse arquivo sem
    saber. Enquanto renderiza, toca o original (`state['bounce_busy']` → "preparando…" no dash) e
    troca sozinho quando fica pronto. Teto `BOUNCE_MAX_S` (o `reverse` segura o clipe na RAM).
    **Camadas (overlay)**: checkbox "camada" + slider de opacidade por item. Marcar empilha POR
    CIMA das já marcadas (ordem de seleção; número = posição, 1 = embaixo). Vivo em
    `state['overlays']` (`[{file, opacity}]`, POST `/overlays`, arrasto = `save:false`), gravado
    em `tuning.OVERLAYS` ao soltar/marcar (bloco acrescentado se o `tuning.py` não tiver).
    `_composite` mistura por cima da fonte atual no loop GL (uint16, ~2 ms/camada) →
    `state['frame_comp']`, que é o que sobe pro shader, entra na transição e na análise de imagem.
    Frame de cada camada: vídeo = entrada do `_pool` ou um ffmpeg próprio em `_ovl`; imagem =
    `_still_cache`. Só camadas do set ativo; renomear/apagar mídia atualiza a lista. Sem alpha
    (PNG transparente vira opaco — o pipeline é rgb24).
    **Troca rápida**: imagem parada decodifica 1x pro `_still_cache` (troca = swap de ponteiro,
    sem ffmpeg rodando à toa; `prewarm_stills` aquece tudo no start). Vídeo: `tuning.VIDEO_POOL`
    mantém um `ffmpeg -re` por vídeo do set ativo numa thread (`_pool_reader`) → troca entre
    vídeos ~0ms (custo: N decodes simultâneos; `VIDEO_POOL_MAX` limita, `=0` desliga). Fora do
    pool, a troca sobe o ffmpeg novo e só mata o antigo quando o novo entrega o 1º frame
    (`_await_first`) — sem piscar preto.
  - **Transições** = `transitions/*.glsl` (estilo gl-transitions: uma `vec4 transition(vec2 uv)`
    com `getFromColor`/`getToColor`/`progress`; cabeçalho `// ms: N` = duração). Cada item de
    `MEDIA` tem `transition`: `""` usa `tuning.TRANSITION_DEFAULT`, `"none"` = corte seco,
    `"<arquivo>.glsl"`. Na troca de mídia o `video_thread` põe `state['transition']`
    (`{path, ms, from`=frame A`, t0}`) e o loop GL roda um **passe FBO** (`_wrap_transition`
    embrulha o arquivo num harness; `trans_program` compila/cacheia por mtime) que mistura A
    (`tex_a`, snapshot) e B (`tex`, frame vivo) em `fbo_tex` → esse texture vira o `u_texture_0`
    do preset (o preset nem sabe). Termina quando `progress ≥ 1` → volta a ler `tex` direto.
    Galeria enxuta: **sem sets nem teclas** (mirror do código de shader se um dia precisar).
    Endpoints: GET `/transitions`, POST `/transition-default` `/new-transition`
    `/rename-transition` `/delete-transition`. Hot-reload do `.glsl` = re-checado no início de
    cada transição (não por frame como o preset).
  - **Shaders** = `.frag`. "+ criar .frag" gera um template mínimo em `presets/<set>/` e o ativa.
    Cabeçalho `// fx: n1, n2, …` → `dash_data.parse_fx_manifest` → `u_fx_<nome>` (0..1) + slider;
    nível vivo em `state['fx']`, gravado em `tuning.FX`. MIDI ainda **não** ligado: `state['fx']`
    é onde um `midi_thread` (pygame.midi) escreveria — ver `<details id="midi-maybe">` em `docs/`.
- **SETS (galerias de mídia e shader) = subpastas de verdade**, `default` incluso:
  `shaders/presets/<set>/*.frag`, `media/<set>/*` — `presets/default/` e `media/default/` são
  pastas normais; `default` é só o **fallback** (sempre existe, não some). A lista de sets vem
  **do disco**. `tuning.SHADER_SET`/`MEDIA_SET` = set ativo (a galeria mostra só ele). `SHADER`
  = `image.frag` ou `presets/<set>/x.frag`; `MEDIA[i].file` = sempre `<set>/x.png` (o set sai do
  caminho). `SHADER_KEYS`/`MEDIA_KEYS` = `{set: {alvo: tecla}}`, valem só no set ativo (mapa
  flat antigo migra pra `{"default": …}`). Apagar um set **nomeado** funde os arquivos no
  `default` e apaga a pasta; apagar o **`default`** o **esvazia** e recria vazio. Endpoints
  `/shader-set[-new|-del]`, `/media-set[-new|-del]`. (`_migrate_default_to_folder` já rodou uma
  vez no start pra mover os arquivos que eram soltos em `presets/`/`media/`.)
- **Atalhos** (`SHADER_KEYS[SHADER_SET]` / `MEDIA_KEYS[MEDIA_SET]`): a tecla troca pro alvo —
  **na janela OpenGL do native_synth** OU em qualquer parte do dash (listener global, ignora foco
  em campo de texto). `dash_server` grava `tuning.py` **e** patcha o módulo `tuning` na hora
  (mesmo objeto que o native segura) → troca no próximo frame, sem esperar o reload por mtime.
  Shader já usado volta instantâneo (cache de programa GL por arquivo no main loop).
  Endpoints da galeria de shaders: `POST /shader` `/new-shader` `/rename-shader` `/delete-shader`
  `/shader-key`; da mídia: `POST /media` (reescreve os itens do set ativo, casa por `file`),
  `/media-add` (body = bytes, `?name=`), `/media-del`, `/media-key`; de transições:
  `GET /transitions`, `POST /transition-default` `/new-transition` `/rename-transition` `/delete-transition`.
- **Dashboard HTML** (substituiu os dashes de terminal): `dash_server.py` (HTTP+SSE stdlib) +
  `dash_data.py` (funções puras) + `dash.html`. Abre 1 aba só ("PRISMA!"), com tabs "Source Audio" /
  "Source Image" / "Visuals" / "Output Image" / "Output Lights" no header (troca a seção visível; as
  duas últimas ainda placeholder); shift+click numa tab abre ela em janela própria
  (`?panel=audio` / `?panel=image`), sincronizadas ao vivo. Regula tudo ao vivo, grava em `tuning.py`: knobs,
  ranges das 8 faixas (com toggle `BANDS_ENABLED` e overlap), canais, shader ativo (`SHADER`) +
  potenciômetros de efeito (`FX`), galerias de mídia/transição/shader, fonte de áudio/vídeo,
  saída de vídeo. Sincronização entre abas/janelas usa um guard por TEMPO (`TOUCH_MS` em
  `dash.html`), não por foco — foco sozinho não prova edição em andamento (um `<select>` pode
  ficar focado bem depois do dropdown fechar); se algum campo parecer "travado" sem atualizar,
  é esse o mecanismo a olhar.
- **Hot-reload por mtime** (edita/salva/aplica, sem restart): `shaders/image.frag` /
  `shaders/presets/<set>/*.frag` (o loop segue o `mtime` **e** o caminho de `tuning.SHADER`),
  `transitions/*.glsl` (re-checado no início de cada transição), `src/tuning.py`,
  `src/dash_server.py`, `src/dash_data.py`, `dash.html`. Só o `src/native_synth.py` em si
  precisa de restart (`watch_synth.sh` faz automático).
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
