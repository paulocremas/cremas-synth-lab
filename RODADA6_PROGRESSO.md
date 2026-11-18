FEITO

# Bom dia — resumo da rodada 6 (modo noturno, 2026-11-18)

Os 8 itens estão no app (`dist/prisma/` e `~/.local/share/prisma/`, conferido com `cmp`). A suíte `tests/dash_gestos.py` passou com
**82/82** (eram 75; entraram 7 testes `t6_*`), e as auto-checagens do `src/dash_server.py` e do `src/dash_data.py` passaram. Não fiz
commit nem push, não abri o app e não mexi no `tuning.py` vivo: rodei tudo na porta de teste 8799.

**O que mudou no /v6**
1. **Knob + jack numa peça só** (variante A): a tampa é a porca do jack. Arrastar na saia gira; apertar no centro pega o cabo. Com o jack
   livre, dá pra puxar o cabo do knob até um alterador. Knob ligado só mostra a faixa.
2. **Fader de opacidade comprido**, colado na tela, com o jack do alterador embaixo. No mixer e na saída, o jack fica na ponta do fader.
3. **A faixa de/até agora muda no alterador**: arrastar as pontas, arrastar o meio (move as duas), roda, 2 cliques = padrão, Shift = fino.
   O knob e o painel dele não editam mais a faixa. O alterador cresce, uma linha por ligação, cada linha na cor do cabo dela.
4. + 5. **Grade sem invasão**: nada passa do relevo, o OUT fica no meio da altura, sem espaço sobrando e com o mixer mais baixo.
6. **Roda nova**: as fatias são as famílias dos gabinetes, cada uma com o material dela, mais máscaras, alteradores e "mistura e saída".
   As máscaras antes nem apareciam na roda.
7. **Matiz "não faz nada"** — não é bug. Ele gira as cores em volta do cinza, então cinza e branco ficam iguais. E depois do Contornar
   ele age só nas linhas, que são brancas. **Precisa da sua decisão**: (i) um LED "sem efeito visível" no módulo; (ii) sugerir
   Tingir/Paleta/Rampa quando a entrada é cinza. Não mexi no átomo.
8. **Seletores**: chave = tecla; 2–4 opções = fader de entalhes; 5 ou mais = seletor rotativo. A escolha ligada a um alterador continua
   seletor e acende a opção viva.

**O que escolhi por você (dá pra trocar)**
- Item 1: variante **A**. Compare: `design/rodada6/item1-knobs.png` (A) × `item1-knobs-B.png` (B, jack no flanco); de longe:
  `item1-knobs-longe.png` × `item1-knobs-B-longe.png`. No console do dash, `G6.knobStyle('B')` troca na hora.
- Item 8: a regra **S3/S2/S1**. O book tem as mesmas peças em cada estilo: `item8-S1.png`, `item8-S2.png`, `item8-S3.png`; a regra
  aplicada em `item8-regra.png` e `item8-regra-ligado.png`.
- Item 2: coube limpo, então não precisei mostrar duas opções: `item2-modulos.png`.
- Item 3: "arrastar o espaço" — fiz as duas leituras. O meio da faixa move as duas pontas, e o alterador arrasta pelo osciloscópio ou
  pelo nome.
- Item 6: os átomos de mistura (Deslocar, Máscara, Misturar) entraram em "mistura e saída". Todos os 49 átomos têm `cat:`, então não
  existe a fatia "outros".

**PNGs** (todos em `design/rodada6/`): antes e depois dos módulos `antes-modulos.png` × `item5-depois-modulos.png`; `item2-modulos.png`;
`item3-modulos.png`; roda `item6-antes-roda.png` × `item6-depois-roda.png` (e `-aberta`); knobs `item1-*`; seletores `item8-*`. Para
refazer as fotos: `.venv/bin/python tests/v6_foto.py <prefixo> modulos|knobs|roda|S1|S2|S3|regra|regra-ligado`.

**Como testar no app**: o dash recarrega sozinho. No MONTAR:
- toque um preset num knob e mexa a faixa nas linhas do alterador;
- puxe o centro de um knob livre até um alterador;
- dois cliques no vazio abrem a roda;
- no Misturar, use o seletor rotativo (clique no nome, arraste a saia, Shift+clique);
- antes, faça backup do `~/.local/share/prisma/src/tuning.py`, porque mexer no app grava nele.

---

# RODADA 6 — diário (modo noturno)

Ordem: 4 → 5 → 2 → 1 → 3 → 6 → 7 → 8. PNGs em `design/rodada6/` (gerados por `tests/v6_foto.py <prefixo> [cena]`, que sobe o
dash isolado na porta 8799 e fotografa o canvas a 100%).

