# Padrão ÁTOMO (efeito atômico) — v1

Um átomo é um `.frag` em `shaders/presets/atomos/` que faz **uma coisa só** e combina com qualquer outro
porque todos seguem o mesmo contrato. O `dash_data.atom_problems` confere cada regra abaixo; o selfcheck
(e o CI) falha se um átomo da pasta quebrar alguma.

## 1. Uma coisa só
Um verbo por arquivo: Tingir, Contornar, Desfocar, Espelhar. Se o efeito precisa de "e" pra ser descrito
("contorna **e** pinta **e** pulsa no grave"), são dois ou três átomos. Combinar é trabalho da mesa.

## 2. Cabeçalho (nesta ordem)
```glsl
// fx: forca=0.5, matiz=0.5          (knobs 0..1 com padrão; pode faltar se não tem knob)
// cat: cor                          (cor|luz|forma|geometria|distorcao|textura|tempo|mistura|gerador)
// in: src                           (só quem lê a entrada B: padrão ao inserir — src | fb)
// ATOMOS · Tingir. Uma frase do que faz. Depois, o que cada knob faz.
```

## 3. Entradas: só a imagem e o relógio
- `u_texture_0` = **A, a corrente** (o que vem antes). `u_texture_1` = **B** (só com `// in:`).
  `u_texture_src` = a fonte crua. Todas topo→baixo: `st.y = 1.0 - st.y` antes de ler.
- `u_resolution`, `u_time`, e o relógio da música `u_beat` / `u_bar` (fase 0..1 da batida/compasso).
- **Proibido ler o som** (`u_bass`, `u_kick`, faixas, `u_chan`…) e ter knob `on_*`: o som entra por um
  **modulador** (Som, LFO, Imagem, Macro) solto num knob — assim qualquer átomo reage a qualquer coisa.
- **Proibido `layer`** (misturar com o original): quem faz isso é a **opacidade** da peça e o modo de
  mistura. Knob que repete a opacidade só confunde.

## 4. Knobs — poucos e essenciais
- **No máximo 3**: o principal + até 2 detalhes de regulagem simples. O átomo existe pra deixar a visão e o
  controle fáceis; knob a mais é sinal de que são dois átomos (cor do rastro do Feedback = um Matiz em paralelo).
- O **1º knob do `// fx:` é o PRINCIPAL**: o efeito em si (quanto ondula, quanto pinta, quantas fatias). Ele é
  o botão grande da peça; a opacidade vira um knob de apoio. Átomo sem knob: o principal é a opacidade.
- Todos 0..1. Knob de dois lados (girar, deslocar, mais/menos) tem **0.5 = neutro**.
- Nomes do vocabulário comum, pra a mesma palavra fazer a mesma coisa em todo átomo:
  `forca` (quanto o efeito age), `tamanho`, `velocidade`, `matiz`, `saturacao`, `angulo`, `limiar`,
  `borda` (macia↔dura), `quantos` (repetições/fatias/níveis), `zoom`, `giro`.
- Com o padrão de todos os knobs, o átomo já faz algo visível (ninguém solta uma peça e "nada acontece").

## 5. Saída: alfa é cobertura
- **Filtro** (transforma A: cor, luz, forma, distorção, textura): `gl_FragColor = vec4(cor, 1.0)`.
- **Traço / gerador** (desenha por cima: contorno, pontos, listras): alfa = **onde desenhou**
  (0 = deixa a corrente passar). O motor compõe a peça por cima do que vem antes usando esse alfa.
- Com isso as interações saem sozinhas: Contornar desenha só as linhas por cima da imagem; um Tingir
  **depois** pinta tudo (linhas e imagem); pra pintar **só** as linhas, o Tingir vai **em paralelo** no
  Contornar (seção 7).

## 6. Sem estado e barato
- Memória só pela entrada B `fb` (a própria fileira 1 quadro atrás) — é o Feedback, não variável escondida.
- Um passe. Laço de amostras pequeno (≲ 16 leituras por pixel): a mesa soma dezenas de peças.

## 7. Na cadeia × em paralelo
- **Na cadeia** (solto entre peças): age em TUDO que vem antes. Tingir depois do Contornar pinta a imagem toda.
- **Em paralelo** (solto EM CIMA de uma peça): vira uma etiqueta embaixo dela e age **só na saída dela**,
  antes de ela entrar na cadeia, mantendo o alfa dela. Tingir em paralelo no Contornar pinta só as linhas.
- Arrastar a etiqueta até outra peça liga o **mesmo** modificador nela (um fio pontilhado mostra): um Matiz
  com LFO pintando o Contornar e os Pontos juntos, com um knob só.
- Motor: o modificador mora na pilha `~post` da cena (itens com `id`); a peça guarda `post: [ids]`.
