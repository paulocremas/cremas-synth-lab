# PLANO — a conversa entre átomos (v5 → "em cima" de verdade)

Pedido (2026-11-05): os átomos têm que conversar de forma fluida e intuitiva — ex.: soltar um átomo de COR em cima de
outro átomo e a cor pegar **só o efeito dele, não o fundo**; rever todo botão (sem redundância, cada um com motivo);
o leigo faz combinações incríveis e o conhecimento técnico fica só pra quem ESCREVE átomos; tudo se mescla sem costura.
Base: `shaders/ATOMO.md` (v2), `PLANO_PADROES.md`, decisões no topo do `dash5.html`.

## 0. Diagnóstico — por que a conversa trava hoje
O motor já tinha o "modificador paralelo" (`post`: átomo solto em cima de outro age só na camada dele, antes de juntar),
mas ele só funcionava num caso:

| Situação | Hoje | Por quê |
|---|---|---|
| Tingir em cima do **Contornar** (desenha com alfa) | ✔ pinta só as linhas | a camada do Contornar já é só a linha |
| Tingir em cima do **Brilhar / Separar / Pontos / Vinheta** (filtros) | ✘ pinta a tela toda | a camada de um filtro é a imagem INTEIRA (ele troca a entrada) |
| Onda / Rodar / Espelhar em cima do Contornar | ✘ a cor anda, a linha não | o `post` travava o alfa (`glColorMask` sem A) |
| Feedback em cima do Contornar ("rastro só da linha") | ✘ não roda | o `post` não rodava átomo com memória |
| Opacidade do átomo de cima | ✘ ignorada | o `post` não lia `opacity` |
| Átomo de cima que lê B (Deslocar, Misturar) | ✘ B sem textura | o `post` só ligava a textura 0 |
| Listras em cima do Contornar | ✘ vira listra na tela toda | quem desenha não ficava DENTRO do de baixo |
| No card | etiqueta tracejada fora da conta da altura (vaza); zona de soltar de 14 px "só neste" | o card foi desenhado antes do NÓ = ÁTOMO |
| Soltar num card | 3 alvos (antes / em cima / depois) no mesmo card; "antes/depois" = o "+" do fio | redundância |

Resultado: o gesto mais natural ("põe isso EM CIMA daquilo") dava resultado diferente conforme o átomo de baixo — o
leigo não tem como saber se o de baixo "desenha" ou "filtra". Isso é um caso especial, não uma regra.

## 1. Pesquisa (o que os outros fazem com "escopo")
- **Photoshop — máscara de corte (clipping mask)**: camada de ajuste solta em cima e "presa" (Alt+clique entre as
  duas) age só na camada de baixo; o painel mostra a presa **recuada com uma setinha ↳**. Por padrão, ajuste age em
  tudo abaixo. → nosso par **fio (tudo) × em cima (só ele)**, e o recuo ↳ no card.
- **Procreate — alpha lock × clipping mask**: pintar só onde a camada já tem pixel. → quem DESENHA em cima desenha
  **dentro** do de baixo (a cobertura não cresce).
- **After Effects** — efeito na camada age no conteúdo da camada (inclusive mover/distorcer); "adjustment layer" age em
  tudo abaixo. → espaço em cima MOVE a forma do de baixo (alfa junto), não só a cor.
- **Resolume** — ordem clipe → camada → composição; efeitos do clipe só no clipe. → em cima = efeito de clipe; depois
  da mistura (SAÍDA) = composição.
- **Bitwig — dispositivos aninhados**: o efeito mora DENTRO do device e vai junto no preset; o novato pode ignorar. →
  a pilha "em cima" é parte do nó (copiar / receita leva junto).
- **TouchDesigner Feedback TOP** — o que está DENTRO do laço age a cada volta. → em cima de um átomo com memória = age
  a cada volta (já era o loop RETORNO: espiral, fumaça). É o mesmo princípio: só no que ELE faz (o rastro), não na fonte.

