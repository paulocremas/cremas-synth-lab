# synth — GLSL puro & SuperCollider, da base

## Objetivo
Aprender síntese de sinal de baixo nível com o mesmo vocabulário em dois domínios:
**SuperCollider** (áudio: amplitude × tempo) e **GLSL puro** (imagem: cor × pixel, por frame).
Cada ferramenta isolada, depois comparar, só então compor.

## Ambiente (2026-11-19)
- SuperCollider 3.13.0 cru. GLSL: VS Code `circledev.glsl-canvas` + `slevesque.shader`; `shaders/check.frag` = smoke-test.
- `src/native_synth.py` (PyOpenGL): fontes (câmera/tela/mídia via `ffmpeg`) + áudio (FFT) → grafo de shaders → janela de saída.
  `dash_server.py` (HTTP+SSE stdlib), `dash_data.py` (puras). Arquivos/fluxos: [README.md](README.md); instalar: [INSTALAR.md](INSTALAR.md).
- **Linux + Windows**: tudo que toca o sistema passa por `src/plat.py` — nunca `xrandr`/`parec`/`select`/`/dev/video` direto.
  Windows só testado no CI (sem GPU: o smoke para no 1º OpenGL).
- **App `prisma`** (PyInstaller, `packaging/launcher.py`) roda uma CÓPIA na pasta de dados (`~/.local/share/prisma/` |
  `%LOCALAPPDATA%\prisma` | `<pasta>/dados` com `portable.txt`), recopiando `src/*.py` (menos `tuning.py`) e `dash*.html` a cada
  abertura; `shaders/`, `transitions/`, `models/` via `updater.sync_data` + `.entregue.json` (intocado atualiza, editado fica, apagado
  não volta). Código novo no app já → copiar pra `dist/prisma/` **e** a pasta de dados. Import novo em `src/` → listar no `if False:`
  do `launcher.py` (`packaging/check_imports.py` acusa).
- **Release**: tag `vX.Y.Z` → `.github/workflows/release.yml` (`.deb`, `.exe` `packaging/prisma.iss`, zip); tag com `-` = pré.
  `packaging/updater.py` compara `VERSION` com a última Release. Publicado: `v0.1.0-beta.16` (master = branch `dashboard-channels-output`).
- Dash = Chromium `--app` próprio (`_open_dash_window`; Edge no Windows; `PRISMA_NO_BROWSER=1` nos testes). SEGURAR Esc 2 s → `POST /quit` (dash e janela de saída).
- Hot-reload por mtime: `.frag`, `transitions/*.glsl`, `tuning.py`, `dash_server.py`, `dash_data.py`, `dash*.html`.
  **`native_synth.py`, `ritmo.py` e `telao_sim.py` só reabrindo** (dash novo + native velho não combinam).

## Armadilhas / convenções
- Setter do `dash_server` grava o `tuning.py` (`_write_atomic`) **e** patcha o módulo `tuning` na hora (o reload do native roda no
  loop de áudio, que pode parar). `None` nunca vai pro `tuning.py` (`_scene_with` tira); flags = `1`, não `True`.
- Sync entre abas = guard por TEMPO (`TOUCH_MS`), não foco. Elemento recriado a cada SSE perde clique/pointer capture — atualizar
  no lugar. Classe no `body` não pode colidir com classe de componente (`body.blackout`).
- Set ativo **é** o estado vivo e auto-salva (`save_active_scene`); troca = `request_scene` → `apply_scene(defer=True)` no fim do
  frame GL (disco em `_persist_scene` numa thread: gravar no loop = frame perdido) + transição VIVA em `render_mix` (`lt['old']`).
- Ao vivo: knobs/opacidades/intensidade passam por `_smooth` (`PARAM_SMOOTH_MS`); som e master/blackout NÃO.
  Intensidade dos efeitos = `OUTPUT_GRADE.fxamt`.
- **Ritmo/som** (`src/ritmo.py`): `Tempo` (BPM, PLL, TAP), `Key`, `Secao`, `Ataque` (onset por faixa). O `audio_thread` alimenta o
  `Tempo` com TODO chunk (pular distorce o BPM); fase (`u_beat`/`u_bar`/`u_phrase`) calculada no render. Troca quantizada
  (`SCENE_QUANT`, `next_boundary`), `TRANS_BEATS`, `PHRASE_BARS`; `/tempo-cmd`.
