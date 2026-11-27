# Backlog

Ideias combinadas e ainda não feitas. Ao começar uma, mover pro código/commit e tirar daqui.

## Sync com a música — o que ficou (feito: movimento loop/disparo/segue, presets, grade, frase, seção, rastreio como fonte)
- Pads de EVENTO (`pad:1..4`) no MIDI learn / teclado: o motor já dispara (`/grid {op: 'ev'}`), falta o controle na tela.
- Calibrar a SEÇÃO com 2–3 faixas reais (heurística: falha sem bumbo e em drop sem pausa); teclas/pads pra forçar seção.
- Beat/downbeat neural (BeatNet, beat_this) e estrutura de faixa analisada antes do show (All-In-One): exige torch.
- `luz`/`mov` por CAIXA (hoje = a imagem de entrada inteira); sustentação de envelope com gate (ADSR); forma desenhada à mão.
- Ableton Link / MIDI clock como relógio externo; pinça (dois dedos) pro zoom no toque.
- Movimento com gesto de rastreio em `disparo` compartilhado entre caixas: o contador é por caixa — id próprio por caixa.

## Em cima / v6 (historico/PLANO_CONVERSA.md; feito: marca, em cima com memória/espaço/B/opacidade, card ↳, zona = card, auditoria §5.3)
- Prévia fora do ar ao soltar EM CIMA (o `/try` só troca a pilha principal).
- Arrastar a linha ↳ pra FORA do card (vira nó no fio) e um nó do fio PRA DENTRO de outro card (vira em cima).
- Filtro que RECORTA (alfa < entrada) com algo em cima: a marca volta por cima da entrada e o recorte some ali.

## ÁTOMO v2 — o que ficou (feito: prelúdio, estado 16F + passo fixo, semear/limpar, loop retorno, no:<id>, matriz, onda a/b/c)
- UI do PLANO_PADROES §11 (feito: knobs redondos no card do nó): loop visível (↻ no nó), receitas dobráveis com macros,
  adicionar/remover.
- `// ritmo:` só declarado: falta o knob de velocidade TRAVAR no BPM (divisões da batida) no motor e no dash.
- `// escala:` em átomo SEM estado (Brilhar a meia resolução) — hoje só o estado tem resolução própria.
- Interação 2 de verdade: Reação semeada pela máscara **Mãos** (testado com um Limiar no lugar: headless não tem pessoa).
  Máscara como IMAGEM na corrente (o cinza dela como B de outra caixa) seria a regra geral pra isso.
- Fluido: confinamento de vorticidade de verdade (curl → gradiente do |curl|) e uma vista "vetor" (liquify num Deslocar).
- Matriz: teste de borda escura de átomo de média sobre cobertura parcial; checar o sinal do vetor de quem escreve vetor.
- Knobs renomeados na migração (valor volta ao padrão em cena antiga): Níveis `quantos` → `forca`; Feedback perdeu
  `zoom`/`giro` (vão no loop ↻ com Rodar). O `in: fb` (feedback de 8 bits da caixa) segue rodando nas cenas antigas.
- Physarum (agentes) como átomo com estado; presets antigos (Clássicos) virarem RECEITAS de átomos.

## v5 — canvas de caixas (feito: caixas, fios, SAÍDA, máscara por caixa com Assunto/Brilho/Cor, cadeado)
- Máscaras que faltam: Olhos (precisa de modelo de rosto), Movimento (precisa da entrada 1 quadro atrás, não o `fb` da caixa).
- Caixa salva na biblioteca (a caixa como preset; os grupos da v4 só aparecem na Biblioteca do equipamento).
- Prévia fora do ar ao soltar MÁSCARA (o `/try` só troca a pilha) e miniatura de cada átomo da caixa escolhida.
- Teste com tela de toque e MIDI físico na v5; caixa que recorta + quem lê ela recebe só o RGB (sem o alfa do recorte).

## Card do nó (v5) — o que ficou (feito 2026-11-02: entrada × saída, nome do jack por dentro, LED no ar, nó sem entrada)
- Prévia do ÁTOMO (miniatura no cabeçalho) só quando escolhido: hoje só fonte, staging e saída têm (custo de `/frame`).
- Teste em sala escura e com tela de toque no palco (zoom padrão 72%).