## 2. O modelo — três gestos, três sentidos (o leigo só precisa disto)
1. **No FIO** (o "+" no meio do cabo, ou puxar de uma saída): o átomo trabalha **na imagem inteira** que chega.
2. **EM CIMA** (soltar no card de um átomo): o átomo trabalha **só no que o de baixo FEZ** — a MARCA dele.
   Máscara em cima = **onde** o de baixo age.
3. **JUNTAR** (vários fios numa mistura ou saída): camadas, com opacidade e modo.

### 2.1 A MARCA (regra nova do motor, vale pra qualquer átomo)
Todo átomo, além da imagem, tem uma **marca** = o que ele mudou, como camada RGBA (cor + cobertura):
- quem **desenha** (`cat: gerador | forma`): a marca é o que ele desenhou (o alfa dele);
- **filtro** (todo o resto): a marca é a saída dele **onde ela difere da entrada** — `smoothstep(MARCA_LO, MARCA_HI, |saída − entrada|)`
  (cor ou cobertura). Brilhar → o halo; Separar → as franjas; Vinheta → a borda escura; Espelhar → a metade espelhada;
  Luz/Matiz → a tela toda (mudou tudo). O átomo não declara nada: o motor compara.
- átomo com **memória**: a marca é o que recircula (o loop RETORNO de sempre).

Juntar de volta: `marca' sobre a entrada` (POR CIMA, alfa direto). Sem nada em cima, nada muda (o filtro segue TROCA).
Identidade garantida: se o de cima não faz nada, o resultado = o átomo sozinho, com erro ≤ ~0,4 · `MARCA_HI` no pior
pixel (onde a diferença fica abaixo do limiar) — invisível; e **onde a marca é zero o fundo sai intacto, por construção**.

### 2.2 Como cada átomo age EM CIMA (sai das regras que já existem, `atom_replaces`)
| Quem está em cima | Age na marca como | Exemplo |
|---|---|---|
| **filtro de cor/luz** | troca a cor, cobertura igual | Tingir no Brilhar = halo colorido, câmera intacta |
| **filtro de espaço** | move cor E cobertura | Onda no Contornar = a linha ondula; Rodar no Pontos = os pontos giram |
| **quem desenha** | desenha DENTRO (alpha lock) | Listras no Contornar = linha listrada |
| **com memória** | rastro da marca (a cobertura cresce) | Feedback no Contornar = a linha deixa rastro, o fundo limpo |
| **máscara** | limita ONDE o de baixo age | Rosto em cima do Desfocar = só o rosto desfoca |
| (tudo) | opacidade = quanto do de cima vale; B ligado | Deslocar em cima lê a entrada B dele |

Vários em cima: um depois do outro, na ordem (de cima pra baixo no card), todos presos ao MESMO de baixo (como no
Photoshop). O mesmo id em vários nós = um só (fio de "usar aqui também"), como já era.

## 3. Contrato do átomo — o que muda pra quem ESCREVE átomos (ATOMO v2 → v2.1)
Pouco, de propósito: a conversa sai de regras do motor, não de código em cada átomo.
- **Nada novo obrigatório.** A marca é derivada (`cat` + comparação); o encaixe "em cima" usa as mesmas regras de alfa
  (§5 do ATOMO: filtro devolve o alfa que leu, espaço move o alfa, quem desenha dá cobertura).
- **`// B: nome`** (opcional, recomendado em quem lê B): o que a entrada B SIGNIFICA pra este átomo — vira o nome do
  jack e do inspetor ("direção", "outra imagem", "forma", "empurra", "semente"). O leigo lê o verbo, não a letra.
- Regras que ganham peso (a matriz agora confere "em cima"): alfa honesto (filtro que devolve `1.0` quebra a marca),
  neutro = identidade (o de cima no neutro some), espaço em fração da tela (o de cima roda na mesma camada).