- Eventos do som (`dash_data.SOUND_EVENTS` kick/caixa/chimbal/golpe) = SÓ do som; o substituto do relógio (`kick~`…, 2 compassos sem
  som = batida) só com `ev.rel = 1` no alterador (selo pelo SSE `tempo.sub`). Kick: `amp ≥ SILENCE_AMP` e grave ≥ `KICK_FLOOR` × pico
  longo; caixa/chimbal/golpe = `ritmo.Ataque` (fluxo LINEAR — o log fazia chimbal virar caixa; `ATAQUE_FAIXAS`, `ATAQUE_FLOOR`).
  Níveis `grave/medio/agudo` = a mais forte das finas (`SOUND_GROUPS`). CALIBRAR SILÊNCIO (`POST /silencio`, `state['cal_req']` →
  `audio_thread` mede `SIL_SEGUNDOS` → `dash_server.save_silencio` → `tuning.SILENCIO`, só vale na `fonte` medida): `sil_amp`, piso do
  kick, `Ataque.ruido` e o ruído descontado das faixas (`named_band_levels(noise=)`), tudo × `SIL_MARGEM`.
- Faixas: nível = magnitude / teto da PRÓPRIA faixa (`named_band_levels`), teto ≥ `BAND_FLOOR` × pico longo (`BAND_LONG_DECAY`) — sem
  o piso, faixa vazia amplifica o próprio chiado. Limiar por faixa = `BAND_GATE` (`dash_data.band_gate`). Faixas/espectrograma/
  calibrar leem o espectro COMBINADO (`GraveLongo`: FFT de `GRAVE_N` abaixo de `GRAVE_HZ`, a de 1024 acima — na curta o Sub-bass era
  ~1 fatia com o baixo vazando); kick/ataques/tempo seguem na curta (precisam do instante).
- **Movimento** (Claude Doc "PRISMA — sync com a música"; `shaders/ATOMO.md` §9): `mod[knob] = {b, lo, hi, modo: loop|disparo|segue,
  lfo, ev: {src, cond, rel}, env, seg, q, id, nome, mais}` → `_mod_value`/`_mod_total` (estado por id em `_MV`; MESMO id = o mesmo
  movimento; sinal em `MV_OUT` → SSE `mv` + `mv_t`). Eventos = CONTADORES (`_music_events` → `state['ev']`); rastreio vira fonte
  (`_trk`). GRADE `/grid` → `grid_q` → `grid_apply` na fronteira. Vocabulário em `dash_data` (`MOV_PRESETS`, `EVENTS`, `/vocab`);
  `/mv-freeze` = SOCORRO. Camada com `acao: {liga, desliga}` = evento liga/desliga. Controlador = item de `~ctl` com `mod.sinal`
  (a receita); `syncCtls` nunca apaga; `forEachMod`/`dropMod` tratam knob, extra (`mais`) e camada
  (`L.mod.opacity`) igual. No dash: famílias `FAMS` (relógio | som | imagem e corpo | mão) = o anel de DENTRO da roda (`ring: 'in'`).
- Show: macros `m1..m4` (= o módulo MÃO: `MAO_KEY` `~mao`, faders = controladores `MAO_IDS` sem desenho próprio, pads = `pad:N`), `Limiter` (anti-estrobo + teto, `LIMITS`; agindo = `#lim-top` na barra — "a tela escurece" é ele), auto-nível (`_auto_levels` → `u_lv`), PRÓXIMA cena
  (`set_cue`/`take_cue`), MIDI `kind: 'rel'` = encoder.
- **Webcam virtual** (`tuning.VCAM`, `/vcam`): `read_canvas` → `vcam_q` → `vcam_thread` → `plat.VCam` (v4l2loopback `card_label=PRISMA`,
  fora do `list_cams`; Windows `pyvirtualcam`). Luzes: `src/luzes.py` (Art-Net, `LIGHTS`).
- Testar o native: SEMPRE em segundo plano com a webcam e `PRISMA_HIDDEN=1`; `PRISMA_GL_CHECK=1` religa a checagem do PyOpenGL.
- Câmera NUNCA presa: ffmpeg nasce via `plat.child_cmd` (`setpriv --pdeathsig`; criar só de thread longa); `plat.reap_orphans` mata
  órfão com `FFMPEG_SIG`; `_pool_reader` reabre o travado (`READER_STALL_S`). `list_cams` só lista nó que captura vídeo.
- `/select` não mexe na saída: fonte viva tem ffmpeg próprio em `_ovl`; v4l2 é exclusivo → `_feed` copia de lá. Canal `file#N` =
  mesma fonte 2× (`_chkey`/`_base_key`); pilha por canal em `BINDINGS`, pela POSIÇÃO. Fora do `pool` some mas fica lembrado.
- 60 fps: `src_tex`/`comp_last` só refazem se o frame é OUTRO objeto (`is`). Ritmo = prazo absoluto (`pace_t`). Análise completa só
  com o painel Imagem aberto (`comp_want`/`out_want`), senão `image_levels_lite`; nada de análise no loop GL (`out_analysis_thread`).
  Vídeo: `plat.hw_decode`, `fps=30` ANTES do `scale`.
