# PLANO — usabilidade e design do PRISMA inteiro

Escrito em 2026-11-18, depois da rodada 5 do `/v6`. Não está implementado. Cada fase vira um `PROMPT_*.md` próprio, como o
`PROMPT_RODADA6.md`, que é a fase 0.

Cada item tem:
- **o problema**, visto no app, no print ou no código;
- **a proposta**;
- **a referência**, listada no fim;
- **como saber que ficou bom**: um teste de gesto, uma medida ou uma tarefa de ensaio.

Decisões já fechadas (mini TV, famílias, jack visto de cima, cabo VCV, sem parafuso, sem alavanca, legibilidade acima de tudo,
P/S/C) **não são reabertas aqui**. O plano constrói em cima delas.

---

## 1. Princípios
Toda decisão de tela passa por eles. Em conflito, vale o de cima.

1. **O palco não pode cair.** Nada que o músico faça no TOCAR derruba a imagem por engano. Ações perigosas pedem gesto
   deliberado (segurar, ou dois passos), e toda ação tem desfazer.
2. **Ler de longe, num relance.** No escuro, a 1 m da tela, no meio de um show:
   - texto ≥ 10 px no canvas a 100% e ≥ 13 px nos painéis;
   - contraste de texto ≥ 4,5:1;
   - estado por forma **e** cor, nunca só cor.
3. **Uma coisa, um lugar para mexer.** O mesmo valor não se edita em dois lugares com regras diferentes. Exemplo da rodada 6:
   a faixa do alterador mora no alterador e só aparece no knob.
4. **Mexer direto na peça.** O que se vê no módulo se mexe no módulo. O inspetor é a "tampa traseira", só para o avançado.
   O Unity recomenda o oposto para grafos de dados; aqui vale o hardware, porque é instrumento.
5. **Um vocabulário físico só.** Knob, fader, tecla, seletor, liga, jack, cabo, tela, plaqueta, LED. As mesmas peças na barra,
   no inspetor, nas cenas e no equipamento (memória `estetica-programa-todo`).
6. **O sistema diz o que está acontecendo** (heurística 1 de Nielsen):
   - o que está vivo, o que está ligado por cabo, o que o MIDI controla;
   - o que não está fazendo efeito;
   - o que caiu (câmera, vídeo, áudio).
7. **Nada pisca, nada pula.** Animação de 150–250 ms com propósito. Prévia nunca fica preta ao mudar o zoom ou a seleção.
   Layout nunca se mexe sozinho sob o mouse.
8. **Alvos generosos.** ≥ 24 px de tela por alvo, ou 24 px de folga entre eles (WCAG 2.5.8). Espaço de um polegar entre knob e
   jack (regra do VCV).
9. **Teclado para quem sabe, mouse para quem chega.** Tudo tem atalho, e nenhum atalho é a única porta.
10. **Mostrar, não explicar.** Rótulo curto, dica no hover, e a tela vazia ensina o primeiro passo.

---

## 2. Sistema de peças (o design system do PRISMA)
**Problema.** As peças nasceram módulo a módulo: tamanhos, alvos e estados variam, e cada tela nova reinventa. A barra de cima
e o canvas usam botões-pílula de texto ("visual", "cabos", "arrumar"...) que não são do vocabulário dos módulos.

### 2.1 Fichas
Cada peça ganha uma ficha (no `design/`, como página viva igual ao `mini-tv.html`) com:
- tamanho, alvo de clique e zona de pick no G6;
- estados: normal · hover · apertado · ligado por cabo (anel de modulação) · aprendendo MIDI · com MIDI · desligado ·
  **sem efeito visível** · erro;
- desenho foto e desenho cel.

As peças:
- **knob-jack** (rodada 6): girar no anel, cabo no centro, anel de faixa + valor vivo quando ligado;
- **fader-jack:** trilha comprida, jack no pé, faixa + valor vivo quando ligado;
- **seletor:**
  - S1 rotativo com ponteiro;
  - S2 fader de entalhes;
  - S3 teclas iluminadas;
  - a regra de qual usar depende do número de opções (rodada 6, item 8);