## 4. Motor (`native_synth.run_row`)
- [x] `stack_prog` (shader `STACK_SRC`): op 0 = extrai a MARCA de um filtro (entrada × saída → RGBA com cobertura da
  mudança); op 1 = DENTRO (alpha lock) pra quem desenha; op 2 = TROCA com opacidade (`mix(marca, de cima, a)`).
- [x] `post` sem `glColorMask`: espaço move a cobertura.
- [x] em cima com MEMÓRIA: `run_state` do item em cima, lendo a marca (buffer próprio pelo id).
- [x] opacidade do de cima (suavizada, × EFEITOS) e entradas B (`bind_inputs`).
- [x] juntar: com algo em cima, `marca'` entra POR CIMA (u_aout 3) na entrada; o modo/opacidade do de baixo valem.
- [x] constantes `dash_data.MARCA_LO/HI`.

## 5. Dash v5
### 5.1 Card do nó
- [x] **Em cima** = linhas no card (não etiqueta): `↳ ícone Nome` + o knob principal (barra) + liga/desliga,
  recuadas como no Photoshop; a altura do card conta as linhas (antes vazava).
- [x] entrada B com o nome do `// B:` (no inspetor e no título do jack; o jack segue "B": o vão de 24 px não cabe palavra).
- [x] máscara = "só onde" (rótulo da zona e do inspetor).

### 5.2 Soltar (três alvos, sem sobreposição)
- [x] átomo solto **no card de um átomo** = EM CIMA (o card inteiro é o alvo, rótulo "só no que <Nome> faz";
  máscara: "<Nome> só onde …"). Some a zona de 14 px e as zonas "antes/depois" dentro do card de átomo (o "+" do fio
  faz isso).
- [x] átomo solto **no fio** = na corrente (o "+" de sempre).
- [x] átomo no card de **fonte / mistura / saída** = depois dela (como antes).
- [x] máscara solta num card de átomo = "só onde".

### 5.3 Auditoria de botões — cada um com motivo (P palco · S segurança · C montagem)
| Onde | Elemento | Motivo | Decisão |
|---|---|---|---|
| topo | cadeado | S | fica |
| topo | bloco da música (abre tempo) | P/S | fica; o **TAP de dentro sai** (o TAP do topo é o mesmo, sempre à mão) |
| topo | TAP | P | fica |
| topo | Equipamento · EFEITOS/MASTER · SOCORRO · BLACKOUT | C · P · S · S | ficam |
| cenas | cena (pad), + nova | P · C | ficam |
| cenas | **imagem da cena** (☀) | — | **sai do caminho**: luz/cor da cena = átomos na SAÍDA (mesma coisa, um conceito só). Aparece só se a cena já usa |
| cenas | grade / dura | P | ficam |
| canvas | zoom − + | C | fica |
| canvas | cabo tensão + opacidade (2 réguas fixas no topo) | preferência | **viram 1 botão "cabos"** (abre as duas réguas) |
| canvas | custo GPU | C | fica (só montando) |
| canvas | + staging | C | **"+ mistura"** (palavra do leigo; o código segue `mix`) |
| canvas | + saída · arrumar · desfazer | C | ficam |
| inspetor do átomo | liga · espelho · variações · tirar | P · C · C · C | ficam |
| inspetor do átomo | **dado** (sortear knobs) | — | **sai**: VARIAÇÕES faz o mesmo com prévia fora do ar (mais seguro) e Ctrl+Z |
| inspetor do átomo | "mais → lê: o que vem antes / a fonte crua" | — | **sai**: o fio A já diz de onde lê (ligue a fonte no A). Cena antiga com `in: src` mostra 1 botão "ler o que vem antes" |
| inspetor do átomo | "mais → dispara" vazio | — | só aparece se houver o que mostrar (cena antiga) |
| inspetor do nó | "Onde no palco" em todo nó | — | **sai**: lugar é da SAÍDA (fica no inspetor da saída) |
| inspetor do nó | "Máscara da caixa" | C | **"Só onde (máscara)"** |
| inspetor em cima | "paralelo · só nos átomos abaixo" | — | **"em cima de X · só no que X faz"** + opacidade (agora vale) |