| item | estado |
|---|---|
| 4 nada invade o relevo | FEITO |
| 5 grade / OUT no meio | FEITO |
| 2 fader ao lado da tela | FEITO |
| 1 knob+jack | FEITO |
| 3 faixa no alterador | FEITO |
| 6 roda | FEITO |
| 7 módulo de cor | FEITO (diagnóstico + proposta) |
| 8 seletores | FEITO |

## 4 + 5 · área útil e grade de colunas — FEITO
Feitos juntos (o 5 refaz o `hzLayout` e o 4 é a regra que ele segue).
- `hzLayout` virou GRADE: átomo = `[liga + entradas] [tela] [nome / teclas / knobs + fader] [OUT]`; fonte = `[másc] [nome em cima
  da tela] [OUT]`; mixer/saída = `[nome + linhas] [tela] [OUT]`. Todas as colunas centradas na vertical; OUT no meio da altura; trilho
  de entradas centrado (abaixo do LIGA, que fica no canto de cima à esquerda — decisão da rodada 5 mantida).
- ÁREA ÚTIL (`hzUseful`): gabinete − bisel (2 px; FORMA = 18, o sulco duplo conta como relevo) − 8 px de folga; o canto que sobra do
  raio da família. Tudo (knob com o anel de fora, jack, rótulo, aba do OUT, teclas, VU, tela) cabe nela. Grade de 4 px (W/H múltiplos
  de 4, deslocamentos com `f4` pra nunca passar da área).
- Altura = coluna mais alta; largura = soma das colunas. O painel de teclas agora tem a largura do que ele tem (`tvWide().w`), não 248 fixo.
- Mixer encolheu pra altura das linhas (2 jacks: 180 → 152 px).
- Texto: rótulos viraram PLAQUETAS de 10 px (`lbl`), nada mais em 9 px solto.
- ALTERADOR: geometria própria (`ctlLay`, `CTL6`): jack DENTRO da área útil, uma linha por ligação (cresce em altura; base do item 3),
  `ctlWH` no lugar de `CTL_W/CTL_H` no /v6 (ctlSpot, rectOfNode, declutter). `c.out` passou a ser o centro do jack (antes `+10`).
- Teste novo `t6_dentro_do_relevo`: todo átomo da biblioteca (49: 0–3 knobs, teclas, B), fonte, mixer 2/4/8, saídas, alterador com
  0/1/3 ligações; toda peça dentro da área útil; W/H na grade; depois do ARRUMAR nada se sobrepõe.
- PNG: `design/rodada6/antes-modulos.png` × `design/rodada6/item5-depois-modulos.png` (Contornar, Polar, Misturar, mixer + alterador).

Suíte depois de 4+5: 76/76 verdes; copiado pro `dist/prisma/` e `~/.local/share/prisma/` (cmp ok).

## 2 · fader de opacidade comprido ao lado da tela + jack — FEITO
- Átomo: o fader VERTICAL saiu do fim da fileira dos knobs e ficou COLADO à direita da tela, com a altura dela; o JACK do alterador
  (`cvj`) fica embaixo do fader. Tela + fader + jack = um grupo centrado (sem texto "opac.": decisão antiga "sem 'opacidade' escrito").
- A opacidade NUNCA vira knob no /v6 (`tvKnobs`). Ligada (`row.mod.opacity`): o fader não arrasta (toast explica), a trilha mostra a
  faixa de/até na cor do cabo e o cursor anda com o valor vivo. Id `bar:<nó>:<id>:opacity` igual (MIDI/learn seguem).
- Mixer/saída: cada linha = jack · nome + fader · JACK do alterador (na ponta do fader) · olho. Coube limpo (a linha ganhou 4 px), então
  não precisei mostrar duas opções.
- O cabo do alterador chega NO JACK (cvs/`knobTarget`: soltar no fader ou no jack liga, o cabo vai pro jack); apertar o jack ligado pega o cabo.
- Extra: o inspetor guarda o LADO enquanto couber (seguindo a câmera, não pula de lado — o `t6_painel` pegou isso com a nova largura).
- Teste novo `t6_fader_ao_lado_da_tela`; `t6_oscilador_opacidade` atualizado (ligada continua fader, sem knob). Suíte 77/77; copiado.
- PNG: `design/rodada6/item2-modulos.png` (Misturar com a opacidade ligada no alterador; mixer com a camada 1 ligada).

## 1 · KNOB + JACK numa peça só — FEITO (variante A)
- Escolhida a **A** (recomendada): a TAMPA do knob é a porca do jack (furo no meio), a SAIA é o knob (serrilha + ponteiro). O knob cresceu
  pra `HZ.KR` 24 (disco de 48 px; jack `KJ` 12): centro = 24 px de alvo, anel da saia = 12 px de cada lado (WCAG 2.5.8 a 100%).
