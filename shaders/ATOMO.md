# Padrão ÁTOMO — v2 (2026-10-31)

Um átomo é um `.frag` em `shaders/presets/atomos/` que faz **uma coisa só** e encaixa em **qualquer outro**. Não há
tipos que impedem ligação (o Eurorack: tudo é tensão; o Sandin Image Processor: módulos feitos pra maximizar a
interligação). Quem garante que a combinação faz sentido são as regras abaixo; o `dash_data.atom_problems` confere o
texto e a **matriz de emergência** (`src/matriz.py`, no `--selfcheck`) renderiza todo par. Regra que só serve pra um
átomo = falta uma regra geral.

## 1. A imagem: uma coisa só corre nos fios
Todo fio carrega uma imagem **RGBA com alfa direto** (cor sem multiplicar pelo alfa: em 8 bits o pré-multiplicado
perde cor nos rastros fracos) — no motor também: corrente, fio entre nós, fim de caixa e staging. A transparência de um
PNG ou do recorte da máscara **segue pelos fios** (PNG → Matiz → staging continua recortado). Quem LÊ escolhe a **leitura**:

| Leitura | O que é | No código |
|---|---|---|
| **cor** | RGB | `A(st).rgb` |
| **cobertura** | A: onde a peça desenhou (o motor usa ao juntar a camada) | `A(st).a` |
| **quantidade** | luma Rec.709 | `luma(c)` |
| **direção** | vetor 2D de qualquer imagem | `dirOf(...)` |

**Direção sai de qualquer imagem**: o leitor tem a ESCOLHA `direcao` = `fixa` (o knob `angulo`) · `relevo` (desce
do claro pro escuro) · `redemoinho` (o relevo girado 90° = curl 2D, Bridson 2007: gira sem fonte nem ralo) · `vetor`
(a imagem já é vetor: R = x, G = y, **0.5 = parado**, G > 0.5 = pra cima). Comprimento ≤ 1. No código:
`dirOf(u_texture_1, st, floor(u_fx_direcao * 3.999), u_fx_angulo)` — o `floor(... * K)` no átomo é o que faz o dash
mostrar a escolha. Vetor no fio = RG centrado em 0.5 em 8 bits (o Hydra usa RG sem centro; aqui cinza = parado).

## 2. Cabeçalho (nesta ordem; só a linha ATOMOS é obrigatória)
```glsl
// fx: forca=0.3, direcao=0.375, angulo=0.25   (≤ 3 knobs 0..1; o 1º = PRINCIPAL)
// opcoes: direcao=fixa|relevo|redemoinho|vetor (nomes da ESCOLHA)
// cat: distorcao                               (cor|luz|forma|geometria|distorcao|textura|tempo|mistura|gerador|mascara)
// in: src                                      (lê a entrada B; padrão ao inserir: src | fb)
// bipolar: angulo                              (knob de dois lados: 0.5 = nada)
// ritmo: velocidade                            (knob de rapidez: pode travar no BPM — UI no próximo chat)
// estado: canais=4, passos=8, fases=1, escala=0.35   (átomo com memória, §6)
// mod: forca=pulsa                             (movimento SUGERIDO)
// ATOMOS · Deslocar. Uma frase do que faz. Depois, o que cada knob faz.
```
O nome depois de `ATOMOS ·` é o que o dash mostra (o arquivo não tem acento: `Reacao.frag` → "Reação").
Do ISF (VDMX) copiamos o buffer persistente declarado e o "um arquivo, vários passes" (`PASSINDEX` = `u_fase`); não
copiamos o JSON nem knob fora de 0..1 (aqui tudo é 0..1 pra todo movimento caber em todo knob, como o 0–1 V do LZX).

## 3. O prelúdio (`dash_data.ATOM_PRELUDE`, o motor põe antes de todo átomo)
O átomo **não declara** os uniforms comuns nem `#ifdef GL_ES`: escreve só as funções dele e o `main`. Vem pronto:
- `u_resolution`, `u_time`, `u_beat`, `u_bar`, `u_phrase`, `u_dt`, `u_seed`, `u_texture_0/1/2/src`, `u_state`,
  `u_vista`, `u_fase`, `u_semear` (e `u_agl`, do motor).
