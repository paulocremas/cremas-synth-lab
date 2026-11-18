# synth — GLSL puro & SuperCollider, da base

## Objetivo
Aprender síntese de sinal de baixo nível com o mesmo vocabulário em dois domínios:
**SuperCollider** (áudio: amplitude × tempo) e **GLSL puro** (imagem: cor × pixel, por frame).
Cada ferramenta isolada, depois comparar, só então compor.

## Ambiente (2026-11-17)
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
  Frase (`PHRASE_BARS`, `Tempo.p0` = "1 da frase", `u_phrase`), `golpe` (onset do fluxo), `Secao` (intro/sobe/drop/pausa por
  REGRA: energia curta × longa + kicks/compasso, decidida no "1"; forçar vale até o fim da frase). `/tempo-cmd`: x2, d2, one,
  nudge, frase1, secao.
- **Movimento** (Claude Doc "PRISMA — sync com a música"; `shaders/ATOMO.md` §9): 3 tipos (imagem, sinal 0..1, evento) e 7
  regras. `mod[knob] = {b, lo, hi, modo: loop|disparo|segue, lfo, ev: {src, cond}, env: {a, d} batidas, seg: {a, r} ms, q, id,
  nome}` → `native_synth._mod_value` (estado por id em `_MV`; MESMO id = o mesmo movimento, a faixa é de cada knob; sinal vivo
  em `MV_OUT` → SSE `mv`). Eventos do quadro = CONTADORES (`_music_events` → `state['ev']`: batida/compasso/frase/kick/golpe/
  secao:*/pad:N/`ev_man`; sem som 2 compassos kick/golpe caem pra batida); rastreio vira fonte por caixa (`_trk`,
  `dash_data.track_signals`, y pra cima; `rosto.on` = contador de aparições `d['n']`). Opacidade do átomo e da caixa
  (`row.mod.opacity`) aceitam movimento. GRADE: `/grid` (`fx_off`, `box_off`, `ev`) → `grid_q` → o native aplica na fronteira
  de `SCENE_QUANT` (beat|bar|phrase) numa thread (`grid_apply`); caixa com `acao: {liga, desliga}` = evento liga/desliga.
  Vocabulário/presets em `dash_data` (`MOV_PRESETS`, `EVENTS`, `/vocab`); `// mod: knob=preset` no `.frag` só sugere.
  `/mv-freeze` = SOCORRO congelar.
- Show (fase 4): macros = fontes `m1..m4` do ♪ (`MOD_SOURCES`, `MACROS`); proteção `Limiter` (anti-estrobo
  WCAG 2.3.1 + teto de brilho, ganho no master, `LIMITS`); auto-nível por fonte (`auto`, `_auto_levels` → `u_lv`
  no blend); PRÓXIMA cena (`set_cue`/`take_cue`, `state['scene_cue_sc']` aquece fontes, prévia `which=cue` em
  `lt['cue']`); MIDI `kind: 'rel'` = encoder (63/65 ou 1/127).
- **Webcam virtual** (`tuning.VCAM = {on, w, fps}`, `dash_data.vcam_cfg`, `/vcam`, Saída → Proteção no dash5): o loop GL
  encaixa o palco (`read_canvas`) num quadro 16:9 fixo (blit + PBO) → `vcam_q` → `vcam_thread` → `plat.VCam` (Linux: ffmpeg
  no nó do v4l2loopback, `card_label=PRISMA` primeiro, fora do `list_cams` enquanto escreve; Windows: `pyvirtualcam` = câmera do OBS).
- Luzes: `src/luzes.py` (Art-Net, detector ArtPoll/WLED, mapeamento por câmera `scan`) + aba Luzes; `LIGHTS`.
- Testar o native: SEMPRE em segundo plano com a webcam e `PRISMA_HIDDEN=1` (janela nunca na tela);
  `PRISMA_GL_CHECK=1` religa a checagem de erro do PyOpenGL (desligada por desempenho).
- Câmera NUNCA presa: ffmpeg de fonte nasce via `plat.child_cmd` (`setpriv --pdeathsig TERM`: morre junto com o prisma, até
  kill -9; criar só de thread longa ou que mata o próprio filho); ao abrir, `plat.reap_orphans` mata órfão com a assinatura
  `FFMPEG_SIG` (= `_FAST_IN`); `_pool_reader` mata ffmpeg vivo sem frame há `READER_STALL_S` e reabre com espera crescente
  (0.3→5 s). `list_cams` só lista nó que captura vídeo (UVC: `/dev/video1` = metadados).
