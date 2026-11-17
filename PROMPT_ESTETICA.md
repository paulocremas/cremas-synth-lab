# Prompt — PRISMA: estética "mini TV" (foto-real + cel shading) no programa todo, e enxugar botões e telas

Cole num chat novo, na pasta do repo. Este prompt substitui o `PROMPT_VISUAL.md`, que propunha painel escuro estilo VCV com
parafusos e foi superado.

Você vai:
1. Levar a estética aprovada dos módulos para o `dash5.html`.
2. Adaptar o RESTO do programa à mesma estética, com dois temas trocáveis no menu: **foto-real** e **cel shading**.
3. Revisar todos os botões e a distribuição das telas, para enxugar e melhorar o que já existe.

O motor (`native_synth.py`) não muda. O comportamento dos gestos também não, salvo o que a revisão do item 3 aprovar.

## Leia antes
- `CLAUDE.md` (seção dash5) e o comentário de decisões no topo do `dash5.html`.
  - Todo elemento tem motivo: P palco / S segurança / C montagem.
- **`design/mini-tv.html`**: o mockup APROVADO, com todo o desenho em HTML/CSS/SVG.
  - Abra no navegador.
  - O menu VISUAL no canto troca entre foto-real e cel.
  - `?tema=cel` na URL abre já em cel.
  - Peças para portar: `atom()`, `body()`, `screen()`, `edgeJack()`/`jackProfile()`, `plugProfile()`, `cable()`, `fader()`,
    `knobSVG()`/`knobCel()`, `rockerSVG()`/`rockerCel()`, `envMod()`, as classes por família e o bloco `.cel …` do CSS.
- `tests/dash_gestos.py`: 28 testes de gesto, todos verdes, que precisam continuar verdes.
  - Rodar: `.venv/bin/python tests/dash_gestos.py`.
  - Todo bug de usabilidade novo vira um teste ali.
- Memória do projeto: `visual-mini-tv-decisoes`.

## Decisões APROVADAS (não reabrir)
**Módulo = mini TV de plástico**
- Largura fixa. A tela segue a proporção da FONTE, e o módulo estica ou encolhe na vertical.
- Tela em cima.
- IN e MÁSC empilhados na borda esquerda, OUT na direita, e o fader de opacidade entre eles.
- Knobs rente ao pé. O CV de cada knob sai por baixo, como um jack.

**Jack, cabo e controles**
- Jack FLAT de perfil: só a porca sextavada, rente à borda.
- Plugue magnético achatado, um disco baixo na cor do cabo.
- O cabo é uma curva única que cai com o peso.
- Liga = esfera de vidro vermelha com textura xadrez. Ligado = aceso.
- Knob com movimento: a TAMPA brilha na cor do controlador.
- Controlador (envelope) = caixinha com osciloscópio, faixa de/até em faders e jack de CV em cima.
- SAÍDA: um fader de opacidade por entrada.

**Gabinete por família**

PRISMA é a 1ª "marca" de módulos. A ideia é a de fabricantes num jogo de saque: o material conta quem fez a peça.

| família | final |
|---|---|
| cor | o liga vira a RODA DE CORES girando; desligado, para e apaga. Arco-íris forte no pé. |
| luz | ouro escovado com brilho por trás do módulo |
| forma | aro fino de borracha, sulco duplo e curvas de nível |
| geometria | régua sutil e triângulos marcados a 15°, que somem perto do título |
| distorção | senos moldados só na metade de baixo |
| textura | borracha com losangos (piso de ônibus) |
| tempo | eco do gabinete em degradê lilás→rosa, borrado, bem sutil, respirando |
| gerador | verde-água martelado com VU de agulha. O título para antes do VU: animação NUNCA cobre texto. |
| máscara | preto fosco, moldura roxa, xadrez escuro sutil |

- Fonte (câmera etc.) e saída: prata neutro.
- Materiais curtidos para linhas futuras: couro preto, chapa xadrez de alumínio, jeans.