## Grafo / cabos VCV — o que ficou (feito 2026-11-01: entradas com nome, fio grudado + menu, stagings, várias saídas no palco, espelhos)
- Saída com aspecto diferente do palco: as camadas esticam pra caber (como o `rect` de antes); a textura da saída com átomos
  é do tamanho da mistura (círculo vira elipse no `asp()`). Saída com resolução própria = junto com "Várias saídas" (janelas).
- Entrada B dos átomos DEPOIS da mistura (staging/saída) e máscara num staging: o motor roda, a bolinha não existe no card.
- Cor do cabo escolhida à mão (hoje = a do nó de onde sai); arrastar várias pontas de uma vez (Ctrl no VCV).
- Alt+arrastar (espelho) pode ser pego pelo gerenciador de janelas no Linux: o menu e o botão do inspetor fazem o mesmo.
- Espelho de átomo de MÁSCARA e de modificador paralelo (`post`); "ir ao original" com destaque piscando.
- Nó com prévia pedida roda mesmo fora de uma saída (como o viewer do TouchDesigner): com muitos nós soltos, custo de GPU.
- v3/v4 não editam cena com staging/saída (o motor migra o que elas mandam; a v5 é o dash do app).
- GERADOR SEM ENTRADA (o oscilador do VCV): hoje Listras/Pontos/Ruído só nascem lendo um fio. Uma fonte "vazio" (transparente)
  faria um gerador virar camada sozinho num staging — o fio já leva o alfa (2026-11-02).
- Encaixe no palco pelo pixel mais perto: a fileira lida por camada (`u_snap`) e o caminho de antes às vezes escolhem a linha
  VIZINHA (a cada ~11 linhas, conforme a escala das telas). Invisível; só some com uma regra de amostragem única pra tudo.

## v4 — patch (feito na v4: ligação por zona, ramos, LFO/som/macro como peça, variações, prévia por passo, grupos, publicados no Show, custo por fileira)
- Modulador por imagem de UM módulo ou fonte (hoje `luz`/`mov` = a imagem de entrada inteira, ~14 Hz).
- Teste em tela de toque de verdade (alvos já ≥ 44 px no Show) e com controlador MIDI físico na v4.

## Canvas / telas — o que falta
Feito: telas do palco físico (`tuning.SCREENS`, metros + pixels, editor na aba Saída) cujo contorno
é o canvas; fontes posicionadas nele (`OVERLAYS[i].rect`, vista Canvas da mesa no Palco, com prévia
com efeitos e bandeja arrasta-e-solta); fora das telas = preto. Tela com forma livre (`rot` + `poly`,
editor com giro/vértices/formas prontas/lápis; native, pixel map e telao_sim).
Ainda não:
- **Várias saídas**: no grafo já há várias SAÍDAS (cada uma um `rect` no palco), mas o pixel map (`PIXEL_MAP` + blocos
  `ox/oy/pw/ph`) segue um raster/janela só. Falta mais de um (uma janela por saída/monitor) pra parede maior que um 4K ou
  LED + projetor. Espelho por bloco.
- **Rotação** e **recorte** (crop) por OBJETO (fonte no canvas). Tela com keystone/quad livre (projeção;
  hoje o painel é retângulo girado + polígono). Ímã com tela girada (hoje desliga).
- Imagem da cena e calibração ainda passam na janela inteira; a análise/fumaça (`_composite` na
  CPU) ignora `rect`/telas; shaders da pilha rodam com `u_resolution` da janela.

## Telão simulado — o que falta (`src/telao_sim.py` já desempacota o raster no palco)
- Grade de LEDs/módulos visível no zoom; projetor com keystone/sobreposição.
- Versão Windows (hoje X11: wmctrl/xwininfo/x11grab por id).

## Saída no telão real
- Reconhecimento automático só roda com o dash aberto (`pollOutputs`); telão que some deixa a janela de saída
  sem destino (só avisa) — voltar pra janela normal?
- vsync explícito na janela de saída (tearing no LED); fontes/shaders em 640×480 deixam o conteúdo mais mole
  que o painel.

