# Prompt — PRISMA /v6, rodada 6: knob-jack, fader ao lado da tela, alterador editável, layout sem invasão, roda, módulo de cor, seletores

Cole num chat novo, na pasta do repo. Responda em pt-BR.

Esta rodada mexe só no canvas dos módulos do `/v6`, que é o bloco `G6` no fim do `dash5.html`, e no que ele usa: `hzLayout`,
`tvWide`, `knobSpec`, `paintCtl`, `wheelSectors`. O motor (`native_synth.py`) não muda, salvo o item 7 se o diagnóstico mandar.

## Leia antes
- `CLAUDE.md`, seções **dash5** e **/v6**: decisões fechadas, não reabrir.
- O comentário de decisões no topo do `dash5.html`.
- Memórias `prisma-v6-jogo` e `visual-mini-tv-decisoes`.
- O código:
  - `hzLayout` (≈ `dash5.html:3461`), a geometria do módulo horizontal;
  - `tvWide` (≈ `:3352`), as teclas dentro do card;
  - `ctlRange` (≈ `:3936`), a faixa de/até no DOM antigo;
  - `wheelSectors` / `openWheel` (≈ `:4855`/`:4909`);
  - no bloco G6: `build()`, `knobSpec`, `paintCtl` (≈ `:8556`), `liveSkin`, as mãos (`turnStart`/`turnMove`, `cvHand`, `pick`).
- `tests/dash_gestos.py`: 75 testes, todos verdes, e precisam continuar verdes.
  - Os do /v6 são `t6_*`, abertos com `v6_open()`.
  - Todo item desta rodada ganha teste `t6_*`.

## Regras de trabalho
- **Cada mudança vai pro app na hora.** Copie `dash5.html` (e o que mais mudar em `src/`) para `dist/prisma/` **e**
  `~/.local/share/prisma/`, e confira com `cmp`. O dash recarrega sozinho.
- **Mexer no app aberto grava o `tuning.py` vivo.** Antes de clicar ou testar nele, faça backup do
  `~/.local/share/prisma/src/tuning.py`.
- **Commit e push só quando o usuário pedir.**
- **Mostre antes de fechar.** Nos itens de desenho (1, 2, 5 e 8), tire um PNG do canvas pelo CDP (o `dash_gestos.py` já sabe
  abrir) e mostre ao usuário antes de dar o item por fechado.
- **Ambiguidade de verdade = perguntar.** Pergunte com uma imagem do estado atual, não com texto solto.

## MODO NOTURNO (o usuário está dormindo; vale acima das regras de "mostrar" e "perguntar")
- **Não espere resposta.**
  - Onde o texto manda mostrar ou perguntar, decida pela opção marcada como recomendada (variante A no item 1; a regra
    S3/S2/S1 no item 8; no item 2, a opção mais limpa) e implemente.
  - Salve os PNGs das variantes não escolhidas e do antes/depois em `design/rodada6/`, para ele trocar de manhã.
- **Diário em `RODADA6_PROGRESSO.md`**, atualizado ao FIM DE CADA ITEM:
  - item, feito/pendente, o que decidiu e por quê, testes, PNGs.
  - Ao começar, se o arquivo já existe, LEIA e continue do primeiro item pendente (uma sessão anterior pode ter caído no
    meio). Confira com `git diff` o que já está no código.
- **Ordem:** 4 → 5 → 2 → 1 → 3 → 6 → 7 → 8. Layout primeiro, porque os outros dependem da grade.
- **A suíte fica verde a cada item.**
  - Item quebrado e sem conserto em ~1 h: desfaça só ele, marque "pendente: motivo" e siga.
  - Nunca deixe o `dash5.html` do app quebrado: só copie para `dist/` e para a pasta de dados com a suíte verde.
- **Não toque no app aberto.** Use só a porta de teste (8799). Não abra a janela do PRISMA nem grave o `tuning.py` vivo.
  Nada de commit e nada de push.
