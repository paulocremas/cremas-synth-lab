# Prompt — PRISMA: distribuição de jacks, knobs e faders inspirada no VCV Rack + módulos "filho"

Cole num chat novo, na pasta do repo. Continua o `PROMPT_ESTETICA.md`: a estética (mini TV, famílias, foto-real | cel, leve)
já está no `dash5.html` e **não muda**. Agora muda a **distribuição** das peças dentro de cada módulo e entram os módulos "filho".

## Leia antes
- `CLAUDE.md` (seção dash5) e as decisões no topo do `dash5.html`, principalmente os blocos de 2026-11-17 (MINI TV e as três rodadas
  seguintes: jack visto de cima, cabos do VCV por cima dos nós, clique pega o cabo / Shift cria, cor aleatória por cabo, MIXER de N
  jacks, SAÍDA com uma entrada, Enter = lista de módulos).
- Memória do projeto: `visual-mini-tv-decisoes`.
- `design/mini-tv.html` (o mockup aprovado das famílias e dos temas).
- `tests/dash_gestos.py`: 36 testes de gesto, todos verdes, que continuam verdes. Todo bug de usabilidade novo vira teste ali.

## 1. Pesquisar o VCV primeiro
Procure imagens e páginas de módulos do VCV Rack (VCV Fundamental: VCO, VCF, ADSR, VCA, Mixer, Scope; Befaco; Audible Instruments;
Bogaudio) e anote **como eles distribuem** as peças:
- onde ficam as entradas e as saídas (as saídas costumam ficar embaixo, num fundo mais escuro);
- como os knobs se agrupam por função e por tamanho (um grande principal, pequenos de ajuste em grade);
- onde ficam os faders, as chaves e os botões, e como o texto serigrafado é curto;
- o espaçamento e a grade (HP) que deixam o painel limpo.

Resuma o que vai copiar e por quê, com as fontes. Não copie a arte nem a marca de nenhum fabricante: só a lógica da distribuição.

## 2. Pedidos do usuário (2026-11-17)
- **Distribuição nova**, mais intuitiva, bonita e agradável, com as estéticas que já existem.
  - Acabou a regra de manter os knobs alinhados com a parte de baixo.
  - O **fader de opacidade do efeito fica em cima do preview de vídeo**, acima da tela.
- **Opções viram módulos "filho".** Coisas como o seletor "sentido" (enrolar | desenrolar) do Rodar e o "modo" (normal, soma, tela,
  multiplicar, diferença) do Misturar deixam de ser lista ou chip dentro do card.
  - Cada uma vira um módulo separado visualmente, com botões "analógicos" (teclas, chaves de alavanca, seletor rotativo).
  - O cabo entre pai e filho **não se mexe**: já nasce ligado e fica preso.
- **Como pai e filho se ligam (decidido): o FILHO é a ENTRADA e o PAI é a SAÍDA.**
  - O cabo preso sai do filho e entra no pai. O sinal passa primeiro pelo filho e depois chega ao pai.
  - O PREVIEW de vídeo e a saída de imagem ficam no PAI. Pela lógica do sinal, a alteração (o "sentido", o "modo") tem que vir ANTES
    do que o preview mostra.
  - No motor nada muda: a escolha continua um valor do átomo (`floor(u_fx_X*K)` ou `step(.5,u_fx_X)`). O filho é o painel físico
    dessa escolha, desenhado à esquerda/antes do pai, com o cabo preso indo dele até a entrada do pai.
  - A corrente de imagem que chega no átomo continua chegando no pai, mesmo com o filho desenhado antes dele. Mostre no mockup como isso
    fica claro: o fio de imagem entra no pai, e o fio preso do filho entra no pai por outro jack.
