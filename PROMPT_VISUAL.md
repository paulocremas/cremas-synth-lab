# Prompt — PRISMA: o canvas com cara de módulos de synth (estilo VCV) — cole num chat novo, na pasta do repo

Você vai revisar a ESTÉTICA do dash v5 (`dash5.html`) pra cada nó do canvas parecer um **módulo de sintetizador**
(painel de Eurorack / VCV Rack): painel, nome serigrafado, knobs com escala, jacks com nome, LEDs. Também vai
reposicionar as coisas dentro do nó e no resto da tela pra tudo falar a mesma língua visual.
O comportamento NÃO muda: é visual + posição. O motor (`native_synth.py`) fica intocado.

As decisões abaixo já foram APROVADAS pelo Paulo; os pontos **[aberto]** são seus pra decidir com pesquisa.

Antes de tudo leia:
- `CLAUDE.md`, em especial "GRAFO / cabos VCV" e "v5".
- O comentário de decisões no topo do `dash5.html`. Todo elemento tem motivo: P palco / S segurança / C montagem.
- `shaders/ATOMO.md`: `// cat:`, os knobs 0..1 e o 1º = PRINCIPAL; os 5 tipos de controle.
- `BACKLOG.md`.
- No `dash5.html`:
  - os tokens do `:root`, `#cv`, `.bx`/`.bx.mix`, `.port`, `.knob`/`.nk`;
  - `renderBoxes`, `boxEl`, `mixEl`, `layerRow`, `mirrorRow`, `nodeKnobs`/`nodeKnobH`, `boxH`/`boxW`;
  - `inPortEl`/`outPortEl`, `drawBoxWires`, `curve`, `cableCfg`, `nodeColor`;
  - os controles `dragCtl`, `switchCtl`, `choiceCtl`;
  - o inspetor (`renderModCtl`, `renderMixCtl`, `layerCtl`) e a barra do topo.

## Decisões aprovadas
1. **Nó = módulo.**
   - Painel com cara de alumínio/plástico escuro: borda fina, cantos quase retos e, se couber, os "parafusos" nos cantos
     como marca de módulo.
   - Nome serigrafado em CAIXA ALTA no topo, com o glifo da `cat:` e o número estável (`n`).
   - A largura vem de uma grade fixa (como o **HP** do Eurorack): poucos tamanhos de nó, não uma largura por nó.
2. **Knobs de synth.**
   - Corpo redondo com traço indicador, ARCO DE ESCALA em volta (o valor aceso; com movimento, o arco mostra a faixa
     `lo..hi` e um ponto anda nela) e nome curto embaixo, serigrafado.
   - O PRINCIPAL é maior que os outros.
   - Chave e escolha viram peças de synth: chave = alavanca/botão com LED; escolha = seletor de posições com as opções
     escritas em volta ou embaixo.
   - O GESTO não muda: `dragCtl` relativo + arraste infinito, roda do mouse, ids `bar:`.
3. **Jacks.**
   - Entradas e saídas parecem jacks (anel + furo) e as duas são diferentes à primeira vista, como no VCV, onde as
     saídas ficam numa placa de cor invertida.
   - Cada jack tem o nome serigrafado: A, B, máscara, 1..N, +.
   - Plugado = o anel na cor do cabo (como hoje).
4. **LEDs de estado.** LED pequeno no painel:
   - no ar (chega numa saída);
   - movimento vivo no knob (`MV_OUT`);
   - estado (`// estado:`);
   - laço (fio tracejado).
   Sinais que já existem: nenhum dado novo do motor.
5. **Staging e SAÍDA** = módulos de mixer, como os canais de um mixer de VCV/Eurorack: uma tira por camada (fader ou
   knob de opacidade, modo, liga/desliga, jack de entrada na tira). A SAÍDA tem placa de cor própria, pra ser achada de
   longe.
6. **Espelho** = um módulo de 2 HP: só o ícone + a marca de cor do original, nenhum knob (como hoje, no estilo novo).
7. **Cabos** com cara de cabo de patch:
   - mais grossos, com uma sombra leve e o plugue desenhado na ponta;
   - cor, tensão e opacidade como hoje;
   - continuam POR BAIXO dos nós.
8. **O resto da tela fala a mesma língua**: a barra do topo, as colunas laterais, o inspetor e as abas do equipamento
   usam os mesmos tokens. Não vira esqueumorfismo pesado: o canvas é o "rack"; o resto é a "bancada", mais neutra.
9. **ELIMINATÓRIO (continua valendo).**
   - Nenhum cabo cobre knob, com qualquer tensão, opacidade ou zoom.
   - Nada fica menor que o alvo de clique de hoje.
   - No modo palco (cadeado), tudo lê de longe, numa sala escura.
   - Sem animação que pisca (prefers-reduced-motion respeitado).

## [aberto] — decidir com pesquisa e trazer na fase 0
- **Onde moram os jacks.**
  - Na BORDA (como hoje, garante o eliminatório).
  - Ou numa FAIXA DE JACKS no pé do painel, como no VCV: o cabo chega por baixo do nó, então o jack na face pode
    esconder o fio. Mostre como resolve isso.
- **Canvas livre × trilhos de rack.**
  - Hoje o canvas é livre com zoom: a visão do Paulo é "zoom no canvas", então não perca isso.
  - Opções: imã pra fileiras (trilhos) e larguras em HP, ou só a grade de fundo mais "rack".
