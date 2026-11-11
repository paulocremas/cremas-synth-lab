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
- **v3** (`dash3.html`, `/v3`; nasceu da v2): abas Show (= `perform`, estrutura travada) e Montar; mesmo grid nas duas.
  Mesa = raias de MÓDULOS: item da pilha lê a corrente (`in` ausente ou `'chain'`; só `in: 'src'` lê a fonte
  crua — desde 2026-10-24: antes, sem `in` = crua e a última peça cobria as outras); `ins` = entrada B (`u_texture_1/2`: outra raia, `'fb'` = ela mesma 1 frame atrás, `'src'`).
  Shaders leem textura TOPO→BAIXO: a corrente passa por cópia virada (`lt['chain']`); saída de raia lida por
  alguém fica em `lane_out` (topo→baixo). Unidades 10/11 (`INS_UNITS`), 12 (`u_texture_src`). Cabeçalho do
  `.frag`: `// cat:` (glifo na paleta) e `// in:` (ins padrão) → `dash_data.parse_meta` → `/shaders` `meta`.
  Átomos em `shaders/presets/atomos/` seguem o PADRÃO ÁTOMO (`shaders/ATOMO.md`, conferido por
  `dash_data.atom_problems` no selfcheck): um verbo, só imagem + relógio (som = modulador no knob, sem
  `on_*`/`layer`), knobs 0..1 de vocabulário comum (o 1º = PRINCIPAL, o botão grande da peça), alfa = cobertura (a camada
  da peça é RGBA e o blend usa). MODIFICADOR PARALELO: átomo solto EM CIMA de uma peça age só na saída
  dela (`post: [ids]` → pilha `~post` da cena, `_post_items`; mesmo id em várias peças = um só, com fio). ↶ desfazer (por cena) e 🛟 socorro só no dash.
- **v5** (`dash5.html`, `/v5` = o dash que o app abre desde 2026-10-24; decisões no topo do arquivo + Claude Doc "PRISMA v5"): canvas de CAIXAS. Caixa = fileira do
  OVERLAYS (`id`, `n` = número estável, `xy`/`fold` = lugar no canvas, o native ignora); entrada = fonte ou o FIM de outra
  caixa (`file: '@<id da caixa>'`: `_graph_wants` mapeia id de fileira, `render_mix` guarda o tap DEPOIS da máscara).
  MÁSCARA DA CAIXA =
  `BINDINGS[k].matte = {items, op: 'e'|'ou', cut}`: átomos `// cat: mascara` leem a ENTRADA, dão cinza (`own` textures,
  `u_use_mask` 1 no blend); fora passa a entrada (`m_in`) ou, com `cut`, transparente na SAÍDA. `u_subject` (unidade 13,
  `SUBJ_UNIT`) = máscara U²-Net pro átomo Assunto. No dash, `stackOf(k + '|m')` = os itens da máscara. Sem abas
  Show/Montar: cadeado (`mode` continua 'show'|'montar'); equipamento em 5 abas (`EQ_GROUP`). Larguras das colunas + zoom do canvas por modo
  (`v5layout`); arrasto = `follow()`/`swallowClick()`/`edgeTrack` (soltar perdido não trava o canvas). Knob/fader = `dragCtl`: RELATIVO sobre o
  valor do próprio arrasto (passou do fim e voltou = anda na hora) + ARRASTO INFINITO SEM pointer lock (o Chromium mostra
  "press Esc" e não dá pra esconder): depois de 4 px o cursor some (`html.kdrag`) e, a `WRAP_PX` do clique, `POST /warp` →
  `plat.warp_pointer` (XWarpPointer | SetCursorPos; Wayland = finito) o devolve, salto ignorado; segurando knob
  (`knobHeld`) `renderCtl`/`renderBoxes` esperam soltar (a assinatura do renderCtl tem VALORES); SSE não troca `lastBindings`. Grupos e região por item
  saíram da UI (a região ainda roda; "mais" converte pra máscara).
  NÓ = ÁTOMO (2026-10-28): fonte sem átomo → nó de efeito com 1 átomo (lê o anterior) → … → SAÍDA; knobs sempre abertos,
  REDONDOS no card (`nodeKnobs`/`nodeKnobH` = altura no `boxH`; ids `bar:` de sempre).
  `normalizeNodes()` (em todo `sendBindings/sendOverlays(true)` e ao receber cena antiga) divide caixa com vários átomos em
  corrente — redireciona quem lia o FIM ANTES de criar os nós (chave do nó = o que ele lê); a ponta herda `AIR_PROPS` e a
  máscara. `healRemove`/`dropEmptyNode` fecham a corrente; `topoOrder` = nó depois de quem ele lê (senão 1 quadro de atraso/nó).
  CARD (2026-11-02; o "módulo de synth" foi revisto no mesmo dia, decisões no topo do `dash5.html`): entrada = anel vazado, saída =
  cheia com setinha, nome do jack por dentro, LED no ar; apagar a fonte / tirar o fio do A = nó SEM ENTRADA (`NO_IN = '@-'`), nunca
  uma fonte nova. `cvZoom()` = cache do `applyLayout` (ler estilo no meio do `renderBoxes` forçava layout).
  Fio na bolinha "máscara" = átomo **Luma** (`atomos/Luma.frag`, máscara com `ins: ['@id']`). Caixa que lê outra rastreia a
  FONTE de origem (`_track_root`).