**Tema cel shading**
- Cada peça tem desenho chapado próprio, não um filtro por cima.
- Contorno de espessura constante.
- Gabinete com terminador curvo: luz de cima-esquerda e 3 tons.
- Luz de recorte fria na borda direita e risco de brilho no topo.
- Retícula de pontos na sombra e sombra chapada roxo-escura deslocada.
- Tela com brilho em faixa, imagem posterizada com o filtro `#toon` só na imagem.
- Fundo azul-noite com retícula nas bordas.
- Texto dos gabinetes escuros em claro.

**Animação só em módulo LIGADO.**

## O que fazer
1. **Plano curto antes de mexer.** Diga quais peças do mockup viram quais elementos do dash5 (`.bx`, `nodeKnobs`, `.kj`,
   `.port`, `drawBoxWires`, `ctlSpot`/controladores, nó de SAÍDA, nó de fonte, `.lv` imagem viva → a tela da TV).
   - A imagem viva (`which=fx`) vai DENTRO da tela da mini TV, na proporção da fonte.
   - Os pictogramas `i-at-*` e a cor `--cc` continuam como identidade.
   - Encaixe a família no gabinete.
2. **Tema como estado do programa.**
   - O menu tem a opção Foto-real | Cel.
   - A escolha é lembrada. Decida com motivo se fica no `localStorage` ou no `tuning`.
   - O tema troca o DESENHO das peças, não só o CSS.
3. **Desempenho é requisito.** O canvas tem dezenas de nós, a 60 fps no palco.
   - Texturas como imagem fixa gerada uma vez, não filtro SVG ao vivo por nó.
   - `feTurbulence`/`feDiffuseLighting` viram PNG/data-URL cacheado.
   - Sem `backdrop-filter` no canvas.
   - Um modo leve sem grão, sem foco e sem animação.
   - Meça antes e depois com a mesma cena.
4. **Resto do programa na mesma pele.** O plano está proposto no fim do mockup e não foi aprovado item a item, então proponha e
   confirme:

   | parte | proposta |
   |---|---|
   | barra de cima | TOCAR/MONTAR como teclas de TV antiga, liga geral de vidro, nome da cena em visor VFD |
   | PROGRAMA (`#pvw`) | monitor de estúdio com luz de "no ar" |
   | inspetor (`#insp`) | a "tampa traseira" do módulo escolhido |
   | roda da biblioteca | catálogo com a miniatura do gabinete |
   | cenas | cartuchos, com transição numa alavanca T-bar |
   | som/master | faders de mesa de corte e VU de agulha; blackout como chave com tampa |
   | palco | telas como painéis de LED |
5. **Revisão de botões e telas: enxugar e melhorar.**
   - **Inventário primeiro.** Liste cada botão, painel e tela com o motivo P/S/C, quantas vezes se usa e onde está. Use uma
     tabela num Claude Doc ou artefato para eu marcar.
   - **Proposta.** O que some, o que se junta, o que muda de lugar e o que vira gesto. Com mockup quando a mudança for visual.
   - **Só remova o que eu aprovar.** Elemento de Segurança (S) nunca some sem eu dizer.
   - **Para eu escolher, use um artefato com escolha por clique e comentário** gravados no db do artefato (`db.collection(...)`),
     como no `design/mini-tv.html`. Depois leia com `db_list`.
6. **Implementar em etapas pequenas**, cada uma com:
   - os testes de gesto verdes, e teste novo para cada gesto novo;
   - `.venv/bin/python src/dash_server.py`, que roda os selfchecks;
   - cópia para `dist/prisma/` e para a pasta de dados `~/.local/share/prisma/` (memória "sempre atualizar o binário");
   - as decisões atualizadas no topo do `dash5.html` e no `CLAUDE.md`.

## Como trabalhar comigo
- Responda em pt-BR.
- Mostre visual por artefato (mockup) antes de implementar mudança grande. Eu escolho clicando e comentando no próprio artefato.
- Nada de recriar a estética de jogo ou produto existente: só a IDEIA de "fabricantes reconhecíveis".
- Commit só quando eu pedir.
