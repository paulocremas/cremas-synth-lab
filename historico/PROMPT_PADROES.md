# Prompt — PRISMA: padrões de integração entre nós (ÁTOMO v2) — cole num chat novo, na pasta do repo

Você vai **implementar os PADRÕES** que fazem os nós do PRISMA se integrarem de forma natural e surpreendente:
qualquer átomo encaixa em qualquer outro e o resultado faz sentido, inclusive em combinações que ninguém programou.
O foco estético é **formas orgânicas** (fluxo, tinta, crescimento, bolha, coral), sempre no tempo da música.
A direção já está traçada em **`PLANO_PADROES.md`** (leia inteiro primeiro): contratos C1–C5, garantias do motor,
matriz de emergência, migração, átomos novos, critério de aceite e fases. Pontos **[aberto]** são seus pra decidir
com pesquisa.

Antes de tudo leia: `CLAUDE.md`, `PLANO_PADROES.md`, `shaders/ATOMO.md`, `BACKLOG.md`, o comentário de decisões no
topo do `dash5.html`, `dash_data.atom_problems`/`parse_meta`, e no `native_synth.py` o `render_mix` (corrente,
`blend_into`, `_post_items`, `_ins_tex`, `lane_out`), `_lane_textures` e a sim de fluido (`build_sim_programs`).

## Pesquisa: LIBERADA e obrigatória
Use a skill de pesquisa profunda (deep-research) ou buscas em modo extended, várias em paralelo, lendo fontes
primárias. Diga o que cada fonte muda nas decisões. Pontos a fechar:
- **Contrato de imagem**: alfa pré-multiplicado vs direto em cadeias de composição (Porter-Duff; Nuke, Fusion,
  TouchDesigner); codificação de vetor (RG centrado em 0.5 em 8 bits vs com sinal em 16f); o `modulate` do Hydra.
- **Estado na GPU**: ping-pong, quantos passos por quadro, `dt` estável, MRT vs dois passes, no OpenGL que o motor
  usa (confira a versão/contexto no código). Gray-Scott (parâmetros que não explodem nem morrem), Stable Fluids
  (Jos Stam), fluxo óptico barato (Horn-Schunck/Lucas-Kanade em shader, diferença de quadros).
- **Precisão**: 8 bits vs RGBA16F em feedback, dither na saída (Bayer/blue noise), custo de memória.
- **Vocabulário do sintetizador de vídeo** (LZX: rampas, modeladores de onda, keyer, colorizador; Sandin Image
  Processor) e técnicas orgânicas em shader (domain warping e paletas cosseno de Inigo Quilez, curl noise de Bridson).
- **Integração por contrato** em outras áreas: o padrão de tensão do Eurorack/VCV Rack, ISF (Interactive Shader
  Format: cabeçalho de inputs/passes/persistent buffers — compare com o nosso `// fx:`), os operadores do
  TouchDesigner, a cadeia do Hydra. O que copiar e o que evitar.

## Como trabalhar (fases do `PLANO_PADROES.md` §12)
0. **Pesquisa → `shaders/ATOMO.md` v2** (o contrato curto, com as leituras de imagem, neutro, tempo, semente,
   estado, loop, sinal) + as decisões **[aberto]** com recomendação. **Pare e traga pra eu aprovar ANTES de codar**
   (2–4 decisões estruturais, explicadas simples).
1. **Motor**: 16 bits só onde há estado/feedback + dither final; `u_dt`; `u_seed`; prelúdio GLSL comum; `// estado:`
   com buffer duplo e eventos `semear`/`limpar`; loop **retorno** (o laço do Feedback) além do **pós** que já existe
   (`_post_items`); fonte de movimento `no:<id>`. Cenas e `tuning.py` atuais abrem sem perder nada.
2. **Verificação**: `atom_problems` estendido + MATRIZ DE EMERGÊNCIA no `--selfcheck` (todo par A→B, todo átomo como
   B de todo leitor de B, estado 300 passos, neutro ≈ identidade). Falhou = buraco no contrato, conserte a REGRA.
3. **Migrar** os átomos atuais (tabela do §8) e tirar `sortidos/`/`default/` da biblioteca da v5 (gaveta
   "clássicos"; continuam rodando nas cenas antigas).
4. **Onda a** de átomos novos (Ruído, Rampa, Dobrar, Polar, Limiar, Paleta) e as **5 interações do §10 rodando de
   verdade**, com prints do `/frame`. Ondas b/c (Afiar, Brilhar, Células, Movimento, Fluido, Reação) se der tempo,
   na ordem; senão viram BACKLOG com o desenho pronto.
Fora do escopo (próximo chat, §11): knobs no card, loop visível, receitas dobráveis, interações de adicionar/remover.
No dash, só o mínimo pra testar (ESCOLHA de direção, `semear`/`limpar` como evento, `no:<id>` na lista de fontes).

## Regras (valem do começo ao fim)
- **Tudo em segundo plano, NADA aparece na tela.**
  - Native: sempre `PRISMA_HIDDEN=1 PRISMA_NO_BROWSER=1`, em segundo plano, com backup/restauro do `src/tuning.py`.
    Se a porta 8765 estiver ocupada, é o MEU prisma aberto: não abra outro, espere liberar.
  - Navegador só headless (Brave em `/usr/bin/brave-browser`; Playwright num venv do scratchpad com
    `executable_path`), perfil isolado. Prints só de páginas headless e de `/frame`.
  - Nunca `pkill -f` com algo do próprio comando; use o PID. Nada de computer-use nem captura da área de trabalho.
- **Teste como gente**: aperte, espere ~0.5 s, aí arraste (o SSE de 20 Hz troca os objetos no meio).
- **Teste visual de verdade**: forma orgânica se julga olhando. Para cada átomo novo e cada interação do §10, gere
  prints do `/frame` em vários instantes (o estado evolui) e confira: sem fantasma que não apaga, sem banding, mesmo
  rastro a 30 e a 60 fps.
- Todos os testes do `CLAUDE.md` passando (o CI roda todos). Import novo em `src/` → `packaging/launcher.py`.
- Toda mudança vai pro app na hora: `dist/prisma/` **e** a pasta de dados (memória "sempre atualizar o binário").
- Ao fim: atualize `CLAUDE.md` (enxuto), `BACKLOG.md`, `shaders/ATOMO.md`, o `GLOSS` do `docs/index.html` (termos
  novos: leitura, direção, estado, semear/limpar, loop pós/retorno) e marque no `PLANO_PADROES.md` o que foi feito.

## Entrega final
Em português simples: o contrato v2 numa página, as decisões tomadas (e por quê, com as fontes), o que mudou no
motor, os átomos migrados e os novos, prints das 5 interações do §10, o resultado da matriz de emergência (o que ela
pegou), e o que ficou pra depois.
