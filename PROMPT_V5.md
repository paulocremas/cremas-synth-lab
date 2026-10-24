# Prompt — PRISMA v5: canvas de camadas de átomos (cole num chat novo, na pasta do repo)

Você vai desenhar e construir a **v5 do PRISMA**: um dash **novo** (`dash5.html`, servido em `/v5`), mais
**minimalista e limpo** que a v4, organizado como um **canvas** no espírito do TouchDesigner. A v1–v4 continuam
existindo e funcionando até a v5 ser aprovada (o app segue abrindo a v3; não troque sem o meu ok).

Antes de tudo leia: `CLAUDE.md`, `BACKLOG.md`, `shaders/ATOMO.md` (o padrão de átomo), o comentário de decisões
no topo do `dash4.html` e o documento de design da v4 (link na memória `v4-design`).

## Regras desta tarefa (valem do começo ao fim)
- **Tudo em segundo plano, NADA aparece na tela.** Eu trabalho em outra coisa com um rastreador que tira prints.
  - Native: sempre `PRISMA_HIDDEN=1 PRISMA_NO_BROWSER=1`, em segundo plano, com backup/restauro do `src/tuning.py`.
  - Navegador só `--headless=new` com `--user-data-dir` isolado no scratchpad (nunca o perfil padrão). CDP pra
    console, ações e prints (o node tem `WebSocket` nativo).
  - Nunca fonte `screen:` nos testes. `telao_sim.py` só fora da tela; na dúvida, não rode.
  - Nada de computer-use, `xdg-open` ou captura da área de trabalho. Prints só de páginas headless e de `/frame`.
  - Nunca `pkill -f <algo do próprio comando>`; use o PID. **Só UM prisma**: se a porta 8765 estiver ocupada é o
    MEU prisma aberto — não abra outro (briga por porta, webcam e `tuning.py`); espere a porta liberar.
  - Se alguma etapa só funcionar com algo visível, pare e pergunte.
- Pesquisa liberada (modo extended se for nichado); cite as fontes.

## O que já existe (não reaprenda)
- **Átomos** (`shaders/presets/atomos/`, padrão `shaders/ATOMO.md`, conferido por `dash_data.atom_problems` no
  selfcheck): um verbo por arquivo; só imagem + relógio (som entra por MODULADOR no knob); knobs 0..1, o 1º é o
  PRINCIPAL; saída RGBA com **alfa = cobertura** (o motor compõe pela alfa). 20 átomos hoje.
- **Motor** (`native_synth.render_mix`): fileira = fonte → peças em cadeia (sem `in` ou `'chain'` = lê o que vem
  antes; `in: 'src'` = fonte crua) → camada do programa (opacidade + modo). Ramo = fileira com `file: '@<id>'` que
  lê a saída da peça `id` (tap). Entrada B `ins` (`'fb'`, `'src'`, outra fileira, `'@id'`). **Modificador paralelo**:
  `post: [ids]` (pilha `~post` da cena) age só na saída daquela peça. Moduladores: som, LFO, imagem (`luz`/`mov`),
  macros M1–M4. Máscara do assunto: U²-Net (`subject_thread`, `region: subject|bg` por item, `u_use_mask`).
- **v4** (`dash4.html`): 3 colunas, fileiras + zonas de soltura, variações (mutação + cruzar), grupos, publicados no
  Show, Socorro, Equipamento (todos os editores). Funciona, mas **ainda está poluída**.

## Princípio que manda em tudo: MINIMALISMO
A razão de atomizar é deixar **ver e controlar fácil**. Cada átomo tem só regulagem simples e essencial: o knob
PRINCIPAL + no máximo 2 detalhes (o padrão já cobra: `ATOM_MAX_KNOBS = 3`). Se precisa de mais, são dois átomos.
Na tela isso vira: dentro da caixa, cada átomo mostra **só o principal**; detalhes só ao abrir aquele átomo.
Nada de painel lotado: se um controle não é essencial pro show, ele não aparece até ser pedido.