## 6. Verificação
- [x] `src/matriz.py`: **todo par X ↑ Y** (Y em cima de X, referência numpy da mesma regra): sem NaN; **fundo intacto**
  (onde a marca de X é zero, sai a entrada); **identidade** (Y neutro ⇒ X sozinho); quem desenha em cima não aumenta a
  cobertura; X ↑ Feedback roda 30 passos.
- [x] selfcheck do native/dash_server/dash_data.
- [x] prints do `/frame` (motor isolado, vídeo da mídia): Tingir ↑ Brilhar = só o halo vermelho; Onda ↑ Contornar = só a
  linha ondula; Feedback ↑ Contornar = rastro só da linha. Dash v5 no Brave headless: card com a linha ↳, sem erro de JS.

## 7. Depois (combinado, não feito agora → BACKLOG)
- Prévia fora do ar ao soltar EM CIMA (o `/try` só troca a pilha principal).
- Arrastar um átomo de dentro de "em cima" pra fora (vira nó no fio) e vice-versa com o mesmo gesto.
- Gerador sem entrada (fonte "vazio") — Listras/Ruído como camada sozinhos.
- Nome do jack B em TODOS os leitores de B (feito nos átomos da biblioteca; receitas antigas usam o padrão).

## 8. v6 — a tela repensada do zero (pedido de 2026-11-05: "minimalismo e performance ao vivo"; PROPOSTA, falta aprovar)
O §5 consertou a v5 sem mudar a casa de lugar. Aqui a pergunta é outra: se não existisse nada, o que a tela PRECISA ter?
Mockup: `docs/mock_v6.html` (estático, só pra decidir a direção).

### 8.1 Sete palavras (o leigo só aprende estas)
| Palavra | É | Some da tela (vira detalhe interno) |
|---|---|---|
| **Fonte** | câmera, vídeo, imagem | "caixa", "fileira", "canal" |
| **Átomo** | um verbo na imagem | "módulo", "preset", "clássico" |
| **Fio** | a ordem: o próximo age em TUDO que chega | "corrente", "entrada A" |
| **Em cima** | só no que o de baixo FEZ (máscara em cima = ONDE) | "paralelo", "post", "máscara da caixa", "loop retorno" |
| **Mistura** | junta fios em camadas; com lugar no palco = é uma SAÍDA | "staging" × "saída" (dois nós pra mesma coisa) |
| **Movimento** | o que faz um knob andar sozinho com a música | "controlador", "modulador", "macro" |
| **Cena** | o estado guardado; GO leva a próxima ao ar | "set" |
Fica fora do vocabulário do leigo (menu "mais" de quem monta): espelho, entrada B crua/↺, modo de mistura, laço.

### 8.2 Dois modos = duas telas (não um cadeado sobre a mesma tela)
O palco e a montagem têm tarefas opostas: montar = precisão, muitas opções, tempo; tocar = poucos alvos grandes, zero
risco, olhos no telão. Hoje o cadeado esconde coisas da MESMA tela (a cabeça tem que lembrar o que sumiu).
- **TOCAR** (padrão ao abrir um show): três faixas. Esquerda = CENAS (pads grandes, letra do teclado). Centro = PROGRAMA
  enorme (o que o público vê) com PRÓXIMA pequena + GO embaixo. Direita = os knobs PUBLICADOS da cena + M1–M4 (≥ 56 px).
  Canvas não aparece (no palco ninguém religa fio). Topo: só música, EFEITOS, MASTER, BLACKOUT, SOCORRO.
