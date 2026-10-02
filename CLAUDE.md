# synth — GLSL puro & SuperCollider, da base

## Objetivo
Aprender síntese de sinal de baixo nível com o mesmo vocabulário em dois domínios:
**SuperCollider** (áudio: amplitude × tempo) e **GLSL puro** (imagem: cor × pixel, por frame).
Cada ferramenta isolada, depois comparar, só então compor.

## Ambiente (2026-10-02)
- SuperCollider 3.13.0 cru. GLSL: VS Code `circledev.glsl-canvas` + `slevesque.shader`; `shaders/check.frag` = smoke-test.
- `src/native_synth.py` (PyOpenGL): fontes (câmera/tela/mídia via `ffmpeg`) + áudio (FFT) → pilha de shaders por
  fonte → janela de saída. `dash_server.py` (HTTP+SSE stdlib), `dash_data.py` (puras), `dash.html` (v1, `/`),
  `dash2.html` (v2 ao vivo, `/v2`). Arquivos/fluxos: [README.md](README.md); instalar: [INSTALAR.md](INSTALAR.md).
- **Linux + Windows**: tudo que toca o sistema passa por `src/plat.py` — nunca `xrandr`/`parec`/`select`/`/dev/video`
  direto. Windows só testado no CI (sem GPU: o smoke para no 1º OpenGL); 1º teste real pendente.
- **App `prisma`** (PyInstaller, `packaging/launcher.py`) roda uma CÓPIA na pasta de dados (`~/.local/share/prisma/` |
  `%LOCALAPPDATA%\prisma` | `<pasta>/dados` com `portable.txt`), recopiando `src/*.py` (menos `tuning.py`) e
  `dash*.html` a cada abertura. Quer código novo no app já → copiar pra `dist/prisma/` **e** a pasta de dados
  (`packaging/build.sh` atualiza o launcher velho do `dist/`).
- **Release**: tag `vX.Y.Z` → `.github/workflows/release.yml` (`.deb`, `.exe` `packaging/prisma.iss`, zip portátil);
  tag com `-` = pré. `packaging/updater.py` compara `VERSION` com a última Release. Publicado: `v0.1.0-beta.1`, na
  branch `dashboard-channels-output` (ainda não no `master`).
- Dash = Chromium `--app --kiosk` próprio (`_open_dash_window`; Edge no Windows; `PRISMA_NO_BROWSER=1` nos testes).
  3× Esc (saída ou dash → `POST /quit`) fecha tudo.
- Hot-reload por mtime: `.frag`, `transitions/*.glsl`, `tuning.py`, `dash_server.py`, `dash_data.py`,
  `dash*.html`. **`native_synth.py` e `telao_sim.py` só reabrindo** (dash novo + native velho não combinam).

## Armadilhas / convenções
- Setter do `dash_server` grava o `tuning.py` (`_write_atomic`) **e** patcha o módulo `tuning` na hora — o
  reload por mtime do native roda no loop de áudio, que pode parar; sem patch o dash "volta pro lugar".
- `None` nunca vai pro `tuning.py` (`_scene_with` tira o campo); flags = `1`, não `True` (`json.dumps`).
- Sync entre abas = guard por TEMPO (`TOUCH_MS`), não foco. Campo "travado" → olhar isso.
- Set ativo **é** o estado vivo e auto-salva (`save_active_scene`); troca = `request_scene` → aplicada no fim
  do frame GL (`apply_scene`, `_applying`) + transição.
- `/select` não mexe na saída: fonte viva tem ffmpeg próprio em `_ovl`; v4l2 é exclusivo → `_feed` copia de lá.
- Canal `file#N` = mesma fonte 2× (`_chkey`/`_base_key`); pilha por canal em `BINDINGS`, pela POSIÇÃO.
  Fora do `pool` some da mesa/saída mas fica lembrado.
- 60 fps (`OUTPUT_FPS`): `src_tex`/`comp_last` só refazem se o frame é OUTRO objeto (`is`, guardando o frame).
- Passes: mistura → `SCENE_GRADE` → transição (`from` antes da calibração) → `OUTPUT_GRADE` (`master` →
  `u_dim`); os dois grades usam `calibrar.frag`.
- Canvas (`_stage` no native = `stageOf`/`canvasOf` no dash), encaixado com barras (`_canvas_box`): o contorno das
  telas `SCREENS`, ou o raster do telão. Fonte no canvas = `rect` 0..1 (origem em cima) em `OVERLAYS` → `_rect_uv`.
- Tela com forma livre: `rot` (centro) + `poly` (0..1 no painel SEM giro); geometria única em
  `dash_data.screen_axes` (= `shapeAxes` no dash). Shader: `inShape` (`POLY_GLSL`, textura `u_poly` 32×16, unidade 8).
