# synth — GLSL puro & SuperCollider, da base

## Objetivo
Aprender o nível baixo de síntese de sinal em dois domínios que compartilham a mesma lógica —
ondas e emissões eletrônicas — só que aplicada a coisas diferentes:

- **SuperCollider** (`sclang`/`scsynth`): síntese de áudio. Sinal = onda sonora (amplitude x tempo).
- **GLSL puro**: síntese de imagem. Sinal = onda de cor/luz (valor x posição de pixel, por frame,
  calculado em paralelo na GPU).

Meta: entender o comportamento isolado de cada ferramenta primeiro, comparar onde o vocabulário se
repete (oscilador, frequência, fase, ruído, filtro, feedback), e só depois compor coisas mais
complexas — visual reagindo a áudio, ou os dois lado a lado.

## Estado do ambiente (2026-08-27)
- SuperCollider 3.13.0 instalado (`sclang` + `scsynth`), sem SuperDirt/Tidal — synth cru, pronto
  pra escrever UGens direto.
- GLSL: extensões VS Code `circledev.glsl-canvas` (live preview WebGL, uniforms `u_time`/
  `u_resolution`/`u_mouse` — mesmo modelo do Shadertoy/Book of Shaders) + `slevesque.shader`
  (syntax highlighting). Sem app externo — tudo dentro do editor.
- `check.frag` nesta pasta é só teste de fumaça do pipeline (VS Code → GLSL Canvas → GPU).
- Removido desta máquina: Tidal (lib cabal), extensão VS Code do Tidal, quarks SuperDirt/Vowel/
  Dirt-Samples, startup.scd antigo do SuperCollider.
- **`native_synth.py`**: ferramenta nativa (Python + PyOpenGL, sem navegador) que implementa a
  Fase 3 na prática, fora do índice de fases — captura webcam/tela (ffmpeg) + áudio do sistema
  (`parec`/PulseAudio), faz FFT de áudio (bass/mid/treble clássico + 8 faixas finas Sub-bass..Air
  + detecção de kick) e alimenta `image.frag` via uniforms em tempo real. `tuning.py` guarda as
  constantes de calibração com hot-reload (edita e salva, aplica na hora, sem reiniciar o
  programa nem perder o áudio em andamento).
- O mesmo script também faz **análise de imagem** do frame de entrada cru (brilho, cor
  dominante/média, matiz, saturação, temperatura de cor, nitidez, bordas, movimento, simetria,
  entropia, coloridez...), com versão "quanto no total" (medidor) e "onde na tela" (grid
  espacial 3x3) pra cada uma — dashboard próprio, numa janela `gnome-terminal` separada
  (`--full-screen`) quando disponível.

## Vocabulário compartilhado (onda / sinal)

| Conceito | SuperCollider | GLSL |
|---|---|---|
| Oscilador | `SinOsc`, `Saw`, `Pulse` | `sin()`/`fract()` numa shaping function |
| Frequência | `.freq` do UGen | quantas repetições do padrão cabem na tela |
| Fase | `.phase` | offset dentro do `sin()`/`fract()` |
| Amplitude | `.mul`, envelope (`EnvGen`) | brilho/intensidade da cor |
| Ruído | `LFNoise`, `WhiteNoise` | `random()`, Perlin `noise()` |
| Filtro | `LPF`/`HPF`/`RLPF` | blur, kernel convolution |
| Feedback | `LocalIn`/`LocalOut`, delay | pingpong buffer, reaction-diffusion |
| Taxa de amostragem | sample rate (44.1kHz, no tempo) | resolução/frame rate (no espaço) |

## Plano de estudo

