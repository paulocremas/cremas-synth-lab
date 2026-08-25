# Mapa das documentações — GLSL & SuperCollider

Índice de leitura rápida dos textos-fonte do [Plano de estudo](CLAUDE.md#plano-de-estudo).
Cada entrada resume o que o capítulo/tutorial realmente ensina, pra consultar antes de reabrir
o arquivo bruto local (`docs/glsl/NN.md`, `docs/sc/NN.md`) ou a internet.

Baixado e lido por completo em 2026-08-23, direto dos repositórios oficiais:
- GLSL: [thebookofshaders](https://github.com/patriciogonzalezvivo/thebookofshaders), capítulos 00–18 (todo o índice publicado)
- SC: [SuperCollider-Tutorials](https://github.com/elifieldsteel/SuperCollider-Tutorials) do Eli Fieldsteel, os 12 tutoriais citados no plano

---

## GLSL — The Book of Shaders

### Fase 0 (navegação)

### GLSL cap. 00 — Introduction
**Arquivo local:** `docs/glsl/00.md`
Capítulo de abertura, sem código GLSL: apresenta o livro como um guia para *fragment shaders*, comparando a técnica com a prensa de Gutenberg — imagem gerada de forma paralela (todos os pixels ao mesmo tempo) em vez de serial (traço a traço, como um pintor). Define o público-alvo (programadores com noção de álgebra linear e trigonometria) e o escopo: formas procedurais, padrões, texturas, animações, processamento de imagem (convoluções, blur, LUTs) e simulações (Game of Life, reaction-diffusion, Voronoi), terminando em Ray Marching. Deixa claro o que o livro NÃO cobre — não é um livro de OpenGL/WebGL nem de matemática, só aplica esses conceitos. Detalhe prático: cada capítulo tem exemplos interativos que o autor recomenda editar ao vivo, pois mudar o código e ver o resultado imediato é essencial para o aprendizado.

### GLSL cap. 01 — Getting started (What is a fragment shader?)
**Arquivo local:** `docs/glsl/01.md`
Explica a ideia central de um fragment shader: uma função que roda em paralelo para cada pixel da tela, recebendo uma posição e devolvendo uma cor, ao contrário do desenho sequencial tradicional (círculo, depois retângulo, depois linha). Usa a metáfora da GPU como uma mesa de muitos "tubos" (threads) pequenos processando em paralelo, contra a CPU com poucos tubos grandes processando em série — e mostra a conta de quantos pixels por segundo uma tela precisa (ex. 800x600 a 30fps = 14,4 milhões de cálculos/s). Define GLSL como o padrão OpenGL Shading Language regulado pelo Khronos Group. O ponto prático mais importante do capítulo: cada thread da GPU é *blind* (não enxerga o que as outras threads fazem) e *memoryless* (sem memória do frame anterior) — restrição estrutural que explica por que shaders são notoriamente difíceis para quem começa.

### GLSL cap. 02 — Hello World
**Arquivo local:** `docs/glsl/02.md`
Primeiro código GLSL de fato: em vez de imprimir texto, o "hello world" pinta a tela inteira com uma cor sólida atribuída à variável global reservada `gl_FragColor`, dentro da única função `main()` do shader (sintaxe estilo C). Introduz o tipo `vec4` (vetor de 4 floats normalizados 0.0–1.0 mapeados para R, G, B, A) e menciona `vec3`/`vec2`/`float`/`int`/`bool`, além de macros de pré-processador (`#ifdef GL_ES`, `#define`) e a diretiva `precision mediump float;` que controla a precisão (e velocidade) dos floats. Pegadinha central: GLSL não faz casting automático — `vec4(1,0,0,1)` com inteiros gera erro; é preciso sempre usar ponto decimal (`1.0`). Também mostra construir `vec4` a partir de um `vec3` mais um valor: `vec4(vec3(1.0,0.0,1.0),1.0)`.

### GLSL cap. 03 — Uniforms
**Arquivo local:** `docs/glsl/03.md`
Introduz `uniform` como o mecanismo de entrada de dados da CPU para todas as threads da GPU simultaneamente (mesmo valor, somente leitura) — tipos suportados incluem `float`, `vec2/3/4`, `mat2/3/4`, `sampler2D`, `samplerCube`. Apresenta as três uniforms convencionais do livro: `u_time` (segundos desde o início), `u_resolution` (tamanho do canvas) e `u_mouse` (posição do mouse), comparando com os nomes equivalentes do ShaderToy (`iTime`, `iResolution`, `iMouse`). Mostra animação básica combinando `u_time` com `sin()`, e lista funções nativas aceleradas por hardware: `sin/cos/tan/pow/exp/log/sqrt/abs/floor/ceil/fract/mod/min/max/clamp`. Introduz `gl_FragCoord` (posição do pixel, varia por thread — diferente de uniform) e o idioma central `st = gl_FragCoord.xy/u_resolution.xy` pra normalizar coordenadas de tela em 0.0–1.0.

### GLSL cap. 04 — Running your shader
**Arquivo local:** `docs/glsl/04.md`
Capítulo prático sobre ferramentas pra rodar shaders fora dos exemplos interativos do livro: `glslCanvas` (elemento `<canvas>` pro navegador), `glslViewer` (linha de comando, útil no Raspberry Pi), `glslEditor` e `glslGallery`. Mostra integração das mesmas uniforms em Three.js, Processing e openFrameworks. Não introduz sintaxe GLSL nova — é sobre onde/como colar o shader `.frag` já aprendido. **Nota do projeto:** aqui é diferente — usamos a extensão `glsl-canvas` do VS Code em vez de qualquer um desses; o modelo de uniforms é o mesmo.

---

### Fase 1 (vocabulário central)

### GLSL cap. 05 — Shaping functions
**Arquivo local:** `docs/glsl/05.md`
Abertura da seção "Algorithmic drawing": ensina a moldar um valor 1D (o eixo x normalizado) usando a metáfora da "cerca" entre 0.0 e 1.0. Introduz `pow()` pra curvar a interpolação linear, `step(limite, valor)` (degrau binário) e `smoothstep(a, b, valor)` (transição suave) — com o idioma de somar dois `smoothstep()` pra desenhar um "bump": `smoothstep(0.2,0.5,x) - smoothstep(0.5,0.8,x)`. Explora `sin()`/`cos()` em profundidade (fase, frequência, amplitude) com `u_time`, `abs()` (onda "quicando") e `fract()`. Aponta recursos externos (funções de Iñigo Quilez, biblioteca LYGIA) como caixa de ferramentas avançada.

### GLSL cap. 09 — Patterns
**Arquivo local:** `docs/glsl/09.md`
Fecha "Algorithmic drawing" ensinando repetição/tiling: como o custo de um shader é constante por pixel independente de quanto se repete uma forma, shaders são ideais pra padrões. Técnica central: escalar as coordenadas antes de aplicar `fract()`, quebrando o espaço 0–1 em N subcélulas repetidas, cada uma virando uma coordenada local 0–1 (idioma: `st = fract(st * N)`). Matrizes de transformação podem ser aplicadas dentro de cada célula individualmente. Introduz Truchet Tiles: um elemento mínimo (ex. triângulo) rotacionado diferente por célula, compondo padrões infinitos a partir de uma peça reutilizável.

### GLSL cap. 10 — Random
**Arquivo local:** `docs/glsl/10.md`
Gera aleatoriedade dentro do ambiente determinístico de um shader — base de ruído, Voronoi e fBm depois. Técnica principal: `fract(sin(x) * numero_grande)`, que "quebra" a onda regular do seno em algo pseudo-caótico (função `rand()`). Mostra como controlar a distribuição (`rand()*rand()`, `sqrt(rand())`, `pow(rand(),5.)`) e estende pra 2D usando `dot()` pra colapsar um `vec2` num float antes do truque do seno. Introduz tiling: `floor()` (célula) + `fract()` (posição dentro da célula) pra gerar valor aleatório constante por célula — base de mosaico e padrão Truchet/`10 PRINT`. Esse `rand()` é pseudo-aleatório determinístico: mesma entrada, mesma saída.

### GLSL cap. 11 — Noise
**Arquivo local:** `docs/glsl/11.md`
Ruído "orgânico" e suave (Perlin noise), em contraste com o random cru do cap. 10 — motivado pela textura procedural que Ken Perlin criou pro filme Tron (1982). Constrói ruído 1D interpolando (`mix()`) valores aleatórios entre pontos inteiros vizinhos (linear, depois com `smoothstep()` ou curva cúbica `f*f*(3.-2.*f)`), e estende pra 2D interpolando os 4 cantos de uma célula — "value noise", com aparência meio "blocada". Explica gradient noise (Perlin clássico, 1985): interpola vetores de direção nos cantos em vez de valores simples. Cobre a versão melhorada (curva quíntica) e o Simplex Noise (Siggraph 2001), que troca a grade quadrada por triângulos equiláteros — mais barato em dimensões altas (N+1 cantos em vez de 2^N).

### GLSL cap. 17 — Kernel convolutions
**Arquivo local:** `docs/glsl/17.md`
**Sem conteúdo publicado.** O arquivo tem só o título "## Kernel convolutions", zero texto, zero código, zero link. Não dá pra estudar filtro/blur direto pelo livro aqui — precisa de fonte alternativa (ex. artigos sobre "image kernel" / gaussian blur em GLSL, ou LearnOpenGL).

### GLSL cap. 18 — Filters
**Arquivo local:** `docs/glsl/18.md`
**Sem conteúdo publicado.** Mesma situação do cap. 17: só o título "## Filters", nada mais. Mesma recomendação — buscar fonte alternativa quando chegar nessa etapa do plano.

---

### Fase 2 (avançado, opcional por enquanto)

### GLSL cap. 13 — Fractal Brownian Motion
**Arquivo local:** `docs/glsl/13.md`
fBm: soma de várias "oitavas" de ruído em frequências crescentes e amplitudes decrescentes, gerando detalhe fractal auto-similar. Revisa onda (`sin(x*frequency)*amplitude`) e superposição de senoides antes de implementar fBm como loop somando `amplitude * noise(frequency * x)`, multiplicando frequência por "lacunarity" e amplitude por "gain" a cada oitava. Mostra variantes: turbulence (`abs()` do ruído, vales afiados) e ridge (cristas), fechando com "domain warping" de Iñigo Quilez — usar fBm pra distorcer a entrada de outro fBm (`fbm(p + fbm(p + fbm(p)))`), técnica de nuvens/terrenos procedurais.

### GLSL cap. 14 — Fractals
**Arquivo local:** `docs/glsl/14.md`
**Quase sem conteúdo.** O texto é literalmente "Coming soon ..." seguido só de uma lista de links pro shadertoy.com (fractal básico, Mandelbrot em três variantes, IFS, Julia em duas variantes, Fractal Wheel, floco de Koch). Nenhuma explicação de teoria nem de implementação — o capítulo aponta inteiramente pra fora do livro.

### GLSL cap. 12 — Cellular Noise (bônus, não citado no plano mas é pré-requisito natural de Voronoi)
**Arquivo local:** `docs/glsl/12.md`
Cellular noise / Voronoi (algoritmo de Steven Worley, 1996): distance field até um conjunto de "feature points". Mostra cálculo por `for` loop (limite precisa ser `const` em GLSL) e depois a técnica de tiling — um ponto aleatório por célula, checando só as 9 células vizinhas em vez de todos os pontos, essencial pra paralelismo de GPU. Guardar a posição do ponto mais próximo (não só a distância) transforma isso num diagrama de Voronoi de verdade, usado pra colorir cada célula.

### Chapters não citados no plano, mas com conteúdo real (referência solta)
- **cap. 06 — Colors** (`docs/glsl/06.md`): swizzle, `mix()`, HSB via `rgb2hsv`/`hsv2rgb`, coordenadas polares com `atan(y,x)`.
- **cap. 07 — Shapes** (`docs/glsl/07.md`): retângulos com `step()`, círculos como distance field, formas polares com `atan`+`length`.
- **cap. 08 — 2D Matrices** (`docs/glsl/08.md`): `mat2` de rotação `mat2(cos,-sin,sin,cos)`, ordem translate→transform→translate-back.
- **cap. 15 — Textures** (`docs/glsl/15.md`): `sampler2D`+`texture2D()`, correção de aspect ratio, sprite sheets.
- **cap. 16 — Image operations** (`docs/glsl/16.md`): quase sem texto, só widgets interativos (invert, add/sub/mul, blend modes).

---

## SuperCollider — tutoriais de Eli Fieldsteel

### Fase 0 (navegação)

### SC tutorial 01 — Navegação do ambiente/IDE
**Arquivo local:** `docs/sc/01.md`
Interface do SuperCollider: workspace, post window e documentação de ajuda, todas reposicionáveis. Paradigma "receiver.message" (ex. `3.cubed`), avaliação de linha (shift-return) e de blocos (command-return), diferença entre variáveis locais (`var`, só existem na mesma execução) e globais (a-z minúsculas ou `~nome`, persistem entre execuções). Atalhos de ajuda: command-D (doc do termo sob o cursor), shift-command-D (busca livre).

### SC tutorial 02 — Arquitetura cliente-servidor e primeiro som
**Arquivo local:** `docs/sc/02.md`
SuperCollider é dois programas: `sclang` (linguagem/cliente) e `scsynth` (servidor de áudio), comunicando via OSC. Boot/stop do servidor local (`s.boot`/`s.quit`), som imediato com `{UGen.ar}.play` e o atalho vital command-período pra parar tudo. UGens têm três métodos: `.ar` (audio rate), `.kr` (control rate, ~64x mais lento, pra modular outros UGens) e `.ir` (calcula uma vez). Armadilha comum: pra dar `.free`, precisa guardar o retorno de `.play` numa variável (não dá pra liberar a Function).

### SC tutorial 03 — SynthDef vs Function.play
**Arquivo local:** `docs/sc/03.md`
`Function.play` é bom pra testes rápidos; `SynthDef`/`Synth` é o caminho flexível e reutilizável — SynthDef é a "receita", Synth é a execução. Sintaxe `SynthDef.new(\nome, {...}).add`, precisa de UGen de saída explícito (`Out.ar(bus, sinal)`). Cria instâncias com `Synth.new(\nome, [\arg, valor])`. Constrói um exemplo progressivo com `Pulse.ar`, `LFNoise0.kr`, `LFPulse.kr` e `FreeVerb.ar`, todos ajustáveis em tempo real via `.set`.

### SC tutorial 04 — Envelopes e doneAction
**Arquivo local:** `docs/sc/04.md`
Controle suave de duração (evitando cliques de corte abrupto): `Line.kr`/`XLine.kr` (linear vs exponencial — XLine não pode cruzar zero), e `doneAction` (0 = não faz nada, Synth continua rodando mudo gastando CPU; 2 = libera o Synth automaticamente). `EnvGen` + `Env` (breakpoints de `levels`/`times`/`curve`, visualizável com `.plot`), argumento `gate` (dispara indo de não-positivo pra positivo) e prefixo `t_` pra argumentos-trigger. Fecha com `Env.adsr`. Armadilha prática: usar `s.plotTree`/`s.freeAll` quando Synths com `doneAction:0` se acumulam sem serem liberados.

### SC tutorial 05 — Expansão multicanal
**Arquivo local:** `docs/sc/05.md`
Um Array de UGens (ou array como argumento, ex. `SinOsc.ar([300,500])`) vira múltiplos canais de saída automaticamente, visível no medidor (`s.meter`). `Mix` soma tudo a um canal, `Splay.ar` espalha um array no campo estéreo, `.dup(n)`/`!n` duplica. Duas armadilhas centrais: nunca passar array de busses em `Out.ar` (sobrepõe sinal); e duplicar um UGen já instanciado (`PinkNoise.ar(0.5)!2`, mesma instância em todos os canais) é diferente de duplicar dentro de uma função (`{...}!n`, instâncias/valores únicos por canal).

---

### Fase 1 (vocabulário central)

*(Oscilador/frequência/fase → `SinOsc` básico, já coberto nos tutoriais 1-5 acima; sem tutorial dedicado extra.)*

### SC tutorial 10 — Patterns (Pbind, Pseq, Prand)
**Arquivo local:** `docs/sc/10.md`
Sistema de Patterns pra sequenciar dados/Synths no tempo. `Pbind` gera "note events" a partir de pares chave-valor (`\dur` controla o tempo entre eventos), retorna `EventStreamPlayer` via `.play`. Padrões geradores: `Pseq` (sequência fixa), `Pwhite`/`Pexprand` (aleatório linear/exponencial), `Prand`/`Pxrand`/`Pwrand`/`Pshuf` (escolha aleatória com variações) e `Pkey` (referencia outra chave do mesmo evento). `Pdef` manipula patterns em tempo real, `quant` sincroniza mudanças a um grid rítmico, `Ppar` toca múltiplos Pbinds em paralelo. Nested patterns (Pseq contendo Prand) misturam estrutura fixa com variação controlada.

### SC tutorial 20 — Entrada de áudio ao vivo e delay
**Arquivo local:** `docs/sc/20.md`
Captura de microfone: `SoundIn` (wrapper de `In.ar`, conta canais de entrada a partir de zero — mais portável que `In.ar` com índice fixo; `AudioIn` é deprecated). A partir do sinal capturado: ring modulation (multiplicar por `SinOsc`) e cadeia de delay com `DelayL`/`CombL`, misturada ao original via `XFade2`. Modularização com `Bus.audio` privado e `Group`/`Group.after` pra ordem de execução. Detalhe prático importante: UGens de delay/comb alocam memória dinamicamente — o `memSize` padrão (8192 KB) é baixo demais pra várias linhas de delay, precisa aumentar `s.options.memSize` (ex. `2.pow(20)`) antes do boot.

### SC tutorial 21 — Introdução à síntese FM
**Arquivo local:** `docs/sc/21.md`
FM clássica: um modulador (`SinOsc.ar`) soma seu sinal à frequência de um portador (`SinOsc.ar(500 + SinOsc.ar(...))`); o `mul` do modulador controla profundidade — baixo é vibrato, na faixa audível (~20Hz+) vira timbre complexo com só dois osciladores. `MouseX.kr`/`MouseY.kr` (+ `.poll`) pra explorar interativamente. Vira SynthDef `\fm` com `carHz`/`modHz`/`modAmp`, depois `Env.perc` + `EnvGen.kr(doneAction:2)`, `Pan2.ar`. Fecha com `Pbind` sequenciando FM — armadilha: `exprand`/`rrand` (linguagem) fixam valor pra todos os eventos do Pbind, tem que usar `Pexprand`/`Pwhite` (Pattern) pra sortear valor novo por evento.

---

### Fase 2 (avançado, isolado)

### SC tutorial 22 — FM avançada: sidebands e índice de modulação
**Arquivo local:** `docs/sc/22.md`
Aprofunda a teoria pra construir instrumento FM afinável: amplitude do modulador = número de sidebands, frequência do modulador = espaçamento entre sidebands, frequência da portadora = centro dos sidebands. Índice de modulação (`index = modAmp/modHz`) ≈ número de pares de sidebands audíveis menos 1. Reconstrói `\fm` com `freq`/`cRatio`/`mRatio`/`index` — razões inteiras = espectro harmônico, não-inteiras = inarmônico (tipo sino). Adiciona envelope dedicado ao índice (`iEnv`). Apresenta `PMOsc` (phase modulation) como equivalente pronto da FM manual, com nota de bug de truncamento de fase acima de ±8pi naquela versão do SC.

### SC tutorial 23 — Wavetable synthesis
**Arquivo local:** `docs/sc/23.md`
Wavetable = coleção ordenada de valores (potência de 2) representando um ciclo de onda. UGen principal: `Osc` (interpolação linear, wavetable customizável via Buffer; parentes: `COsc`, `VOsc`, `Shaper`). Formato especial "wavetable format" (via `asWavetable`) pré-computa pares de valores pra acelerar interpolação no servidor. Quatro formas de gerar wavetables: `Signal.sineFill` (harmônicos), `Buffer.sine1/2/3` (sine3 permite parciais não-inteiros → aliasing), via `Env` (`asSignal`+`asWavetable`) e `Signal.waveFill` (algorítmico ponto a ponto). Detalhe prático: wavetables aleatórias podem ter DC offset — usar `LeakDC` no SynthDef.

### SC tutorial 25 — Síntese granular offline (GrainBuf)
**Arquivo local:** `docs/sc/25.md`
Fatiar um som gravado em Buffer em grãos curtos e remontar. Família de UGens: `GrainFM`/`GrainSin` (sintetizam e granulam), `GrainIn` (granula sinal arbitrário), `GrainBuf`/`TGrains`/`Warp1` (leem de Buffer) — foco em `GrainBuf`. Argumentos-chave: `trigger` (Impulse=síncrono vs Dust=assíncrono), `dur`, `soundbuf` (precisa ser mono — estéreo falha silenciosamente), `rate` (pitch shift), `pos` (posição de leitura 0–1), `interpolation` (1/2/4, qualidade vs CPU), `envbufnum`, `maxGrains` (teto de sobreposição, default 512). Automação de `pos` com `LFNoise1` (errático), `Line` (time-stretch) ou `LFSaw`/`Phasor` (loop). Rate negativo toca de trás pra frente.

### SC tutorial 26 — Síntese granular em tempo real (microfone)
**Arquivo local:** `docs/sc/26.md`
Continuação prática do 25, sobre microfone ao vivo. `GrainIn` é descartado pra esse uso (sem rate nem posição de leitura). Solução: `GrainBuf` sobre buffer circular, com 4 SynthDefs em Groups ordenadas (`Group.after`): `\mic` (SoundIn→bus), `\ptr` (Phasor gera rampa, usando `BufFrames` sem o `-1`), `\rec` (BufWr grava usando a rampa) e `\gran` (GrainBuf lê grãos). Ponto central: o ponteiro de leitura precisa ficar atrasado (`ptrSampleDelay`) em relação ao de gravação, senão captura a descontinuidade do buffer circular (clique). Implementa `minPtrDelay` e cálculo automático de `maxGrainDur` considerando o `rate`. Variações: freeze (rate=0), pointer randomizado, múltiplos ponteiros, harmonizador ao vivo (`rate` por semitom via `midiratio`). Cita `PitchShift` como alternativa mais simples e pronta.

---

## Lacunas confirmadas (não é falha de busca — o conteúdo simplesmente não existe na fonte)

| Onde | O que falta | O que fazer |
|---|---|---|
| GLSL cap. 17 (Kernel convolutions) | Só o título, zero texto | Buscar fonte alternativa quando chegar em "Filtro" na Fase 1 |
| GLSL cap. 18 (Filters) | Só o título, zero texto | Idem |
| GLSL cap. 14 (Fractals) | "Coming soon" + links soltos pro Shadertoy | Usar os links como ponto de partida, sem prosa explicativa do livro |
| GLSL — Feedback/pingpong (Fase 1) | Não existe capítulo nem numeração no livro (índice para em 18) | Fonte externa (creative coding / Shadertoy) quando chegar na Fase 3 |
| GLSL — Ray marching (Fase 2) | Não existe capítulo nem numeração no livro | Fonte externa (ex. artigos do Inigo Quilez) — já anotado como opcional no plano |
