# Prompt — PRISMA: cabos como no VCV, stagings, várias saídas e espelhos — cole num chat novo, na pasta do repo

Você vai mudar o canvas da v5 (`dash5.html`) e o motor (`native_synth.py`) pra o PRISMA se comportar como um
**sintetizador modular de verdade**:
- fios puxados e ligados como no **VCV Rack**;
- **stagings** (mixers intermediários) entre os nós e as saídas;
- **várias saídas**, cada uma posicionada à vontade nas telas do palco;
- **espelhos** de um átomo (o mesmo átomo, com um só conjunto de knobs, agindo em vários lugares).

As decisões abaixo já foram APROVADAS pelo Paulo; os pontos **[aberto]** são seus pra decidir com pesquisa.

Antes de tudo leia: `CLAUDE.md`; o comentário de decisões no topo do `dash5.html`; `shaders/ATOMO.md` (§7 o encaixe);
`BACKLOG.md`.
- No `dash5.html`: `renderBoxes`, `atomRow`, `nodeKnobs`, `boxH`, `wireDragStart`, `normalizeNodes`, `healRemove`,
  `topoOrder`, o nó SAÍDA (`outEls`), o fio de máscara (Luma), `clickInsert`, `startDrag`/`placeZones`.
- No `native_synth.py`: `render_mix`, `_graph_wants`, `_post_items` (o "mesmo id = um modificador só"), `tap_tex`,
  `_stage`, `SCREENS`, `OVERLAYS[i].rect`, `_rect_uv`.

## Decisões aprovadas
1. **Clicar na bolinha de saída GRUDA um fio no cursor.**
   - O próximo clique decide: numa entrada, liga; no VAZIO, abre um menu com átomos (biblioteca com busca), nó vazio,
     staging novo e saída — o nó nasce ali, já ligado; Esc cancela.
   - Arrastar continua funcionando.
2. **Regras do VCV.**
   - Saída aceita VÁRIOS fios; entrada aceita UM.
   - Puxar uma entrada já ligada pega a ponta do fio: leva pra outra entrada, ou solta no vazio pra apagar.
   - Puxar uma saída cria mais um fio.
   - Fio com cor; passar o mouse destaca o fio e as duas pontas.
   - Cada nó mostra as entradas com nome: **A** (a corrente), **B** (a entrada B do átomo) e **máscara**. Isso substitui
     a lista "entrada B" do inspetor e a faixa "máscara" que aparece ao puxar.
   - Juntar várias imagens = um staging.
3. **Acaba "só a ponta no ar"**: um nó só sai de uma saída quando você tira o fio. Um nó pode alimentar ao mesmo tempo
   outros nós, stagings e saídas.
4. **STAGING = nó mixer.**
   - N entradas, cada uma uma camada (opacidade, modo, ordem — o PROGRAMA de hoje, em miniatura).
   - Átomos próprios DEPOIS da mistura.
   - A saída vai pra outro staging ou pra uma saída.
   - Laço (A → B → A): **[aberto]** proibir no gesto, ou aceitar com 1 quadro de atraso (como o `fb`).
5. **VÁRIAS SAÍDAS.**
   - Cada saída é uma imagem final; o nó SAÍDA de hoje vira só mais um mixer (entradas numeradas) = "saída 1".
   - No mapeamento, cada saída é posicionada LIVREMENTE no canvas do palco, sobre as telas `SCREENS` (as slices do
     Resolume: uma saída num painel do telão, outra no projetor).
   - Continua sendo UMA janela/raster; várias janelas físicas seguem no BACKLOG ("Várias saídas").
6. **ESPELHO (cópia ligada) de um átomo.**
   - O original tem os knobs; os espelhos NÃO têm knob nem texto: um chip pequeno com o ÍCONE do átomo e uma MARCA DE
     COR igual à do original (como a cor do cabo).
   - O nome aparece só ao passar o mouse; clicar leva ao original.
   - Espelho em QUALQUER lugar: no meio de uma corrente, num staging, antes de uma saída — onde estiver, o átomo age
     ali, com os knobs e os movimentos do original.
   - Motor: generalizar o "mesmo id = o mesmo modificador" (`_post_items`); o estado (átomo com `// estado:`) de um
     espelho é **[aberto]**: um buffer por lugar, ou proibir espelho de átomo com estado.
7. **Tensão e opacidade dos cabos**: dois controles GLOBAIS no topo do canvas (como as configurações do VCV), lembrados
   por modo (montar/palco), como o zoom. Tensão = quanto o cabo cai (reta ↔ curva funda).