- **Telão** = `PIXEL_MAP = {on, w, h}`. O computador vê o telão como UMA resolução (EDID); blocos e espaço entre eles
  ficam na processadora. Ligado: canvas É o raster e sai como está; tela com `ox/oy/pw/ph` = BLOCO (vista Pixel
  map). x/y/w/h/rot em metros = só PREVIEW (`isBlock`: redimensionar no palco não mexe em pw/ph; `paintBlocks`).
  Reconhecer: `/detect-output` (relê o xrandr — o native só lista monitores ao abrir) / `pollOutputs` → `mapTelao`.
- `src/telao_sim.py` (só Linux) = processadora de mentira: monta o telão (salvo em `~/.config/prisma/telao_sim.json`)
  e anuncia SÓ nome + resolução em `dash_data.VIRTUAL_OUTPUTS`; recorta pelo mapa DELE. Captura a saída pelo id
  (WM_CLASS `prisma.prisma`; o título do dash também tem "Saída"); janela fora da tela, sem `_wm_fullscreen`.
- O app empacotado só leva o que o `if False:` do `launcher.py` importa: import novo em `src/` → listar lá
  (`packaging/check_imports.py` no CI acusa).
- Prévias v2: `/frame?which=out|sel|comp|src|fx` (`_preview_frame`; `out_want`/`fx_want` = só enquanto pedidas).
- Dash v2: decisões no comentário do topo do `dash2.html`. Faixas na ordem do ESPECTRO (`specOrder`/
  `_clamp_ranges`; v1 ainda por índice). localStorage `mixKeys`/`fxPick` compartilhado com a v1.
- Elemento recriado a cada SSE perde clique/pointer capture — atualizar no lugar.
- Classe no `body` não pode colidir com classe de componente (blackout = `body.blackout`, não `.blk`).

## Testes
`.venv/bin/python src/dash_server.py` e `.venv/bin/python src/native_synth.py --selfcheck` (+ `src/plat.py`,
`src/dash_data.py`, `src/telao_sim.py --selfcheck`, `packaging/updater.py`, `packaging/check_imports.py` — o CI roda
todos). Build local fora do `dist/`: `DIST=<pasta> packaging/build.sh`. Testes que gravam usam `tuning.py`
temporário (`tuning_path`). Rodar o native do repo migra/auto-salva o `src/tuning.py` do repo; porta 8765 pode
estar com o prisma aberto; simulador aberto = telão virtual anunciado (teste que lê saídas isola o
`VIRTUAL_OUTPUTS`). Arrastar/clicar no dash do app aberto GRAVA no `tuning.py` vivo — backup antes.

## Docs
- Fluxo técnico: <https://paulocremas.github.io/cremas-synth-lab/> (`docs/index.html`) — respeitar
  glossário `GLOSS` + `linkify`, cores por região + linhagem, `<details>` retraído, `.maybe` separado da cor.
- [MAPA.md](MAPA.md) = índice dos currículos. [BACKLOG.md](BACKLOG.md) = combinado e ainda não feito.

## Vocabulário (onda / sinal)

| Conceito | SuperCollider | GLSL |
|---|---|---|
| Oscilador | `SinOsc`, `Saw`, `Pulse` | `sin()`/`fract()` numa shaping function |
| Frequência | `.freq` | repetições do padrão na tela |
| Fase | `.phase` | offset no `sin()`/`fract()` |
| Amplitude | `.mul`, `EnvGen` | brilho da cor |
| Ruído | `LFNoise`, `WhiteNoise` | `random()`, `noise()` |
| Filtro | `LPF`/`HPF`/`RLPF` | blur, convolução |
| Feedback | `LocalIn`/`LocalOut` | pingpong buffer |
| Amostragem | sample rate (tempo) | resolução/fps (espaço) |

## Plano de estudo
[Book of Shaders](https://thebookofshaders.com/) · [Fieldsteel](https://github.com/elifieldsteel/SuperCollider-Tutorials).

| Fase | SuperCollider | GLSL |
|---|---|---|
| 0 · navegação | tut. 1–5 | cap. 00–08 |
| 1 · oscilador/fase | `SinOsc` | cap. 05 |
| 1 · ruído | `LFNoise`/`WhiteNoise` | cap. 10–11 |
| 1 · padrões | tut. 10 (Pbind) | cap. 09 |
| 1 · filtro | `LPF`/`HPF`/`RLPF` | cap. 17–18 |
| 1 · feedback | tut. 20 | fora do livro |
| 2 · avançado | 21–23, 25–26 | cap. 13–14 |
| 3 · fusão | RMS → OSC → uniform | uniform de áudio no shader |

Fase 3 já existe no native (`parec`/numpy no lugar de SC→OSC). 1º exercício: `{SinOsc.ar(440, 0, 0.2)}.play;`
vs. `gl_FragColor = vec4(vec3(sin(u_time * 4.0) * 0.5 + 0.5), 1.0);` no `check.frag`.