Baseado em dois currículos já validados, não inventado do zero:
- GLSL: [The Book of Shaders](https://thebookofshaders.com/) (Patricio Gonzalez Vivo)
- SuperCollider: [série de tutoriais do Eli Fieldsteel](https://github.com/elifieldsteel/SuperCollider-Tutorials) (~30 vídeos numerados)

**Fase 0 — Navegação da ferramenta (ainda não é síntese, é aprender onde as coisas ficam)**
- SC: tutoriais 1–5 (Fieldsteel)
  - 1: layout do IDE — workspace, post window, help
  - 2: arquitetura cliente-servidor — `sclang` fala OSC com `scsynth`
  - 3: `SynthDef`+`Synth` (a "receita" e sua execução) vs `Function.play` (atalho rápido pra testar)
  - 4: som toca indefinidamente até ser liberado — controle de duração/envelope
  - 5: expansão multicanal — um Array de UGens vira várias saídas de áudio
- GLSL: Book of Shaders cap. 00–08
  - 00–01: o que é um shader — programa que roda em paralelo, um por pixel, na GPU
  - 02: hello world — primeiro `gl_FragColor`
  - 03: uniforms — variáveis que o CPU injeta no shader (`u_time`, `u_resolution`, `u_mouse`)
  - 04: como o shader roda (pipeline de compilação/execução)
  - 05: shaping functions — moldar uma curva (`sin`, `pow`, `smoothstep`) pra controlar como um valor varia
  - 06: cor como vetor RGB, misturas e espaços de cor
  - 07: desenhar formas usando distância (`length`, `step`)
  - 08: matrizes — rotação/escala/translação do espaço de coordenadas

**Fase 1 — Vocabulário central, isolado, um conceito por vez, nos dois ao mesmo tempo**
- Oscilador/frequência/fase → SC: `SinOsc` básico (onda senoidal repetindo N vezes por segundo)
  · GLSL: cap. 05 (Shaping functions — o mesmo `sin()`, mas repetindo N vezes por tela/eixo)
- Ruído → SC: `LFNoise`/`WhiteNoise` (valores aleatórios no tempo, com ou sem suavização)
  · GLSL: cap. 10–11 (Random — hash pseudo-aleatório por pixel; Noise — versão suavizada/interpolada, tipo Perlin)
- Padrões/repetição → SC: tutorial 10 (Patterns — sequenciar dados/eventos ao longo do tempo, ex. uma sequência de notas)
  · GLSL: cap. 09 (Patterns — repetir uma forma no espaço via `fract()`/módulo das coordenadas)
- Filtro → SC: `LPF`/`HPF`/`RLPF` (deixam passar só frequências baixas/altas/uma faixa do som)
  · GLSL: cap. 17–18 (Kernel convolutions — somar pixels vizinhos com pesos, base do blur; Filters — blur, sharpen, etc. construídos em cima disso)
- Feedback → SC: tutorial 20 (live input — captar microfone e realimentar a saída), `LocalIn`/`LocalOut` (realimentar o próprio sinal dentro do synth)
  · GLSL: **sem capítulo correspondente no livro** — o índice oficial do repo vai só até o cap. 18; "pingpong buffer" (usar o frame anterior como input do atual) é técnica real de creative coding mas fica fora do escopo do Book of Shaders. Deixar pra Fase 3/depois, com outra fonte.

**Fase 2 — Técnicas de síntese mais avançadas, ainda isoladas**
- SC: tutoriais 21–22 (FM — um oscilador modulando a frequência de outro, gera timbres complexos com poucos osciladores), 23 (wavetable — ler uma tabela de valores em loop como forma de onda), 25–26 (granular — fatiar um som gravado em grãos curtos e remontar, de buffer e depois em tempo real)
- GLSL: cap. 13–14 (fBm — somar camadas de noise em escalas diferentes, dá aspecto orgânico/nuvem; Fractals — repetição recursiva de um padrão). Ray marching **não tem capítulo publicado no livro** (índice para em 18) — mais avançado, opcional, buscar outra fonte (ex. artigos do Inigo Quilez) quando chegar lá.

**Fase 3 — Fusão**
- Áudio controlando visual: amplitude/RMS do SC modulando um uniform do shader via OSC (mesma ponte que vimos com Hydra/SuperDirt)
- Comparar lado a lado: mesmo conceito (ex. ruído), duas saídas diferentes, ver o comportamento
- Já implementado (fora de ordem) em `native_synth.py` — ver "Estado do ambiente" — só que com
  `parec`/numpy direto em vez de SC+OSC; o exercício SC→OSC→shader ainda fica de pé como
  comparação de abordagem quando chegar nessa fase pelo caminho planejado.

## Primeiro exercício (Fase 1, oscilador)

SC — ouvir uma frequência:
```supercollider
{SinOsc.ar(440, 0, 0.2)}.play;
```

GLSL — ver uma "frequência" (edite `check.frag`, troque a cor por algo tipo `sin(u_time * 4.0)`):
```glsl
gl_FragColor = vec4(vec3(sin(u_time * 4.0) * 0.5 + 0.5), 1.0);
```

Compare: o que "frequência" significa em cada um — ciclos por segundo no ouvido vs. ciclos por
segundo na tela. Esse é o primeiro par pra sentir o comportamento antes de seguir pra ruído.