- **Arrastar:** o filho arrasta livre; arrastar o pai leva o filho junto, como um grupo.
- **Zoom out semi-infinito.** Hoje o zoom do canvas vai de 40% a 200% (`CVZ_LIM = [0.4, 2]` no `dash5.html`, `setCvZoom`), e com
  dezenas de módulos não dá pra ver o patch inteiro. O zoom out deve ir bem mais longe, a ponto de caber qualquer patch na tela, com
  um piso só de segurança (ex.: 2–5%).
  - O zoom deve andar suave e continuar centrado no cursor, como hoje.
  - O ZOOM SEMÂNTICO (`#cv-in.zl-far` / `zl-near`) ganha níveis: bem de longe, cada módulo vira um bloco simples na cor da família com
    o nome legível (e talvez a imagem viva), sem knobs, textura, sombra nem texto pequeno. Os cabos ficam finos.
  - DESEMPENHO: bem de longe, todos os módulos estão na tela ao mesmo tempo. Nada de prévia ao vivo de todos (pedir só as que estão
    grandes o bastante: o `liveCv`/`pumpPreviews` já pede só as visíveis), e o desenho de cada módulo tem que ficar leve. Meça com o
    teste "desempenho" no zoom mínimo.
  - Um atalho para "caber tudo" (enquadrar o patch inteiro) e voltar ao zoom de antes.

## 3. O que confirmar com o usuário antes de implementar (não supor)
- Quais controles viram filho: todas as ESCOLHAS e CHAVES (`// opcoes:`, chaves) ou só as que têm 2 ou mais opções?
- Onde exatamente o filho nasce (à esquerda do pai, já que ele vem antes no sinal? acima?) e se ele pode ser recolhido para dentro do pai.
- O filho conta como nó no motor/cena (`OVERLAYS`) ou é só desenho do dash (guardado no átomo, ex.: `s.filhos = {knob: {xy}}`)?
  Recomendação: só desenho, para o motor não mudar.

## 4. Como fazer
1. **Pesquisa** (item 1), em texto curto com links.
2. **Mockup em artefato** (HTML/CSS/SVG, no estilo do `design/mini-tv.html`), mostrando:
   - 3 ou 4 módulos reais redistribuídos: Contornar, Rodar com o filho "sentido", Misturar com o filho "modo", e o Mixer 4;
   - os dois temas;
   - as dúvidas do item 3 lado a lado (onde o filho nasce, recolhido ou não), com o filho já como ENTRADA e o pai como SAÍDA.
   O usuário escolhe clicando e comentando no próprio artefato. Grave as escolhas no db do artefato (`db.collection(...)`, como no
   `design/plano-inventario.html`) e leia com `db_list`.
3. **Implementar em etapas pequenas** no `dash5.html`. Hoje a geometria é calculada em JS e o card recebe a altura:
   - mexer em `tvH`/`boxH`, `TV_*`, `nodeKnobs` ('row'), `tvConn` (fader de opacidade), `cvEnd` (onde chega o CV de cada knob) e
     `ctlSpot` (onde nasce o controlador);
   - escolha/chave hoje: `barCtl` → `choiceCtl`/`switchCtl` (com `chseg`), dentro de `.nkw`;
   - o arrasto em grupo vai no `boxDragStart` (já existe o mecanismo de grupo da seleção: `groupOf`/`grpMove`).
4. **Em cada etapa:**
   - os testes de gesto verdes, e teste novo para cada gesto novo (o filho preso, arrastar o pai leva o filho, o fader em cima da tela,
     o zoom out até o piso e o "caber tudo");
   - `.venv/bin/python src/dash_server.py` (selfchecks); se mexer no motor, também `.venv/bin/python src/native_synth.py --selfcheck`;
   - medir com o teste "desempenho" (comparar antes e depois);
   - copiar para `dist/prisma/` e para `~/.local/share/prisma/` (memória "sempre atualizar o binário"; `native_synth.py` só vale
     reabrindo o app);
   - atualizar as decisões no topo do `dash5.html` e no `CLAUDE.md`.

## Como trabalhar comigo
- Responda em pt-BR.
- Visual primeiro, num artefato com escolha por clique e comentário; implemente depois que eu escolher.
- Só tire um elemento que eu aprovar; elemento de Segurança (S) nunca some sem eu dizer.
- Commit só quando eu pedir.