- **GRAFO / cabos VCV** (2026-11-01; `PROMPT_CABOS.md`, decisões no topo do `dash5.html`): nós no OVERLAYS = fonte | átomo |
  **STAGING** `{kind: 'mix', id, layers}` | **SAÍDA** `{kind: 'out', id, nome, rect (no palco), layers}`; chave `'+<id>'`
  (`dash_data.node_key`), átomos DEPOIS da mistura em `BINDINGS['+<id>']`. Camada = `{from: '@<id>', opacity, blend, off, mod,
  acao, rect (dentro do mixer)}` (0 = atrás). Fileira não tem mais `off`/opacidade/modo/`rect`/`acao` de SAÍDA: cena sem `out`
  → `dash_data.migrate_graph` (motor via `_graph`, cache por identidade; dash `migrateGraph`, mesmos ids `stable_id`): o que
  estava no ar vira entrada da "saída 1" (v5: `off` = meio de corrente; v3/v4: entra desligada). Motor PUXA (`graph_pull`: só
  roda o que chega numa saída, + `no:` + nó com prévia pedida) e ordena sozinho (`graph_order`; LAÇO = o fio que fecha lê o
  quadro anterior). `render_mix`: `run_row` por fileira → `bake` (FIM com alfa em `lay_tex`, cor amostrada encaixada
  `u_snap`) → `mix_node` (3 texturas RGBA PRÉ-MULTIPLICADAS, cobertura no alfa, `u_pre`/`u_aout`) → saída SEM átomos desenha
  as camadas DIRETO no palco (cena antiga = mesmo `/frame`); com átomos, a textura dela no `rect`. **ESPELHO** = item
  `{file, espelho: <id>, id}` → `resolve_mirrors` (knobs/movimento/liga do original, fio e buffer de estado do lugar, `_seed` do
  original). Grade/ação por camada = `layer_off {node, from}`. Dash: entrada aceita UM fio (A/B/máscara/camada N), saída
  vários; clique na bolinha = fio grudado (`cableStick`; vazio → `nodeMenu`), `plug`/`unplug` (o `connect()` é o SSE!);
  cabos POR BAIXO dos nós, tensão/opacidade globais por modo (`v5cable`); Alt+arrastar = espelho; mapeamento = aba Saída →
  "Saídas no palco" (2 cliques = entrar e posicionar as entradas).
  CINCO TIPOS DE CONTROLE (topo do `dash5.html`): knob | CHAVE (`step(.5, u_fx_X)` → `knob_switches`/meta `chave` → `switchCtl`;
  propriedades liga/desliga = `swEl`) | ESCOLHA (`floor(u_fx_X * K)` → `knob_choices`/meta `escolha`, nomes em `// opcoes:`,
  opção i = `(i+0.5)/N` → `choiceCtl`) | conjunto (chips `.on`) | ação.
  Mover átomo entre caixas: alça `.grip` (ou o nome) → zonas `ins` (`moveModules`); máscara: chip `.mc` → `moveMask`;
  Ctrl+X/C/V = `clipTake`/`clipPaste` (recortar leva o PRÓPRIO item, id junto — ramo que lia ele volta ao colar). Shift+arrastar
  (no começo ou no meio, `drag.copy`) = cópia (`prepItems`: id novo; máscara: `copyMask`).
  Navegar: roda = zoom no cursor (`setCvZoom(z, ev)`), arrastar o vazio / botão do meio = mover a vista (scroll do `#cv`, barras
  escondidas; `CVI` tem uma tela de folga); roda num knob/barra muda o valor (`stopPropagation`).
- **ÁTOMO v2** (`shaders/ATOMO.md`, `PLANO_PADROES.md`; aprovado 2026-10-31): todo `.frag` de `atomos/` é compilado com o
  PRELÚDIO `dash_data.ATOM_PRELUDE` (`atom_source`; `uv()`, `A/B/S/E()`, `Am()`, `luma`, `asp`, `dirOf`, `fbm`, `paleta`,
  `decai`, `u_dt`, `u_seed`) — o átomo NÃO declara uniform comum. Alfa direto (o FIO leva o alfa: `lt['src']`/`chain`/taps
  RGBA; PNG e recorte entram na corrente no começo da fileira); FILTRO entra por TROCA (`u_aout` 5), `cat: gerador|forma`
  POR CIMA (3) — `dash_data.atom_replaces`; filtro devolve o alfa que leu; direção =
  ESCOLHA fixa|relevo|redemoinho|vetor (RG, 0.5 = parado). `// estado:` → `run_state` (render_mix): buffer duplo RGBA16F
  por id (`st_bufs`), PASSO FIXO `_state_steps` (60/s × passos, ≤ 2× por quadro), `u_vista` 0 atualiza / 1 mostra,
  `u_fase` (sub-passes), escala = linhas/1080; item `estado: {semear, limpar}` (eventos) + `POST /state-cmd`; `post` num nó
  com estado = loop RETORNO (`u_agl` = 1, antes de cada passo). Camada da peça (`lt['layer']`) é 16F e o blend dela tem
  dither. Sinal `no:<id>` (`grab_no`, `_no_wants`: o nó roda mesmo fora da SAÍDA) e `key_hue` (tom) são fontes de
  movimento. `src/matriz.py` = MATRIZ DE EMERGÊNCIA (no `--selfcheck`, só com GL). Biblioteca v5: só átomos; o resto em
  "Clássicos"; nome mostrado = `// ATOMOS · Nome.` (`parse_meta` `nome`).