- Passes: mistura → `SCENE_GRADE` → transição → `OUTPUT_GRADE` → com telão, `OUTPUT_MAP_SRC` (grades usam `calibrar.frag`).
- Canvas (`_stage` = `stageOf`/`canvasOf` no dash) = SEMPRE o palco (telas `SCREENS` + vãos); `rect` 0..1 → `_rect_uv`. Forma livre:
  `rot` + `poly`, geometria única `dash_data.screen_axes` (= `shapeAxes`), shader `inShape` (`POLY_GLSL`, unidade 8).
- **Telão** = `PIXEL_MAP`: mistura no canvas do palco (`CMP_W/H`, `MAX_CANVAS_PX`), `OUTPUT_MAP_SRC` copia cada tela pro BLOCO dela
  (`_out_blocks`: `ox/oy`, `pw/ph`, `orot`). `isBlock`: redimensionar no palco não mexe em pw/ph. `/detect-output` relê o xrandr.
  `src/telao_sim.py` (Linux) = processadora de mentira, anuncia em `dash_data.VIRTUAL_OUTPUTS`; captura a saída pelo WM_CLASS
  `prisma.prisma` (o título do dash também tem "Saída"), janela fora da tela, sem `_wm_fullscreen`.
- Saída "por cima do PRISMA" (`PIN_MON` `'@topo'`): `plat.keep_on_top` + `dash_data.pin_rect`; só lugar mudou → move sem reabrir o GL.
- **Assunto**: item com `region: subject|bg` → `blend_into` × máscara do `subject_thread` (U²-Net-p, sob demanda `subject_want`).
  **Rastreio** (`src/rastreio.py`, cv2.dnn, `models/`): `track_thread` sob demanda (`track_want`), `TRACK_U` → `_bind_track`.
  `cv2` precisa estar no `.venv`. Unidades de textura ocupadas: 8 `u_poly`, 10/11/12 `in`/`ins`, 13 `u_subject` (`BINDINGS[k].matte`).
- **Motor do grafo** (`render_mix`): nós = fonte | átomo (`file: '@<id>'`; `NO_IN = '@-'`) | mistura `{kind: 'mix'}` | SAÍDA
  `{kind: 'out'}`; camada = `{from, opacity, blend, off, mod, acao, rect}`. Cena velha → `migrate_graph` (= `migrateGraph`).
  `graph_pull`/`graph_order` (laço = quadro anterior) → `run_row` → `mix_node` (RGBA pré-multiplicado); textura TOPO→BAIXO (`copy_flip`).
  CORRENTE = UM SOBRE O OUTRO (decisão do usuário): átomo lendo outro age SÓ na MARCA dele (`mark_tex`); fonte crua no meio = a raiz
  (`_track_root`). ESPELHO → `resolve_mirrors`. `post` = legado (`flattenPosts`).
- **ÁTOMO** (`shaders/ATOMO.md`, `shaders/presets/atomos/`): `dash_data.ATOM_PRELUDE`; cabeçalho → `parse_meta`/`atom_check` (até 3
  knobs, 6 com `montagem:`); filtro = TROCA, `gerador|forma` = POR CIMA (`atom_replaces`); `// estado:` → `run_state`. `src/matriz.py`
  = todo par. Som/cor/giro = RECEITAS (`shaders/receitas/*.json`). Átomo novo = desenhar o pictograma (`atomIcon`; teste `cards`).
