Continuação do PRISMA (branch dashboard-channels-output). Responda em pt-BR. Leia antes, inteiros: CLAUDE.md, o TOPO do dash5.html (as decisões,
em ordem; as últimas são REPAGINADA, PELES e CABER TUDO VOA), BACKLOG.md (seções de 2026-11-26 e 2026-11-27), shaders/ATOMO.md, README.md, a
documentação (docs/index.html = como funciona; docs/tecnico.html = fluxo técnico) e este arquivo.

ESTADO (2026-11-27)
- Nada commitado no branch desde 1c238a6 (só a pasta docs/ foi publicada direto no master: 8af952d). Commit só se eu pedir.
- Tudo entregue em dist/prisma/ e ~/.local/share/prisma/. tests/dash_gestos.py: 57 testes (o t6_pele_unica às vezes falha só na suíte).
- Entrou em 27/11: layout B "cantos" (barra de cima = show, pílula da vista, monitor do programa, avisos na boia), cena ◀ ▶ + próx + GO,
  cenas no MIDI, módulo MÃO (macros M1–M4 + pads), envelope E2 (gatilho à esquerda, OUT ∿ e ½), jack de evento realista, 10 peles escuras
  (menu ⋯), voo da câmera no H. Documentação: https://paulocremas.github.io/cremas-synth-lab/

O QUE EU QUERO: UMA REVISÃO GERAL E COMPLETA DO PRISMA. LEVE O TEMPO QUE FOR, PESQUISE TUDO.
Nada de implementar no impulso: tudo de CASO PENSADO, cada proposta justificada por uma técnica de usabilidade, uma pesquisa (com a fonte) e
uma evidência no nosso app (foto, medida, contagem de passos). Antes de mexer em qualquer coisa, entregue a revisão e espere eu escolher.

FRENTE 1 — USABILIDADE GERAL, COM FOCO NO CANVAS
- Aplique as técnicas de verdade, não de enfeite, e diga qual usou em cada achado:
  - avaliação heurística (as 10 de Nielsen) e PERCURSO COGNITIVO (cognitive walkthrough) de cada tarefa, passo a passo;
  - KLM/GOMS (estimar o tempo de cada tarefa em gestos), lei de FITTS (tamanho e distância dos alvos — no touchpad), lei de HICK (quantas
    opções por escolha), carga cognitiva, RECONHECER em vez de LEMBRAR, revelação progressiva, significantes/affordances, feedback imediato,
    prevenção de erro e desfazer, consistência, memória espacial (as coisas ficam onde a mão espera);
  - para o CANVAS em especial: navegação (rolar, zoom, caber, voltar), zoom semântico (o que aparece de longe/perto), foco + contexto,
    densidade e leitura do patch, onde nasce cada módulo, arrumar, seleção (um, vários, retângulo), ligar e desligar cabos (clique-clique e
    arrasto), achar um cabo no meio de muitos, mover sem quebrar, desfazer, e se falta algo (minimapa? busca no canvas? "ir até"?).
- Pesquise como resolvem: VCV Rack, Bitwig Grid, Reaktor, TouchDesigner, Max/MSP, Pure Data, Blender (editor de nós), Unreal Blueprints,
  Houdini, Resolume, Synesthesia, Notch, Figma/Miro (canvas infinito). O que eles acertam que nós não temos? O que fazemos melhor?
- Percorra as tarefas reais, do zero, como alguém que nunca abriu o PRISMA e como eu (notebook + touchpad, ao vivo, no escuro):
  abrir e escolher a fonte; montar uma corrente de 3 módulos; pôr um módulo no meio de um cabo; ligar um envelope no kick a um knob; usar a
  MÃO com MIDI; montar e trocar cenas (◀ ▶, próxima, GO, grade); mixer com 2 fontes; máscara (só o rosto); telão/palco; recuperar de um
  problema no meio do show (socorro, blackout, desfazer); achar um módulo na biblioteca; voltar a um patch grande dias depois.
- Para cada tarefa: quantos cliques/gestos e quanto tempo (KLM), onde trava, o que não é descobrível (só tecla, só gesto, só dica), o que não
  dá retorno visível, onde dá pra errar sem volta, texto que não se entende, alvo pequeno demais, conflito de teclas, o que cansa no show.

FRENTE 2 — A BIBLIOTECA ESTÁ COMPRIDA DEMAIS: COMO REVER?
- Hoje: 49 átomos, 35 receitas, os alteradores por família, fontes, mixers/saídas — espalhados pela RODA (fatias + listas), pela aba
  Equipamento › Biblioteca (uma lista corrida de módulos .frag, transições, mídia) e pela paleta antiga.