8. **ELIMINATÓRIO — cabo nunca atrapalha os knobs.**
   - Fios passam POR BAIXO dos nós (no VCV ficam por cima: aqui é ao contrário, de propósito).
   - As bolinhas ficam na BORDA do nó, então a curva nunca cruza a área de knobs do próprio nó.
   - Ao girar um knob, os fios somem até soltar; ao passar o mouse num nó, os fios dele acendem e os outros ficam fracos.
   - Com QUALQUER tensão/opacidade, nenhum knob pode ficar coberto ou difícil de pegar. Os knobs redondos do card
     (`nodeKnobs`) continuam como estão.

## Pesquisa (curta, fontes primárias)
- O manual do VCV Rack sobre cabos (empilhar, puxar da entrada, cor, tensão/opacidade): o que copiar e o que evitar.
- O Advanced Output do Resolume (input map/slices × output map) pro mapeamento das saídas.
- Group/Return do Ableton pro staging.
- Como TouchDesigner/Max mostram "a mesma coisa em vários lugares" (os espelhos).
Diga o que cada fonte muda.

## Fases
0. **Desenho → aprovação.** Pare e traga 2–4 decisões estruturais, explicadas simples:
   - o MODELO DE DADOS (como stagings, saídas e espelhos moram no `tuning.py`: `OVERLAYS`/`BINDINGS` ou estrutura nova);
   - a MIGRAÇÃO (cenas e `tuning.py` atuais abrem sem perder nada: as linhas da SAÍDA de hoje = entradas da saída 1);
   - os laços;
   - o mapeamento das saídas.
   Mais os pontos [aberto]. NÃO codar antes do ok.
1. **Motor**: stagings e várias saídas no `render_mix` (cada um uma textura, em ordem topológica); espelhos; cada saída
   posicionada no palco (rect por saída, como `OVERLAYS[i].rect`).
2. **Dash — cabos VCV**: entradas nomeadas, um fio por entrada, vários por saída, puxar/mover/apagar, cor, tensão e
   opacidade, fios por baixo.
3. **Dash — o clique na bolinha** (fio grudado + menu no vazio), stagings e saídas no canvas, espelhos (chip + marca de
   cor + ir ao original).
4. **Mapeamento**: as saídas como retângulos no canvas do palco (aba Saída/telas), com prévia.

Fora do escopo: várias janelas físicas; receitas dobráveis; o resto da UI do `PLANO_PADROES.md` §11.

## Critério de aceite
- Em headless, com prints:
  - criar por clique (fio grudado → vazio → átomo) uma corrente de 3 nós;
  - ligar dois nós num staging, o staging em outro staging e na saída 1;
  - uma segunda saída posicionada noutra tela;
  - um Matiz com espelhos em dois stagings: girar o original muda os dois (prints do `/frame`).
- Cabos em 3 tensões e 2 opacidades: nenhum knob coberto (prints do canvas com zoom).
- Cena antiga abre igual (mesmo `/frame` antes e depois da migração).

## Regras (valem do começo ao fim)
- **Tudo em segundo plano, NADA aparece na tela.**
  - Native: sempre `PRISMA_HIDDEN=1 PRISMA_NO_BROWSER=1`, com backup/restauro do `tuning.py` (do repo e, se rodar a
    cópia do app, o da pasta de dados). Porta 8765 ocupada = o prisma do Paulo aberto: não abra outro.
  - Navegador só headless (Brave em `/usr/bin/brave-browser`; Playwright num venv do scratchpad com `executable_path`),
    perfil isolado.
  - Nunca `pkill -f` com algo do próprio comando; use o PID.
  - A câmera pode entregar quadros pretos: use o vídeo de `media/` pros prints.
- **Teste como gente**: o dash abre TRAVADO (F2 destrava); aperte, espere ~0.5 s, aí arraste.
- Todos os testes do `CLAUDE.md` passando (inclui a matriz de emergência). Import novo em `src/` → `packaging/launcher.py`.
- Toda mudança vai pro app na hora: `dist/prisma/` **e** a pasta de dados.
- Ao fim: atualize `CLAUDE.md` (enxuto), o comentário de decisões do `dash5.html`, `BACKLOG.md`, `shaders/ATOMO.md`
  §7 e o `GLOSS` do `docs/index.html` (staging, saída, espelho, tensão do cabo).

## Entrega final
Em português simples:
- o modelo novo numa página;
- as decisões (e por quê, com as fontes);
- o que mudou no motor e no dash;
- prints do critério de aceite;
- como uma cena antiga foi migrada;
- o que ficou pra depois.