- `/select` não mexe na saída: fonte viva tem ffmpeg próprio em `_ovl`; v4l2 é exclusivo → `_feed` copia de lá.
- Canal `file#N` = mesma fonte 2× (`_chkey`/`_base_key`); pilha por canal em `BINDINGS`, pela POSIÇÃO.
  Fora do `pool` some da mesa/saída mas fica lembrado.
- 60 fps (`OUTPUT_FPS`): `src_tex`/`comp_last` só refazem se o frame é OUTRO objeto (`is`, guardando o frame).
- Passes: mistura → `SCENE_GRADE` → transição (`from` antes da calibração) → `OUTPUT_GRADE` (`master` →
  `u_dim`) → com telão, `OUTPUT_MAP_SRC`; os dois grades usam `calibrar.frag`.
- Canvas (`_stage` no native = `stageOf`/`canvasOf` no dash) = SEMPRE o palco: contorno das telas `SCREENS` com os
  vãos. Sem telão: encaixado na janela com barras (`_canvas_box`). Lugar no canvas = `rect` 0..1 (origem em cima)
  da SAÍDA e de cada camada dentro dela → `_rect_uv`.
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
- **Motor do grafo** (`render_mix`): nós no OVERLAYS = fonte | átomo (`file: '@<id>'` = lê o FIM do nó id; `NO_IN = '@-'` = sem
  entrada) | mistura `{kind: 'mix', id, layers}` | SAÍDA `{kind: 'out', id, nome, rect, layers}` (chave `'+<id>'`,
  `dash_data.node_key`); camada = `{from: '@<id>', opacity, blend, off, mod, acao, rect}`. Cena velha → `migrate_graph`
  (= `migrateGraph` no dash, ids `stable_id`). Motor PUXA (`graph_pull`) e ordena (`graph_order`; laço = lê o quadro anterior):
  `run_row` → `bake` → `mix_node` (RGBA pré-multiplicado). Shaders leem textura TOPO→BAIXO (`copy_flip`, `lt['chain']`, `tap_tex`).
  CORRENTE = UM SOBRE O OUTRO (decisão do usuário): nó de 1 átomo lendo outro age SÓ na MARCA dele (`mark_tex`/`mark_fundo`,
  `mk_on`); filtro transforma a marca, quem desenha cria marca nova dentro dela (`STACK_SRC` op 3); saída = marca sobre o fundo.
  Fonte → Contornar → Vinheta = vinheta só nas linhas. "Cru" = ramo paralelo. FONTE CRUA no meio da corrente = a raiz
  (`_track_root`), não a entrada. ESPELHO = item `{espelho: <id>}` → `resolve_mirrors`. `post`/`~post` ("em cima") = legado:
  o dash converte em nó (`flattenPosts`), o motor ainda lê. Máscara da caixa = `BINDINGS[k].matte` (átomos `cat: mascara` leem
  a ENTRADA; `u_subject` unidade 13). `in: 'src'`/`ins` (B: outra raia, `'fb'`, `'src'`) nas unidades 10/11/12.
- **ÁTOMO** (`shaders/ATOMO.md`; `shaders/presets/atomos/`): compilado com `dash_data.ATOM_PRELUDE` (não declara uniform comum).
  Cabeçalho: `// fx:`, `cat:`, `in:`, `B:`, `opcoes:`, `bipolar:` (só assim o knob tem dois lados), `entra: troca|cima`,
  `marca:`, `estado:`, `montagem:` → `parse_meta`/`atom_check` (QUEBRA × avisos; até 3 knobs, 6 com montagem; CHAVE
  `step(.5,u_fx_X)` e ESCOLHA `floor(u_fx_X*K)` não contam). Filtro = TROCA (devolve o alfa lido), `gerador|forma` = POR CIMA
  (`atom_replaces`). `// estado:` → `run_state` (buffer duplo 16F, passo fixo). `src/matriz.py` = todo par de átomos (selfcheck).
  Som/cor/giro não ficam dentro do átomo: RECEITAS (`shaders/receitas/*.json`, `recipeItems`).
- **Movimento no knob**: controlador = item de `~ctl` `{file: 'ctl', id, xy, mod: {sinal}}`; o knob guarda receita + faixa
  (`mod[knob].id`), extras em `mod[knob].mais` (somam: `_mod_total`; `forEachMod`/`dropMod` tratam igual). `syncCtls` cria
  um controlador por movimento e NUNCA apaga. Trocar o átomo (`swapAtom`) desfaz as ligações, os controladores ficam soltos.
