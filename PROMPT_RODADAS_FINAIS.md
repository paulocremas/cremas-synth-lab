# PROMPT — rodadas que ficaram da revisão geral + roda mais bonita com busca

Responda sempre em pt-BR. Repo `cremas-synth-lab`, branch `dashboard-channels-output`. Leia antes: `CLAUDE.md`, `DECISOES.md`
("O que vale hoje"), o fim do `BACKLOG.md` (seção "Revisão geral 2026-11-27 — o que ficou") e a memória `prisma-revisao-geral`.
O book da revisão é o artefato `Lqxf2fWuwoghNmWQmvJHFN` (local: `design/revisao-geral/`).

**O usuário já autorizou fazer todas as rodadas que ficaram** ("pode fazer as rodadas que ficaram"). Não precisa pedir licença rodada
por rodada. **Pare e pergunte só** se uma mudança puder perder o trabalho dele (cenas, `tuning.py`, mídia) ou se faltar uma decisão
que é dele (está marcada abaixo).

## Regras (as de sempre)
- Rodadas PEQUENAS. Cada uma termina com teste verde e é entregue na hora em `dist/prisma/` **e** na pasta de dados
  (`~/.local/share/prisma/`). O `native_synth.py` só vale reabrindo o app.
- `tests/tudo.sh` (rápido) a cada rodada; `tests/tudo.sh --lento` antes de fechar qualquer rodada que mexa no dash5 ou no motor.
  O `t6_pele_unica` falha às vezes só na suíte (rode sozinho). Todo bug de usabilidade vira teste em `tests/dash_gestos.py`.
- Antes de mexer em formato de dados: backup do `src/tuning.py` **e** do `tuning.py` da pasta de dados, no scratchpad. Teste que
  agenda gravação aponta `_cfg['tuning_path']` pro temporário e dá flush antes de devolver (já gravou no repo uma vez).
- Notebook com touchpad: todo gesto tem caminho sem arrastar e tolera ~8 px; roda sem Alt não gira controle. Tudo escuro;
  legibilidade primeiro; cor = significado (imagem azul, sinal âmbar, evento verde; no ar verde, escolhido laranja, perigo vermelho).
  Preferir tirar a acrescentar. Medir o fps real (não só o ms): o canvas está em 60 fps com ~37 nós.
- Decisão nova vai em `DECISOES.md` (histórico + "o que vale hoje"); o que sobrar vai pro `BACKLOG.md`; atualize `CLAUDE.md` quando
  um nome/arquivo mudar (ele é lido toda sessão, então mantenha curto).
- **Commit só se o usuário pedir.** Os `git mv`/`git rm` da revisão estão preparados no git, esperando o commit dele.

## Ordem sugerida

### Rodada A — a roda de adicionar módulos (pedido novo, faça primeiro)
Código: `openWheel` em `dash5.html` (~linha 4137), `floatList`, `wheelSectors`, CSS `.wheel`/`.wh-s`/`.wh-mid`/`.wh-in`.
Hoje a roda abre com a lista "procurar em tudo" já com o cursor na busca. Mas depois de escolher uma fatia, a busca filtra só
aquela família, e o atalho de digitar (`kd`) só funciona sem a lista aberta.
1. **Escrever com a roda aberta = procurar em QUALQUER módulo, sempre.** Fatia escolhida, foco onde estiver, sem precisar clicar no
   campo. A busca cobre tudo que a roda cria: átomos, receitas, fontes, mistura/saída, alteradores, eventos e MÃO. Tolera acento e
   erro pequeno ("cromatico" acha "Cromático"), casa por nome, apelido e família, e destaca o trecho achado. ↑/↓ escolhe,
   Enter cria, Esc limpa a busca (e um segundo Esc fecha), Backspace no campo vazio volta pra fatia. Teste novo:
   `t6_roda_busca_tudo` (abrir a roda, escolher uma fatia, digitar o nome de um módulo de outra família, Enter → o módulo nasce).
2. **Embelezar** dentro das regras do topo do dash5 (uma luz de cima, sombra em camadas, `led()`, material da família via
   `G6.swatch`) e respeitando as 10 peles (`SKINS`, `skinContrast`). Ideias pra avaliar, não lista obrigatória:
   - abrir com animação curta (≤ 150 ms, desligada com `prefers-reduced-motion`);
   - fatias com o material e o pictograma maiores, e a escolhida acesa em laranja;
   - meio da roda dizendo onde o módulo entra ("depois de X");
   - lista com o pictograma (`atomIcon`) e uma linha de descrição.

   Mostre um antes/depois com `tests/estetica.py` (todas as peles) e confira que o fps não caiu.

### Rodada B — conferir o motor de verdade
Rode o native em segundo plano com a webcam e `PRISMA_HIDDEN=1`. Confira o ms por quadro no HUD (`state.output.ms`) e o erro de
shader por arquivo (`shader_errors`; quebre um `.frag` de propósito numa cópia temporária). Até aqui os dois só foram checados de
forma estática.

### Rodada C — F1 · migração única no Python
Ids determinísticos, migrados ao ler a cena, no `migrate_graph`. Hoje o `graphFix` do JS é o migrador de verdade: ele vira só
leitor. O teste `t6_js_python_concordam` precisa continuar verde. Teste com as cenas reais da pasta de dados (cópia).

### Rodada D — F6 · bloco CONTROLES fora de `BINDINGS`
`~ctl`, `~ev` e `~mao` saem de `BINDINGS`, com migração nos dois lados. Depois, **F8 · plano do quadro**: tirar do `render_mix`
uma função pura que monta o plano (ordem, passes, texturas) e testar no CI sem GL.

### Rodada E — F7 · `scenes.json`
As cenas saem do `tuning.py` (que fica só com os ajustes). Migração automática na 1ª abertura, guardando o backup ao lado. Atenção
ao `updater.sync_data` e ao launcher, que recopiam arquivos.

### Rodada F — Etapa 4 · build
Rode `packaging/build.sh` (ou `DIST=<pasta>`), confira se o binário novo abre e só então apague
`dist/prisma/dash{,2,3,4}.html`. Rode `packaging/check_imports.py`.

### Rodada G — Etapas 7 e 8 · dividir o código (a mais arriscada: por último)
- `native_synth.py` → módulos com nomes NOVOS: motor_grafo, movimento, captura, análise, saída. Cada import novo precisa entrar no
  `if False:` do `packaging/launcher.py`.
- Painel em pasta (`painel/`): só se a rodada anterior ficar verde. O hot-reload por mtime e o launcher precisam cobrir os arquivos
  novos.
- Atualize o `CLAUDE.md`.

### Rodada H — sobras pequenas
- Desmontar os sets de shader/mídia (v1–v3) do servidor: a partida e o self-check de mídia ainda usam.
- Código morto que sobrou (lista no BACKLOG).
- **1ª abertura sem vídeo:** a pasta `media/` não está no git. Proponha uma cena semente só com átomos geradores, sem mídia, em vez
  de um vídeo. **Decisão do usuário:** confirme antes de trocar a semente.

### Fica só desenhado (não implementar sem aprovação)
- **P6:** várias saídas/telões, warp e borda suave entre projetores.
- **`// ritmo:`** dos átomos (travar no BPM).

Faça um book curto (artefato com db de escolhas) com as opções e a recomendação de cada um.

## No fim
Atualize a memória `prisma-revisao-geral` (o que foi feito e o que ficou). Republique o book com um quadro "Aplicado em <data>".
Responda em pt-BR com o que mudou para quem usa, os desvios e o motivo de cada um, o que ficou e o lembrete de reabrir o app e de
fazer o commit.