- **MONTAR**: esquerda = BIBLIOTECA (busca + 4 abas: Fontes · Átomos · Movimentos · Receitas). Centro = CANVAS. Direita
  = INSPETOR só com o que não cabe no card (movimento, publicar, B, memória, "mais"). PROGRAMA vira monitor pequeno
  fixo no canto do canvas.
- Troca: um seletor com as PALAVRAS "TOCAR | MONTAR" (o cadeado dizia "travado", que é o efeito, não a tarefa). F1/F2.

### 8.3 Linguagem visual (menos tinta, mais sinal)
- **4 cores com sentido, nada decorativo**: verde = no ar · laranja = escolhido / o que a mão faz · azul = anda sozinho
  (movimento) · roxo = onde (máscara). Vermelho só perigo. Some a cor por categoria do átomo (linha no topo do card): o
  ícone já diz o tipo e a cor competia com os 4 sentidos.
- **Card sem moldura pesada**: superfície um tom acima do fundo, título = ícone + verbo, knobs. Número do nó, LED de
  estado/laço e nome do jack só de PERTO (zoom semântico) — de longe = só verbo + fios.
- **Em cima = recuo ↳** (Photoshop); **onde = faixa roxa** no pé; **fio = 1,5 px neutro**, acende ao passar o mouse.
- **Tipografia**: uma família; 3 tamanhos (título 13, corpo 12, legenda 11); números em mono. Rótulo em caixa alta com
  espaçamento só no título de painel (hoje 18 rótulos competem).
- **Palco escuro**: fundo #0b0d10, nada branco puro fora do PROGRAMA; animação só onde há informação (batida, movimento).
- **Alvos**: ≥ 32 px montando, ≥ 56 px tocando (Fitts; tela de toque no palco).

### 8.4 Cada controle e o motivo (inventário da v6; o que não está aqui não existe)
| Lugar | Controle | Motivo (tarefa) | Modo |
|---|---|---|---|
| topo | TOCAR / MONTAR | trocar de tarefa | ambos |
| topo | faixa da música (BPM, batidas, seção, tom); clique = o painel do tempo (×2, ÷2, "1", seção) | ver e corrigir o tempo, que move tudo | ambos |
| topo | TAP (botão próprio) | bater o tempo: ação de palco, precisa de alvo fixo e mapeável no MIDI (revisto: juntar no BPM sobrecarregava um clique) | ambos |
| topo | EFEITOS (fader) | tirar todos os efeitos de uma vez sem perder nada | ambos |
| topo | MASTER (fader) | brilho final | ambos |
| topo | BLACKOUT | preto na hora (S) | ambos |
| topo | SOCORRO | sair do pânico: congelar, desfazer, cena segura (S) | ambos |
| topo | ⚙ (ícone) | equipamento: áudio, saídas/telas, luzes, MIDI | ambos |
| esquerda | pad de cena (letra) | levar ao ar / marcar a próxima (clique direito) | ambos |
| esquerda | + cena | guardar o estado como cena | montar |
| esquerda | grade (na hora / batida / compasso / frase) | trocar no tempo da música | ambos |
| centro | PROGRAMA | o que o público vê (S) | ambos |
| centro | PRÓXIMA + GO | ensaiar e soltar a próxima cena | tocar |
| canvas | arrastar da biblioteca: no FIO / EM CIMA / no vazio | os três gestos (§2) | montar |
| canvas | zoom (roda; − %) e ARRUMAR | achar e organizar | montar |
| canvas | desfazer (Ctrl+Z; botão) | errar sem medo | montar |
| card | knobs; ↳ linhas em cima; faixa "só onde" | o átomo e o que está preso nele | ambos (tocar: só publicados) |
| inspetor | MOVIMENTO (presets 1 toque) | fazer andar com a música | montar |
| inspetor | ★ publicar | levar um knob pro TOCAR | montar |
| inspetor | liga · variações · tirar | ouvir sem, explorar com prévia, apagar | montar |
| inspetor › mais | modo de mistura · espelho · B crua/↺ · semear/limpar | o raro | montar |
| direita (tocar) | knobs publicados · M1–M4 | a mão no show | tocar |
**Sai da tela** (motivo): cadeado (vira TOCAR/MONTAR) · TAP de dentro do painel do tempo (= o do topo) · "imagem da cena" (= átomo na
saída) · réguas de cabo (preferência → ⚙) · custo GPU (vira aviso de SAÚDE só quando passa do limite) · "+ staging" e
"+ saída" (um só: "+ mistura"; a mistura ganha lugar no palco = saída) · dado (= variações) · "lê a fonte crua" (= fio A)
· número do nó, LED de estado/laço, nome do jack de longe (zoom semântico) · cor por categoria (ícone).

