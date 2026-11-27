Continuação do PRISMA (branch dashboard-channels-output). Responda em pt-BR. Leia antes: CLAUDE.md, o TOPO do dash5.html (as decisões,
em ordem; as últimas são ACABAMENTO, PODA + PEDIDOS e REVISÃO DA PELE), BACKLOG.md (seções de 2026-11-26) e este arquivo (PROMPT_REPAGINADA.md).

ESTADO (2026-11-27)
- Nada commitado desde 1c238a6. Pendentes:
  - modificados: BACKLOG.md, CLAUDE.md, README.md, dash5.html, docs/como-funciona.html, packaging/build.sh, packaging/launcher.py,
    src/dash_server.py, src/native_synth.py, tests/dash_gestos.py;
  - apagados: dash.html até dash4.html;
  - novos: design/fase4/, design/acabamento/, design/revisao/, tests/estetica.py, tests/tela_foto.py, PROMPT_REPAGINADA.md.
  Commit só se eu pedir.
- Tudo entregue em dist/prisma/ e ~/.local/share/prisma/ (conferido com cmp). A suíte tests/dash_gestos.py passou 51/51.
- O que entrou em 26/11 (detalhes no topo do dash5.html):
  - ACABAMENTO: uma luz de cima; sombra em camadas nos sprites; metal usinado nos knobs e jacks; cabo com volume e o sinal andando no cabo
    aceso; LED com halo; mesa com luz e grade de pontos (#gdots, camada CSS); CABOS abre por cima.
  - PODA: um modo só (saíram TOCAR, F1/F2 e a estrela de publicar); MISTURA fora da barra (o mixer vem da roda); CABOS virou ícone no
    grupo do zoom; SOCORRO virou só a boia.
  - PEDIDOS:
    - o "+" na bandeja da fonte troca a fonte (srcPick);
    - a cor do cabo não muda ao pegar nem ao religar (cableKey + CABLE_PIN);
    - tecla INVERTER no envelope (ctlInvert: de > até em todas as ligações);
    - evento sem módulo de origem vira a plaqueta "seção · drop", fora do módulo.
  - REVISÃO DA PELE:
    - tudo que flutua tem o material do painel (--pnl);
    - campos = poço; selects com seta própria;
    - sinal = âmbar também no painel;
    - conserto: a aba Controle do Equipamento abria vazia.
- Decisões tomadas por mim, sem confirmação (se eu estranhar alguma, reverter sem discutir): tons, halo e pontos do acabamento; SOCORRO só
  ícone; renomear/apagar da biblioteca só com o mouse em cima.
- PERGUNTA ABERTA: as macros M1–M4 ficaram sem lugar na tela (hoje só pelo MIDI). Viram um módulo no canvas ou saem?

COMO É HOJE (inventário pra repaginada)
- Barra de cima:
  - visor da música (BPM, fase, seção; clique = popup "Tempo da música");
  - TAP;
  - avisos de saúde (chips);
  - EQUIPAMENTO;
  - EFEITOS e MASTER (faders);
  - SOCORRO (boia);
  - BLACKOUT (sob tampa).
- Barra do canvas (#cv-h):
  - zoom (− % +) e ⤢ caber tudo;
  - ícone dos cabos (tensão e opacidade);
  - CENAS · nome (popover com grade, duração, transição e a lista);
  - PROGRAMA (janela flutuante | fundo | esconder; tem a PRÓXIMA + GO);
  - ARRUMAR;
  - DESFAZER (N).
- Canvas:
  - módulos e cabos;
  - a RODA (2 cliques no vazio ou Enter): fontes, famílias, mistura e saída, máscaras, receitas; no anel de dentro, os alteradores;
  - o painel do módulo (botão direito parado ou 2 cliques);
  - o HUD de fps.
- Gavetas: Equipamento (Entrada, Saída, Luzes, Biblioteca, Controle) e Socorro.
- Invisível (legado):
  - a coluna da direita (#right: macros M1–M4 e lista de movimentos);
  - a da esquerda (#left: só aparece como o popover de CENAS).

O ENVELOPE (alterador): o que é cada peça
- Plaqueta com o nome + a linha "o que segue" (ex.: envelope · kick).
- Jack REDONDO no canto de cima à direita = SAÍDA DO SINAL (0..1): o cabo âmbar vai dele até um knob ou fader.
- Tecla com o desenho do envelope, embaixo do jack = INVERTER.
- QUADRADO na lateral ESQUERDA = GATILHO (entrada de evento, cabo verde): o evento que dispara o envelope (kick, caixa, batida… do
  RELÓGIO E SOM, ou o comparador de outro envelope).
- QUADRADO na lateral DIREITA com "≥½" = COMPARADOR (saída de evento): manda um evento toda vez que o sinal passa da metade (histerese
  0,4/0,6). Liga no LIGA de um módulo, num seletor, no ▶▶ da fonte ou no gatilho de outro envelope.
- Tela = osciloscópio (o sinal vivo; invertido, desenha descendo).
- Linhas de baixo = uma por ligação: a faixa de/até (as pontas arrastam), na cor do cabo.

O QUE EU QUERO AGORA
1. REPAGINADA TOTAL do design e da DISTRIBUIÇÃO dos recursos: onde cada coisa mora, o que some, o que vira módulo, tecla ou gesto.
   Antes de implementar: inventário + 2 a 3 propostas de layout com mockups (design book em artefato com db de escolhas, como o
   design/vcv-layout.html). Eu escolho; depois implementa.
2. Explicar os quadradinhos das laterais dos envelopes (acima) e repensar se estão claros: rótulo? ícone? posição?
3. Ganhar espaço no canvas: a barra do canvas (#cv-h: zoom, cabos, cenas, programa, arrumar, desfazer) não precisa existir. Levar tudo
   pra outro lugar (barra de cima, um canto do canvas, a roda, teclas…).

REGRAS
- Uso notebook com touchpad: todo gesto precisa de um caminho sem arrastar e tem que tolerar ~8 px de tremido; a roda sem Alt não mexe
  em controle.
- Preferir TIRAR a acrescentar (poda). Um modo só, tipo VCV.
- LEGIBILIDADE acima de tudo. Texto em plaqueta, nada de parafuso ou enfeite, a imagem das prévias nunca muda com o tema.
- Cor = significado: imagem azul, sinal âmbar, evento verde; no ar verde, escolhido laranja, perigo vermelho.
- Mudou dash5.html: rodar tests/dash_gestos.py antes de entregar (alguns falham às vezes só na suíte: rodar sozinho). Todo bug de
  usabilidade vira teste.
- Fotos de todas as superfícies: tests/estetica.py <pasta> (antes e depois).
- Medir o fps real, não só G6.stats.ms: a rasterização fica fora do JS.
- Toda mudança vai na hora pro dist/prisma/ e pra ~/.local/share/prisma/. Decisões novas vão no TOPO do dash5.html.
