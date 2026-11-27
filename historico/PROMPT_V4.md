# Prompt — PRISMA v4 (cole num chat novo, na pasta do repo)

Você vai desenhar e construir a **v4 do PRISMA**, um dash **totalmente novo** (`dash4.html`, servido em `/v4`).
A v1 (`/`), a v2 (`/v2`) e a v3 (`/v3`) continuam existindo e funcionando: nada delas pode quebrar.

Antes de qualquer coisa, leia o `CLAUDE.md`, o `BACKLOG.md` (seção "v3 — módulos"), o comentário de decisões no
topo do `dash3.html` e o do `dash2.html`. Eles registram o que já foi decidido e por quê.

## Regras desta tarefa (valem do começo ao fim)
- **Tudo em segundo plano, NADA aparece na tela.** O usuário trabalha em outra coisa ao mesmo tempo, com um
  rastreador de tempo que tira prints da tela dele. Nenhuma janela pode abrir: nem a saída do native, nem o dash,
  nem o navegador, nem o simulador de telão.
  - Native: sempre `PRISMA_HIDDEN=1 PRISMA_NO_BROWSER=1`, em segundo plano.
  - Navegador: só `--headless=new` com `--user-data-dir` isolado no scratchpad. Nunca o perfil padrão: ele entrega
    a URL pro navegador aberto do usuário e abre uma aba na tela dele.
  - Nunca use fonte `screen:` (captura de tela) nos testes: ela grava a área de trabalho do usuário. Use webcam,
    vídeo ou imagem.
  - `telao_sim.py` só com a janela fora da tela (já é o padrão dele); na dúvida, não rode.
  - Nada de computer-use, captura da área de trabalho ou `xdg-open`. Prints só de páginas headless e de frames do
    native (`/frame?which=...`), salvos no scratchpad.
  - Se alguma etapa só funcionar com algo visível, pare e pergunte.
- **Pesquisa liberada:** use a busca e a leitura de páginas à vontade (o modo extended quando o assunto for nichado),
  e cite as fontes.

## O que é o PRISMA
Um VJ/sintetizador visual ao vivo. O `src/native_synth.py` (OpenGL) pega fontes (câmera, tela, vídeo, imagem) e
áudio (FFT, BPM, tom), passa cada fonte por uma pilha de shaders e manda pra uma janela de saída (monitor, projetor
ou telão de LED). O dash é uma página HTML servida pelo `src/dash_server.py` (HTTP + SSE, só stdlib). Ele abre numa
janela de navegador `--app`, **sem barra de endereço**. Roda offline: sem CDN.

## A visão do usuário (o que a v4 tem que entregar)
1. **Módulos atômicos com interações naturais.** Inserir uma fonte e montar efeitos como peças: um contorno e depois
   um módulo de cor, e a cor pinta o contorno (camadas que agem sobre o que está atrás). Liberdade pra combinar o
   que ninguém previu. Tanto ele quanto qualquer leigo precisam conseguir criar, e **descobrir coisas sem querer**.
2. **Fácil de usar ao vivo.** As posições de tudo foram pensadas pro show: alvos grandes no que se toca muito,
   nada estrutural ao alcance de um clique errado, o PROGRAMA (o que o público vê) sempre visível.
3. **Fácil de resolver qualquer pepino.** Quando algo dá errado no meio do show, o caminho pra resolver tem que
   ser óbvio, rápido e sempre no mesmo lugar.
4. **Simples e bonito.** Menos coisa na tela, hierarquia clara, acabamento de software de palco profissional.

## O que já aprendemos (v1 → v3) — não reaprenda do zero
**Motor (já existe, use):**
- Item da pilha com `in: 'chain'` lê o resultado dos módulos anteriores da raia. Sem `in` = legado (lê a fonte
  crua): **cenas antigas não podem mudar de aparência**. `ins` = entrada B/C (`u_texture_1/2`): outra raia,
  `'fb'` = a própria raia 1 frame atrás (feedback), `'src'` = a fonte crua. `u_texture_src` = a fonte crua, sempre.
- Os shaders leem a textura **de cima pra baixo** (`st.y = 1 - st.y`). Toda textura que vira entrada precisa estar
  nessa orientação (`lt['chain']`, `lane_out`), senão o conteúdo sintético (partículas, gotas) sai invertido.
- Cabeçalho do `.frag`: `// fx:` (knobs e padrões), `// cat:` (tipo), `// in:` (entradas padrão), mais a 1ª linha
  livre = descrição. Lido por `dash_data.parse_meta` / `parse_fx_defaults` e servido em `/shaders` (`meta`).
  Átomos em `shaders/presets/atomos/` (Feedback, Deslocar, Máscara, Misturar).
- Cada módulo é um passe de GPU, e a corrente custa mais uma cópia por módulo encadeado. Feedback e entradas B
  entre raias têm 1 frame de atraso quando a raia lida vem depois na ordem.
- 23 presets antigos repetem a mesma lógica de gatilho (`on_kick`, `on_sub`… e `nivel()`). Isso é um
  **modulador** disfarçado: candidato natural a virar um átomo de controle.
- Modulação por som já existe por knob (`mod: {knob: {b: [faixas|kick|m1..m4], lo, hi}}`) e macros M1–M4.