## Windows / distribuição
- 1º teste real no Windows: `v0.1.0-beta.1` (pré-lançamento, zip portátil) foi pra um amigo — esperar o
  `prisma.log` (`dados\prisma.log` no portátil). Pontos não vistos rodando: OpenGL com driver de verdade,
  loopback WASAPI (`plat.PcmProc`), câmera dshow, dash no Edge, monitores DPI-aware.
- `--region`/`--window` e `_raise_output_over_dash` só no Linux.
- Release final `v0.1.0`: juntar `dashboard-channels-output` no `master` e taggear de lá.
- Actions avisa Node 20 depreciado (`checkout@v4`, `setup-python@v5`) — subir as versões.
- Instalador/zip sem assinatura de código (SmartScreen avisa).

## Plano geral 2026-11-26 (Claude Doc "PRISMA — plano geral: gestos, estética e fluidez") — o que ficou de fora
- **Verbos de patch com versão** (cada gesto = uma operação pequena + desfazer pela inversa): feito só o "estado por diferença" no SSE;
  as travas `boxDrag`/`TOUCH_MS`/`swallowClick` continuam. Mexe no formato da cena — fazer com calma, com teste de cada gesto.
- **Duas camadas de canvas** e **separar o `dash5.html` em arquivos**: adiados — o quadro mede < 1 ms; separar exige o launcher/hot-reload
  conhecerem os arquivos novos e um build novo do executável.
- **Executável**: o `launcher.py` novo copia só `dash5.html` + `favicon.png`; o binário de agora ainda copia os 4 dashes antigos (por isso
  eles continuam só dentro de `dist/prisma/`). Refazer o build (`packaging/build.sh`) e aí apagar `dist/prisma/dash{,2,3,4}.html`.
- **Leitor de cartuchos**: controles do VÍDEO (pausa, velocidade, voltar ao início) — o motor não tem; arrastar um cartucho PRA FORA da
  bandeja (hoje: Ctrl+clique tira).
- **Evento vira cabo**: gate de verdade com duração (hoje os eventos são instantes: o LIGA ALTERNA a cada evento); pads MIDI e seção
  (`secao:*`, `pad:N`) como jacks no módulo (hoje só pelo cabo que já exista); o evento que dispara ação grava o `tuning.py` a cada vez
  (`grid_apply` com `save=True`) — se pesar, aplicar só ao vivo.
- **Pele única**: o código do tema `cel` (56 lugares) e o CSS do canvas HTML apagado continuam no arquivo, sem uso; o corpo do PAINEL ainda
  usa os controles web (só a tampa e o cabeçalho mudaram); a letra condensada não entrou no canvas (decisão fechada dos módulos).

## Acabamento 2026-11-26 (topo do `dash5.html`, "ACABAMENTO"; fotos e patch em `design/acabamento/`) — o que ficou
- **Painel do módulo**: só a tampa de borda a borda, separadores mais leves e o nome em 2 linhas; as fichas (parado/normal/soma…) e as
  linhas continuam web — fazer com as peças do canvas (tecla, seletor de entalhes).
- **Cartucho, fader e seletor**: ainda sem a luz única (sombra/brilho do acabamento); o osciloscópio do alterador podia ter o
  traço com brilho de fósforo (halo do `led()`).
- **Modo leve**: liga pelo custo do JS (`G6.stats.ms`), que não vê rasterização — medir também o fps real antes de ligar.

## Poda 2026-11-26 (TOCAR saiu) — próximos cortes
- **Coluna da direita** (`#right`): as macros viraram o módulo MÃO (repaginada 2026-11-27); o `#right` ainda existe escondido (os
  faders `#macros` registram o MIDI `macro:N`, o `#pgm-p`/`#next-p` são levados pra janela do PROGRAMA) — desmontar com calma.
- **Código morto que ficou**: os ramos JS do tema `cel` (o CSS saiu), o código depois dos `if (G6) return` (canvas HTML antigo) e a
  geometria /v5 (`tvH`/`tvGeo`: ainda servem a módulo dobrado e espelho), `s.pub` nas cenas, `renderPalette` (roda escondida).