- **Dash** = `dash5.html` (único: `/`, `/v5`, `/v6`); as DECISÕES moram em `DECISOES.md` (o que vale hoje + histórico; decisão nova = lá). REPAGINADA 2026-11-27 (B "cantos"): barra de cima = show (cena ◀ ▾ ▶ · próx · GO; avisos
  na BOIA); sem barra do canvas: a vista é a PÍLULA `#cv-nav` (⋯ = arrumar/cabos/programa); PROGRAMA = monitor do canto (aba NO AR).
  PELES (2026-11-27): menu ⋯ › pele (`v6skin`), 10, todas escuras; uma pele = tokens `SKINS` (canvas: `skinBody`/plaqueta/knob/jack/cabo; HTML: `--k-*`,
  `body.skinned`); 'atual' = os pintores de sempre. Contraste cobrado por `skinContrast` (t6_peles); fundo decorado só em camada CSS parada. UM MODO só (TOCAR saiu em 2026-11-26; `mode` = 'montar'
  só como chave de preferência). Cor do cabo = `cableColor` pela identidade com o ID da fileira (`cableKey`) + `CABLE_PIN` (cabo religado mantém a cor). O canvas é um JOGO (bloco `G6` no fim): geometria
  `hzLayout`, alvo `G6.pick`, o que mexe nos dados é o código do dash5 (`plug`/`unplug`/`cableEnd`/`linkMv`/`dupNode`). Canvas HTML de
  reserva e v1–v4 APAGADOS (2026-11-26). Sem filhos (escolha = teclas/seletores no card, `tvWide`/`selSty`).
  Plano 2026-11-26 (Claude Doc "PRISMA — plano geral: gestos, estética e fluidez", fases 0–4 FEITAS): cabo = CLIQUE PEGA, CLIQUE SOLTA
  (`CLICK_PX`, `cvFinish`/`evFinish`, direito/Esc cancela); módulo SOLTO num fio entra (`dropOnWire` + `SLIDE`); SACUDIR tira da corrente
  (`shakeTrack`); roda gira controle SÓ com Alt, touchpad rola, pinça = zoom (`wheelDev`); FONTE = LEITOR com bandeja (`o.tray`,
  `srcGo`/`srcStep`, `/grid` `src_set|src_next` → `src_swap`; pool quente prioriza a bandeja); EVENTO VIRA CABO: módulo RELÓGIO E SOM
  (`EV_KEY '~ev'`), o cabo mora no DESTINO (`acao`: `alterna` = LIGA, `opcao:<knob>` = seletor via `opt_next`, `proximo` = leitor,
  camada `alterna`; alterador = `mod.sinal` disparo), COMPARADOR `cmp:<id>` (native `_music_events`, histerese 0,4/0,6); PELE: cor do
  cabo POR TIPO (`CABLE_IMG`/`CABLE_CV`/`EVCOL`), um tema + leve automático, TAMPA (`data-guard`), visor (`#toast`), painel no material.
  Elemento: todo controle tem motivo; estrutural leva `.ed`. Arrasto: `follow()`+`rafMove`+`wiresFollow` (nunca `drawBoxWires` nem CSS
  `body.x *` = restyle); o stream trava no APERTO (`boxDrag`); click sintético pós-arrasto é engolido (`swallowClick` — em teste, chamar o
  handler). Rolar a vista NÃO refaz fios; escolher nó/fio não entra no `cvSig`; segurando knob, `renderCtl`/`renderBoxes` esperam.
  Knob = `dragCtl` + `/warp`. `plug`/`unplug` = fios (`connect()` é o SSE!). Osciloscópio usa a hora do SERVIDOR (`mv_t`).
  ACABAMENTO (topo do dash5): uma luz (de cima), sombra em camadas DENTRO do sprite (`softShadow`, margem `SHADOW_PAD`), LED `led()`,
  pontos da mesa = camada CSS `#gdots` que só desliza. Nada que encha a tela no `frame()` a cada quadro: custa rasterização FORA do JS
  (`G6.stats.ms` não vê; a grade no canvas derrubou 60 → 44 fps) — medir o fps, não só o ms.
- Prévias: `/frame?which=out|cv|sel|comp|src|fx|mask|steps|try` (só enquanto pedidas; `&w=` largura na tela, `&fmt=rgba`). SSE manda
  overlays/bindings/pool/source_fit SÓ quando mudam (+1 s de refresco, `_SSE_DIFF`).

## Testes
`tests/tudo.sh` = todos os self-checks num comando (`--lento` = + motor com GL e os gestos).
`.venv/bin/python src/dash_server.py`, `src/native_synth.py --selfcheck`, `src/plat.py`, `src/dash_data.py`, `src/ritmo.py`,
`src/telao_sim.py --selfcheck`, `packaging/updater.py`, `packaging/check_imports.py` (o CI roda); `src/matriz.py [pasta]` = matriz + PNG.
GESTOS: `tests/dash_gestos.py [palavra]` (Chromium headless via CDP, porta 8799, cena própria) — todo bug de usabilidade vira teste;
rodar antes de entregar mudança no dash5; recusa rodar se a 9333 tem navegador órfão; alguns falham às vezes só na suíte (rodar sozinho).
Fotos: `tests/estetica.py <pasta> [palavra]` = TODAS as superfícies (revisão de pele); tela inteira: `tests/tela_foto.py <png> [painel] [perto]`. Build fora do `dist/`: `DIST=<pasta> packaging/build.sh`. Testes que gravam usam `tuning_path`
temporário. Rodar o native do repo migra o `src/tuning.py` do repo; porta 8765 pode ser o prisma aberto; arrastar no dash do app aberto
GRAVA no `tuning.py` vivo — backup antes.

## Docs
- Leiga: <https://paulocremas.github.io/cremas-synth-lab/> (`docs/index.html`; `como-funciona.html` = redireciona); fluxo técnico: `docs/tecnico.html` — respeitar
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

Fase 3 já existe no native (`parec`/numpy no lugar de SC→OSC).