- **liga:** esfera de vidro; a família cor = roda de cores;
- **jack** de imagem × jack de controle: precisam se distinguir sem cor. Proposta:
  - imagem = porca sextavada;
  - controle = porca redonda menor, como os dois tamanhos de jack do hardware;
- **cabo** de imagem × cabo de controle. Proposta:
  - imagem = cabo grosso com plugue;
  - controle = cabo mais fino, com um brilho que corre na direção do sinal no ritmo do valor (vivo, barato);
- **plaqueta** (texto), **LED**, **tela/osciloscópio**, **VU**.

### 2.2 Tokens
- **Cor semântica** (fechada no `PLANO_CONVERSA.md`):
  - vermelho só perigo;
  - roxo = máscara/onde;
  - a cor da família no gabinete;
  - o **cabo** com paleta sorteada, testada para daltonismo (deuteranopia e protanopia). Dois cabos vizinhos nunca no mesmo
    par confundível.
- **Tipografia:** escala 10 / 12 / 14 / 18 / 24, uma família de letra, plaqueta gravada para o gabinete e letra lisa para os
  painéis.
- **Grade de 4 px; raios e bisel por família** (o `RAD` do G6). **Área útil** do módulo = interno menos bisel menos 8 px
  (rodada 6, item 4).
- **Movimento:** 150 ms para hover e acender, 250 ms para abrir e fechar, zoom suave já feito. `prefers-reduced-motion` e o
  tema LEVE desligam o resto.

### 2.3 Como medir
- Teste `t6_dentro_do_relevo`: toda peça dentro da área útil.
- Teste de alvo mínimo: todo `ctrls`/`ports` com raio de pick ≥ 12 px de tela a 100%.
- Contraste checado por script nas cores dos tokens.

---

## 3. Canvas dos módulos (MONTAR)

### 3.1 Módulo
- **Grade de colunas** (rodada 6, item 5): `[entradas] [tela] [fader-jack] [nome/seletores/knob-jacks] [OUT]`, tudo centrado na
  vertical, OUT no meio. Sem vazio: no print, o POLAR e o MISTURAR têm um terço vazio.
- **Estado no corpo, sem texto:**
  - desligado = gabinete apagado e tela parada;
  - sem efeito visível = LED âmbar com dica (rodada 6, item 7);
  - laço (lê o quadro anterior) = ícone de laço no OUT;
  - erro de shader = tela com estática e plaqueta vermelha.
- **Nome legível em todo nível de zoom:** no "longe" o nome cresce para ter ≥ 10 px na tela (zoom semântico, já feito no
  bloco). Conferir no "normal".
- **Hover em qualquer peça:** destaca os cabos dela e esmaece o resto a 30%, como pediram na Vuo. Hoje isso só acontece
  girando knob.
- **Selecionar um módulo:** mostra os cabos dele inteiros por cima de tudo.

### 3.2 Cabos
- **Arrastar um cabo acende os jacks COMPATÍVEIS** (imagem × controle) e apaga os outros. Soltar perto (≤ 24 px) gruda.
- **Soltar um cabo no vazio** abre a roda **filtrada pelo tipo**:
  - cabo de imagem → átomos e saídas;
  - cabo de controle → alteradores;
  - o módulo escolhido nasce ali já ligado. É o "arrastar do pino" do Unreal, Blender e Resolume Wire (fast patching).
  - Hoje o vazio abre o menu do nó (`t6_vazio_abre_menu`); propor a troca ao usuário.
- **Cabo longo ou por cima de módulo:**
  - no print, o cabo amarelo atravessa os dois POLAR;
  - opção de rota "por fora" (curva que contorna) **ou** "arrumar" que minimiza cruzamentos (camadas de Sugiyama no
    `tidyPlace`);
  - medir cruzamentos antes e depois na cena do usuário.
- **Botão "cabos" (opacidade):** vira um fader pequeno da barra do canvas, com as peças da casa.

### 3.3 Navegação
- **Mapa** no canto (mini-mapa clicável) quando a cena passa de 2 telas. O HUD de hoje vira só modo de desenvolvedor.
- **Ctrl+F = procurar módulo pelo nome**: a câmera vai até ele e acende.
- **Molduras/grupos** com nome e cor: arrastar a moldura leva tudo, e de longe vira um bloco nomeado ("Câmera A",
  "Ritmo"). Referência: as âncoras e o "dock" do TouchDesigner.