- `uv()` (0..1 topo→baixo) · `px()` (1 pixel, só pra derivada) · `A/B/C/S(st)` (corrente, entrada B, C, fonte crua)
  · `Am(st)` (A pré-multiplicada, pra quem faz média) · `E(st)` (o estado) · `luma` · `aspecto()` · `asp(st)` (centro
  0, x corrigido) / `desasp(p)` · `rot(a)` · `hash`/`noise`/`fbm(p, detalhe)` (com `u_seed`) · `dirOf` ·
  `paleta(t, a, b, c, d)` (cosseno do Inigo Quilez) · `decai(s)` (quanto sobra num passo com meia-vida `s` segundos).
- `#line 0` depois do prelúdio: o erro de compilação aponta a linha do arquivo.

## 4. Knobs: poucos, 0..1, neutro previsível
≤ 3; o 1º é o PRINCIPAL (o botão grande); vocabulário comum (`forca`, `tamanho`, `velocidade`, `matiz`,
`saturacao`, `angulo`, `limiar`, `corte`, `borda`, `quantos`, `zoom`, `giro`, `direcao`, `rastro`, `detalhe`).
CHAVE = o código só lê `step(0.5, u_fx_X)`; ESCOLHA = `floor(u_fx_X * K)` + `// opcoes:` (repetição numérica que não é
escolha: escreva `floor(K * u_fx_X)`).
- **Neutro**: o principal é "quanto" (**0 = nada**, a peça vira identidade) ou é de dois lados (`// bipolar:`,
  **0.5 = nada**). A matriz confere: principal no neutro + todo bipolar em 0.5 = a entrada. Movimento a partir do
  neutro = o efeito entra e sai.
- **Quem desenha ou gera** (`cat: gerador`, ou alfa < 1 no padrão: Contornar, Listras) tem o "quanto" na
  **opacidade** da peça; o principal pode ser forma (quantos, tamanho).
- O padrão do `// fx:` faz algo visível (ninguém solta uma peça e "nada acontece").

## 5. Espaço, tempo, acaso, saída
- **Espaço em fração da tela**, aspecto corrigido. Nada de "3 pixels" (a matriz renderiza em 2 tamanhos e compara).
- **Tempo em segundos** (`u_time`); acumular só dentro de estado (§6), em passo fixo.
- **Semente**: `u_seed` = hash do id do nó; dois Ruídos iguais não ficam gêmeos e a cena volta igual.
- **Alfa = cobertura**: filtro devolve **o alfa que leu** (`vec4(cor, A(st).a)`), não `1.0` — o mesmo átomo serve na
  corrente opaca, num fio com transparência e no loop de uma peça que desenha só linhas. Espaço move cor e cobertura
  juntas; cor não mexe na cobertura. Quem faz **média** de amostras (Desfocar, Brilhar) soma `Am()` e divide pelo alfa.
- **Como entra na corrente** (`dash_data.atom_replaces`): **FILTRO = TROCA** — a saída dele substitui a entrada e a
  opacidade é quanto do original volta (o "blend with original" do After Effects); o alfa é o que ele devolve (Rodar
  num recorte gira o recorte, sem fantasma). **Quem desenha** (`cat: gerador | forma`) vai **POR CIMA** (cobertura soma).
  Corrente opaca = o mesmo resultado nos dois (cena antiga não muda).
- **Matéria** (Ruído, Rampa, Células, Reação, Fluido, Movimento): cinza opaco = quantidade pura (ou vetor). Paleta
  pinta; pra ver por cima de outra coisa, modo soma/tela ou a opacidade.
- Barato: ≲ 16 leituras por pixel. A camada da peça é **16F**; o motor cai pra 8 bits com **dither** (±1 nível).