**Interface (o que funcionou e deve sobreviver, mesmo que com outra forma):**
- Knob = "slider invisível" vertical com arrasto relativo, Shift = fino, duplo-clique = padrão. Fader relativo
  (clicar nunca pula o valor = nunca manda flash pro telão). MIDI learn + soft takeover. Um loop rAF só, 60 fps.
- Sync entre abas por **tempo** (`TOUCH_MS`), não por foco. Elemento recriado a cada SSE perde clique e captura:
  atualize no lugar.
- **Annunciator de saúde** (fps, áudio, vídeo, shader, telão, link) com gravidade, histerese (`HOLD`) e "agora /
  por quê / o que fazer + botão que resolve". O 🛟 socorro da v3 junta emergência fixa (blackout, imagem crua,
  cena anterior, desfazer), os problemas de agora e os consertos. Mantenha o princípio: no pânico ninguém procura.
- Show (estrutura travada) × Montar, com o **mesmo grid** nas duas, pra o olho não reaprender onde está cada coisa.
- Cores = estado (verde no ar, laranja selecionado, azul MIDI, vermelho perigo). Tipo de módulo por glifo/forma,
  nunca por essas cores. **Glifos ◐ ◑ não existem na fonte do sistema** (viram "›"): teste cada símbolo
  renderizado, ou use SVG inline.
- Desfazer (por cena) e 🎲 (sortear knobs) liberam a exploração. O `Limiter` (anti-estrobo WCAG 2.3.1 + teto de
  brilho) protege a sala de qualquer acaso.

**Fraquezas da v3 que a v4 deve resolver:**
- A mesa ainda é uma lista de raias lineares: não há canvas livre, ligação por proximidade nem ramificação visível.
- A paleta é uma lista longa, o inspetor fica lotado (caixas `on_*`, modos, região, entrada…), o topo é denso e a
  v3 herdou muito markup da v2.
- Não há modulador como peça, prévia por módulo, mutação nem átomo composto (ver `BACKLOG.md`).

## Pesquise antes de desenhar
Use a busca na web e traga as fontes. No mínimo:
- **Patch/modular:** Reactable (ligação por proximidade), Hydra (`modulate`, `mask`, `blend`), VCV Rack/Eurorack
  (todo cabo serve em toda entrada), Bitwig Grid e os moduladores arrastáveis, TouchDesigner (TOPs, CHOPs),
  Notch, Resolume Arena + Wire (parâmetros expostos), cables.gl, Max/Jitter, Ableton (cadeia de devices e racks).
- **Descoberta:** Synplant (mutação genética), geradores de variação, "happy accidents" em instrumentos.
- **Palco e cue:** grandMA, QLab, disguise; botão de pânico; annunciators de cabine e de broadcast.
- **UX/HCI:** Fitts, Hick, reconhecer em vez de lembrar, carga cognitiva sob estresse, affordances (Norman),
  contraste e daltonismo (WCAG), toque × mouse × MIDI.

## Como trabalhar
1. **Pesquisa → documento de design** com as decisões, o porquê de cada uma e o que foi descartado. Traga 2 ou 3
   decisões estruturais pra eu aprovar antes de codar: o modelo de grafo (raias × canvas livre × híbrido), a regra
   de ligação automática e o layout das telas.
2. **Motor:** estenda só o necessário (grafo com N entradas, modulador como átomo, prévia por módulo…), sempre
   compatível com as cenas e o `tuning.py` existentes. Cada mudança no native tem um teste no `--selfcheck`.
3. **`dash4.html` do zero.** Pode reaproveitar a *lógica* provada (knob, MIDI, saúde, sync), mas a arquitetura,
   o layout e o visual são novos. Quando a v4 estiver aprovada, `_open_dash_window` passa a abrir `/v4`.
4. **Testes** (todos os do `CLAUDE.md` + o native de verdade):
   - Native SEMPRE em segundo plano, com a webcam e `PRISMA_HIDDEN=1 PRISMA_NO_BROWSER=1`. Antes, backup do
     `src/tuning.py`, e restaure depois.
   - Navegador de teste SEMPRE com perfil isolado (`--user-data-dir` no scratchpad). Sem isso o Chrome entrega a
     URL pro Chrome aberto do usuário. Use CDP (`--remote-debugging-port`; o node 24 tem `WebSocket` nativo) pra
     ler o console, rodar ações e tirar prints. `--screenshot` sozinho dispara antes dos dados chegarem.
   - Nunca `pkill -f <algo que aparece no próprio comando>`: mata o shell antes do restore. Use o PID (`$!`).
   - Confira se só existe UM prisma rodando: dois abrem duas saídas, e só o primeiro fica com a porta 8765.
5. Atualize o `CLAUDE.md`, o `BACKLOG.md` e o comentário de decisões no topo do `dash4.html`.

## Entrega final
Depois de construir, escreva uma **explicação das decisões, revendo todo o design, a UX e a UI**: o modelo
mental (o que é um módulo, como as peças se ligam), o layout tela por tela e por que cada coisa está onde está,
o fluxo ao vivo e o fluxo de "deu pepino", a linguagem visual (cor, tipo, glifos, movimento), a acessibilidade,
o que foi tirado e por quê, e o que ficou pra depois. Em português, citando as referências pesquisadas.