- No item 7, o diagnóstico com câmera colorida pode ser feito no native de teste em segundo plano (`PRISMA_HIDDEN=1`) ou pela
  leitura do shader. Não mude o átomo; só proponha no diário.
- **Ao terminar tudo:** escreva `FEITO` na primeira linha do `RODADA6_PROGRESSO.md`, e embaixo o resumo para o usuário ler de
  manhã: o que mudou, o que escolheu por ele e onde estão os PNGs.

## Os pedidos (rodada do usuário, 2026-11-18, com print do app)

### 1. KNOB + JACK numa peça só
"O knob e o jack devem ser misturados, tipo um knob + jack mesmo."

Hoje (rodada 5) o knob É o jack: ligado não gira, e apertar pega o cabo. Mas visualmente ainda é um knob comum.

Quero UMA peça física:
- **Variante A (recomendada): jack no CENTRO da tampa do knob.**
  - Visual:
    - a tampa é a porca do jack, com o furo no meio;
    - o corpo e a saia continuam sendo o knob, com o ponteiro na saia;
    - o plugue pousa no centro, na cor do cabo.
  - Gesto:
    - arrastar no anel ou na saia = girar;
    - apertar no centro = cabo (pegar, plugar ou soltar);
    - ligado = o anel de fora mostra a faixa de/até e o valor vivo (o arco de modulação do Bitwig), e girar fica bloqueado.
  - Pick: centro com raio ≥ 9 px de mundo = jack; o resto do disco = knob.
  - O knob cresce o quanto precisar para as duas zonas terem alvo bom: ≥ 24 px de tela a 100% (WCAG 2.5.8).
- **Variante B: jack fundido no flanco** (silhueta em "8"). Use se a A ficar ilegível de longe.
- Desenhe as duas no sprite, mostre ao usuário e implemente a escolhida.
- O cabo de controle chega no centro.
- No LOD "longe", desenhe só o disco com o anel aceso.

### 2. Fader de opacidade COMPRIDO ao lado da tela, com jack embaixo
"O fader de opacidade deve ficar ao lado da tela, comprido, com um jack embaixo dele para ligar o alterador."

- **Átomo:** fader VERTICAL colado na lateral direita da tela, com a altura da tela. Embaixo dele vai o jack de controle da
  opacidade.
  - Sai o `vfader` atual, que fica no fim da fileira dos knobs.
- **Ligado** (`row.mod.opacity`): o fader não arrasta. A trilha mostra a faixa de/até e o valor vivo, igual ao anel do knob.
  - O id continua `bar:<nó>:…:opacity`; MIDI e learn seguem funcionando.
- **Mixer e saída:** cada linha já tem fader horizontal. Ponha o jack de controle da camada na ponta do fader, antes do olho,
  com a mesma regra (`linkLayerMv`).
  - Se não couber limpo, mostre ao usuário as duas opções.
- O cabo do alterador hoje chega no fader por `L.mod.opacity`. Ele tem que passar a chegar NESSE jack: atualize `pick`,
  `inAt` e o desenho do cabo.

### 3. Editar os LIMITES no ALTERADOR (e não no knob) + arrastar o espaço
"Não tá dando para editar os limites no alterador (não deve ser possível fazer isso no knob). Também não dá pra arrastar o espaço."

Hoje o `paintCtl` só desenha as linhas `rg` (de/até) como barras mortas. Nenhuma mão do G6 trata elas.

Implemente nas linhas da faixa do alterador:
- **Gestos:**
  - arrastar a ponta esquerda = **de**; arrastar a direita = **até**;
  - arrastar o MEIO (o "espaço" entre as pontas) = move as duas juntas, mantendo a largura (decisão `egrip` do design book);
  - 2 cliques = faixa padrão;
  - roda do mouse em cima = abre ou fecha a faixa em volta do meio;
  - Shift = passo fino;
  - bipolar (`metaOf(file).bipolar`): o zero no meio.