- **Notas** no canvas (plaqueta solta com texto), para o show.

### 3.4 Barra do canvas
- No print, "CANVAS" + zoom + 7 pílulas de texto + "janela" ocupam uma faixa inteira.
- Proposta: título sai; zoom vira peça (− 43% +, ⤢) com as teclas da casa; "visual/cabos/cenas/programa/mistura/arrumar/
  desfazer" viram teclas com ícone + rótulo curto agrupadas por função:
  - vista: visual, cabos, programa, mistura;
  - montagem: arrumar, desfazer;
  - cenas.
- Ganha-se uma linha de canvas.

### 3.5 Como medir (tarefas de ensaio, cronometradas, sem ajuda)
- **T1:** câmera → Contornar → Vinheta → saída, em < 60 s.
- **T2:** pôr um LFO na opacidade do Vinheta e limitar entre 20% e 80%, em < 30 s.
- **T3:** achar o módulo "Polar 2" numa cena de 40 módulos, em < 10 s.
- **T4:** tirar um cabo errado sem apagar o certo, com 0 erros.

---

## 4. Alteradores (controladores / movimentos)
- **Nome único: "Alterador"** em toda a interface (roda, inspetor, dicas). Hoje aparecem "controlador", "movimento" e
  "envelope". O nome é o que o usuário usa.
- **Corpo:**
  - osciloscópio maior, com a grade discreta;
  - a faixa de/até editável (rodada 6, item 3), uma linha por ligação, na cor do cabo dela;
  - texto do tipo ("segue grave", "LFO · 1 compasso") ≥ 10 px; no print está em 9 px e mal se lê.
- **Ponte com o knob:**
  - passar o mouse no knob-jack acende o alterador que o move e o cabo;
  - passar no alterador acende todos os knobs que ele move;
  - de longe, o anel do knob na cor do alterador basta.
- **Tipo trocável no próprio módulo:** um seletor S1 com sin/tri/saw/sq/aleatório para o LFO, e um seletor S2 para a fonte do
  som (grave/kick/agudo). Hoje é preciso o inspetor.
- **Congelar** (já existe `/mv-freeze`): tecla no próprio alterador + a de SOCORRO global.
- **Medir:** a tarefa T2, e `t6_alterador_faixa`.

---

## 5. Roda / biblioteca
- **Fatias = as famílias com a amostra do material** (rodada 6, item 6) + Fontes · Máscaras · Alteradores · Mixer/Saída ·
  Receitas. Sem duplicata e sem vazia.
- **Dentro da fatia:**
  - lista com o pictograma, o nome e uma linha do que faz;
  - **prévia ao passar o mouse**: o átomo aplicado na imagem viva do módulo onde a roda abriu, ou numa imagem de teste.
    Mostrar é melhor que descrever.
- **Topo da lista:** "recentes" (os 5 últimos) e "favoritos" (estrela).
- **Digitar com a roda aberta** procura em tudo (já existe) e aceita sinônimos ("blur" → Desfocar, "hue" → Matiz, "chroma" →
  Cor).
- **Visual da roda:** sai do DOM antigo e vem para as peças da casa, um disco com as fatias como teclas de família.
  A roda abre onde o mouse está e nunca sai da tela (já faz).
- **Medir:** "achar e pôr o Desfocar" em < 5 s; nenhum átomo em "outros".

---

## 6. Inspetor (a tampa traseira)
- **O que mostra:**
  - só o que não está no card: avançado, modo de mistura, máscara/região, rastreio, alias MIDI, notas;
  - nunca uma segunda cópia editável do que o card já edita (princípio 3);
  - o que o card tem aparece só como leitura e com o link "mexer no card".
- **Seções** com cabeçalho-plaqueta, retraídas por padrão, lembrando a última aberta por tipo de módulo.
- **Posição:** já segue a câmera (`inspFollow`). Nunca cobre o módulo que inspeciona; se não couber, vai pro outro lado.
- **Fechar:** Esc, clique fora ou o mesmo gesto que abriu (já faz).
- **Medir:** contar campos que existem no card e no inspetor ao mesmo tempo; a meta é zero.