- **EM CIMA** (2026-11-05, `PLANO_CONVERSA.md`; ATOMO §7.4): átomo solto NO CARD de outro (`post`) age só na MARCA dele — quem
  desenha = o alfa; FILTRO = saída onde difere da entrada (`STACK_SRC` op 0, `dash_data.MARCA_LO/HI`). O de cima lê a marca em `A()`:
  filtro troca (cor/espaço/memória, `run_state` com o id dele, opacidade e B valem), quem desenha fica DENTRO (op 1); a marca volta
  POR CIMA da entrada (fundo intacto). Em cima de átomo com estado = loop RETORNO. Card: linhas `↳` (`stackRow`, `STK_H` no `boxH`);
  soltar no card de átomo = em cima, no fio = corrente. Matriz confere todo par X ↑ Y. `// B: nome` = o que a entrada B significa.
  §8 do plano = v6 (`docs/mock_v6.html`); fase 1 FEITA: seletor TOCAR | MONTAR (`#mode-seg`, `mode` segue 'show'|'montar')
  no lugar do cadeado; em TOCAR o `#cv-p` some e `#pgm-p`/`#next-p` vão pro `#center` (`setMode`); sem publicado = o
  principal de cada átomo no ar. DECLARAR, NÃO PROIBIR (§9): `dash_data.atom_check` → QUEBRA (fora da biblioteca) ×
  avisos (roda, "!" na biblioteca) + `ouve`/`ve` (som/rastreio em qualquer átomo, ♪/olho); `// entra:` e `// marca:`
  (`atom_replaces`, `atom_marca`); `/shaders` meta `atom` = sem QUEBRA; `cat:` desconhecida → grupo "Outros".
  v6 fases 2–4: mistura = saída (`setOnStage` troca `kind` mix ↔ out; só "+ mistura" no topo do canvas), biblioteca em 4 abas
  (`PAL_TABS`, `palCat` = aba; busca em todas), card sem cor de categoria, custo de GPU no aviso de fps da SAÚDE.
- **Rastreio** (`src/rastreio.py`, cv2.dnn, modelos opencv_zoo em `models/`): Rosto/Olhos (YuNet), Corpo/Mãos
  (BlazePose; acha a pessoa pelo NanoDet e depois segue pelos próprios pontos), Objeto (NanoDet, 80 classes COCO), Contorno dos olhos (Face Mesh do MediaPipe `.tflite` via
  `readNetFromTFLite`, entrada NCHW 0..1; tipo `olho` → `u_olho[64]`, 16 pontos por pálpebra; átomo Olhos).
  `track_thread(tipo)` + `track_want`/`track` por fonte base, só sob demanda; `TRACK_U` = uniforms → `_bind_track`
  (pilha e máscara). Átomos de máscara em `atomos/` (ATOMO.md §8). O antigo `u_eyes` (preset Olhos) sai daqui.
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

- **Controlador** (dash5, 2026-11-04): o movimento com corpo no canvas = item da pilha `~ctl` do BINDINGS `{file: 'ctl', id, xy,
  mod: {sinal}}` (id = o do movimento); o knob ligado guarda a receita + a faixa (`mod[knob].id`), o motor não muda. `syncCtls`
  cria um por movimento; cabo tracejado até a altura do knob (`cvEnd`). Átomo não tem cor/giro/som dentro: os Clássicos viraram
  RECEITAS (`shaders/receitas/*.json` → `/receitas`, `recipeItems`; item `paralelo: [...]` = modificador paralelo, ex. Tingir
  só na linha do Contornar) e saíram da biblioteca (cena antiga roda o `.frag` velho). Átomo/receita solto NO FIO = nó no meio
  (`insertOnWire`, zona `wire` no meio de cada cabo); nó novo empurra quem ele cobre (`declutter`); ARRUMAR recoloca controladores.
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
todos; `src/matriz.py [pasta]` sozinho = a matriz + PNG por átomo). Build local fora do `dist/`: `DIST=<pasta> packaging/build.sh`. Testes que gravam usam `tuning.py`
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