- Gesto: arrastar na SAIA = girar; apertar no CENTRO = jack (livre: puxa o cabo AO CONTRÁRIO até um alterador e liga; ligado: pega o cabo,
  outro knob = muda, vazio = tira). Ligado: a saia não gira e a roda não mexe; o anel de fora mostra a faixa de/até na cor do cabo e o
  ponteiro anda com o valor vivo (o arco de modulação do Bitwig). O cabo de controle chega no CENTRO.
- Zona do jack no `pick`: raio `max(KJ, 9 px de tela)`, com teto `KR − 6` (de longe o jack não engole o knob inteiro).
- O "ALCANCE" saiu do `knobSpec` (o knob ligado só mostra; a faixa vai pro alterador no item 3).
- LOD "longe": sem ponteiro, só o disco + o anel aceso (mais grosso).
- B (jack no flanco, "8") ficou só no book: `G6.knobStyle('B')` troca na hora (pra comparar).
- Teste `t6_knob_jack_peca` (saia gira, centro liga ao contrário, ligado não edita, cabo no centro, alvos ≥ 24 px). O teste comparava o JSON
  da faixa como texto (a ordem das chaves muda) — agora compara o objeto.
- PNGs: `design/rodada6/item1-knobs.png` (A, escolhida) × `item1-knobs-B.png`; de longe: `item1-knobs-longe.png` × `item1-knobs-B-longe.png`.
- Suíte 78/78; copiado pro `dist/prisma/` e `~/.local/share/prisma/` (cmp ok).

## 3 · editar os limites NO ALTERADOR (e não no knob) — FEITO
- Cada linha do alterador = uma ligação (knob, opacidade do átomo ou entrada do mixer). Gestos na linha: ponta esquerda = **de**, ponta
  direita = **até**, o **MEIO** (o "espaço" entre as pontas) = as duas juntas, mantendo a largura (`egrip`); clique fora das pontas = a
  ponta mais perto pula até ali; 2 cliques = a faixa PADRÃO (a mesma que ligar daria: a do preset em volta do valor | opacidade 0..valor |
  valor ± 0,3); roda = abre/fecha em volta do meio; Shift = fino (×0,2). Funciona no TOCAR também (é controle, não estrutura).
- Grava em `mod[n].lo/hi` (camada: `L.mod.opacity`), igual ao `ctlRange.set`; KNOB_BIND | IO_OVL (touch/live/commit, trava o stream).
- Visual: cada linha leva a COR DO CABO dela (tarja + faixa + pontas) e o nome curto do knob (entrada do mixer = "entr. N"); bipolar =
  o zero marcado no meio; o valor vivo = a bolinha branca; mexendo, uma plaqueta "de → até". Linha de 20 px (alvo ≥ 12). Mais de 2
  ligações = o alterador cresce (já vinha do item 4).
- Tirado do KNOB: o knob ligado não gira nem com a roda (item 1); o painel do knob (`pieceCtl` → `rangeCtl`) só MOSTRA no /v6 (`ro`:
  clique avisa "a faixa muda no alterador").
- "Arrastar o espaço": fiz as duas leituras — o MEIO da faixa move as duas pontas (acima) e o alterador arrasta por qualquer parte que não
  é controle (osciloscópio, nome) — a linha da faixa não arrasta o módulo.
- Testes novos: `t6_alterador_faixa` (pontas, meio, roda, 2 cliques, knob e painel não editam) e `t6_alterador_arrasta`.
- PNG: `design/rodada6/item3-modulos.png` (alterador ANDA com 3 ligações: giro do Polar, opacidade do Misturar, entrada 1 do mixer).
- Suíte 80/80; copiado (cmp ok).

## 6 · a RODA com as categorias certas — FEITO
- Diagnóstico (`design/rodada6/item6-antes-roda.png`): fatias = `Fontes, cor, luz, forma, geometria, distorção, textura, tempo, mistura,
  gerador, Movimentos, Receitas, Misturas`. Confirmado: (a) vinham do `CATS` antigo; (b) "mistura" 2× (categoria de átomo + Misturas);
  (c) "Movimentos"; (d) sem cor/material; (e) DOM com o visual antigo. E um a mais: as MÁSCARAS não entravam (o filtro `!isMaskFile`
  tirava a categoria inteira — o ramo dela no código era morto).
- Agora (`item6-depois-roda.png`, `item6-depois-roda-aberta.png`): `Fontes · cor · luz · forma · geometria · distorção · textura · tempo ·
  gerador · máscaras · alteradores · mistura e saída · receitas`. Os átomos de mistura (Deslocar, Máscara, Misturar) entraram em
  "mistura e saída" junto com os mixers e as saídas. "outros" só aparece se sobrar átomo sem `cat:` — hoje NENHUM (os 49 têm `cat:`).