## 6. Memória: átomo com estado
`// estado: canais=N, passos=P, fases=F, escala=E` → buffer duplo próprio **RGBA16F** (`native_synth.run_state`).
- **Um arquivo, duas fases**: `u_vista == 0` = ATUALIZA (lê `E()` = o passo anterior e as entradas, escreve o estado
  novo); `u_vista == 1` = MOSTRA (escreve a imagem que vai pro fio). Sim com várias etapas por passo (Fluido: avecção,
  pressão × 12, projeção) usa `u_fase` = 0..F-1.
- **Passo fixo** (Gaffer, "Fix your timestep"; `_state_steps`): P passos a cada 1/60 s de relógio, sobra pro próximo
  quadro, no máximo 2× por quadro. `u_dt` = o passo; nunca `u_time` pra acumular. A 30 ou a 60 fps sai o mesmo rastro.
- **escala** = linhas do buffer ÷ 1080, FIXA (não depende da janela): a mesma forma em qualquer saída.
- **Estado zerado = vazio** (regra de desenho: a Reação guarda `1 − A` pra o zero ser "sem forma").
- **Eventos**: `limpar` = o motor zera o buffer (sem código no átomo); `semear` = `u_semear` vale 1 num passo (o
  átomo diz o que é semear). Item: `estado: {semear: <evento>, limpar: <evento>}` (os eventos do MOVIMENTO) ou o botão
  no inspetor (`POST /state-cmd {id, op}`). "O drop apaga o coral e ele cresce de novo" sai sem código especial.
- Rastro que apaga até o preto: 16 bits + um piso (abaixo de meio nível de 8 bits = preto).

## 7. O encaixe (5 ligações + espelho)
Cada ligação é uma **entrada com nome na borda do nó** (cabos como no VCV Rack: a entrada aceita UM fio, a saída quantos quiser;
o fio que fecha um laço lê o quadro anterior).
1. **Corrente (A)**: o nó que este lê (`file: '@<id>'`). 2. **Entrada B** (`ins`: o fio na bolinha B; sem fio = `src` (a crua)
ou `fb` (ele mesmo 1 quadro atrás)). 3. **Máscara** da caixa (§9; um fio na bolinha "máscara" = átomo Luma).
4. **Loop do nó** (átomo solto NO MEIO, `post: [ids]`): num nó comum = **pós** (age na camada antes de juntar — o
efeito de clipe do Resolume); num nó com estado = **retorno** ↻ (age no que recircula, antes de cada passo — o laço do
Feedback TOP do TouchDesigner: Rodar = espiral, Desfocar = fumaça). O átomo do retorno lê o estado como a corrente
(`u_agl = 1`) e roda na resolução dele. 5. **Junção** = um **staging** ou uma **saída** (mixer): cada entrada é uma camada
(opacidade + modo + ordem, `layers`); átomos do mixer agem DEPOIS da mistura, na imagem já junta.
**Espelho** (`{file, espelho: <id>, id}`): o MESMO átomo noutro lugar — knobs, movimentos e liga/desliga do original; fio e
estado (um buffer por lugar) são do lugar; `u_seed` = o do original. Vale pra qualquer átomo; a matriz não muda (é o mesmo `.frag`).

## 8. Sinal e evento
O MOVIMENTO não muda (§10). Pontes: **qualquer nó vira sinal** — fonte `no:<id>` = brilho médio da saída do nó, 0..1
(`grab_no`, ~20 Hz; o nó roda mesmo fora da SAÍDA), como o "TOP to CHOP" do TouchDesigner; **o tom da música**
(`key_hue`, a cor do tom) é sinal; **evento → estado** (`semear`/`limpar`).