- **Cor do painel.**
  - Uma cor por `cat:` (como as marcas de módulo), ou painéis neutros com só uma faixa/glifo colorido.
  - Não pode brigar com a cor dos cabos (`nodeColor`) nem com `--live`/`--sel`/`--bad`.
- **Prévia do nó** (a miniatura do `/frame`) como "telinha" do módulo: tamanho e lugar.
- **Tipografia de serigrafia**: uma fonte do sistema condensada ou uma fonte local. Sem CDN: o app roda offline.
  Se embutir, a licença tem que permitir.
- **Palco × montar**: o que muda no módulo quando trava (jacks e nomes de jack somem? knobs crescem?).

## Pesquisa (curta, fontes primárias)
- O guia de painel do VCV Rack (manual do VCV: tamanho em HP, margens, cores, fontes, jacks de entrada/saída) e o
  Component Library do VCV: o que copiar e o que não serve pra tela.
- Convenções de painel de Eurorack (Doepfer A-100: HP, alturas) e 2–3 painéis bem lidos (Mutable Instruments, Make
  Noise, Befaco) pra hierarquia de knob principal × detalhe.
- Como Bitwig Grid e Reaktor Blocks resolvem "módulo bonito em tela, sem virar foto".
- Contraste: WCAG 1.4.3/1.4.11 pro texto e os controles no escuro.
Diga o que cada fonte muda.

## Fases
0. **Diagnóstico + desenho → aprovação.**
   - Prints headless do estado atual (montar e palco; zoom 50/100/150%; uma cena com 3 nós em corrente, 1 staging, 2
     saídas e 1 espelho).
   - Lista curta do que está feio ou confuso.
   - 2–3 MOCKUPS (HTML estático no scratchpad, renderizado headless) do módulo de átomo, do staging e da saída, lado a
     lado com o atual.
   - Os pontos [aberto] com recomendação.
   NÃO mexer no `dash5.html` antes do ok.
1. **Tokens + anatomia**: tokens novos no `:root` (painel, serigrafia, jack, LED, HP) e a grade de larguras;
   `boxH`/`boxW` refeitos em cima dela.
2. **Módulo de átomo**: painel, knobs/chave/escolha novos, jacks, LEDs, prévia.
3. **Staging, saída e espelho** no estilo novo; cabos com plugue e sombra.
4. **A bancada**: barra do topo, colunas, inspetor, equipamento, menus (`nodeMenu`), toasts.
5. **Acabamento**: palco × montar, zoom, desempenho, contraste.

Fora do escopo:
- mudar o motor, o formato da cena ou o `tuning.py`;
- funções novas (receitas dobráveis, várias janelas, o resto do `PLANO_PADROES.md` §11);
- as v1–v4.

## Critério de aceite
- **Antes × depois** em headless, com prints: a mesma cena em montar e palco, a 3 zooms.
- **Cabos não cobrem knob**: em 3 tensões e 2 opacidades, `elementFromPoint` no centro de CADA knob/chave/escolha devolve
  o próprio controle (0 cobertos), e cada alvo tem pelo menos o tamanho de hoje.
- **Os gestos continuam iguais**, rodados de novo no estilo novo:
  - fio grudado → vazio → átomo (corrente de 3);
  - puxar uma entrada ligada e soltar no vazio apaga; Esc cancela; Ctrl+Z desfaz;
  - Alt+arrastar = espelho;
  - mapeamento das saídas.
- **Desempenho**: `renderBoxes` com 30 nós não fica mais lento que hoje (meça antes e depois); girar um knob não
  recria o nó (SSE atualiza no lugar).
- **Contraste**: texto ≥ 4.5:1 e controles/jacks ≥ 3:1 contra o painel (medido nas cores dos tokens).
- Zero erro no console.

## Regras (valem do começo ao fim)
- **Tudo em segundo plano, NADA aparece na tela.**
  - Native: sempre `PRISMA_HIDDEN=1 PRISMA_NO_BROWSER=1`, com backup e restauro do `tuning.py` (o do repo e, se rodar a
    cópia do app, o da pasta de dados). Porta 8765 ocupada = o prisma do Paulo aberto: não abra outro.
  - Navegador só headless: Brave em `/usr/bin/brave-browser`; Playwright num venv do scratchpad com `executable_path`;
    perfil isolado.
  - Nunca `pkill -f` com algo do próprio comando; use o PID.
  - A câmera pode entregar quadros pretos: use o vídeo de `media/` pros prints.
- **Teste como gente**: o dash abre TRAVADO (F2 destrava); aperte, espere ~0.5 s, aí arraste.
- Elemento recriado a cada SSE perde clique/pointer capture: atualizar no lugar.
- Classe no `body` não colide com classe de componente.
- Todos os testes do `CLAUDE.md` passando (inclui a matriz de emergência).
- Toda mudança vai pro app na hora: `dist/prisma/` **e** a pasta de dados.
- Ao fim, atualize:
  - o comentário de decisões do `dash5.html`: anatomia do módulo, tokens, HP;
  - o `CLAUDE.md`, enxuto (uma linha no bullet v5);
  - o `BACKLOG.md`;
  - o `GLOSS` do `docs/index.html` se nascer termo novo (HP, jack, painel).

## Entrega final
Em português simples, numa página:
- antes × depois, com prints;
- a anatomia do módulo, desenhada;
- as decisões (e por quê, com as fontes);
- o que mudou no `dash5.html`;
- os números do critério de aceite;
- o que ficou pra depois.
