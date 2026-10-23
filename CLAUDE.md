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
  `dash*.html` a cada abertura; dados entregues (`shaders/`, `transitions/`, `models/`) via `updater.sync_data` +
  `.entregue.json`: intocado atualiza, editado fica, apagado pelo usuário não volta. Quer código novo no app já → copiar pra `dist/prisma/` **e** a pasta de dados
  (`packaging/build.sh` atualiza o launcher velho do `dist/`).
- **Release**: tag `vX.Y.Z` → `.github/workflows/release.yml` (`.deb`, `.exe` `packaging/prisma.iss`, zip portátil);
  tag com `-` = pré. `packaging/updater.py` compara `VERSION` com a última Release. Publicado: `v0.1.0-beta.2`
  (master = branch `dashboard-channels-output`). Docs `#baixar` lê a Release mais nova da API (pré incluída).
- Dash = Chromium `--app --start-maximized` próprio (arrastável entre monitores) (`_open_dash_window`; Edge no Windows; `PRISMA_NO_BROWSER=1` nos testes).
  3× Esc (saída ou dash → `POST /quit`) fecha tudo.
- Hot-reload por mtime: `.frag`, `transitions/*.glsl`, `tuning.py`, `dash_server.py`, `dash_data.py`,
  `dash*.html`. **`native_synth.py` e `telao_sim.py` só reabrindo** (dash novo + native velho não combinam).

## Armadilhas / convenções
- Setter do `dash_server` grava o `tuning.py` (`_write_atomic`) **e** patcha o módulo `tuning` na hora — o
  reload por mtime do native roda no loop de áudio, que pode parar; sem patch o dash "volta pro lugar".
- `None` nunca vai pro `tuning.py` (`_scene_with` tira o campo); flags = `1`, não `True` (`json.dumps`).
- Sync entre abas = guard por TEMPO (`TOUCH_MS`), não foco. Campo "travado" → olhar isso.
- Set ativo **é** o estado vivo e auto-salva (`save_active_scene`); troca = `request_scene` → aplicada no fim
  do frame GL (`apply_scene(defer=True)`: memória já, disco em `_persist_scene` numa thread — gravar no
  loop custava 10–17 ms = frame perdido na transição) + transição VIVA: `render_mix` desenha a cena nova
  (`lt['out']`) e a que sai (`lt['old']`, dados em `scene_tr['old']`, fontes abertas via `state['scene_from']`);
  na transição a suavização dura o tempo dela (morph: efeito comum às duas cenas anda do valor antigo ao novo).
- Dash: todo elemento tem motivo (P palco / S segurança / C montagem) listado no topo do `dash2.html`;
  estrutural (adicionar/tirar) leva `.ed` (some no modo palco).
- Ao vivo: knobs/opacidades/intensidade passam por `_smooth` no native (`PARAM_SMOOTH_MS`); som (♪/kick) e
  master/blackout NÃO. Intensidade dos efeitos = `OUTPUT_GRADE.fxamt` (fader EFEITOS, × opacidade de todo efeito).
- Ritmo/tom: `src/ritmo.py` (`Tempo`: fluxo espectral → autocorrelação → BPM, PLL de fase, TAP; `Key`: cromagrama +
  Krumhansl; `key_rgb`: círculo das quintas | Scriabin). O `audio_thread` alimenta com TODO chunk (lote de vídeo
  inclusive — pular chunk distorce o BPM); a fase (`u_beat`/`u_bar`) é calculada no render a cada frame. Troca de
  cena quantizada (`SCENE_QUANT`) espera `next_boundary` no fim do frame; `TRANS_BEATS` = transição em batidas.
- Show (fase 4): macros = fontes `m1..m4` do ♪ (`MOD_SOURCES`, `MACROS`); proteção `Limiter` (anti-estrobo
  WCAG 2.3.1 + teto de brilho, ganho no master, `LIMITS`); auto-nível por fonte (`auto`, `_auto_levels` → `u_lv`
  no blend); PRÓXIMA cena (`set_cue`/`take_cue`, `state['scene_cue_sc']` aquece fontes, prévia `which=cue` em
  `lt['cue']`); MIDI `kind: 'rel'` = encoder (63/65 ou 1/127).
- Luzes: `src/luzes.py` (Art-Net, detector ArtPoll/WLED, mapeamento por câmera `scan`) + aba Luzes; `LIGHTS`.
- Testar o native: SEMPRE em segundo plano com a webcam e `PRISMA_HIDDEN=1` (janela nunca na tela);
  `PRISMA_GL_CHECK=1` religa a checagem de erro do PyOpenGL (desligada por desempenho).
- `/select` não mexe na saída: fonte viva tem ffmpeg próprio em `_ovl`; v4l2 é exclusivo → `_feed` copia de lá.
- Canal `file#N` = mesma fonte 2× (`_chkey`/`_base_key`); pilha por canal em `BINDINGS`, pela POSIÇÃO.
  Fora do `pool` some da mesa/saída mas fica lembrado.
- 60 fps (`OUTPUT_FPS`): `src_tex`/`comp_last` só refazem se o frame é OUTRO objeto (`is`, guardando o frame).
- Passes: mistura → `SCENE_GRADE` → transição (`from` antes da calibração) → `OUTPUT_GRADE` (`master` →
  `u_dim`) → com telão, `OUTPUT_MAP_SRC`; os dois grades usam `calibrar.frag`.
