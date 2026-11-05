# PLANO — padrões de integração entre nós (ÁTOMO v2)

Rascunho aprovado como DIREÇÃO em 2026-10-31 (chat de pesquisa). **Fases 0–4 FEITAS em 2026-10-31** (ver o fim). Os detalhes marcados **[aberto]** a pesquisa do
próximo chat decide, com recomendação. Base: `shaders/ATOMO.md` (v1), Claude Doc "PRISMA — sync com a música" (o
MOVIMENTO), comentário de decisões no topo do `dash5.html`.

## 0. O norte e o teste
Poucas regras gerais → qualquer nó encaixa em qualquer nó e o resultado faz sentido, inclusive em combinações que
ninguém planejou (a "química" do Zelda BotW; o Eurorack: tudo é tensão, qualquer saída em qualquer entrada).
**Teste de toda decisão: é uma REGRA geral ou um caso especial?** Caso especial = falta uma regra.
Objetivo estético desta rodada: **formas orgânicas** (fluxo, crescimento, bolha, tinta, coral) a partir de átomos
simples, sempre no tempo da música.

## 1. C1 — A IMAGEM: uma coisa só corre nos fios
Todo fio carrega uma imagem RGBA. Não há tipos que impedem ligação: quem LÊ escolhe a **leitura**:

| Leitura | De onde sai | Quem usa |
|---|---|---|
| **cor** | RGB | quase todos |
| **cobertura** | A (onde a peça desenhou) | o motor, ao juntar a camada |
| **quantidade** | luma (Rec.709) de RGB | máscaras, Limiar, Paleta, Dobrar, força do Deslocar |
| **direção** | ver abaixo | Deslocar, Fluido, Reação (deriva) |

**Direção sai de QUALQUER imagem** (regra mais forte desta rodada): todo leitor de direção tem a ESCOLHA
`fixa (ângulo) | relevo (gradiente da luma) | redemoinho (gradiente girado 90° = curl) | vetor (RG, 0.5 = parado)`.
Assim a câmera crua já tem direção (a tinta escorre pelo contorno da pessoa) e um nó que produz vetor de verdade
(Movimento = fluxo óptico) usa `vetor`. Convenção RG = x/y vem do Hydra (`modulate`) e do fluxo óptico do TouchDesigner.

## 2. C2 — O ÁTOMO (o `.frag`)
Fica tudo da v1 (um verbo, ≤3 knobs 0..1, 1º = PRINCIPAL, não lê o som, sem `layer`/`on_*`, alfa = cobertura,
vocabulário comum de nomes). Entra:
- **Neutro previsível**: o principal é "quanto" (0 = nada acontece) ou de dois lados, declarado `// bipolar: giro`
  (0.5 = nada; a UI mostra o centro). Modular a partir do neutro = o efeito entra e sai.
- **Espaço em fração da tela**, nunca em pixel; aspecto corrigido. Mesma cena em 720p e no telão = mesma forma.
- **Tempo em segundos, nunca por quadro**: `u_dt` (s desde o quadro anterior) pra tudo que acumula; queda de fps
  não muda o rastro. Knob de velocidade declarado `// ritmo: velocidade` pode travar no BPM (divisões da batida).
- **Semente** `u_seed` (hash do id do nó): dois Ruídos iguais não ficam idênticos; a cena volta igual ao ser chamada.
- **Prelúdio comum** injetado pelo motor (como o `POLY_GLSL`): `luma()`, `dirOf()` (as 4 leituras de direção),
  `noise/fbm`, `rot()`, paleta cosseno. Todos os átomos falam as MESMAS funções. **[aberto]** injeção vs `// usa:`.
- Cabeçalho novo (opcionais): `// bipolar:`, `// ritmo:`, `// estado:`, `// escala:` (resolução do nó, ex. 0.5).

## 3. C3 — MEMÓRIA (átomos com estado)
- `// estado: canais=2, passos=4` → o motor dá ao nó um **buffer duplo próprio em 16 bits float** (`u_state` = o
  anterior), roda N passos por quadro e respeita `u_dt`. O Feedback vira o caso mais simples disso.