### 8.5 Fases
1. [x] Tela TOCAR (canvas sai, PROGRAMA no centro, PRÓXIMA + GO, knobs na mão; sem publicado = o principal de cada átomo no ar).
2. [x] Mistura = saída: UM botão "+ mistura"; no inspetor a chave **no palco** troca `kind` mix ↔ out no lugar (a chave do nó
   `'+id'` não muda; o motor não muda); a única saída não sai do palco. Menu do fio: "mistura" e "mistura no palco (saída)";
   "staging" sumiu de todo texto visível.
3. [x] MONTAR: biblioteca em 4 abas com palavras (Fontes · Átomos · Movimentos · Receitas; busca em todas; "Onde (máscaras)"
   e "Outros" dentro de Átomos); card sem a cor da categoria (4 cores com sentido).
4. [x] Cadeado → TOCAR | MONTAR (F1/F2); custo de GPU saiu do topo do canvas e foi pro aviso de fps da SAÚDE.
5. [ ] Falta: zoom semântico completo (número do nó e LEDs só de perto), tipografia em 3 tamanhos, TOCAR com cenas maiores
   e GO no MIDI destacado, inspetor com "mais…" recolhendo espelho/B crua/modo.

## 9. Conceitos — 2ª passagem: fácil de usar SEM limitar quem cria (2026-11-05)
Pedido: conceitos que facilitem o uso mas não limitem o desenvolvedor em nada.