- Canvas (`_stage` no native = `stageOf`/`canvasOf` no dash) = SEMPRE o palco: contorno das telas `SCREENS` com os
  vãos. Sem telão: encaixado na janela com barras (`_canvas_box`). Fonte no canvas = `rect` 0..1 (origem em cima)
  em `OVERLAYS` → `_rect_uv`.
- Tela com forma livre: `rot` (centro) + `poly` (0..1 no painel SEM giro); geometria única em
  `dash_data.screen_axes` (= `shapeAxes` no dash). Shader: `inShape` (`POLY_GLSL`, textura `u_poly` 32×16, unidade 8).
- **Telão** = `PIXEL_MAP = {on, w, h}`. O computador vê o telão como UMA resolução (EDID); blocos e espaço entre eles
  ficam na processadora. Dois espaços (= input/output map do Resolume, stage/feed do disguise): ligado e com
  blocos (`_out_blocks`), a MISTURA é o canvas do palco no tamanho dele (`CMP_W/H`, teto `MAX_CANVAS_PX`); os passes
  finais desenham na textura `canvas` e o último (`OUTPUT_MAP_SRC`) copia cada tela pro BLOCO dela no raster =
  janela (`ox/oy` px; `pw/ph` = painel nativo; `orot` 90/180/270 = deitado, ocupa ph×pw). Palco muda o que sai;
  `isBlock`: redimensionar no palco não mexe em pw/ph. Prévias: `/frame?which=cv` (canvas → `paintStage`) e `out`.
  Reconhecer: `/detect-output` (relê o xrandr — o native só lista monitores ao abrir) / `pollOutputs` → `mapTelao`.
- `src/telao_sim.py` (só Linux) = processadora de mentira: monta o telão (salvo em `~/.config/prisma/telao_sim.json`)
  e anuncia SÓ nome + resolução em `dash_data.VIRTUAL_OUTPUTS`; recorta pelo mapa DELE. Captura a saída pelo id
  (WM_CLASS `prisma.prisma`; o título do dash também tem "Saída"); janela fora da tela, sem `_wm_fullscreen`.
- O app empacotado só leva o que o `if False:` do `launcher.py` importa: import novo em `src/` → listar lá
  (`packaging/check_imports.py` no CI acusa).
- **Assunto** (efeito modular): item da pilha com `region: subject|bg` → `blend_into` multiplica pela máscara
  (`u_use_mask` 2/3, `smoothstep(u_mth)`); máscara = `subject_thread` (U²-Net-p `models/u2netp.onnx` via `cv2.dnn`,
  192 px ~110 ms) por fonte base, só sob demanda (`subject_want`); limiar/borda em `BINDINGS[canal].mask`.
  Dash: região no inspetor, ◐ assunto no Canvas (`which=mask`). `cv2` precisa estar no `.venv` (requirements).
- **v3** (`dash3.html`, `/v3`; nasceu da v2): abas Show (= `perform`, estrutura travada) e Montar; mesmo grid nas duas.
  Mesa = raias de MÓDULOS: item da pilha com `in: 'chain'` lê a corrente (sem `in` = legado, fonte crua — cenas
  velhas não mudam); `ins` = entrada B (`u_texture_1/2`: outra raia, `'fb'` = ela mesma 1 frame atrás, `'src'`).
  Shaders leem textura TOPO→BAIXO: a corrente passa por cópia virada (`lt['chain']`); saída de raia lida por
  alguém fica em `lane_out` (topo→baixo). Unidades 10/11 (`INS_UNITS`), 12 (`u_texture_src`). Cabeçalho do
  `.frag`: `// cat:` (glifo na paleta) e `// in:` (ins padrão) → `dash_data.parse_meta` → `/shaders` `meta`.
  Átomos em `shaders/presets/atomos/`. ↶ desfazer (por cena) e 🛟 socorro só no dash.
- **v4** (`dash4.html`, `/v4`, do zero; decisões no topo do arquivo + doc de design): 3 colunas fixas (Cenas/Peças |
  Patch | Programa, Próxima/GO, Controles, Macros), Show = só knobs publicados (`pub` no item), gavetas Socorro e
  Equipamento (editores da v3 refeitos). Patch = fileiras (topo = frente) + RAMO: fileira com `file: '@<id>'` lê a
  saída do módulo `id` (`tap_tex`; abaixo da mãe = quadro anterior); módulo lido por alguém roda mesmo a 0%/off
  (`_graph_wants` → `need`); `ins: ['@id']` = entrada B lê o módulo (`_ins_tex`). Item: `id`, `pub`, `grp`/`gname` (grupo; biblioteca `shaders/grupos/*.json`, `/groups`).
  LFO = fonte `'lfo'` do ♪ com `mod[k].lfo = {f, r (batidas), ph}` (`dash_data.lfo`, fase de `ritmo.Tempo.pos`); `luz`/`mov` = brilho e movimento da imagem de entrada
  (`dash_data.img_mod_levels`, ~14 Hz).
  Prévias v4: `/frame?which=steps&src=` (miniatura de cada passo, empilhadas) e `which=try&src=i` (`POST /try`
  = variantes fora do ar, renderizadas em `lt['cue']` quando não há cue).
- Prévias v2: `/frame?which=out|sel|comp|src|fx|mask` (`_preview_frame`; `out_want`/`fx_want` = só enquanto pedidas).
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
