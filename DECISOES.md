# PRISMA — decisões do painel (dash5.html)

Antes ficavam num comentário de 330 linhas no topo do `dash5.html`, em ordem de data, uma decisão SUBSTITUINDO a outra. Agora:
**o que vale hoje** aqui em cima (curto, sem histórico) e o **histórico inteiro** embaixo, sem cortes (de onde veio cada escolha, com as fontes).
Decisão nova: acrescente no fim do histórico **e** ajuste "o que vale hoje". O topo do `dash5.html` só aponta pra cá.

## O que vale hoje (2026-11-27)

**Um modo só, o canvas é o palco e a bancada** (como o VCV). Barra de cima = o que se TOCA: música + TAP, a cena (◀ cena ▾ ▶, próx, GO),
EQUIPAMENTO, EFEITOS, MASTER, a boia do SOCORRO (os avisos de saúde moram nela) e BLACKOUT (tampa no botão; tecla `.` direta).
A vista = a pílula no canto de baixo (desfazer · − % + · caber · ⋯ = arrumar, cabos, programa, pele). PROGRAMA = monitor no canto.

**Canvas (o "jogo" G6, desenhado num `<canvas>`):**
- Módulo horizontal (`hzLayout`): tela na largura toda, jacks de imagem à esquerda (in, B, másc, opac), OUT à direita, knob-jack (a tampa
  do knob é a porca do jack), seletores (tecla / entalhes / rotativo). Família = material e cor do gabinete.
- Cabo = CLIQUE PEGA, CLIQUE SOLTA (ou arrastar); `CLICK_PX` 8 px de tremido; direito/Esc cancela. Cor do cabo = o TIPO (imagem azul,
  sinal âmbar, evento verde), tom estável pela identidade. Módulo solto num fio entra no meio; sacudir tira da corrente.
- Roda (2 cliques no vazio, Enter, ou cabo solto no vazio) = UMA lista: já abre com a BUSCA em foco, ★ favoritos e ↺ recentes no topo;
  as fatias (famílias) em volta. Com um módulo escolhido, o novo entra DEPOIS dele. Cabo no vazio = "depois de X", só o que lê o cabo.
- Navegar: touchpad rola, pinça = zoom, roda do mouse = zoom; knob só gira com Alt. H = caber tudo, G = enquadra o escolhido (de novo
  = volta), Ctrl+F = ir até um módulo. De longe (< 42%) o nome numa plaqueta de tamanho fixo. Alvos ≥ 24 px na tela.
- Direito parado: no módulo = painel; no fio = ir à origem / destino / tirar; num knob/fader/pad = aprender MIDI ali.
- Desfazer guardado POR CENA + refazer (Ctrl+Shift+Z / Ctrl+Y). Cena por letra = SEGURAR a letra (tocar só avisa).

**Movimento:** o que mexe no knob é um ALTERADOR (o corpo no canvas, pilha `~ctl`) e o que ele faz é o MOVIMENTO (`mod[knob]`).
Eventos (relógio e som, `~ev`) viram cabo verde até um LIGA, seletor, ▶▶ de fonte, alterador ou knob. MÃO (`~mao`) = M1–M4 + pads.

**Equipamento** (gaveta ≤ 640 px, o canvas fica à vista): Entrada (SIMPLES: volume, kick, grave, médio, agudo com o medidor do que
entra e do que o alterador recebe, auto-ganho, perfis; AVANÇADO: as 8 faixas em português) · Saída · TELÃO (1 palco, 2 raster,
3 saídas no palco; teste por bloco na saída real, identificar, exportar PNG, casa de show, setas de 1 px) · Luzes · Arquivos (gestão:
enviar, renomear, apagar; o que não roda aparece com o motivo) · Controle (MIDI, teclas).

**Pele e acabamento:** 10 peles, todas escuras (menu ⋯ › pele); uma luz de cima, sombra em camadas no sprite, LED com halo, cabo
aceso mostra o sinal andando; nada que encha a tela é pintado a cada quadro (medir o fps, não só o ms). Legibilidade antes de tudo.

**Cores:** imagem azul, sinal âmbar, evento verde; no ar verde, escolhido laranja, perigo vermelho.

## Histórico (o comentário original do topo do dash5.html, inteiro)