- **dash5** (`/v5`, o que o app abre; decisões no topo do `dash5.html`): TOCAR | MONTAR (`mode` 'show'|'montar', `setMode`).
  Nó = MINI TV (`.bx.tv`, mockup `design/mini-tv.html`): gabinete = família (`fam-<cat>`, `tvSkin`), tela `.win>.crt>canvas.lv` na proporção
  do PALCO (`tvAR`). Distribuição (`tvGeo`/`tvJacks`, rodada 4): linha 1 = liga + fader de opacidade EM CIMA da tela (`.r1`, `tvConn`); TELA na
  largura toda; nome (`.bh`) logo abaixo; IN/B/MÁSC numa coluna à esquerda dos knobs (IN na altura do knob, o de baixo na dos CVs), OUT à
  direita na altura do knob (aba `.otab`); jacks a 31 px das bordas; knob sem porcentagem (só girando); knobs (`nodeKnobs` 'row') com o CV `.kj` embaixo; altura = `tvH` (= `boxH`, vai como height). ESCOLHA/CHAVE = MÓDULO FILHO
  (`filKids`/`filEl`: teclas | seletor com lista | tecla) DENTRO do elemento do pai, à esquerda, lugar relativo em `s.filhos[knob] = [dx, dy]`
  (servidor normaliza; o native ignora). O filho está NA CORRENTE: o IN do 1º filho É a entrada A do pai (`inPortEl`); filho → pai = LIGAÇÃO FIXA
  (trilha rígida `.lkc`, terminais quadrados, sem clique; o IN do pai fica `.lk`). Motor igual: o fx do átomo, mesmo id de controle.
  `rectOfNode` = pegada com os filhos (declutter, arrumar, `ctlSpot`). Zoom 2–200% (`CVZ_LIM`) suave: a animação só mexe no `transform` do `#cv-in` (`zTf`/`zoomVis`; trocar o zoom do CSS refaz o layout todo,
  ~80 ms) e o zoom de verdade (`zoomFrame`) entra uma vez no fim; níveis `zlOf`
  (perto | normal | longe | `zl-blk` bloco na cor `--blk` | `zl-ponto`); de longe sem prévia; H / ⤢ = caber tudo (`fitAll`, de novo volta). Fonte/mistura/saída = prata; controlador = osciloscópio
  (`SCOPE`) + faixa de/até (`ctlRange`), nasce EMBAIXO (`ctlSpot`), jack no meio do topo. Jack VISTO DE CIMA; cabo como o VCV (`cableD`,
  plugue `.pg`) POR CIMA dos nós, clique no `#cv-hits` por baixo; clique na saída PEGA o cabo, Shift = novo. Cor do cabo = aleatória por cabo (`cableColor`). MIXER = `kind: 'mix'` com `jacks` (2/4/8),
  camada no jack (`slot`; jack de cima = frente); SAÍDA = UMA entrada (saída antiga com várias vira mixer: `outOneInput`). Enter (MONTAR) = a lista de
  módulos onde está o mouse. Prévia: `liveCv` (o mesmo
  canvas entre renders, só as visíveis); prévia do nó SAÍDA = ela sozinha (native `mix_node`).
  Texto no gabinete = sempre numa PLAQUETA em relevo com letra gravada (`--lbl`/`--lbt`); módulo arrasta por QUALQUER parte
  (`nodeGrab`, exceto `NODRAG`); ARRUMAR = setor por fonte (`tidyPlace`: fonte no meio do setor, o que cruza entre, saída à direita); nome no canvas sem o número do nó (`mixShow`/`visName`).
  Tema (botão "visual"): `body.cel` | foto + `body.leve`, em `localStorage v5tema`; texturas = PNG uma vez (`texturas()` → `--t-*`).
  Rolar a vista NÃO refaz fios. Pictograma `i-at-<Nome>` (`atomIcon`; átomo novo = desenhar o símbolo, o teste `cards` acusa);
  `normalizeNodes`/`graphFix` mantêm 1 átomo por nó; `topoOrder`.
  Escolher ≠ abrir (painel = direito parado ou 2 cliques, contados em `lastTap`); o ACESO é o que o Delete apaga; Esc/vazio = nada;
  Ctrl+A/Ctrl+D. Saídas = telas do palco (`screenOuts`, uma por tela). Pele do resto (barra, PROGRAMA, inspetor, cenas…) e revisão de
  botões: `PROMPT_ESTETICA.md` passos 4–5, marcas no artefato "PRISMA — plano da mini TV + inventário" (db `marcas`). MONTAR: canvas inteiro; Cenas pelo `#cn-btn` (`body.cn-open`), PROGRAMA = janelinha `#pvw`, inspetor `#insp` (`placeInsp`)
  — os dois fecham com clique fora. Biblioteca = RODA (2 cliques no vazio: `openWheel` → `floatList`; `looseNode`/`insertOnWire`).
  Clicar no nome só ESCOLHE (`nameEl`); trocar = ↻ (aparece no mouse). Ctrl+arrastar = `dupNode` sem fios (nó ou seleção; Alt também, mas no
  Linux o Cinnamon pega o Alt). Fio escolhido (`selWire`) solta com qualquer clique fora dele. Navegar: roda = zoom, meio/direito = vista, esquerdo no vazio = seleção (`msel`); à esquerda/em
  cima sem limite (`cvShift`, também no `edgeTrack(…, grow)`). Arrasto = `follow()` + `rafMove` (um passo por quadro) + `wiresFollow` (só os cabos de quem anda, de `WLIVE`; nada de `drawBoxWires`
  nem `body.x *` no CSS — restyle da página toda) /`swallowClick()` (o click sintético logo
  após um arrasto é engolido — em teste, chamar o handler). Knob = `dragCtl` relativo + arrasto infinito (`POST /warp` →
  `plat.warp_pointer`); segurando knob, `renderCtl`/`renderBoxes` esperam. `plug`/`unplug` = fios (`connect()` é o SSE!).