- Meça o tamanho de cada lista e o tempo de achar coisas (Hick, KLM). Pesquise como VCV (browser com tags/favoritos), Bitwig, Ableton
  (browser + coleções), TouchDesigner (OP Create Dialog), Blender (Shift+A + busca), Figma (assets) e paletas de comando resolvem.
- Considere: busca primeiro (digitar já procura), favoritos e recentes, sugestões pelo contexto (o que liga no que está escolhido), agrupar
  por intenção ("mexer na cor", "deformar", "desenhar") em vez de por tipo técnico, esconder o raro (revelação progressiva), juntar átomos
  parecidos (um átomo com um seletor no lugar de três), curar receitas (quais ninguém usa), separar o que é EDITAR ARQUIVO (gestão da
  biblioteca) do que é PEGAR PRA USAR (montar). Proponha 2–3 caminhos com mockups.

FRENTE 3 — PIXEL MAPPING (palco, telas, telão)
- Revise o fluxo inteiro: telas do palco (SCREENS, forma livre, giro), canvas do palco, PIXEL_MAP + blocos (ox/oy, pw/ph, orot), detectar
  saída, telão simulado (src/telao_sim.py), "por cima do PRISMA", várias saídas, padrão de teste e load-in (BACKLOG "Pixel map e telão").
- É fácil pra um técnico de LED montar um mapa num local novo? O que falta (padrão de teste por bloco, exportar o mapa em PNG, gravar
  presets por casa de show, mapa de vários telões/projetores, keystone/warp, borda suave entre projetores)? Onde se erra sem perceber?
- Pesquise Resolume Arena (Advanced Output, slices, mapping), MadMapper, Madrix, disguise, TouchDesigner (Kantan Mapper), NovaStar e
  processadoras de LED — o vocabulário que o técnico já conhece.

FRENTE 4 — A MIXAGEM DO ÁUDIO QUE ENTRA (Equipamento › Entrada)
- Revise: escolha da fonte de áudio (e no Windows), as 8 faixas editáveis (arrastar bordas, trocar), as colunas (kick, amp, cada faixa: on,
  limiar, ativa/teto, piso, pulso), calibrar silêncio, sobreposição, os eventos (kick, caixa, chimbal, golpe), BPM/TAP/seções/tom.
- Pergunte: a pessoa entende o que cada coluna faz e por que mexeria? Os medidores mostram o que importa (o sinal que os alteradores
  recebem)? Há ganho de entrada / estrutura de ganho? Dá pra salvar por casa de show/fonte? O que acontece com microfone ruim, música muito
  baixa ou muito comprimida, silêncio entre faixas? Precisa de modo simples (3 grupos: grave/médio/agudo) e avançado (as 8)?
- Pesquise como TouchDesigner (Audio Analysis), Resolume (FFT, envelope), Synesthesia, Magic Music Visuals, VDMX, MilkDrop/projectM e
  ferramentas de DJ/iluminação (beat detection) apresentam isso.

FRENTE 5 — ESTRUTURA DO NOSSO FRAMEWORK INTERNO DE EFEITOS
- O contrato do ÁTOMO (ATOM_PRELUDE, cabeçalho → parse_meta/atom_check, até 3 knobs / 6 com montagem, filtro = troca vs gerador/forma = por
  cima, // estado: → run_state, bipolar, escolha/chave), as RECEITAS (shaders/receitas/*.json), o MOVIMENTO (mod[knob], _mod_value,
  MOV_PRESETS, EVENTS, cmp:<id>, acao, grade), o GRAFO (render_mix, migrate_graph, graph_pull/order, mark_tex, espelho, post legado), os
  formatos gravados (OVERLAYS, BINDINGS, ~ctl/~ev/~mao) e como o dash5 e o native concordam sobre eles.