## A ideia (minha) — e as decisões já tomadas
Fluxo de **camadas de átomos** num canvas:
```
entrada 1 → Camada 1 (átomos + máscara) → Camada 2 → Camada 3 ──┐
                 └──────────────→ Camada 4 (outra coisa) ───────┴→ SAÍDA (mistura, opacidade de cada entrada)
```
- **Camada = uma CAIXA no canvas** (como um COMP do TouchDesigner / um Rack do Ableton) com os átomos dentro em pilha
  vertical (a cadeia). Fios ligam **só caixas** — menos fio, mais leitura. Uma camada pode alimentar várias (ramo).
- **Saída escolhível**: eu ligo cada ramo a um nó de SAÍDA; dois ramos na mesma saída **se misturam**, e na saída eu
  controlo a **opacidade (e o modo) de cada entrada**. (Hoje há um PROGRAMA só; ver BACKLOG "Várias saídas" —
  confirme comigo se "saída" = PROGRAMA + telas/blocos do telão, ou só mixers internos.)
- **Máscara / rastreamento = átomos**, num **conjunto paralelo pendurado na CAMADA**: decide onde o resultado da
  camada aparece (fora dela passa o que vem antes — como o Matte TOP). **Some** o "tudo / assunto / fundo" de cada
  efeito (print: chips de região no inspetor) — a hierarquia vira visual. Átomos de rastreamento: assunto (U²-Net),
  olhos, movimento, cor/chroma, luminância… produzem alfa.
- **Show**: o canvas aparece **travado e pequeno**; PROGRAMA, cenas e controles publicados grandes.
- **Escopo**: `dash5.html` novo em `/v5`; v4 fica de reserva.

## Pesquise antes de desenhar (e diga se a ideia se sustenta)
TouchDesigner (rede, famílias, Composite/Matte TOP, COMPs, perform mode), Nuke (máscara por nó, `inject`),
Fusion (entrada azul de máscara), Ableton Racks (cadeias paralelas + macros), Notch, cables.gl, Max (presentation),
estudos de usabilidade de editores de nós (o "espaguete", custo de ligar/mover/apagar fio). Traga o que copiar e o
que evitar.

## Como trabalhar
1. **Pesquisa → documento de design curto** (Claude Doc) com o modelo mental, o layout de cada tela e o que sai da
   v4. Traga 2–3 decisões estruturais pra eu aprovar ANTES de codar (ex.: como a caixa abre/fecha; como se liga um
   fio e como se tira; o que é a SAÍDA; onde fica a biblioteca de átomos).
2. **Motor**: estenda só o necessário, compatível com cenas e `tuning.py` atuais (uma cena v4 abre na v5 como
   caixas). Prováveis: camada lendo a SAÍDA de outra camada (tap do fim da fileira), nó de saída/mistura com
   opacidade por entrada, máscara por camada (átomo que gera alfa aplicado no blend da camada), átomos de
   rastreamento (expor a máscara do assunto como uniform de átomo — atualizar o padrão ÁTOMO). Cada mudança com
   teste no `--selfcheck` e no native de verdade.
3. **`dash5.html` do zero**, minimalista: reaproveite a LÓGICA provada (knob, fader, MIDI + soft takeover, saúde,
   sync por tempo, zonas de soltura, variações, editores de equipamento), não o markup. Menos texto na tela,
   hierarquia clara, nada estrutural ao alcance de um clique errado no Show.
4. **Testes**: todos os do `CLAUDE.md` + native real (oculto, webcam) + headless (prints de cada tela, arrastos).
5. Atualize `CLAUDE.md`, `BACKLOG.md`, `shaders/ATOMO.md` e o comentário de decisões no topo do `dash5.html`.

## Entrega final
Explicação em português, simples: o modelo mental (camada, átomo, máscara, saída), o canvas tela por tela, o fluxo
ao vivo e o de "deu pepino", a linguagem visual, o que saiu da v4 e por quê, e o que ficou pra depois — citando as
referências pesquisadas.