## 9. Átomo de MÁSCARA (`// cat: mascara`)
Mora na máscara da caixa (`BINDINGS[canal].matte = {items, op?, cut?}`), lê a ENTRADA da caixa em `A()` e devolve
cinza `vec4(vec3(m), 1.0)`: 1 = mostra o resultado, 0 = passa a entrada (ou transparente, com `cut`). Com `// in:` lê
outra caixa (Luma). Só ele lê `u_subject`/`u_subject_on` (U²-Net) e o rastreio: `u_rosto[4]` (cx, cy, largura,
altura) / `u_olhos[4]` + `u_rosto_on`, `u_corpo[33]` (x, y, visibilidade) + `u_corpo_on`, `u_obj[8]` / `u_obj_p[8]` +
`u_obj_on`, `u_olho[64]` (contorno das pálpebras: `u_olho[(i*2+e)*8 + k]`) + `u_olho_on` — uv da fonte, topo→baixo;
`_on` cai a 0 em ~0.5 s. Várias: `op: 'e'` (multiplica) ou `'ou'` (o mais claro). Hoje: Assunto, Fundo, Brilho,
Cor, Luma, Rosto, Olhos, Corpo, Mãos, Objeto.

## 10. Movimento (Claude Doc "PRISMA — sync com a música")
Três tipos: **imagem**, **sinal** 0..1 (o CV), **evento** (o trigger). Sete regras: tudo vira sinal · sinal só entra
pelo KNOB (o átomo **não lê o som**: nem `u_bass`, nem `on_*`, nem `layer`) · knob = faixa `lo`→`hi` (`lo > hi` =
ducking; várias fontes = a mais forte) · movimento = fonte → modo → forma · evento só dispara · ação discreta cai na
grade · mesmo id = o mesmo movimento. `mod[knob] = {b, lo, hi, modo: loop|disparo|segue, lfo, ev: {src, cond}, env,
seg, q, id, nome}` (`native_synth._mod_value`). `// mod: knob=preset` só sugere (`dash_data.MOV_PRESETS`).

## 10b. Quem MEXE no valor é outro nó (2026-11-04)
Cor é de átomo de cor (Matiz, Tingir, Paleta, Saturar); quem desenha/entorta não tem `matiz`, `giro` de cor nem som dentro
(o Contornar desenha branco, o Mover só empurra). Valor que anda sozinho = um **CONTROLADOR** no canvas (dash v5: o
movimento com corpo — LFO, segue o grave, envelope… — com um cabo tracejado até o knob; pilha `~ctl`, `mod[knob].id` = o id
dele). Os presets antigos (`sortidos/`, `default/`) viraram **receitas** (`shaders/receitas/*.json`: corrente de átomos +
movimentos) e saíram da biblioteca; as cenas antigas continuam rodando o `.frag` velho.

## 11. Verificação
- `atom_problems`: cabeçalho, ≤ 3 knobs, nada do prelúdio redeclarado, só imagem + relógio, `// bipolar:`/`// ritmo:`
  em knob que existe, `// estado:` com `u_vista` e sem `u_time`, `E()`/`u_state` só com estado.
- **Matriz de emergência** (offscreen 64×36, ~2 s): cada átomo sozinho (sem NaN, sem tela chapada, mesma forma em 2
  tamanhos), neutro = identidade, **transparência** (filtro não fura a corrente opaca; entrada com vazio → sem NaN, cor
  não mexe na cobertura), **todo par A → B**, todo átomo como B de todo leitor de B, estado 300 passos com a
  entrada andando (não satura nem morre; `limpar` zera) e todo filtro no loop retorno de todo átomo com estado.
  **Falhou = buraco na regra, não "combinação proibida".** `python src/matriz.py <pasta>` grava um PNG por átomo.

## Os átomos
Filtros: Afiar, Blocos, Brilhar, Desfocar, Deslocar, Dobrar, Espelhar, Esticar, Fatias, Gota, Grão, Inverter, Limiar,
Luz, Matiz, Misturar, Máscara, Mover, Níveis, Onda, Paleta, Polar, Rodar, Saturar, Separar, Tingir, Vinheta. Traço/gerador: Contornar, Listras, Pontos.
Matéria: Ruído, Rampa, Células. Com estado: Feedback, Reação (Gray-Scott), Fluido (Stable Fluids), Movimento (fluxo
óptico). Máscaras: §9.