- **Dados:** grave em `x.mod[n].lo/hi`, igual ao `ctlRange.set`. Para camadas, use `L.mod.opacity`.
- **Visual:**
  - mostre o valor ao vivo na faixa;
  - cada linha leva a cor do cabo dela e o nome curto do knob;
  - linhas com ≥ 12 px de altura de alvo.
- **Mais de 2 ligações:** o alterador cresce em altura, uma linha por ligação. Acaba o "+N no painel".
- **Tirar a edição de faixa do KNOB e do inspetor do knob.** Verifique `knobSpec` ("com ativador = ALCANCE") e o `rangeCtl` do
  painel; o knob ligado só mostra.
- **Confirme o que é "arrastar o espaço".** Se o usuário quis dizer arrastar o ALTERADOR pelo osciloscópio, teste isso também:
  o módulo tem que arrastar por qualquer parte que não seja controle.
- Testes:
  - `t6_alterador_faixa`: ponta, meio, 2 cliques, e o knob não edita;
  - `t6_alterador_arrasta`.

### 4. Nada invade o relevo do módulo
"Os knobs e jacks não devem invadir os relevos dos módulos." No print, os knobs do CONTORNAR passam da borda de baixo.

- Defina uma ÁREA ÚTIL por módulo: o retângulo interno menos o bisel e o raio da família (`RAD`, a borda do `body()`).
- Todo controle e todo jack, com a sombra e o rótulo, cabem nela.
- `hzLayout` calcula `H` e `W` a partir disso. Margem mínima de 8 px até o bisel (regra do VCV: espaço pra um polegar entre
  peças).
- Teste `t6_dentro_do_relevo`: para todo nó da cena de teste (todas as famílias, fonte, mixer, saída, alterador), todo
  `ctrls`/`ports`/`knobs` tem o círculo dentro da área útil. Ele roda também com 0, 1, 2 e 3 knobs, com teclas e com B/MÁSC.

### 5. Usar bem o espaço (o OUT no meio vertical, sem vazios)
"O OUT pode ficar alinhado com o meio verticalmente; pense bem para utilizar bem os espaços."

No print aparecem:
- vazio à direita no POLAR e no MISTURAR;
- o mixer alto demais para o que mostra;
- o alterador com letra miúda.

Refaça `hzLayout` como uma GRADE de colunas:
`[trilho de entradas] [tela] [fader+jack] [nome / teclas / knob-jacks] [OUT]`

- Todas as colunas centradas na vertical.
- **OUT** no meio da altura do módulo. O **trilho de entradas** também, centrado.
- A altura vem da coluna mais alta; a largura é a soma das colunas, sem sobra.
- Grade de 4 px; nada solto.
- Fonte, mixer, saída e alterador seguem a mesma lógica (o mixer encolhe pra altura das linhas dele).
- Texto ≥ 10 px na escala 100%, e etiquetas sempre em plaqueta (decisão antiga).
- Depois, rode "arrumar" na cena de teste e veja se nada se sobrepõe: `boxW`/`boxH` vêm do `hzLayout`.
- Mostre ao usuário o antes e depois de 4 módulos (Contornar, Polar, Misturar, mixer) num PNG.

### 6. A RODA de módulos com as categorias certas
"A roda de módulos não atualizou para as categorias certas."

Diagnostique antes de mexer. Abra a roda no `/v6` (2 cliques no vazio) e tire um PNG.

Suspeitas:
- (a) as fatias vêm do `CATS` antigo (`dash5.html:2798`), com "outros" e "mistura" como categoria de átomo, e não batem com as 9
  FAMÍLIAS dos gabinetes;