- O que está duplicado entre dash5.html e native_synth.py/dash_data.py? Que legado ainda pesa (post, pub, cel, #right, v5)? Os nomes são
  consistentes (alterador/controlador/movimento/ctl)? Escrever um átomo novo é fácil e seguro (o que falha em silêncio)? O que falta de
  teste (src/matriz.py, selfchecks)? Onde uma cena antiga pode quebrar? Dá pra separar o dash5.html (9 mil linhas) sem quebrar o hot-reload
  e o launcher?
- Saída desta frente: um MAPA do framework (o que mora onde, quem chama quem, o formato de cada coisa) + os problemas estruturais com a
  proposta e o risco de cada mudança.

FRENTE 6 — LIMPAR E ORGANIZAR TODA A ESTRUTURA DO CÓDIGO (simples e efetiva)
- Objetivo: qualquer pessoa (ou eu daqui a seis meses) abre o repositório e entende em minutos onde mora cada coisa, sem medo de mexer.
- Faça primeiro o INVENTÁRIO do repositório inteiro: cada pasta e arquivo (src/, packaging/, tests/, shaders/, transitions/, design/, docs/,
  dist/, a raiz com os .md e os PROMPT_*), o tamanho, quem usa, e o que está MORTO (código sem chamada, CSS sem uso, testes quebrados como o
  tests/v6_foto.py, arquivos de rodadas antigas, os 4 dashes velhos ainda em dist/, mock_v6, PROMPT_* já cumpridos, design/ com fotos e
  patches antigos).
- Proponha a ESTRUTURA-ALVO, simples: pastas por responsabilidade (motor, painel, servidor, análise de áudio/imagem, saída/telão, sistema,
  empacotamento, testes, efeitos, documentação), nomes claros, um ponto de entrada por coisa, e onde moram os dados vs o código.
- O dash5.html (~9 mil linhas) e o native_synth.py: como separar em arquivos/módulos com fronteiras claras (ex.: no painel = estado/rede,
  canvas G6, peles, gavetas, MIDI; no motor = grafo, movimento, fontes, saída), SEM quebrar: o hot-reload por mtime, o launcher do
  PyInstaller (a lista do `if False:`, packaging/check_imports.py), a cópia pro dist/prisma e pra pasta de dados, o Windows e o CI.
- Limpeza de código: tirar legado (post/flattenPosts, pub, tema cel, #right/#left, v5mode, chaves velhas do localStorage, CSS do canvas
  HTML antigo, #cv-h e #tema-pop), unificar duplicações entre dash5 e native/dash_data (vocabulário, formatos, migrações), nomes
  consistentes (alterador = controlador = movimento? escolha UM), comentários do topo do dash5 consolidados num documento de decisões
  (DECISOES.md?) em vez de um bloco gigante no HTML, e os testes organizados (um comando roda tudo; o que é lento separado).
- Atualize junto: CLAUDE.md (mais curto, apontando pros lugares certos), README.md, MAPA.md, BACKLOG.md (o que já foi feito sai) e a
  documentação técnica (docs/tecnico.html).
- Faça em ETAPAS seguras: cada etapa pequena, com a suíte inteira passando (tests/dash_gestos.py, os --selfcheck, packaging/check_imports.py,
  o build do executável) e com o app entregue funcionando antes da próxima. Nada de reescrever do zero. Mostre o plano de etapas no book
  antes de começar e diga o risco de cada uma.

E O RESTO TAMBÉM (revisão geral): gavetas (Equipamento, Socorro), painel do módulo, MIDI/teclas, cenas e transições, luzes, webcam virtual,
desempenho (fps real em máquina fraca), instalação e primeira abertura (o que a pessoa vê no 1º minuto), mensagens de erro, a documentação.

COMO TRABALHAR
- Use subagentes se ajudar (pesquisa em paralelo, varredura do código), mas a síntese é sua.
- Fotografe cada passo (tests/estetica.py, tests/tela_foto.py) e meça (KLM por tarefa, tamanho das listas, alvos em px, fps real).
- Cite as fontes da pesquisa.

ENTREGA (antes de implementar)
- Um design book em artefato com db de escolhas (como design/repaginada.html), com: o resumo do que está bom e do que está ruim; uma lista
  priorizada por frente (impacto × esforço) com evidência e técnica; as fotos; os mockups de 2–3 caminhos para a biblioteca, a entrada de
  áudio e o pixel mapping; o mapa do framework; o inventário do repositório, a estrutura-alvo e o plano de limpeza em etapas; e, pra cada
  item, as opções. Eu escolho; depois implementa em rodadas pequenas, cada uma
  com teste e com as decisões no TOPO do dash5.html.

REGRAS (as de sempre)
- Notebook com touchpad: todo gesto com caminho sem arrastar, tolerar ~8 px de tremido; a roda sem Alt não mexe em controle.
- Preferir TIRAR a acrescentar. Um modo só. LEGIBILIDADE acima de tudo. Tudo ESCURO.
- Cor = significado: imagem azul, sinal âmbar, evento verde; no ar verde, escolhido laranja, perigo vermelho.
- Mudou dash5.html: rodar tests/dash_gestos.py antes de entregar; todo bug de usabilidade vira teste. Medir o fps real.
- Toda mudança vai na hora pro dist/prisma/ e pra ~/.local/share/prisma/. Decisões novas no TOPO do dash5.html.
