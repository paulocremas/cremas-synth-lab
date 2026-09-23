# synth — GLSL puro & SuperCollider, da base

## Objetivo
Aprender síntese de sinal de baixo nível em dois domínios com o mesmo vocabulário
(oscilador, frequência, fase, ruído, filtro, feedback):

- **SuperCollider** (`sclang`/`scsynth`) — síntese de áudio; sinal = onda sonora (amplitude × tempo).
- **GLSL puro** — síntese de imagem na GPU; sinal = onda de cor/luz (valor × posição de pixel, por frame).

Entender cada ferramenta isolada primeiro, comparar onde o vocabulário se repete, só depois compor
(visual reagindo a áudio, ou os dois lado a lado).

## Estado do ambiente (2026-09-23)
- **SuperCollider** 3.13.0 (`sclang` + `scsynth`), sem SuperDirt/Tidal — synth cru.
- **GLSL**: VS Code `circledev.glsl-canvas` (preview WebGL, uniforms `u_time`/`u_resolution`/`u_mouse`,
  modelo Shadertoy) + `slevesque.shader`. `shaders/check.frag` = smoke-test do pipeline.
- **`src/native_synth.py`** (Python + PyOpenGL): captura câmeras/telas/mídias (`ffmpeg`) + áudio do
  sistema (`parec`/PulseAudio), faz FFT do áudio (bass/mid/treble + 8 faixas Sub-bass…Air + kick)
  e passa cada fonte de imagem marcada pela sua pilha de shaders, em tempo real. Threads de
  captura e janela de saída reiniciáveis ao vivo pelo dashboard.
- **Layout**: `src/` = `native_synth.py`, `dash_server.py`, `dash_data.py`, `tuning.py`;
  `shaders/` = `image.frag` + `presets/default/*.frag` (+ `check.frag`, fora do pipeline);
  `media/default/*` (gitignored); `transitions/*.glsl`; `dash.html`, `favicon.png`, `docs/`,
  `watch_synth.sh`, `packaging/` na raiz. Caminhos resolvidos relativos ao próprio `.py`.
- **App empacotado (`prisma`)**: o usuário costuma rodar `dist/prisma/prisma`, que executa uma
  **cópia** em `~/.local/share/prisma/` (o launcher recopia o código de `dist/prisma/` a cada
  abertura; `tuning.py`, shaders, transições e mídia de lá são os dados reais dele). Mudou código
  no repo → copiar `src/native_synth.py`, `dash_server.py`, `dash_data.py` e `dash.html` pra
  `dist/prisma/` **e** `~/.local/share/prisma/`; dash/servidor recarregam sozinhos, o native só
  reabrindo o prisma. Config ao vivo = `~/.local/share/prisma/src/tuning.py`, não a do repo.
- **Canais por instrumento**: `tuning.CHANNELS` — lista livre (até 8). Cada canal pode ter uma
  source do PulseAudio (stem isolado) e uma "saída" — uma variável existente (kick/amp/bass/mid/
  treble/uma das 8 faixas) que ele passa a alimentar enquanto a source estiver ligada.
- **Saída de vídeo ao vivo**: monitor / dimensão / tela cheia pela barra "saída" no topo do dash,
  sem reiniciar (`--monitor`/`--fullscreen` na CLI = valor inicial). Lembra o tamanho de antes do
  fullscreen.