- (b) "mistura" aparece duas vezes (categoria + "Misturas");
- (c) "Movimentos" deveria se chamar **Alteradores** (o nome que o usuário usa);
- (d) as fatias não têm a cor ou a textura da família (pedido antigo: "fatias sem a cor da família", "as cores se
  sobrepunham");
- (e) a roda ainda é o DOM `.wheel` com o visual antigo, fora da estética dos módulos.

Proposta:
- **Fatias:** Fontes · as famílias, cada uma com a amostra do material dela, só as que têm átomo · Máscaras · Alteradores ·
  Mixer/Saída · Receitas (se houver).
- Nenhuma duplicada, nenhuma vazia. "Outros" só se sobrar átomo sem `cat`; nesse caso, liste-os no relatório para ganharem
  `cat`.
- Se ainda não ficar claro o que são as "categorias certas", pergunte mostrando o PNG atual e a proposta.

### 7. O módulo de COR "parece não fazer nada"
No print, o MATIZ (família cor) lê o CONTORNAR, que entrega imagem preto e branco. Girar a matiz de um cinza dá o mesmo cinza.
A hipótese é que não seja bug, e sim a entrada não ter cor.

Confirme:
1. Ligue o Matiz direto na câmera colorida e veja a prévia girar.
2. Confira se o liga está aceso e se a opacidade está > 0.
3. Confira se o `mod: giro=anda` está mexendo (osciloscópio).

Se a hipótese se confirmar, é problema de USABILIDADE. Proponha ao usuário, sem mudar o átomo sem ele aprovar:
- **(i)** aviso no módulo quando a saída ≈ a entrada por alguns segundos.
  - O native já tem a prévia do nó; uma diferença média barata entre entrada e saída do nó basta.
  - O módulo mostra o LED "sem efeito visível" com a dica "entrada sem cor".
- **(ii)** sugerir Tingir / Paleta / Rampa (família cor) quando a entrada é cinza.

Se for bug de verdade, corrija e faça teste.

### 8. Botões mais agradáveis: seletor que APONTA para a opção
"Pense numa forma mais agradável de fazer os botões, talvez um fader que aponte para cada opção."

Hoje escolha/chave = TECLAS no card (`tvWide`).

Lembre do que já foi decidido:
- o usuário NÃO gostou da ALAVANCA;
- legibilidade acima de tudo;
- sem parafusos.

Faça um mini book no próprio canvas (sprites lado a lado, PNG para o usuário) com:
- **S1 · seletor ROTATIVO com ponteiro e entalhes:** rótulos em arco em volta, o ponteiro aponta, e a opção escolhida acende
  (LED ou letra clara).
  - Clique no rótulo = vai direto; arrastar = passa por entalhes; roda = próximo.
  - Bom de 3 a 8 opções. É o seletor de onda dos sintetizadores de hardware.
- **S2 · fader de ENTALHES:** trilha curta com N paradas e os rótulos ao lado de cada parada. O cursor pula de entalhe em
  entalhe e a opção acende.
  - Bom de 2 a 4 opções; a recomendação do plugin-builder é não usar knob para 2–4 opções.
- **S3 · teclas iluminadas** (a de hoje), mais bonitas: tecla de rádio de TV antiga, a apertada afunda e acende.

Regra proposta (o usuário confirma): chave liga/desliga = S3 de uma tecla; 2–4 opções = S2; 5+ = S1.

Em todos:
- o mesmo id `bar:` (MIDI segue);
- o ALTERADOR pode ligar (o jack da opção, com o mesmo padrão knob-jack do item 1, se fizer sentido);
- Shift+clique = volta uma;
- alvo ≥ 24 px.

## Ao terminar
- Rode a suíte inteira: `.venv/bin/python tests/dash_gestos.py`, mais `src/dash_server.py`.
- Copie pro app e confira com `cmp`.
- Atualize `CLAUDE.md` (seção /v6, linha "RODADA 6"), o comentário do topo do `dash5.html` e a memória `prisma-v6-jogo`.
- Responda ao usuário com o que mudou, o que ficou para ele escolher (com os PNGs) e como testar no app.