---

## 7. TOCAR (o modo palco)
O que existe: barra de cima com TOCAR/MONTAR, BPM/fase/seção, TAP, fps, Equipamento, EFEITOS, MASTER, SOCORRO, BLACKOUT;
PROGRAMA/PRÓXIMA; cenas/GO.

- **Barra = teclas de TV** (proposta antiga, não aprovada ainda). Com as peças da casa:
  - EFEITOS e MASTER = fader-jack horizontais (o MIDI segue);
  - SOCORRO e BLACKOUT = teclas grandes com capa.
- **BLACKOUT e SOCORRO = segurar 400 ms**, com o anel enchendo, **ou** tecla com capa. Nunca um clique de passagem
  (princípio 1). A tecla MIDI continua imediata (é deliberada).
- **PROGRAMA/PRÓXIMA como mesa de vídeo** (preview/program):
  - PRÓXIMA à esquerda e PROGRAMA à direita, borda tally (vermelho = no ar, verde = próxima);
  - T-bar ou GO grande entre as duas;
  - a transição mostra o progresso na T-bar.
- **Cenas = cartuchos** (proposta antiga):
  - miniatura viva da cena, nome grande, cor;
  - a cena no ar com tally;
  - arrastar para reordenar;
  - número = tecla do teclado ou MIDI.
- **Ritmo:**
  - BPM grande;
  - pontos de batida e compasso;
  - frase e seção (intro/sobe/drop/pausa) como fita colorida que anda;
  - o "1 da frase" bem marcado (é o que o músico usa para o GO quantizado).
- **Saúde num LED só** (verde/âmbar/vermelho) com o detalhe ao passar o mouse: fps da saída, câmera, áudio, vídeo, MIDI.
  Hoje "60 fps" é texto solto. Âmbar e vermelho tocam a atenção sem cobrir o palco.
- **No TOCAR some tudo que é montagem** (`.ed`, já é regra). Conferir peça por peça no inventário de 130 itens (artefato
  "plano da mini TV + inventário", db `marcas`).
- **Medir:**
  - T5: trocar de cena no "1" da próxima frase, em < 3 s de olhar;
  - T6: achar e acionar o blackout, ≤ 1 s, sem acionar por engano em 20 cliques de passagem (teste de gesto).

---

## 8. Equipamento (áudio, imagem, MIDI, saída, telas, luzes, teclas, biblioteca)
- **Cada aba começa pelo ESTADO**, na mesma forma em todas:
  - o que está ligado e funcionando: "Câmera 1 · 30 fps · ok", "Áudio · Monitor of… · nível";
  - depois o "mudar".
- **Assistentes** para o que tem passo a passo:
  - telão (detectar → mapear → testar);
  - luzes (procurar → mapear pela câmera);
  - MIDI (aperte um botão no controlador → pronto).
  - Hoje são formulários com campos `x/y/larg. px`.
- **Linguagem:** o que o músico entende, com o termo técnico na dica. Exemplos:
  - "Processadora do telão" (EDID na dica);
  - "Webcam virtual para OBS/Zoom".
- **Peças da casa** também aqui: números como knob ou campo com arrasto (arrastar o rótulo muda o valor), e chaves como S3.
- **Medir:** T7, ligar uma câmera nova e vê-la no canvas, < 30 s.

---

## 9. Feedback, erros e desfazer
- **Desfazer universal** (Ctrl+Z / Ctrl+Shift+Z) com histórico visível ao passar o mouse no botão: "desfazer: ligar cabo
  Contornar → Matiz".
  - Hoje é "desfazer (1)"; conferir o alcance (gestos, valores, cenas).
- **Avisos (toasts)** curtos, no canto, com ação quando houver ("câmera caiu · reabrir"), empilhados e sem cobrir o PROGRAMA.
- **Erros em linguagem humana:**
  - shader com erro = a linha e o porquê em uma frase, com o módulo apontado no canvas;
  - câmera ocupada = qual programa a está usando.
- **Auto-salvar visível:** um ponto discreto "salvo há 2 s" na barra das cenas (o set ativo já auto-salva; mostrar dá
  confiança).