- **Eventos** que todo átomo com estado aceita: `semear` e `limpar` (contadores, como os eventos do MOVIMENTO) →
  "o drop apaga o coral e ele cresce de novo na frase" sem código especial (usa a GRADE e os eventos que já existem).
- O que vai pro fio é a VISTA do estado (cinza/cor). **[aberto]** dois passes (atualiza / mostra) vs MRT.
- Na ordem: Feedback (migrar), Reação (Gray-Scott), Fluido (extrair o Stable Fluids que já existe no motor, hoje
  preso nos presets Fumaça/Silhueta/Caos). Physarum (agentes) fica pra depois.

## 4. C4 — O ENCAIXE (topologia)
Cinco ligações, todas já existem ou quase:
1. **Corrente (A)**: o nó lê o anterior.
2. **Entrada B**: qualquer nó, `fb` ou a fonte crua.
3. **Máscara** da caixa (átomos `// cat: mascara`, Luma de outra caixa).
4. **LOOP do nó** (um gesto: soltar átomo NO MEIO do nó). Átomo comum → loop **pós**: age na camada dele antes de
   juntar (Resolume: efeito de clipe; Photoshop: máscara de recorte). Átomo com estado → loop **retorno**: age no que
   recircula a cada volta (o laço do Feedback TOP do TouchDesigner) — desenhado como ↻, NUNCA como fio voltando
   (fio pra trás = feedback em todo app de vídeo). O loop age na camada INTEIRA (cor + cobertura): cor não mexe na
   cobertura, espaço (Desfocar, Deslocar) move as duas juntas. **[aberto]** alfa pré-multiplicado vs direto.
5. **Junção**: todo nó entra na corrente como CAMADA (opacidade + modo de mistura) — é assim que "o próximo mistura
   com o anterior".

## 5. C5 — SINAL e EVENTO (o MOVIMENTO, estendido)
O framework do MOVIMENTO não muda (3 tipos, 7 regras, mod no knob). Duas pontes novas, ambas regras gerais:
- **Qualquer nó vira sinal**: brilho/cobertura média da saída de um nó = fonte de movimento `no:<id>` (já há `luz`/`mov`
  da entrada e o rastreio). Ex.: quanto o coral cobriu a tela abaixa o rastro do Feedback.
- **Evento → estado**: `semear`/`limpar` (C3).

## 6. Garantias do motor
- **16 bits float** nas raias com estado/feedback (hoje TUDO é 8 bits: `_lane_textures`, `native_synth.py`; com
  rastro 0.98 o escuro arredonda pra cima e nunca apaga = fantasma + banding). Dither leve na saída final de 8 bits.
- `u_dt`, `u_seed`, prelúdio, resolução por nó, buffer de estado, eventos semear/limpar.
- Custo visível (o dash já soma passes de GPU): estado e escala entram na conta.

## 7. Verificação — a MATRIZ DE EMERGÊNCIA
O teste do Eurorack automatizado, no `--selfcheck` (e no CI onde houver GL):
- `atom_problems` estendido: cabeçalhos novos, neutro declarado, sem pixel fixo, sem `u_time` pra acumular.
- **Todo par A→B** de átomos e **todo átomo como entrada B** de todo leitor de B, renderizados pequenos (64×36,
  offscreen): sem NaN/Inf, sem tela chapada (variância > 0) salvo declarado, principal no neutro ≈ identidade.
- **Estado**: 300 passos com padrões → não explode (satura tudo) nem morre (apaga tudo); `limpar` zera.
- Falhou = o contrato tem buraco (ou o átomo quebra o contrato), não "combinação proibida".