### 9.1 Princípios (de onde vêm)
1. **Chão baixo, teto alto, paredes largas** (Papert/Resnick; Resnick & Silverman 2005: "específico o bastante pra
   entender rápido, geral o bastante pra usos novos"). Leigo começa em 1 gesto; quem escreve GLSL não bate no teto;
   muitos caminhos levam a coisas diferentes.
2. **Declarar, não proibir** (o ISF do VDMX: o shader DECLARA entradas — float, evento, imagem, áudio, FFT — e o host
   monta a interface). Tudo que o desenvolvedor escreve RODA. O motor LÊ o código pra dar nome, controle e encaixe;
   o padrão vira **sugestão visível**, nunca porta fechada.
3. **Deduzir antes de pedir**: o que dá pra ler do código não vira cabeçalho obrigatório (chave = `step(.5, …)`,
   escolha = `floor(… * N)`, ouve o som = usa `u_bass`, vê o rosto = usa `u_rosto`, marca = pela `cat:`). Cabeçalho só
   pra o que o código não diz (nome, o que B significa) ou pra CONTRARIAR a dedução (`// entra:`, `// marca:`).
4. **Expor só o que importa** (custom parameters do TouchDesigner: o de dentro fica dentro). O card mostra o principal +
   o que cabe; o resto existe e está a um clique — nunca apagado.
5. **Todo atalho tem saída** (nenhum beco): receita abre em átomos; "em cima" vira fio e volta; mistura com lugar no palco
   = saída; movimento é um nó que se abre; TOCAR e MONTAR são vistas do MESMO estado.
6. **Tentar e voltar** (Shneiderman, ferramentas de criatividade): prévia fora do ar, variações, desfazer — errar é barato.
7. **Seguro no palco**: o que pode estragar o show (religar, apagar) só existe em MONTAR; em TOCAR tudo é reversível.

### 9.2 Três camadas de conceito (cada uma é opcional pra quem está na de baixo)
| Camada | Quem | Conceitos | Onde aparece |
|---|---|---|---|
| **Tocar** | qualquer um no show | cena, GO, knob na mão, EFEITOS, MASTER, BLACKOUT, SOCORRO | tela TOCAR |
| **Montar** | o leigo que cria | fonte, átomo, fio, em cima (+ só onde), mistura, movimento, receita | tela MONTAR |
| **Mais** | o curioso | entrada B, modo de mistura, espelho, laço, memória (semear/limpar), faixa do movimento | inspetor › mais |
| **Escrever** | o desenvolvedor | GLSL livre + cabeçalho declarativo (abaixo) | `shaders/presets/atomos/*.frag` |

### 9.3 O contrato do desenvolvedor: QUEBRA × FORA DO PADRÃO
Antes: qualquer desvio (4 knobs, ler o grave, `cat:` desconhecida) tirava o arquivo da biblioteca (`atom = not
atom_problems`). Agora dois níveis (`dash_data.atom_problems` × `atom_avisos`):
- **QUEBRA** (o motor não consegue rodar ou encaixar — o arquivo não entra): não compila por redeclarar o prelúdio ou
  `#version`; sem `gl_FragColor`; lê o estado sem `// estado:`; `// estado:` sem `u_vista`.
- **FORA DO PADRÃO** (roda e encaixa; a biblioteca mostra um ⚠ com o motivo, a matriz avisa): mais de 3 knobs, knob sem
  uso / sem `// fx:`, `cat:` desconhecida (vira filtro), sem a linha `ATOMOS ·` (nome = arquivo), lê B sem `// in:`,
  `// mod:`/`// bipolar:`/`// ritmo:` em knob que não existe, estado com `u_time`, uniform que o motor não conhece (vale 0).
- **DECLARADO, não aviso** (o motor liga e o dash MOSTRA pro leigo): lê o som (`u_bass`, `u_kick`, faixas…) → selo ♪
  "ouve a música"; lê o rastreio (`u_rosto`, `u_corpo`…) ou o assunto (`u_subject`) em QUALQUER átomo → selo 👁 e o
  motor pede o rastreio daquela fonte. O caminho recomendado continua (som = movimento no knob), mas não é o único.

### 9.4 Cabeçalhos novos (todos opcionais)
- `// entra: troca | cima` — contraria a dedução da `cat:` (um gerador que é filtro, uma cor que desenha por cima).
- `// marca: mudanca | alfa` — o que "em cima" pega deste átomo (padrão: quem desenha = alfa = a saída como está;
  filtro = mudança). (`tudo` seria igual a `alfa`: ficou de fora.)
- `// B: nome` — o que a entrada B significa (já feito).

### 9.5 Feito nesta rodada (desenvolvimento)
- [x] `atom_problems` (QUEBRA) × `atom_avisos` (FORA DO PADRÃO); `parse_meta` com `ouve`, `ve`, `entra`, `marca`, `avisos`.
- [x] `/shaders` meta: `atom` = é átomo e não QUEBRA (aviso não tira da biblioteca); ⚠, ♪ e 👁 na biblioteca/inspetor.
- [x] Motor: `// entra:` e `// marca:` (`atom_replaces`, `atom_marca`); `u_subject` em qualquer átomo; rastreio pedido por quem lê.
- [x] Matriz: só QUEBRA falha; FORA DO PADRÃO vira aviso impresso.
- [x] Tela TOCAR (v6 fase 1) no dash5: seletor TOCAR | MONTAR no lugar do cadeado; em TOCAR o canvas sai e o PROGRAMA
  ocupa o centro com PRÓXIMA + GO; cenas à esquerda, knobs na mão + movimentos à direita.