- Cada fatia é um disco com o MATERIAL do gabinete da família (`G6.swatch(fam)` = o mesmo `body()` do jogo, em cache por tema) e o nome
  numa plaqueta; o miolo virou metal escuro. A roda continua DOM (a lista com busca, arrastar item pro card etc. seguem iguais).
- Teste novo `t6_roda_categorias` (sem duplicada, sem vazia, todo átomo em UMA fatia, todas com material). Suíte 81/81; copiado (cmp ok).

## 7 · o módulo de COR "parece não fazer nada" — DIAGNÓSTICO (não é bug; nada mudou no átomo)
- Leitura do shader `Matiz.frag`: é a rotação de Rodrigues em volta do eixo do CINZA (1,1,1)/√3. Pra um cinza c = t·(1,1,1), o
  `cross(k, c)` = 0 e o resto volta c: **cinza e branco não mudam com nenhum giro**. Conferido em numpy: (0,5 0,5 0,5) → igual;
  (1 1 1) → igual; (0,9 0,2 0,1) → (0,34 0,86 0) com giro 0,25 → gira.
- E mais forte que isso: pela regra da CORRENTE (um sobre o outro), o Matiz depois do Contornar age SÓ NA MARCA do Contornar (as linhas
  brancas, `mark_tex`/`mk_on` no native). Mesmo com `fundo=imagem` colorida, o que ele gira são as linhas — brancas — logo nada muda.
- O `// mod: giro=anda` do `.frag` só SUGERE (não liga sozinho): se o giro não estiver num alterador, ele fica parado.
- Pra conferir na mão: ligue o Matiz direto na câmera (sem o Contornar) — a prévia gira.
- **Propostas (pra você aprovar; não implementei):**
  - **(i)** LED "sem efeito visível" no módulo: o native já faz a prévia do nó; uma diferença média barata entre a entrada e a saída do nó
    (no tamanho da prévia, a cada ~0,5 s) e, se ficar ≈ 0 por 2–3 s com o liga aceso e opacidade > 0, o módulo acende o LED com a dica
    ("a entrada não tem cor" quando a entrada é cinza; "age só nas linhas do nó anterior" quando for marca).
  - **(ii)** Na família cor, com a entrada cinza: sugerir Tingir / Paleta / Rampa (que CRIAM cor) no próprio aviso, com um clique pra trocar.

## 8 · seletores que APONTAM a opção — FEITO (regra S3/S2/S1)
- Book no próprio canvas, as mesmas 4 peças (Misturar = 5 opções, Fluido = 4, Contornar = 2, Máscara = chave) em cada estilo:
  `design/rodada6/item8-S1.png` (tudo rotativo) · `item8-S2.png` (tudo fader de entalhes) · `item8-S3.png` (tudo tecla = o de antes).
- Implementada a REGRA proposta: **chave = S3** (uma tecla de rádio antigo: afunda e acende) · **2–4 opções = S2** (fader de entalhes) ·
  **5+ = S1** (rotativo). Resultado: `item8-regra.png`; com alterador ligado: `item8-regra-ligado.png`.
  - **S1 rotativo:** o mesmo knob-jack do item 1 com um entalhe por opção; os nomes em arco (−135°…+135°, o curso do knob) em plaquetas;
    o ponteiro aponta, a escolhida acende (LED âmbar + plaqueta escura). Clique no nome = direto; arrastar na saia = passa por entalhes
    (22 px cada); clique na saia = a próxima; roda = próxima/anterior; centro = jack do alterador.
  - **S2 fader de entalhes:** os nomes em cima de cada parada, a trilha com um entalhe por parada, o cursor pula de entalhe em entalhe
    (arrastar = o mais perto; clique na trilha = o mais perto; clique no nome = direto); o jack do alterador na ponta da trilha.
  - **S3:** a tecla de antes (chave).
  - Todos: o MESMO id `bar:` (MIDI segue; o learn arma o seletor), Shift+clique = volta uma, alvos ≥ 24 px (plaqueta de opção = 24 px).
- ALTERADOR na escolha: no /v6 a escolha ligada CONTINUA seletor (antes virava knob e os nomes sumiam): a opção do valor VIVO acende na
  cor do cabo, a faixa aparece no anel (S1) ou na trilha (S2), e na mão ela não muda (o aviso diz que o alterador manda). A chave ligada
  continua virando knob (tecla não tem jack).
- Sem alavanca, sem parafusos (decisões antigas).
- Teste novo `t6_seletores` (estilos pela regra, alvos, nome = direto, Shift = volta, roda, arrastar = entalhe, MIDI, fader pula de
  entalhe, alterador liga no centro do rotativo e a escolha segue seletor e não muda na mão). `t6_dentro_do_relevo` cobre o fader de entalhes.