## 8. Migração dos átomos atuais (exemplos)
| Átomo | Muda |
|---|---|
| Feedback | só `rastro`; zoom/giro saem (Rodar no loop retorno); vira estado 16 bits com `u_dt`; junção escolha max/mistura |
| Deslocar | `angulo` → escolha de direção (fixa/relevo/redemoinho/vetor) + ângulo pra `fixa` |
| Luz, Matiz, Rodar, Fatias, Saturar | declarar `// bipolar:` |
| Listras, Pontos, Onda, Rodar | `// ritmo: velocidade` |
| todos | espaço em fração da tela, `u_seed` onde há acaso |
Presets antigos (`sortidos/`, `default/`) saem da biblioteca da v5 → gaveta "clássicos" (continuam rodando nas cenas)
e viram RECEITAS de átomos depois.

## 9. Átomos novos que PROVAM o contrato
- Onda a (matéria-prima, vocabulário do sintetizador de vídeo LZX): **Ruído** (escala, velocidade, detalhe),
  **Rampa** (linear/radial/ângulo), **Dobrar** (wavefolder na luma → curvas de nível), **Polar** (reto ↔ circular),
  **Limiar** (keyer: corte, borda), **Paleta** (colorizador: cinza → cor).
- Onda b: **Afiar** (oposto do Desfocar), **Brilhar** (bloom), **Células** (voronoi).
- Onda c (estado): **Movimento** (fluxo óptico barato, diferença de quadros → vetor), **Fluido**, **Reação**.

## 10. Critério de aceite: interações que ninguém programou
1. Câmera → Deslocar (direção = relevo de B = Ruído) → Feedback ↻ Desfocar = tinta escorrendo.
2. Reação semeada pela máscara Mãos (B) → a mão desenha coral; `limpar` no drop.
3. Fluido empurrado pelo Movimento da câmera → Paleta com matiz movido pelo tom da música.
4. Câmera → Dobrar → Polar = topografia do rosto virando anéis; principal do Dobrar "segue o grave".
5. `no:<id do coral>` como sinal → abaixa o rastro do Feedback de outra caixa.

## 11. Depois deste plano (UI, já discutido; fora do escopo do 1º chat de mudanças)
Knobs direto no card (painel Controles só no palco, com publicados) · loop visível (etiqueta / ↻) · receitas
dobráveis com 2–4 macros (Rack do Ableton) · adicionar/remover: o fio como alvo, layout que abre/fecha espaço, SAÍDA
como fio visível, soltar no vazio, chave do nó = id fixo.

## 12. Fases do próximo chat
0. Pesquisa → refinar este contrato → `shaders/ATOMO.md` v2 + decisões **[aberto]** → **aprovação**.
1. Motor: 16 bits/dither, `u_dt`, `u_seed`, prelúdio, `// estado:` + semear/limpar, loop retorno, `no:<id>`.
2. Verificação: lint + matriz de emergência.
3. Migrar os átomos atuais; presets antigos pra "clássicos".
4. Onda a de átomos novos + as 5 interações do §10 rodando de verdade (prints do `/frame`).

## 13. Feito (2026-10-31)
Decisões (aprovadas): **alfa direto** (média de amostras usa `Am()`); estado = **um arquivo, duas fases** (`u_vista`,
+ `u_fase` pra sim de várias etapas — o `PASSINDEX` do ISF), sem MRT; **prelúdio injetado** em todo átomo
(`dash_data.ATOM_PRELUDE`). 16F só na camada da peça e no estado, dither ao cair pra 8 bits; passo fixo 60/s.
- [x] Fase 0: `shaders/ATOMO.md` v2.  [x] Fase 1: motor (prelúdio, `u_dt`, `u_seed`, estado + semear/limpar, loop
  retorno, `no:<id>`, 16F/dither).  [x] Fase 2: lint + `src/matriz.py` (42 átomos, 1764 pares; pegou: Dobrar não neutro,
  Fluido saturando, Máscara não neutra, matriz ignorando a escala do estado).  [x] Fase 3: átomos migrados; Clássicos.
- [x] Onda a (Ruído, Rampa, Dobrar, Polar, Limiar, Paleta), b (Afiar, Brilhar, Células), c (Movimento, Fluido,
  Reação). As 5 interações do §10 rodaram no motor (prints do `/frame`); a 2 com Limiar no lugar das Mãos.
- Não feito → BACKLOG ("ÁTOMO v2 — o que ficou").