- **Aba "Visuals"** — sub-abas **Sets** e **Biblioteca** (`showSub`, `?sub=sets|lib`):
  - **Set** = cena: `tuning.SCENES` `[{name, key, transition, selected, sources, bindings, pool?}]`
    + `tuning.SCENE` (ativo). O set ativo **é** o estado vivo e **auto-salva**: todo POST que o
    muda chama `dash_server.save_active_scene()`. `+ set` copia o estado atual. Set em formato
    antigo é convertido na leitura (`_upgrade_scene`). `None` nunca vai pro `tuning.py`
    (`_scene_with` tira o campo; `json.dumps` escreveria `null`).
  - **Saída = só o que está marcado**: `OVERLAYS` `[{file, opacity}]` (`sources` do set; `file` =
    arquivo de mídia ou `webcam:/dev/videoN` | `screen:<monitor>`; ordem = de baixo pra cima).
  - **Pilha por fonte**: `BINDINGS` `{fonte: {shaders: [{file, opacity, blend?}], fx: {shader:
    {nome: 0..1}}}}`, lembrada mesmo com a fonte desmarcada. `blend` ∈ `dash_server.LAYER_BLENDS`
    (normal/soma/tela/multiplicar/clarear). Código do `.frag` é compartilhado; opacidade/modo/forças
    são por fonte.
  - **Seleção** (clique no nome, POST `/select`): só escolhe qual pilha a lista "Efeitos de X"
    edita; também vira a fonte capturada pelo `video_thread` (`state['frame']`) e analisada na aba
    Source Image. Clique num shader = qual aparece em "Força dos efeitos" (manifests `// fx:` via
    `GET /shaders`).
  - **Disponíveis por set** (`pool` = `{sources?, shaders?}`, ausente = tudo, POST `/pool`): fora
    do pool some do editor e da saída, mas `OVERLAYS`/`BINDINGS` ficam lembrados.
  - **Preencher / rebate** são da fonte, não do set: mídia no item de `MEDIA` (`fit`, `bounce: 1`
    — `1` e não `True`, o bloco sai via `json.dumps`); câmera/tela em `SOURCE_FIT` (`{id: 'fit'}`,
    POST `/source-fit`). `fill` = estica pra cobrir; `fit` = encaixa com margens, ciente do
    aspecto da janela (`_fit_vf`). Rebate = vai-e-volta pré-renderizado em `~/.cache/prisma/bounce/`.
  - **Trocar de set** (clique, tecla na janela OpenGL ou no dash): `request_scene` →
    `state['scene_pending']`; o loop GL, no fim do frame, copia a tela (`glCopyTexSubImage2D` →
    `ltargets['from']`), chama `dash_server.apply_scene` (`_applying` segura o auto-save) e roda a
    transição de ENTRADA do set (`''` = `TRANSITION_DEFAULT`, `'none'` = seco). No start aplica
    `tuning.SCENE` sem transição.
  - **Biblioteca**: mídia (upload/renomear/excluir), `.frag` (criar/renomear/apagar), transições
    (criar/renomear/apagar/padrão). Sem pastas: tudo em `media/default/` e `presets/default/`.
    Renomear/apagar atualiza todos os sets, `BINDINGS` e pools (`_remap_scenes`). Arquivo novo
    entra no pool do set ativo. Código de pasta-set antigo (`MEDIA_SET`/`SHADER_SET`, `*_KEYS`,
    `/shader-set*`, `/media-set*`) ficou fixo em `default`, fora da UI; `SHADER`/`SHADER_LAYERS`/`FX`
    no `tuning.py` também não são mais lidos.
- **Render** (loop GL): `_source_frames()` → pra cada fonte marcada: frame em `tex`
  (`u_texture_0`), cópia crua (`LAYER_BLEND_SRC` com `u_flip` — a textura vem topo→baixo, os
  presets fazem `st.y = 1.0 - st.y`), cada shader da pilha desenha em `layer` (`layer_program`,
  cache por mtime; erro = pulado + `state['output']['shader_status']`) e mistura em `src`; `src`
  entra em `out` com a opacidade da fonte; `out` (começa preto) → tela ou transição. `_composite`
  (CPU) mistura as mesmas fontes só pra fumaça/análise/cor dominante (`state['frame_comp']`).
  Troca rápida de mídia: `_still_cache` (imagem) e `tuning.VIDEO_POOL` (vídeo, `_pool_reader`).
- **Dashboard HTML**: `dash_server.py` (HTTP+SSE stdlib) + `dash_data.py` (funções puras) +
  `dash.html`. 1 aba ("PRISMA!") com tabs Source Audio / Source Image / Visuals / Output Image /
  Output Lights (as duas últimas placeholder); shift+click abre a tab em janela própria
  (`?panel=…`). `dash_server` grava o `tuning.py` **e** patcha o módulo `tuning` na hora (mesmo
  objeto do native) → vale no próximo frame. Sincronização entre abas usa guard por TEMPO
  (`TOUCH_MS`), não por foco — se um campo parecer "travado", é esse o mecanismo a olhar.
- **Hot-reload por mtime** (sem restart): `.frag` (por shader, no loop), `transitions/*.glsl` (a
  cada troca de set), `src/tuning.py`, `src/dash_server.py`, `src/dash_data.py`, `dash.html`. Só o
  `src/native_synth.py` precisa de restart (`watch_synth.sh` faz automático).
- **Testes**: `.venv/bin/python src/dash_server.py` e `.venv/bin/python src/native_synth.py
  --selfcheck` (precisam do venv — numpy). Testes que gravam no `tuning.py` usam arquivo
  temporário e apontam `_cfg['tuning_path']` pra ele (senão setters sem `tuning_path` sujam o real).
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