```
  PRISMA v5 — CANVAS DE CAIXAS DE ATOMOS. Servido em /v5 (v4 em /v4, v3 em /v3...). A tela principal (canvas, caixas,
  fios, no SAIDA, biblioteca, inspetor) foi escrita do zero; a infraestrutura provada da v4 veio junto (stream, knob,
  fader, MIDI learn + soft takeover, saude, socorro, cenas/PROXIMA/GO, variacoes, editores de equipamento).
  2026-11-17 (pedido do usuario, vibe VCV/Eurorack): ESCOLHER != ABRIR — clique so' escolhe (mover/apagar); o painel abre com o
    DIREITO parado ou 2 cliques no no' (setSel mantem o painel como estava, openInsp abre). Bolinha verde do no' de atomo = liga/
    desliga. MASCARA = NO' (maskNode: le a mesma entrada, fio na 'másc' = Luma macio). Knob com ativador = ALCANCE (atenuversor:
    base = lo, girar = hi - lo, centro = nada, esquerda = inverte; anel de fora = faixa + valor vivo). Rotulos curtos, sem frase.
    O NOME do no' so' escolhe (trocar = ↻, fonte tambem). 2 cliques contados por tempo + no' (lastTap): o 1o clique redesenha o no'
    e o dblclick do navegador se perdia; Shift+2 cliques no titulo dobra. Gestos com teste em tests/dash_gestos.py.
  2026-11-17 MINI TV (aprovado: design/mini-tv.html, historico/PROMPT_ESTETICA.md, artefato "PRISMA — plano da mini TV + inventário"; substitui
    o "NO' = CARD PLANO" abaixo): no' de ATOMO = mini TV de plastico (.bx.tv, TV_W fixo; mais de 3 knobs alarga), gabinete = a FAMILIA
    (fam-<cat>: decoracao em .skin + halo/eco/VU), tela em cima (.win > .crt > canvas.lv) na proporcao da imagem do no' (= a do PALCO,
    tvAR: o motor entrega cada no' no tamanho do palco; a fonte crua nao chega ao dash), IN/(B)/MASC empilhados na borda esquerda, OUT
    na direita, FADER de opacidade no meio (tvConn, id bar:...:opacity de sempre; com movimento volta a ser knob), knobs numa fileira
    rente ao pe' (nodeKnobs 'row', corpo fisico .kb por CSS girado por --ka; com movimento a TAMPA brilha na cor do controlador) e o
    jack de CV de cada knob (.kj) sai por BAIXO. Altura = tvH (o card recebe ela como height). Liga = esfera de vidro (cor: roda girando).
    Jack FLAT (::before = a porca; ligado = o plugue na cor do cabo); cabo = cableD (sai na direcao do jack e cai com o peso) + sombra e
    brilho como tracos (sem filtro). FONTE/MISTURA/SAIDA = prata (a tela no lugar da miniatura). CONTROLADOR = caixinha do envelope:
    osciloscopio (SCOPE, sinal vivo) + a faixa de/ate de ate' 2 knobs ligados (ctlRange = rangeCtl, a faixa continua MORANDO NO KNOB);
    jack de CV em cima; nasce EMBAIXO do no' com o jack sob o knob (ctlSpot). Clicar no NOME so' escolhe; trocar = ↻ (aparece no mouse).
    TEMA (botao "visual" do canvas): foto-real | cel (body.cel: desenho chapado proprio de cada peca, contorno, 3 tons, recorte frio,
    sombra roxa, reticula; a IMAGEM das telas nunca muda com o tema — 2026-11-17, pedido) + LEVE (body.leve: sem grao, decoracao, sombra grande, animacao; cabo = 1 traco).
    Fica no localStorage v5tema (preferencia desta tela, como zoom/cabos/MIDI; o tuning e' o show). Animacao so' em modulo LIGADO.
    DESEMPENHO: texturas = PNG gerado uma vez (texturas() -> --t-*), nenhum filtro SVG ao vivo por no'; rolar a vista NAO refaz os fios
    (so' reposiciona o inspetor). Medido no teste "desempenho" (tests/dash_gestos.py).
  2026-11-17 (2a rodada, pedidos do usuario no app): JACK VISTO DE CIMA (porca + furo no painel, um pouco pra dentro da borda; ligado ou
    nao e' o MESMO jack) e CABOS COMO NO VCV: o cabo pluga no CENTRO do jack, cai reto com o peso (quadratica + caimento, cableD) e o
    PLUGUE redondo na cor do cabo e' desenhado na camada dos cabos — que agora fica POR CIMA dos nos (SUBSTITUI "cabo por baixo dos nos";
    girando um knob os cabos somem como antes; opacidade no "cabos"). O CLIQUE no cabo fica no #cv-hits, POR BAIXO dos nos (um cabo
    passando por cima de um knob nao rouba o clique dele). CLIQUE numa SAIDA com cabo = PEGA o ultimo cabo dela (solto noutra saida =
    vem de la'; no vazio = tira; Esc volta); SHIFT + clique = cabo NOVO. Saida do envelope (controlador) no MEIO do topo. CV do knob =
    jack no pe' do painel (TV_FOOT). SIMPLES: sem "opacidade" escrito, valores so' ao mexer/mouse, sem selos de movimento no no' (a
    tampa acesa diz), modo de mistura das entradas so' no painel, sem reflexo/linhas no vidro. PREVIA: o MESMO canvas sobrevive ao
    renderBoxes (liveCv: nada pisca preto no zoom/clique), so' as que estao na vista sao pedidas (8 qps); o native passou a mandar 360 px
    e a previa do no' SAIDA = a imagem DELA sozinha (antes: o palco ate' ela). Fundo da mesa no #cvw (o PROGRAMA "fundo" aparece).
  2026-11-17 (3a rodada): COR DO CABO = aleatoria por cabo (cableColor: paleta sorteada pela assinatura, estavel; cabos do mesmo no'
    diferentes); a tampa do knob acende na cor do cabo que chega nele. Cabo VCV = contorno escuro da propria cor (.ws) + nucleo; plugue
    = aro escuro + corpo na cor + furo. Mexendo em knob/botao os cabos ficam a 20% (nao somem). Envelope: jack no CANTO SUPERIOR
    DIREITO, compacto (o osciloscopio ocupa a sobra), arrasta por qualquer parte. Mascara ligada por cabo nao aparece escrita no card.
    No' de atomo mais compacto. MIXER (substitui a "mistura" nova): no' kind 'mix' com `jacks` (versoes 2/4/8 no menu/roda), uma linha
    por jack (jack + fader de opacidade + olho), a entrada fica NO JACK (camada.slot; o servidor guarda slot/jacks), jack de CIMA = NA
    FRENTE (a lista vai de tras pra frente: slot alto primeiro), mistura normal (a de tras so' aparece abaixando a da frente). A SAIDA
    tem UMA entrada (o cabo novo troca); saida antiga com varias entradas vira um MIXER na frente dela (outOneInput, no graphFix).
    Mistura antiga sem `jacks` continua como era (camadas + "+ entrada").
  2026-11-17 (4a rodada): cabos ESMAECEM suave (mexendo em knob: 45% em .3 s; hover de no': troca as classes NO LUGAR com transicao, sem
    refazer os fios). MIXER mais comprido (linha de 52 px, MIX_ROW_H; tela igual) com a SAIDA no canto de BAIXO a' direita (MIX_FOOT).
    ENTER no MONTAR = a lista de modulos (a roda) onde o mouse esta' (como o VCV; digitar procura); no TOCAR continua liga/desliga.
    Proximo: historico/PROMPT_VCV_LAYOUT.md (distribuicao inspirada no VCV + modulos "filho").
  2026-11-17 RODADA VCV (historico/PROMPT_VCV_LAYOUT.md; design book "PRISMA — design book: distribuição e filhos" = design/vcv-layout.html, db
    `escolhas`; a rodada 2 do book ficou sem marcas -> usadas as opcoes padrao dele). SUBSTITUI a distribuicao da MINI TV acima (a pele
    nao muda). C COMPACTA (tvGeo): LINHA 1 = liga + FADER de opacidade EM CIMA da tela (.r1); a TELA entre o TRILHO de jacks a' esquerda
    (in, b, másc, rotulo embaixo; TV_RAILX/TV_RAIL0/TV_RAILD) e a ABA escura da saida a' direita (.otab, OUT no pe' dela); o NOME logo
    abaixo da tela (.bh, 16 px, numero a' direita; arrastar continua por ele); os knobs (rotulo 11 px minusculo, nunca cortado; CV
    embaixo de cada um). Sem parafuso. Fonte/mistura/mixer/saida: tela em cima (sem a linha 1), aba a' direita, nome embaixo. VU do
    gerador = na linha 1. TV_W = 252 (COL_W 324).
    MODULOS FILHO (filKids/filSpec/filEl): toda ESCOLHA e toda CHAVE sem movimento sai do card; 2 opcoes = duas TECLAS, 3+ = SELETOR com
    a lista acesa (knob aponta, clique avanca, Shift volta, clique no nome escolhe), chave = uma TECLA. O FILHO e' a ENTRADA e o PAI a
    SAIDA: cabo PRESO (curto, grosso, na cor da familia, plugue com anel de trava; sem alvo de clique) da aba OUT do filho ate' o jack da
    OPCAO no trilho do pai (.port.opj, rotulo em cima, na linha dos CVs). Motor igual: o valor e' o fx do atomo, mesmo id de controle
    (bar:<no>:<id>:<knob>, o MIDI segue). O filho mora DENTRO do elemento do pai (left/top relativos): arrastar o pai/a selecao leva
    junto; arrastar o filho grava s.filhos[knob] = [dx, dy] (servidor: _norm_overlays). Sem lugar = a' esquerda, o OUT na altura do jack.
    A PEGADA do no' (rectOfNode: sem sobrepor, arrumar em colunas que abrem espaco pros filhos, ctlSpot, caber tudo) inclui os filhos.
    ZOOM 2%..200% (CVZ_LIM), SUAVE (zoomFrame em rAF: so' --cvz, tamanho do mundo e rolagem; nada refeito) e centrado no cursor. NIVEIS
    (zlOf): perto >= 130% | normal | longe <= 70% | BLOCO < 28% (no' = bloco liso na cor da familia --blk, nome que encolhe ate' caber
    e some se nem a 8 px couber, a tela PARADA no ultimo quadro) | PONTO < 9% (so' a cor). De longe: pecas display:none, cabos finos
    (2 px na tela via --cvzi = 1/zoom), sem plugue; o cabo vai pra borda do bloco (portXY/cvEnd sem o jack); nenhuma previa pedida.
    CABER TUDO = H (a tecla de cena no H vem antes) ou o botao ⤢: enquadra o patch; de novo = volta pro zoom e o lugar de antes.
  2026-11-18 RODADA 3 (pedidos do usuario sobre a rodada VCV; SUBSTITUI o que contradiz acima):
    FILHO NA CORRENTE: o filho e' a ENTRADA de verdade — a corrente (fio A do pai) chega no IN do filho mais longe (filKids head; o
    IN dele E' o inPort 'a' do pai, dentro do .fil: inPortEl/cableTarget acham), passa filho a filho e chega no IN do pai. Saiu o jack
    da opcao (.port.opj) e o cabo preso: no lugar, a LIGACAO FIXA = trilha rigida (reta, cotovelo reto, sulco no meio, terminais
    QUADRADOS; .lkb/.lkc/.lkg) sem area de clique; as pontas (OUT do filho, IN do filho seguinte, IN do pai .lk) engolem o clique (antes
    pegar a "ponta" arrastava o pai ou o filho). Lugar padrao: em linha, a' esquerda, na altura do IN do pai (TV_RAIL0).
    ZOOM SEM RELAYOUT: a animacao so' mexe no transform do #cv-in (zTf/zoomVis; o zoom do CSS refazia o layout inteiro, ~80 ms por
    quadro, e o dash todo — envelopes, knobs vivos — parava junto). O zoom de verdade entra UMA vez no fim, sem pulo. Arrastando
    algo, o zoom anda do jeito antigo.
    ARRASTO LEVE: drawBoxWires guarda cada cabo em WLIVE (pontas + geometria + elementos); arrastar no'/controlador/filho so' refaz os
    cabos de quem anda (wiresFollow), um passo por quadro (rafMove); wireNear amostra os fios uma vez (wnCache). O cursor de arrasto
    nao usa mais 'body.dragging *' (refazia o estilo da pagina inteira ao pegar, ~60 ms).
    LEITURA: todo texto do gabinete numa ETIQUETA lisa na cor clara do painel (--lbl = --pl1; cel = branco): nome, rotulos e valores
    dos knobs, rotulos dos jacks, entradas do mixer. Fileira dos knobs 82 px (TV_KROW) e pe' 38 (TV_FOOT): o valor nunca embaixo do
    jack de CV. MIXER: jack dentro do gabinete, o NOME da entrada (vazia = "livre") na etiqueta, sem numero (pedido), linhas lisas. NOMES sem o numero do no' no
    canvas (mixShow/visName: "MIXER", nao "mixer 16"; a saida fica com o dela = a tela); o numero continua no canto, avisos e MIDI.
  2026-11-18 RODADA 4 (SUBSTITUI o trilho ao lado da tela): atomo/fonte = TELA NA LARGURA TODA (tvGeo low); os jacks de imagem descem pra
    linha dos knobs (tvJacks): IN/B/MÁSC numa coluna a' ESQUERDA dos knobs, de baixo pra cima (o de baixo na linha dos CVs, o IN na altura
    do knob; RAILD 48), rotulo EM CIMA de cada jack; OUT a' DIREITA na altura do knob, no pe' da aba escura; fonte: másc ... OUT na
    ultima linha. Jacks a' 31 px das bordas (RAILX/OUTX, pe' TV_FOOT 50; mixer/saida: jack a 18 px). Knob SEM porcentagem (o valor so'
    girando, plaqueta solta). ETIQUETAS REALISTAS: plaqueta em relevo (chanfro, sombra curta) e letra gravada (--lbt). ARRASTAR POR
    QUALQUER PARTE (nodeGrab; so' os controles de NODRAG fazem a coisa deles; a tela inclusive). ARRUMAR POR SETOR (tidyPlace): uma
    faixa por RAIZ (fonte/gerador, na ordem de cima pra baixo), cada no' na media dos setores de onde vem (as duas = entre), colunas
    centradas na faixa (a fonte no meio do setor), saidas na ultima coluna.
  Pesquisa e desenhos: Claude Doc "PRISMA v5 — canvas de camadas de átomos". Decisoes aprovadas (2026-10-24):
  - QUATRO PALAVRAS: fonte, CAIXA, ATOMO, SAIDA (a mascara e' parte da caixa). CAIXA = uma fileira do OVERLAYS
    (o Rack do Ableton / um COMP do TouchDesigner): uma entrada (fonte ou o FIM de outra caixa, file '@<id da caixa>')
    -> atomos em pilha vertical (a cadeia) -> mascara -> uma saida, que pode alimentar varias caixas (ramo).
  - CABOS COMO NO VCV RACK (2026-11-01, historico/PROMPT_CABOS.md, aprovado; substitui "fios so' entre caixas", "so' a ponta no ar",
    "SAIDA = um no' fixo" e a lista "entrada B" do inspetor). Pesquisa: manual do VCV ("drag from port to port", "move or
    delete an existing cable by dragging one of its plugs", tensao/opacidade globais no menu View), Advanced Output do
    Resolume (slice com entrada = uma camada), Group/Return do Ableton (summing container com efeitos), clone do
    TouchDesigner e send/receive do Max ("Show others").
    · ENTRADAS com nome na BORDA ESQUERDA do no' (A = a corrente, B = a entrada B do atomo, mascara = Luma, 1..N + "+" nos
      mixers): cada uma aceita UM fio (ligar em cima troca). SAIDA na borda direita: VARIOS fios, puxar sempre cria mais um.
    · CLICAR numa bolinha = o fio GRUDA no cursor (cableStick): o proximo clique numa entrada liga; no VAZIO abre o MENU
      (nodeMenu: atomos com busca, no' vazio, staging, saida, espelho) e o no' nasce ali ja' ligado; Esc cancela. Arrastar
      faz o mesmo. Puxar uma ENTRADA ligada pega a PONTA: outra entrada = mover; vazio/fora = apagar. Entrada vazia = fio ao
      contrario, ate' uma saida. Clique no fio + Delete (ou o x perto da entrada) tira.
    · Nada sai do ar sozinho: um no' alimenta ao mesmo tempo outros nos, stagings e saidas. Juntar imagens = STAGING.
      LACO (A -> B -> A) aceito: o fio que fecha le o QUADRO ANTERIOR (tracejado), como o LocalIn/LocalOut.
    · CABO: cor = a do no' de onde sai (a marca do espelho usa a mesma); POR BAIXO dos nos (no VCV e' por cima: aqui, de
      proposito, nada cobre um knob); a curva sai pra fora do proprio no' (bolinha na borda); girando um knob os fios somem;
      mouse num no' acende os fios dele e apaga os outros; mouse no fio acende ele e as 2 pontas. TENSAO (quanto cai: 0 = reta)
      e OPACIDADE = globais no topo do canvas, por modo (LS v5cable), como o zoom.
  - STAGING = no' mixer (kind 'mix'): N entradas = camadas (opacidade, modo, liga/desliga, ordem pela alca; em cima = na
    frente; movimento e entra/sai por evento no inspetor) + atomos DEPOIS da mistura; o vazio e' transparente (entra como
    UMA camada noutro mixer). SAIDA (kind 'out') = o mesmo mixer sem saida, com lugar no palco: Saida -> "Saidas no palco"
    (retangulos sobre as telas, com o palco ao vivo ao fundo; 2 cliques = entrar e posicionar cada entrada dentro dela).
    Cena antiga: o que estava no ar vira entrada da "saida 1" (migrateGraph = dash_data.migrate_graph).
  - ESPELHO de um atomo: o MESMO atomo (knobs e movimentos do original) agindo em outro lugar (corrente, staging, saida):
    chip com o icone + a marca de cor do original, sem knob nem texto; nome no title; clique leva ao original. Cria: menu do
    vazio ("espelho ·"), botao no inspetor, Alt+Shift+arrastar o atomo. ALT+ARRASTAR (2026-11-16) = COPIA SOLTA (sem fio nenhum); soltar um no' (ou copia) NUM FIO = entra no meio dele. Original tirado = o 1o espelho vira o original.
  - NÓ = ÁTOMO (2026-10-28, aprovado): cada atomo e' um NO' do canvas (estilo TouchDesigner): no' de FONTE (sem atomo) ->
    no' de EFEITO (1 atomo, le o anterior '@id') -> ... -> SAIDA. Todos os knobs do atomo ficam SEMPRE abertos no no'.
    normalizeNodes() mantem a forma: caixa com varios atomos (cena antiga, colar, inserir) vira corrente; a PONTA herda a
    camada no ar (AIR_PROPS) e a mascara; quem lia o fim le a ponta. healRemove(): tirar um no' fecha a corrente e a mae vai
    pro ar se ele era a ponta; no' de efeito sem atomo e sem mascara some (dropEmptyNode). topoOrder(): no' depois de quem
    ele le (render sem atraso). Inserir/mover/recortar atomo = as mesmas operacoes de antes + normalizar. Clique no
    cabecalho = o atomo (inspetor: atomo + "o no'"). Knobs do no' = REDONDOS no card (nodeKnobs, 2026-11-01): principal primeiro
    e maior, azul = tem movimento, escolha/chave numa linha embaixo; ids 'bar:' de sempre (MIDI aprendido continua).
  - CINCO TIPOS DE CONTROLE, um visual cada (2026-10-28): KNOB = valor continuo (knob/barra); CHAVE = liga/desliga (.sw:
    switchCtl/swEl — knob que o shader so' le como step(0.5), on_*, preencher, auto-nivel, rebate, som do video, tom);
    ESCOLHA = um entre N (choiceCtl: ate' 4 chips, mais = lista; knob que o shader le como floor(x * N), nomes em
    "// opcoes:"); CONJUNTO = varios entre N (chips .on: fontes de um movimento, faixas); ACAO = botao. Chave/escolha
    continuam 0..1 no fx (o motor nao muda) e aceitam movimento (o ♪ volta o knob).
  - (2026-10-28, SUBSTITUIDO em 2026-11-01 pelos CABOS VCV) "tudo acumulativo, so' a ponta no ar": fio do FIM tirava a
    caixa da SAIDA. Ficou: a bolinha de saida do ATOMO do meio (port.aout) numa caixa antiga com varios atomos; a mascara de
    outra caixa = atomo Luma com ins ['@id'] (agora pela bolinha "mascara").
  - CAIXAS LIVRES, ima na grade (12 px) e botao ARRUMAR (coluna = quantas caixas antes, esquerda -> SAIDA). Mover nunca
    religa nada (a "ligacao fixa" da v4). Sem lugar guardado (cena da v4) = arrumada sozinha.
  - (2026-10-24 -> 2026-11-01) a SAIDA fixa na direita virou no' do canvas (STAGING/SAIDA, acima); varias JANELAS = BACKLOG.
  - MASCARA = atomos (// cat: mascara: Assunto U2-Net, Brilho, Cor) numa faixa no pe' da caixa (Matte TOP / entrada de
    mascara do Nuke e do Fusion): o resultado da caixa so' aparece dentro; fora passa a ENTRADA da caixa, ou fica
    transparente com RECORTAR (as caixas de tras aparecem). Varias = 'e' (todas) ou 'ou' (qualquer). Sumiu o chip
    tudo/assunto/fundo de cada efeito (region da v4 ainda roda; o inspetor oferece passar pra mascara da caixa).
  - MINIMALISMO: na caixa cada atomo mostra o nome + a barra do knob PRINCIPAL; clicar de novo abre no lugar os ate'
    2 detalhes. Inspetor (direita) = principal grande + detalhes + B + modular + estrela; o raro (modo, le a crua,
    so' na batida) fica em "mais".
  - SEM ABAS SHOW/MONTAR: um CADEADO (F1/F2). Travado = palco: o canvas encolhe e trava (so' tocar escolhe e mexer as
    barras), PROGRAMA/PROXIMA/controles publicados grandes, biblioteca some. Equipamento: 8 abas -> 5 (Entrada = audio +
    imagem, Saida = saida + telas, Luzes, Biblioteca, Controle = MIDI + teclas).
  - Da v4 ficam: cabine escura (saude), SOCORRO + BLACKOUT, cor = estado (verde no ar, laranja escolhido, azul MIDI/
    modulado, roxo mascara, vermelho perigo), icones SVG, previa fora do ar ao arrastar, variacoes, moduladores como peca
    (LFO/som/imagem/macro soltos num atomo ou knob), modificador paralelo (atomo solto EM CIMA de outro), publicar.
    Sairam: fileiras + zonas por fileira, fim de fileira por fileira, grupos (a caixa ja' e' o grupo), regiao por efeito.
  - NO' = CARD PLANO (2026-11-02; historico/PROMPT_VISUAL.md). O "modulo de synth" (parafusos, placa clara, rodape, plugue, fonte condensada
    em caixa alta, larguras em HP) foi feito e REVISTO no mesmo dia: pesado, ocupava espaco e lia pior. Dos mockups A/B/C ficou o A:
    o card de antes + so' o que resolve problema. ENTRADA = anel vazado, SAIDA = circulo cheio com setinha (a' primeira vista); o nome
    do jack fica POR DENTRO do no' (no vao de 24 px a' esquerda), longe do cabo; jack de mascara = anel roxo no canto de baixo, nome no
    hover. LED "no ar" no lugar do selo NO AR (+ LED de estado e de laco). Knob principal 44 px, os outros 32 (coluna 58 + 3 x 53 px:
    nenhum alvo menor que 53 x 67). Escolha ate' 4 no no' = seletor curto em linha (chseg). Linha fina da cor da cat: no topo do no' de
    atomo (CAT_COLOR, tons apagados). SAIDA achada pela cor verde do cabecalho; staging com cabecalho cinza. Cabos finos, sem plugue.
    No palco: some o nome do jack. Desempenho: cvZoom() = cache do applyLayout e o tamanho da vista vem do ResizeObserver (ler os dois
    no meio do renderBoxes forcava estilo + layout), LED de laco por mapa (readsMemo), autoPlace sai cedo quando todos tem lugar.
  - ENTRADA VAZIA (NO_IN = '@-'): apagar a FONTE de um efeito, ou puxar o fio da entrada A pro vazio, deixa o no' "sem entrada" (jack
    A livre; o motor deixa ele de fora). Antes voltava a ler a fonte do comeco e o efeito virava uma fonte nova.
  POR QUE CADA ELEMENTO EXISTE: (P) palco, (S) seguranca, (C) montagem. Topo: TOCAR|MONTAR (S: era o cadeado), musica (P/S), avisos (S),
  equipamento (C), EFEITOS/MASTER (P), SOCORRO + BLACKOUT (S). Esquerda: cenas (P), biblioteca (C). Centro: canvas (P: o
  que esta no ar; C: montar) + SAIDA (P: o fader de cada caixa). Direita: PROGRAMA (S), PROXIMA+GO/PREVIA (P/S),
  CONTROLES (P), MACROS (P). Gavetas: socorro (S), equipamento (C).
  TAMANHOS (2026-10-27): divisorias entre as 3 colunas (arrastar; 2 cliques = padrao) e zoom do canvas (- 100% +, Ctrl+roda),
    guardados POR MODO neste navegador (localStorage v5layout). ARRASTO: todo arrasto do canvas passa por follow() (solta com
    pointercancel/perder foco/Esc) + swallowClick() (so' o clique daquele tique); perto da beira o canvas rola e as zonas
    de soltura sao medidas de novo (placeZones).
  MOVIMENTO (2026-10-27, Claude Doc "PRISMA — sync com a música"; aprovado): 3 tipos (IMAGEM, SINAL 0..1, EVENTO) e 7 regras
    (tudo vira sinal; sinal so' entra pelo KNOB, knob nao mexe knob; knob = FAIXA lo->hi, lo>hi inverte = ducking; movimento =
    fonte -> modo -> forma; evento so' dispara; acao discreta cai na GRADE; mesmo id = o mesmo movimento). Modos loop (LFO) |
    disparo (envelope num evento, com condicao A:B/%/a cada N) | segue (seguidor com ataque/soltura). O movimento MORA NO KNOB
    (nao e' no com fio): o botao do knob abre os PRESETS (1 toque: pulsa, respira, anda, passos, acaso, segue o grave, estoura
    no drop, abaixa no kick; o // mod: do atomo sugere e aparece primeiro); "abrir..." mostra modo/forma/evento/fontes/quantidade.
    (2026-11-04, SUBSTITUI "nao e' no' com fio": pedido "a cor e' mexida por um atomo de cor e a alteracao de valores por OUTRO
    no' que controla ele") todo movimento tem CORPO: um CONTROLADOR no canvas (pilha CTL_KEY '~ctl', id = o do movimento; o
    knob guarda receita + a faixa dele, o motor nao muda) com saida em losango e cabo tracejado ate' a altura do knob. Puxar o
    losango ate' um knob liga; clicar no cabo + Delete solta; tirar o controlador devolve os knobs. Controlador solto = arrastar
    um da biblioteca ("Controladores") pro vazio. Preset tocado num knob cria o controlador dele (syncCtls).
    RECEITAS (2026-11-04): os Classicos sairam da biblioteca (rodam nas cenas antigas) e voltaram como corrente de atomos +
    controladores (shaders/receitas/*.json, /receitas). Ferramenta (padrao de teste) fica em "Ferramentas".
    Painel MOVIMENTOS (era Macros): M1-M4 + cada movimento da cena com o sinal VIVO do motor (SSE mv); passar o mouse acende o que
    ele mexe; arrastar ate' um knob = segue o mesmo. Opacidade (atomo e caixa na SAIDA) aceita movimento. Caixa: entra/sai sozinha
    num evento (acao). GRADE: liga/desliga de atomo/caixa espera batida/compasso/frase (/grid; tracejado piscando = esperando;
    Shift = na hora). Bloco da musica: tracos da FRASE + SECAO; clique = TAP, x2, /2, "1", empurrar, 1 da frase, forcar secao.
    ZOOM SEMANTICO (+ / -, Ctrl+roda; tambem no meio de um arrasto: zonas e caixa remedidas): longe = so' estrutura, perto = o
    movimento de cada knob escrito e vivo. SOCORRO: congelar movimentos.
  TECLADO: 1-9 caixa (segurar = liga/desliga na SAIDA), setas, Enter, Espaco = GO, Delete, '.', Ctrl+Z, letras = cenas,
  + / - zoom, Shift = na hora (com grade), F1 = TOCAR / F2 = MONTAR, Esc fecha.
  RODADA 6 (/v6, 2026-11-18, noturna; diario e PNGs em historico/RODADA6_PROGRESSO.md / design/rodada6): hzLayout = GRADE de colunas centradas
    (OUT no meio da altura) dentro da AREA UTIL (hzUseful: sem invadir o relevo; grade de 4 px; texto >= 10 px em plaqueta). Fader de
    opacidade COMPRIDO colado na tela, jack do alterador embaixo (mixer/saida: jack na ponta do fader da linha). KNOB-JACK (variante A):
    a tampa e' a porca do jack — saia gira, centro = cabo (livre: puxa ao contrario ate' um alterador); ligado so' mostra. A FAIXA
    de/ate' muda NO ALTERADOR (pontas, meio = as duas, roda, 2 cliques = padrao; o knob e o painel dele so' mostram). Roda = familias
    dos gabinetes com o material (G6.swatch). SELETORES: chave = tecla (S3); 2-4 = fader de entalhes (S2); 5+ = rotativo (S1); a
    escolha ligada continua seletor (acende a opcao viva).
  2026-11-26 (pedido: "arrastar os cabos no note e' muito ruim"; plano no Claude Doc "PRISMA — plano geral: gestos, estetica e
    fluidez"): CABO = CLIQUE PEGA, CLIQUE SOLTA em TODO cabo (imagem e controle). Clique sem arrastar (ate' CLICK_PX = 8 px: o clique
    do touchpad anda) = o cabo fica NA MAO; o proximo clique esquerdo decide (knob = liga; Shift = junta mais um knob; vazio = solta
    os juntados / tira a ponta pega), o DIREITO ou Esc cancela, o do MEIO anda a vista, a roda so' faz zoom (nada gira no caminho) e a
    ponta fica sob o ponteiro quando a vista anda. Clique no centro do knob ligado = PEGA a ponta (antes: escolhia o cabo; escolher =
    clicar no proprio cabo). Arrastar continua valendo igual. Teste t6_cabo_clique_clique.
  FASE 0 do plano (2026-11-26, "faca a fase 0 inteira"): FIO RECEBE MODULO — modulo de atomo SOLTO (A vazia, ninguem lendo) arrastado
    sobre um fio de imagem acende o fio; soltar = entra no meio (nodeOnWire) e quem estava em cima abre espaco DESLIZANDO (declutter +
    SLIDE, 220 ms). Modulo LIGADO so' anda. SACUDIR (4 viradas >= 24 px em 0,7 s) = sai da corrente (spliceOut; a A dele fica vazia) e
    pode entrar noutro fio no mesmo arrasto. RODA: girar knob/fader/seletor/faixa SO' COM ALT (quase-modo); sem Alt a roda mexe na vista:
    touchpad (1o evento do gesto com deltaX ou passo < 40) = ROLA, pinca (wheel + ctrlKey) = zoom, roda do mouse = zoom. MOSTRAR EM VEZ
    DE AVISAR: mexer num controle ligado pisca o ALTERADOR dono dele (pointAt; texto so' se ele estiver fora da vista).
    Testes t6_fio_recebe_modulo, t6_sacudir_solta, t6_touchpad_rola.
  ACABAMENTO (2026-11-26, pedido: "cabos expandir pra direita nao tem sentido, manter os botoes parados" + "embelezar tudo, muito mais
    bonito, agradavel e impressionante sem perder simplicidade"; fotos antes/depois em design/acabamento/). Pesquisa: Comeau "designing
    shadows" (uma luz so', sombra em camadas na cor do fundo), Linear "a calmer interface" (a moldura recua, menos borda, cinza menos
    azul), Blender HIG (editor de nos que rola nos 2 eixos = grade de PONTOS), VCV "light bloom" e o modulo Clarity (cabo aceso mostra a
    direcao). REGRAS: (1) UMA LUZ, de cima: sombra cai pra baixo, brilho so' na borda de cima (softShadow/bevelEdge nos sprites, knob,
    plugue, cabo); (2) PROFUNDIDADE MACIA: 3 camadas de sombra (SHADOW_PAD = a margem do sprite); arrastando, o modulo SAI DA MESA
    (liftShadow); (3) A MOLDURA RECUA: barra/cabecalho de menos contraste, HUD discreto (sem "v6 · jogo"), TAMPA = acrilico fume com a
    faixa de aviso so' no pe' (o texto aparece com o mouse); (4) A MESA: luz no meio + vinheta (#cvw) + grade de pontos presa ao mundo
    (drawDots = a camada CSS #gdots, que so' DESLIZA: pintar no canvas a cada quadro custou 60 -> 44 fps; o PROGRAMA de fundo cobre); (5) LUZ QUE BRILHA: LED com halo (led(): liga, no ar, eventos acendem e apagam em 260 ms),
    anel de escolhido com brilho (selRing), knob com o TRILHO do curso e o arco com borda escura (le' no painel claro), cabo aceso
    (mouse no no'/cabo, escolhido) com o SINAL ANDANDO da saida pro destino; (6) NADA ANDA SOZINHO: CABOS abre por cima (cablePop),
    zoom/cenas/desfazer com largura fixa. Leve = sem sombra macia, halo, brilho nem sinal andando. Nada muda a IMAGEM das previas.
  PODA + PEDIDOS (2026-11-26, tarde; SUBSTITUI o que contradiz acima, inclusive "SEM ABAS SHOW/MONTAR: um CADEADO" e o TOCAR|MONTAR do topo):
    UM MODO SO' ("toca nessa tela mesmo, tipo um VCV"): sairam o TOCAR|MONTAR, F1/F2, o layout de palco e os controles PUBLICADOS (a estrela;
    o `pub` antigo fica nas cenas, sem uso); `mode` = 'montar' so' como chave das preferencias por modo. MISTURA saiu da barra (o mixer vem
    da roda, "Mistura e saida"); CABOS = um icone no grupo do zoom; SOCORRO = so' a boia, sem tampa (acende amarelo/vermelho com problema;
    "abrir a v3" saiu). TROCAR A FONTE NO CANVAS: o "+" no fim da bandeja abre ali a lista de fontes (srcPick; escolher = toca e entra na
    bandeja). COR QUE NAO MUDA: a cor do cabo vem da identidade com o ID da fileira (cableKey), a mao leva a cor do proprio cabo e o cabo
    religado fica com ela (CABLE_PIN). INVERTER no alterador (tecla com o desenho do envelope, no fim da linha do "o que segue"): de > ate'
    em todas as ligacoes (ctlInvert; o motor ja' le invertido), a ligacao nova de um invertido nasce invertida, o osciloscopio desenha
    descendo. Evento sem modulo de origem (secao, pad) = o nome numa plaqueta FORA do modulo (evName), nao mais por cima do osciloscopio.
    Testes t6_cabo_cor_fixa, t6_inverter_alterador, t6_trocar_fonte, t6_modo_unico, t6_botoes_parados.
  REVISAO DA PELE (2026-11-26, "revisao completa da estetica"; fotos de TODAS as superficies antes/depois em design/revisao/, tiradas por
    tests/estetica.py): havia DUAS linguagens — a de hardware (canvas, barra) e a "web escura" (gavetas, popups, listas, selects nativos).
    Agora tudo que FLUTUA (gavetas, cenas, tempo, listas da roda, janela do PROGRAMA) tem o MESMO material do painel do modulo (--pnl:
    metal escuro, borda fina, luz em cima, sombra em camadas), titulo em letra de painel; CAMPO = poco afundado (--well), SELECT sem a seta
    do sistema; TECLA = a da barra (sem caixa alta dentro dos paineis); segmentado = poco com a tecla acesa; a escolhida da lista = filete
    laranja (nao bloco); a RODA escurece o resto da tela; os faders EFEITOS/MASTER com o mesmo corpo; o "." do BLACKOUT numa tampinha;
    "CANVAS" escrito saiu; BIBLIOTECA: renomear/apagar so' com o mouse em cima, cartao de grupos legado some vazio; TECLAS: a tecla numa
    tampinha em coluna propria. SINAL = AMBAR tambem no painel (o editor de movimento era azul, a cor do "modulado" da era do cabo sorteado;
    azul = imagem e MIDI). CONSERTO achado na revisao: o onEqShow ainda usava os nomes das 8 abas velhas — CONTROLE abria vazio (MIDI e
    teclas) e as TELAS da SAIDA nao redesenhavam; ajuda das teclas sem TOCAR/MONTAR e com o Esc segurado. Teste t6_equipamento_abas.
  REPAGINADA (2026-11-27; design book "PRISMA — repaginada" = design/repaginada.html + db de escolhas; SUBSTITUI o que contradiz acima): proposta
    B "CANTOS". A BARRA DO CANVAS (#cv-h) SAIU (+48 px de patch). BARRA DE CIMA = o que se TOCA: musica, TAP, a CENA num poco (◀ volta | cena ▾ |
    ▶ vai = a de antes / a seguinte NA LISTA, da' a volta; "próx" = a PROXIMA, clique desmarca; GO acende com proxima), EQUIPAMENTO, EFEITOS,
    MASTER, a BOIA (os avisos de saude moram NELA: o numero de problemas + a lista no titulo; os chips #ann sairam), BLACKOUT. A VISTA = PILULA
    no canto de BAIXO a' direita (#cv-nav: desfazer N | − % + | caber | ⋯); o ⋯ abre POR CIMA dela: ARRUMAR, CABOS (tensao, opacidade) e o
    PROGRAMA (monitor | fundo | recolher). PROGRAMA = MONITOR preso no canto de baixo, EM CIMA da pilula (v6pvw; arrastar solta; "monitor" volta
    pro canto); ▾ recolhe numa ABA "NO AR" no mesmo canto. HUD de fps mais apagado. O botao "visual" (temaPop) saiu (tema unico).
    CENAS NO MIDI (pedido): Equipamento › Controle tem um botao por alvo (◀, ▶, GO e cada cena) que arma o learn sem fechar a gaveta (midiArm).
    MACROS = o modulo MAO (pergunta aberta respondida): da roda (familia Mao), um por cena (pilha MAO_KEY '~mao'); 4 FADERS M1-M4 (macroV,
    /macros, MIDI 'macro:N') com jack REDONDO ambar e 4 PADS (um toque = pad:N na hora, /grid op ev; MIDI 'pad:N') com jack de EVENTO. Cada
    fader = um controlador de id fixo (MAO_IDS mao-m1..4, sinal {b: ['mN'], nome: 'MN'}) que nao se desenha: o jack e as FAIXAS de/ate' moram na
    MAO (os corpos entram em scene.ctls com c.mao; drawRows). Escolher (clique no corpo) + Delete tira tudo. Sairam da roda "macro M1-4" e
    "envelope: pad N". ENVELOPE E2 (pedido "mais realista estilo jack"): o GATILHO na coluna da esquerda com o nome em plaqueta (evento sem
    modulo de origem — secao — vira o NOME: a plaqueta solta "seção · drop" saiu); as DUAS SAIDAS juntas na placa ESCURA "OUT" (∿ sinal
    redondo, ½ comparador); INVERTER subiu pro canto de cima; CTL6.W 236. JACK DE EVENTO = jack de painel de verdade (evJackPaint: flange
    QUADRADA de metal + bucha com anel verde + furo), em todo lugar (relogio e som, envelope, MAO); plugue do cabo verde com corpo e pino
    (evPlug). Testes t6_botoes_parados (refeito), t6_programa_monitor, t6_cena_vai_volta, t6_saude_na_boia, t6_mao, t6_envelope_e2.
  PELES (2026-11-27; book "PRISMA — estéticas" = design/esteticas.html; pedidos: "faça todas podendo mudar", "no vaporwave o risco na tela nao
    pode interferir na leitura e mantenha a identidade dos modulos", "pesquise a fundo... priorizando visibilidade", "faça TUDO ESCURO"). Menu ⋯ ›
    pele (lembrada: v6skin). 10 peles, TODAS ESCURAS: Hoje (o de sempre, intocado), Nanquim, Grafite sobrio, Braun preto, Brinquedo noturno,
    Aero noturno, Vaporwave (cromo escuro), Brutalista escuro, Neon, Terminal. Uma pele = TOKENS (SKINS): o canvas pinta o gabinete (skinBody),
    plaqueta, rotulo, knob, jack, jack de evento, tela e cabo por eles; o HTML le' --k-* (barra, pilula, menu, monitor, mesa); trocar limpa os
    sprites (G6.reskin). PESQUISA (NN/g glassmorphism e neobrutalism, APCA/Myndex, foruns de plugin de audio KVR/FabFilter, kits de UI vaporwave,
    Rams/Braun, OP-1): (1) TEXTO SEMPRE EM SUPERFICIE SOLIDA — plaqueta ou veu, nunca direto no fundo decorado; (2) contraste por LUMINANCIA, nao
    so' por matiz: ponteiro claro em corpo escuro (o mais lido "de relance"), texto >= 4,5:1 e peca >= 3:1 (skinContrast; o teste cobra);
    (3) BRILHO so' em acento (LED, cabo, contorno) — nunca no texto; o halo do cabo e' um traco largo e fraco, sem desfoque (custo);
    (4) VIDRO com base opaca e reflexo so' em cima; (5) brutalista = borda 2-3 px + sombra dura sem desfoque; (6) Braun: acromatico, a cor
    so' na FUNCAO (GO/BLACKOUT laranja); (7) a cor da tampa liga o controle ao lugar (bolso/OP-1). FUNDO DECORADO = camada CSS PARADA (#cvw +
    #cvw::before): a grade do Vaporwave/Neon so' no rodape, fraca (12% de opacidade), em perspectiva e SUMINDO antes da area de trabalho
    (mascara); o sol do Vaporwave sem listras, baixo e apagado. IDENTIDADE: o MATIZ da familia (FAMHUE) tinge o corpo + a TARJA do topo
    (Neon/Brutalista: a BORDA e a sombra na cor da familia). Cabos e jacks continuam dizendo o TIPO em toda pele (o Terminal tambem). Fontes
    com reserva local (o app roda sem internet). Leve = sem sombra/reflexo. Teste t6_peles.
  CABER TUDO VOA (2026-11-27, "faça a animação do H mais suave"; antes PULAVA): flyTo = ease-in-out cubico, zoom em escala LOG, centro
    deslizando; 340-650 ms pelo tamanho do salto; roda/pinca/arrasto/+- cortam; reduzir movimento = pula. fit(true) (abertura/testes) segue
    na hora. Teste t6_barra_zoom (G6.flying).
  REVISAO GERAL (2026-11-27; book "PRISMA — revisão geral" = design/revisao-geral/ + db de escolhas; sem escolhas marcadas = as RECOMENDADAS,
    em rodadas pequenas). RODADA 1 (consertos): rotulo de FADER numa linha so', cortado com reticencias, nunca por cima do valor (o "BRILHO
    MAXIMO" cobria o 100%: o fader encolhia pra 80 px numa caixa de 260). Teste t6_fader_rotulo.
    RODADA 3 (canvas): IR ATE' = Ctrl+F (canvasFind: modulos e alteradores, sem acento; Enter escolhe e a vista VOA ate' ele; a mesma busca de
    novo = o proximo). G = ENQUADRA o escolhido (frameSel; de novo = volta) — o book dizia "H com algo escolhido": ficou H = sempre TUDO e G = o
    escolhido (Houdini), pra o H nao mudar de sentido conforme a escolha. RODA COM MODULO ESCOLHIDO (ou que acabou de deixar de ser: o 1o clique
    do "2 cliques" tira a escolha, selGone): o atomo/receita ENTRA DEPOIS dele — no fio que sai dele, se for um so' (fica no ar), senao lendo
    ele (wheelRef); o meio da roda diz "depois de X". ALVO >= 24 px NA TELA: jack 12/z de raio, centro do knob, teclas e cartuchos, knob
    redondo (WCAG 2.5.8). DE LONGE (< 42%) o NOME de cada modulo e alterador numa plaqueta de tamanho fixo na tela. DIREITO num FIO = menu
    (ir a' origem, ir ao destino, tirar); DIREITO num knob/fader/pad = "aprender MIDI" ali (midiArm) + abrir o painel (ctxMenu). Cenas: "próx"
    em cada cena da lista (antes so' clique direito/segurar). Testes t6_ir_ate, t6_roda_depois_do_escolhido, t6_alvo_24px,
    t6_enquadrar_e_nome_longe, t6_menu_direito, t6_proxima_visivel.
    RODADA 4 (biblioteca): UMA LISTA SO' — a roda abre JA' com a lista "procurar em tudo" e o cursor no campo (busca a' vista; as fatias
    continuam em volta pra quem navega); o CABO NO VAZIO abre a MESMA roda com "depois de <quem>" (nodeMenu = openWheel(ev, {ref, who}); sem
    Fontes nem alteradores, que nao leem o cabo; mixer, saida, no' vazio e ESPELHOS leem o cabo). ★ FAVORITOS (estrela em cada item) e ↺ RECENTES
    (8) no topo com a busca vazia (LS v6fav/v6rec). RECEITAS: das 19 de um atomo so', 18 trazem um MOVIMENTO (o book errou: nao sao o atomo com
    outro nome) — ficam, e a lista diz "+ movimento"; a Espelho (igual ao Espelhar) foi pra shaders/receitas/_arquivo/. MASCARAS: Fundo = o
    Assunto com inverter → "// oculto:" (cabecalho novo do atomo: RODA, cena antiga segue, nao aparece pra montar); Rosto/Olhos (modelos
    diferentes) e Brilho/Cor/Luma (entradas diferentes) nao juntaram. Alterador sem o "segue o grave" 2x. Equipamento › "Biblioteca" virou
    "ARQUIVOS" (gestao: enviar, renomear, apagar). Testes t6_lista_unica, t6_vazio_abre_menu (refeito).
    RODADA 5 (entrada de audio): ENTRADA SIMPLES (padrao; LS v6audio) | AVANCADO (as 8 faixas de sempre). Simples = VOLUME, KICK, GRAVE, MEDIO, AGUDO
    (grupos = dash_data.SOUND_GROUPS), cada um com DOIS medidores (claro = o que ENTRA; cheio = o que o ALTERADOR RECEBE, depois do limiar =
    band_gate) e UM controle: ganho (AMP_SCALE), limiar do kick (KICK_THRESHOLD), limiar do grupo (BAND_GATE das 2-3 faixas dele); AUTO-GANHO
    rapido/normal/lento = a memoria do teto de cada faixa (BAND_PEAK_DECAY 0,997/0,999/0,9999). PERFIL DE ENTRADA (POST /audio-perfil;
    tuning.AUDIO_PERFIS): salvar como / abrir / apagar o ajuste do som de uma casa ou fonte. SELO: musica COMPRIMIDA (volume alto e quase
    parado por ~8 s) = "use os ataques"; som muito baixo = "suba o ganho". NOMES EM PORTUGUES (BAND_PT: sub, grave, medio, medio-agudo,
    presenca, agudo, brilho, ar; amp = volume; rel/atk/mem = solta/ataque/memoria) — as chaves do motor nao mudaram. Teste t6_entrada_simples.
    RODADA 6 (pixel map): TELAO = ABA PROPRIA do Equipamento (as telas sairam da Saida; EQ_GROUP telas -> telao), passos "1 · Palco" (metros),
    "2 · Raster" (px que o telao recebe), "3 · Saidas no palco"; barra de LOAD-IN: TESTE POR BLOCO na saida real (native OUTPUT_MAP_SRC u_test:
    fundo na cor do bloco, grade 8x8, as 2 diagonais, uma diagonal que ANDA = quadro travado, o NUMERO em 7 segmentos e a borda de 1 px; POST
    /map-test; desliga sozinho em 5 min e ao sair da aba), IDENTIFICAR (o bloco da tela escolhida pisca 3 s), EXPORTAR PNG (palco + raster com
    nome/numero/medida: o gabarito do tecnico e de quem faz conteudo), CASA DE SHOW (POST /casa, tuning.CASAS = telas + raster + calibracao do
    telao), SETAS = 1 px no raster / 1 cm no palco, Shift = x10. Varias saidas/warp/borda suave = depois (P6). Teste t6_telao; selfcheck native.
    RODADA 7 (framework): ERRO DE ATOMO A' VISTA — o motor guarda o erro de compilacao POR ARQUIVO (output.shader_errors; antes o proximo que
    compilava apagava o aviso do quebrado, que seguia fora do ar) e o SOCORRO lista todos; na aba Arquivos o atomo que NAO RODA (quebra) e o que
    foge do padrao (⚠) aparecem com o motivo (antes sumiam calados); atom_check avisa "// opcoes:" com numero de nomes != o K do floor(). UM
    NOME: ALTERADOR (o corpo) e MOVIMENTO (o que ele faz) — "controlador"/"ativador" sairam do texto da tela ("controlador MIDI" = o aparelho
    fica). CONCORDANCIA JS x PYTHON (t6_js_python_concordam): stableId, migrateGraph, shapeAxes, faixas, eventos, formas de LFO, presets,
    modos de mistura e grupos grave/medio/agudo — um par que divergir quebra o teste.
    RODADA 2 (seguranca no show): DESFAZER POR CENA — trocar de cena guarda a pilha dela (UNDO_BY) e traz a da cena nova (antes zerava); REFAZER
    = Ctrl+Shift+Z / Ctrl+Y (limpa a cada mudanca nova). CENA POR LETRA = SEGURAR (HOLD_MS, como 1-9); tocar so' avisa no visor ("segure Q").
    Recomendado no book era Shift+letra, trocado por SEGURAR porque Shift ja' e' "na hora" na grade. No servidor: a acao da GRADE (evento ->
    liga/opcao/proximo) muda so' o estado vivo e grava com atraso (dash_server.grid_flush, GRID_SAVE_S 1,5 s; troca de cena e /quit gravam
    antes) — antes cada kick com acao regravava o tuning.py. Testes t6_desfazer_por_cena, t6_cena_segurar; selfcheck do dash_server.
```