- **Socorro**: os avisos já moram na boia (2026-11-27); se o "congelar movimentos" e a "imagem crua" ganharem tecla, a gaveta pode virar só o diagnóstico.
- **Seção como jack** no RELÓGIO E SOM (os pads já são jacks na MÃO; o envelope por seção mostra o nome no gatilho, sem cabo).

## Revisão da pele 2026-11-26 (`design/revisao/`, `tests/estetica.py`) — o que ficou
- **Gaveta ENTRADA**: as colunas das faixas (kick, amp, Sub-bass…) ainda têm os knobs web teal e os campos numéricos crus — fazer com o
  knob/fader do canvas.
- **Janela de saída** sem dados (sem o native) mostra campos vazios e um quadro preto grande: um "aguardando a saída" no lugar.
- **Painel do ALTERADOR**: o cabeçalho ainda não tem o material (o do módulo de átomo tem); a frase de ajuda longa podia ir pro `title`.

## Repaginada 2026-11-27 (proposta B "cantos", topo do `dash5.html`; book `design/repaginada.html`) — o que ficou
- **Peles (feito 27/11)**: 10 peles escuras no menu ⋯. Ficou: as GAVETAS (Equipamento/Socorro) e o painel do módulo só trocam o material nas peles
  que definem `--pnl`; teclas/seletores/faders DENTRO dos módulos continuam com o desenho de hoje; as fontes de cada pele dependem do que o
  sistema tem (sem internet = a reserva); o book `design/esteticas.html` ainda mostra as versões CLARAS (as do app viraram noturnas).
- **MÃO**: fader sem Alt+roda (só arrasto/MIDI); a MÃO não entra no retângulo de seleção nem no ARRUMAR; um por cena.
- **Monitor do PROGRAMA** pode cobrir módulos no canto de baixo (rolar a vista / recolher na aba NO AR).

## Revisão geral 2026-11-27 (book "PRISMA — revisão geral" = `design/revisao-geral/`; decisões em `DECISOES.md`) — o que ficou
Feito em 8 rodadas: consertos, segurança no show (desfazer por cena, cena segurada, a grade não grava a cada evento), canvas (Ctrl+F,
G, módulo nasce ligado, alvos 24 px, nomes de longe, menu do direito), biblioteca (lista única com busca, ★/↺, receitas, Fundo oculto),
entrada simples/avançada + perfis, TELÃO (aba, teste por bloco no motor, PNG, casa, setas), erros de átomo à vista, concordância JS×Python,
poda (≈460 regras CSS, grupos v4, código Python sem uso), `historico/`, `tests/tudo.sh`, gaveta ≤ 640 px, dica no canvas vazio, HUD do motor.
- **F1 · migração única no Python** (ids determinísticos, ao ler a cena; o JS `graphFix` é hoje o migrador de verdade) — risco alto: rodada própria.
- **F6 · bloco CONTROLES** fora de `BINDINGS` (`~ctl`/`~ev`/`~mao`, com migração) e **F8 · plano do quadro** extraído do `render_mix` (testável no CI).
- **F7 · `tuning.py` como banco** → `scenes.json`: depois de F1/F2.
- **Etapa 4**: build novo do executável (`packaging/build.sh`) e só então apagar `dist/prisma/dash{,2,3,4}.html` (o binário de 26/10 ainda copia).
- **Etapa 7**: dividir o `native_synth.py` (motor_grafo, movimento, captura, análise, saída — nomes NOVOS). **Etapa 8**: o painel em pasta (`painel/`).
- **Sets de shader/mídia** (v1–v3) no servidor: rotas sem cliente, mas a partida e o self-check de mídia ainda usam — desmontar com calma.
- **1ª abertura**: a semente do repo agora é VAZIA (com a dica); falta um vídeo de demonstração que possa ir no pacote (a pasta `media/` não está no git).
- **P6**: várias saídas/telões, warp e borda suave entre projetores. **Entrada**: o `// ritmo:` dos átomos (travar no BPM) segue só declarado.
- **Motor**: a medida de ms por quadro (HUD) e o erro de shader por arquivo só foram testados de forma estática — conferir abrindo o app.
- **Limpeza de disco** (fora do git, só apagar à mão): `build/` (536 MB, gerado), `dist/prisma_0.60+9358291_amd64.deb` (27 MB, de 23/09).

