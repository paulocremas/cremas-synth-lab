# Prompt — PRISMA: knobs + átomos como um framework de SYNC COM A MÚSICA (cole num chat novo, na pasta do repo)

Você vai **planejar** (e só depois de eu aprovar, construir) a forma definitiva de **configurar os knobs** e de os
**átomos interagirem** no PRISMA. Hoje funciona, mas cada peça foi crescendo por conta própria. Eu quero um
**framework**: um vocabulário pequeno, que encaixa sempre do mesmo jeito, com **controle simples e efetivo** ao vivo.
O **maior objetivo é o sync com a música**: tudo que se mexe deve poder andar no tempo, na batida, na frase e na
energia da música, sem eu programar nada no meio do show.

Antes de tudo leia: `CLAUDE.md`, `BACKLOG.md`, `shaders/ATOMO.md`, o comentário de decisões no topo do `dash5.html`
(o dash que o app abre), `src/ritmo.py` e o glossário `GLOSS` do `docs/index.html`.

## O norte: um AMBIENTE onde peças padronizadas interagem sozinhas
O plano forte não é uma lista de recursos. É um **ambiente virtual com poucas regras** em que qualquer efeito que
segue a estrutura padrão **interage corretamente com qualquer outro**, inclusive em combinações que ninguém
planejou. É a lógica do design sistêmico dos jogos: a "química" do Zelda: Breath of the Wild (poucas regras de
elementos × materiais, e o jogador descobre interações que os devs não roteirizaram), Noita (cada pixel obedece à
física), os immersive sims. No mundo do som, o equivalente é o **modular (Eurorack)**: tudo é tensão, então qualquer
saída liga em qualquer entrada e faz sentido.
- Toda decisão do plano passa por este teste: **é uma REGRA geral ou um caso especial?** Caso especial ("o átomo X
  reage ao Y") é sinal de que falta uma regra. Prefira propriedades (o que uma peça É e o que ela emite/aceita) a
  ligações feitas à mão.
- Descreva as regras como um contrato curto (tipos de sinal, faixas, quem lê o quê, em que ordem) e mostre 3–4
  interações **emergentes** que saem dele sem código extra (ex.: um rastreio de mão vira envelope, o envelope mexe a
  máscara, a máscara recorta um feedback que já respondia ao LFO).
- O padrão ÁTOMO (`shaders/ATOMO.md`) já é o começo disso para imagem; estenda a mesma ideia para o MOVIMENTO
  (moduladores) e para a interação entre átomos.

## Nomenclatura: adote a que já existe
Não invente nomes quando a área já tem um. Monte um **glossário** (termo, definição de uma linha, de onde vem, nome
na tela em português) e use-o no código, no dash e nos docs (`GLOSS` do `docs/index.html`).
- Fontes de termos: síntese e modular (oscilador, **LFO**, **envelope** / ADSR / AD, gate, trigger, clock,
  divisor de clock, sample & hold, slew, quantizador, sequenciador, VCA, attenuverter, CV), DAWs (modulação: fonte →
  destino, quantidade/profundidade, macro, sidechain, follow action), VJ/compositing (layer, blend, matte, key).
- **Defina "envelope" de uma vez** e encaixe o LFO nessa definição. Proposta a avaliar: tudo que mexe um knob é um
  **modulador**; um modulador desenha uma **forma** no tempo; o **envelope** é a forma disparada por um evento
  (trigger: batida, kick, onset, gesto), que roda uma vez; o **LFO** é a mesma forma em loop, presa ao clock da
  música. Sintes modernos já fazem isso: o LFO do Vital/Serum tem modo envelope (dispara e para). Se essa unificação
  vale, um primitivo só (forma + modo: loop | disparo | sync) pode cobrir LFO, envelope e sequência. Decida com base
  na pesquisa e diga onde a unificação quebra.
- Mapeie o que já existe para os termos novos: `mod`/♪, `lfo`, `kick`, macros `m1..m4`, `lo`/`hi` (= faixa ou
  quantidade?), faixas do espectro, `build`, `u_beat`/`u_bar`.

## Regras desta tarefa (valem do começo ao fim)
- **Tudo em segundo plano, NADA aparece na tela.**
  - Native: sempre `PRISMA_HIDDEN=1 PRISMA_NO_BROWSER=1`, em segundo plano, com backup/restauro do `src/tuning.py`.
    Se a porta 8765 estiver ocupada, é o MEU prisma aberto: não abra outro, espere liberar.
  - Navegador só headless (o Brave em `/usr/bin/brave-browser` serve; Playwright num venv do scratchpad com
    `executable_path`), perfil isolado. Prints só de páginas headless e de `/frame`.
  - Nunca `pkill -f` com algo do próprio comando; use o PID. Nada de computer-use nem captura da área de trabalho.
- **Teste como gente, não como robô**: aperte, espere ~0.5 s, aí arraste. O SSE (20 Hz) troca os objetos do estado
  no meio; um bug assim (caixa voltando pro lugar) só aparecia segurando antes de mover.
- **Pesquise a fundo**: use a skill de pesquisa profunda (deep-research) ou buscas em modo extended, várias em
  paralelo, lendo as fontes primárias (palestras da GDC, manuais do Vital/Bitwig/Elektron/Eurorack, artigos de
  MIR). A pesquisa é a base do plano, não um enfeite: cite as fontes e diga o que cada uma muda nas decisões.

## O que já existe (não reaprenda; confira no código)
- **Átomo** (`shaders/presets/atomos/`, padrão em `shaders/ATOMO.md`, conferido por `dash_data.atom_problems`): um
  verbo; até 3 knobs 0..1 (o 1º = PRINCIPAL, o botão grande da peça); **não lê o som** (som entra por modulador no
  knob); pode ler o relógio da música `u_beat`/`u_bar` (fase 0..1). Alfa = cobertura. Máscara = `// cat: mascara`
  (Assunto, Fundo, Brilho, Cor, Rosto, Olhos, Corpo, Mãos, Objeto; os de IA vêm de `src/rastreio.py`).
- **Caixa** (v5): fonte → átomos em cadeia → máscara → SAÍDA. Modificador paralelo (`post`), entrada B (`ins`), ramo
  (`file: '@id'`).
- **Knob modulado** = `item['mod'][knob] = {b: [fontes], lo, hi, lfo?}` → `native_synth._mod_value`: anda de `lo`
  a `hi` pela fonte mais forte. Fontes (`dash_server.MOD_SOURCES`): 8 faixas do espectro + `kick`, macros `m1..m4`,
  imagem `luz`/`mov`, `lfo` (`dash_data.lfo`: forma sin/tri/saw/sq/rnd, `r` = batidas por ciclo, `ph`; fase de
  `ritmo.Tempo.pos`). Knobs/opacidades deslizam por `_smooth` (`PARAM_SMOOTH_MS`); som e kick não.
- **Música** (`src/ritmo.py`): BPM por fluxo espectral + autocorrelação, PLL de fase, TAP; tom (Krumhansl) →
  `key_rgb`; `build` (subida) no estado. Troca de cena quantizada (`SCENE_QUANT`: batida/compasso), transição em
  batidas (`TRANS_BEATS`), PRÓXIMA + GO.
- **Palco**: estrela publica um knob no Show (`pub`); Controles = publicados; MIDI learn + soft takeover; macros
  M1–M4 (um fader mexe vários knobs, cada um na sua faixa).
- **Como se configura hoje** (`dash5.html`: `knobCell`, `modEditor`, `applyModulator`): botão ♪ ao lado de cada knob
  abre uma caixa com LFO (forma, ciclo, fase), chips de som, imagem e macro; faixa lo→hi arrastando as pontas no
  knob; moduladores da biblioteca podem ser soltos num knob. Funciona, mas é um painel de opções por knob — não é
  um sistema.

## Perguntas que o plano tem que responder
1. **Contrato e vocabulário**: quais são as regras do ambiente e as poucas palavras do glossário que as descrevem
   (ex.: fonte → forma → destino → quantidade)? Um modulador é peça no canvas, propriedade do knob, ou os dois? Como
   ver de relance o que mexe o quê?
2. **Tempo musical de primeira classe**: o que falta além do LFO? Ex.: envelope disparado na batida/kick/onset
   (ataque/queda em batidas), sequência por passo dentro do compasso (o "p-lock" do Elektron), probabilidade/condição
   (a cada 2 compassos, só no 1), seguir a FRASE (intro/build/drop/break: detecção de seção ou marcação ao vivo),
   ducking tipo sidechain (o kick abaixa algo), quantizar QUALQUER ação (ligar átomo, trocar máscara) e não só a cena.
3. **Configuração simples**: o que aparece por padrão e o que só sob pedido? Presets de movimento ("pulsa na
   batida", "respira por compasso", "estoura no drop") aplicáveis com um gesto? O átomo pode SUGERIR o seu movimento
   padrão no cabeçalho do `.frag` (ex.: `// mod: forca=kick`)?
4. **Interação entre átomos**: além de cadeia/paralelo/máscara/entrada B, eles precisam conversar (um átomo dirigir
   o knob de outro, um rastreio virar modulador: `rosto.x`, `mão.y`)? Até onde vai sem virar espaguete?
5. **Palco**: o que o músico/VJ toca ao vivo (poucos controles grandes, macros, MIDI) e o que fica travado; o que
   acontece quando o BPM some ou erra (fallback, TAP, segurar a fase).
6. **Compatibilidade**: cenas e `tuning.py` atuais abrem sem perder nada; o padrão ÁTOMO muda o mínimo.

## Pesquise antes de desenhar (e diga o que copiar e o que evitar)
Design sistêmico e emergência: GDC 2017 "Breaking Conventions with The Legend of Zelda: Breath of the Wild" (o
chemistry engine), a palestra de GDC sobre a física de pixels do Noita, immersive sims (Harvey Smith, "systemic
design"), autômatos celulares. Modular: o padrão Eurorack (faixas de CV, gate × trigger, clock), VCV Rack.
Ableton Live (Racks, macros, Max for Live LFO/Shaper/Envelope Follower), Bitwig (modulators em qualquer parâmetro),
Elektron (parameter locks, trig conditions, LFO por faixa), Resolume (BPM sync, envelopes, dashboard), TouchDesigner
(CHOPs de beat, Audio Analysis), Synesthesia, VDMX, Notch, MadMapper; DJs: beatgrid e análise de frase do rekordbox
/Serato; MIR: detecção de onset/downbeat/estrutura (madmom, beat_this, All-In-One) e o que roda em tempo real na CPU.

## Como trabalhar
1. **Pesquisa → documento de design curto** (Claude Doc): o contrato do ambiente (as regras gerais), o glossário,
   as interações emergentes que saem dele, como cada tela muda, um exemplo de show do começo ao fim (música real: intro → build → drop), e o que sai do jeito atual.
   Traga **2–3 decisões estruturais pra eu aprovar ANTES de codar**.
2. Depois do ok: **motor** só no necessário (com teste no `--selfcheck` e no native de verdade), **dash5** (lógica
   provada reaproveitada, minimalismo: knob principal visível, detalhes só ao abrir), `shaders/ATOMO.md`.
3. **Testes**: todos os do `CLAUDE.md` + native oculto com webcam + headless (prints e arrastos com espera).
4. Atualize `CLAUDE.md`, `BACKLOG.md` e o comentário de decisões no topo do `dash5.html`.

## Entrega final
Explicação em português, simples: as regras do ambiente e o glossário, exemplos de interação que ninguém programou
e funcionam, como configurar um knob em 1–2 gestos, como os átomos interagem,
como tudo fica no tempo da música, o fluxo ao vivo e o de "deu pepino" (BPM errado, sem som), e o que ficou pra
depois — citando as referências pesquisadas.