---

## 10. Teclado e atalhos
- **Folha de atalhos no `?`**, desenhada como as peças, agrupada por modo.
  - `#keyhelp` existe; conferir se cobre o /v6 (H, Enter, Ctrl+A/D, Delete, Shift+cabo, Ctrl+arrastar...).
- **Atalhos dos padrões da área**, onde não conflitar com os da casa:
  - Tab ou Enter = lista de módulos (VCV);
  - F = enquadrar a seleção, A = tudo (Blender/TouchDesigner; H já é o "caber tudo" daqui);
  - Ctrl+G = agrupar;
  - Ctrl+F = procurar.
- **Cinnamon pega o Alt:** nenhum gesto essencial com Alt (já é regra no Ctrl+arrastar).

---

## 11. Primeira vez e aprendizado
- **Canvas vazio ensina:** "2 cliques no vazio = escolher um módulo · arraste do OUT para um IN = ligar", com uma seta
  desenhada como plaqueta. Some depois do primeiro cabo.
- **Cena de exemplo** ("Primeiros passos": câmera → 3 átomos → saída + 1 LFO) e um link "abrir exemplo".
- **Dica contextual uma vez só** por gesto novo (por exemplo, na primeira vez que um knob vira jack: "ligado por cabo: mexa a
  faixa no alterador"). Guardar em `localStorage`.
- **Medir:** uma pessoa nova faz T1 sem ajuda em < 3 min.

---

## 12. Acessibilidade e legibilidade
- **Escala da interface** (90/100/125/150%) no menu "visual", para telas 4K e projetor. O canvas já tem zoom; isto é a barra e
  os painéis.
- **Daltonismo:**
  - cabos e famílias nunca dependem só da cor: textura da família, forma do jack, rótulo no hover;
  - simular protanopia e deuteranopia nos PNGs do book.
- **Contraste** do tema cel e do tema leve conferido por script.
- **Teclado alcança todo controle dos painéis**, com foco visível.

---

## 13. Desempenho percebido
O desempenho medido já está bom: 60 fps cravados e ~1 ms/quadro.
- **Resposta visual < 100 ms** a todo gesto: o servidor confirma depois, e a tela muda já (otimista). Hoje é assim na maior
  parte; conferir troca de átomo e troca de fonte.
- **Prévias** nascem com o último quadro conhecido, nunca pretas; o mixer do print está com a tela preta (conferir se é
  prévia ou conteúdo).
- **Título da janela "PRISMA · v5"** → "PRISMA — <nome da cena>".

---

## 14. Processo
- **Uma rodada = um prompt + um book:** PNGs lado a lado das variantes, o usuário marca, implementa-se o marcado. Já funciona;
  manter.
- **Todo bug de usabilidade vira teste de gesto** (`tests/dash_gestos.py`), e a suíte fica verde antes de entregar.
- **Ensaio de usabilidade a cada fase:**
  - as tarefas T1–T7 cronometradas com o usuário, e uma vez com alguém que nunca viu o PRISMA;
  - gravar a tela, anotar onde hesita;
  - cada hesitação vira item.
- **Auditoria de heurísticas** (as 10 de Nielsen) por tela no começo de cada fase, como tabela no próprio prompt.
- **Inventário** (130 botões/telas, db `marcas`): cada peça é marcada fica / muda / sai antes da fase que a toca.

---

## 15. Fases (ordem proposta)
| fase | o quê | depende de |
|---|---|---|
| 0 | `PROMPT_RODADA6.md`: knob-jack, fader-jack, alterador editável, relevo, grade do módulo, roda, cor, seletores | — |
| 1 | Sistema de peças + tokens (§2), fichas no `design/`, testes de alvo e relevo | 0 |
| 2 | Canvas: cabos inteligentes, hover, soltar no vazio filtrado, procurar, mapa, molduras (§3) | 1 |
| 3 | Alteradores completos (§4) + roda com prévia (§5) | 1 |
| 4 | TOCAR: barra, segurar para blackout, PROGRAMA/PRÓXIMA mesa de vídeo, cartuchos, saúde (§7) | 1 |
| 5 | Inspetor como tampa traseira, sem duplicatas (§6) | 2 |
| 6 | Equipamento por estado + assistentes (§8) | 1 |
| 7 | Feedback/erros/desfazer, atalhos, primeira vez, acessibilidade (§9–12) | 2–6 |
| 8 | Apagar a reserva HTML (`?html`) e os testes dela, depois de um ensaio real | ensaio |

---

## 16. Perguntas para o usuário (antes da fase de cada uma)
1. Knob-jack: jack no centro da tampa (A) ou fundido no flanco (B)? Será mostrado em PNG.
2. Seletores: a regra "chave = tecla, 2–4 = fader de entalhes, 5+ = rotativo" serve?
3. Soltar cabo no vazio: abrir a roda filtrada (proposta) ou manter o menu do nó de hoje?
4. Cabo de controle diferente do de imagem (mais fino + brilho que corre)?
5. BLACKOUT/SOCORRO: segurar 400 ms ou tecla com capa?
6. Barra do TOCAR como "teclas de TV" e cenas como cartuchos: aprovado para ir ao book?
7. Nome único "Alterador" para o que hoje é controlador/movimento/envelope?

---

## Referências
- **VCV Rack — Panel Guide.** Projetar como hardware; espaço de um polegar entre knob e porta; saída com fundo invertido.
  <https://vcvrack.com/manual/Panel>
- **Bitwig — The Unified Modulation System.** O knob modulado continua usável e mostra a faixa da modulação.
  <https://www.bitwig.com/userguide/latest/the_unified_modulation_system/>
  - Grid: porta de modulação com profundidade ao lado: <https://bitwig.com/userguide/latest/grid_modules>
  - Contorno vivo da modulação no knob:
    <https://admiralbumblebee.com/music/2017/06/23/Bitwig-Modulators.html>
- **Ableton Live — MIDI and Key Remote Control.** Faixa mín/máx de cada mapeamento editável e invertível num lugar só.
  <https://ableton.com/de/manual/midi-and-key-remote-control>
- **TouchDesigner — Network Editor.** Navegação, viewer por nó, dock para reduzir bagunça.
  <https://derivative.ca/UserGuide/Network_Editor>
- **Resolume Wire.**
  - Interface: <https://resolume.com/support/en/7.9/wire-user-interface>
  - Fast patching (arrumar da esquerda pra direita, laços como exceção): <https://www.resolume.com/support/en/fast-patching>
- **Observable — clarifying data flow in canvases.** Entradas sempre de um lado e saídas do outro, para achar sem procurar.
  <https://observablehq.com/blog/clarifying-data-flow-in-observable-canvases>
- **Vuo — destacar os cabos do selecionado.** <https://community.vuo.org/t/better-cable-highlighting/5752>
- **Node-RED — visibilidade das ligações.** <https://discourse.nodered.org/t/improving-connection-visibility/26436>
- **Unity Graph Toolkit.** Valores no inspetor × no grafo; o contraponto ao princípio 4.
  <https://discussions.unity.com/t/unity-s-graph-toolkit-experimental-available-today-in-unity-6-2/1664909/175>
- **Blender — UX dos Geometry Nodes** (modificadores ao mover, escolher ligações).
  <https://devtalk.blender.org/t/proposal-addressing-geometry-nodes-ux-issues/23239?page=3>
- **Seletores discretos.**
  - MathWorks DiscreteKnob, opções em volta e ponteiro:
    <https://au.mathworks.com/help/matlab/ref/matlab.ui.control.discreteknob.html>
  - Plugin-builder, knob com entalhes; para 2–4 opções, não use knob:
    <https://plugin-builder-docs-public.pages.dev/widgets/knob>
- **Teenage Engineering OP-1.** Cor liga o controle ao que ele muda na tela.
  <https://teenage.engineering/guides/op-1/original/layout>
- **W3C — WCAG 2.2, 2.5.8 Target Size (Minimum).** 24×24 px ou 24 px de folga.
  <https://www.w3.org/WAI/WCAG22/Understanding/target-size-minimum.html>
- **Nielsen Norman Group — 10 heurísticas de usabilidade.** <https://www.nngroup.com/articles/ten-usability-heuristics/>