- v3/v4 (`dash3.html`, `dash4.html`): legado; decisões no topo de cada arquivo. Prévias: `/frame?which=out|cv|sel|comp|src|fx|
  mask|steps|try` (`_preview_frame`, só enquanto pedidas). LFO = fonte `'lfo'` com `mod[k].lfo`; `luz`/`mov` = `img_mod_levels`.
- Elemento recriado a cada SSE perde clique/pointer capture — atualizar no lugar. Classe no `body` não pode colidir com
  classe de componente (blackout = `body.blackout`).
- **Rastreio** (`src/rastreio.py`, cv2.dnn, modelos opencv_zoo em `models/`): Rosto/Olhos (YuNet), Corpo/Mãos
  (BlazePose; acha a pessoa pelo NanoDet e depois segue pelos próprios pontos), Objeto (NanoDet, 80 classes COCO), Contorno dos olhos (Face Mesh do MediaPipe `.tflite` via
  `readNetFromTFLite`, entrada NCHW 0..1; tipo `olho` → `u_olho[64]`, 16 pontos por pálpebra; átomo Olhos).
  `track_thread(tipo)` + `track_want`/`track` por fonte base, só sob demanda; `TRACK_U` = uniforms → `_bind_track`
  (pilha e máscara). Átomos de máscara em `atomos/` (ATOMO.md §8). O antigo `u_eyes` (preset Olhos) sai daqui.
- **Saída "por cima do PRISMA"** (monitor = `dash_data.PIN_MON` `'@topo'`): janela sempre no topo (`plat.keep_on_top`: wmctrl
  `above` | HWND_TOPMOST) ancorada no dash — sobre o painel PROGRAMA ou num canto (`pin = {box (px de tela, o dash mede), onde,
  tam, aspect do palco}` → `dash_data.pin_rect`); o dash remede a cada 0,5 s e, se só o lugar mudou, o native MOVE a janela
  (`pygame._sdl2` Window.position) sem reabrir o GL.
- **Limiar por faixa** (coluna do mixer de áudio): `tuning.BAND_GATE = {nome: {th, m}}` (`/band-gate`, `dash_data.band_gate`):
  `ativa` = gate (abaixo vale 0), `teto` = limite; amp + 8 faixas (o kick tem `KICK_THRESHOLD`).
- Faixas de áudio: nível = magnitude / teto da PRÓPRIA faixa (`named_band_levels`); o teto nunca cai abaixo de
  `BAND_FLOOR` (0.25, `getattr` no tuning) × o pico de LONGO prazo dela (`BAND_LONG_DECAY`) — sem esse piso,
  faixa sem som amplificava o próprio chiado até acender.

## Testes
`.venv/bin/python src/dash_server.py` e `.venv/bin/python src/native_synth.py --selfcheck` (+ `src/plat.py`,
`src/dash_data.py`, `src/telao_sim.py --selfcheck`, `packaging/updater.py`, `packaging/check_imports.py` — o CI roda
todos; `src/matriz.py [pasta]` sozinho = a matriz + PNG por átomo). GESTOS do dash5: `tests/dash_gestos.py [palavra]` (dash real
em Chromium/Brave headless via CDP, mouse de verdade, tuning temporário na porta 8799, cena fixa própria) — todo bug de
usabilidade vira um teste aqui; rodar antes de entregar mudança no dash5. O teste mata o GRUPO do navegador ao sair e recusa rodar se a porta 9333 já tem um (órfão de rodada velha = falhas aleatórias). Build local fora do `dist/`: `DIST=<pasta> packaging/build.sh`. Testes que gravam usam `tuning.py`
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
