"""Constantes de calibracao do native_synth.py.

Editar e salvar este arquivo aplica NA HORA, sem reiniciar o programa — o audio_thread
fica de olho no mtime e recarrega sozinho (mesmo esquema de hot-reload do image.frag,
so que pro lado Python em vez do shader).
"""

# limiares de frequencia do bass/mid/treble classico (tambem definem a cor azul/ciano/
# magenta no monitor)
BASS_MID_HZ = 150
MID_TREBLE_HZ = 4000

# ponytail: escalas calibradas ouvindo musica real nessa maquina (saida Bluetooth) —
# cada banda tem energia natural bem diferente (grave sempre mais forte que agudo).
# se ficar sempre 0 ou sempre grudado em 1, ajusta esses numeros pro seu volume/fonte.
BASS_SCALE = 0.15
MID_SCALE = 6.0
TREBLE_SCALE = 30.0

# cada chunk e ~23ms — cru, os valores tremem muito frame a frame. suaviza tipo um
# envelope (attack/release): perto de 1.0 = mais suave/lento, perto de 0 = segue cru.
# SMOOTHING = valor global, usado por amp/bass/mid/treble classico e pelo espectrograma
# (nao sao uma banda especifica, entao nao tem "posicao" pra interpolar).
SMOOTHING = 0.9

# as 8 bandas finas (Sub-bass..Air) NAO usam o SMOOTHING acima — cada uma usa um valor
# de RELEASE interpolado entre esses dois extremos, conforme a posicao dela (grave->agudo)
# na lista FREQ_BANDS: grave decai rapido (RELEASE baixo, pega a proxima batida rapido),
# agudo fica estavel (RELEASE alto, menos tremido/ruidoso). Sub-bass usa SMOOTHING_MIN,
# Air usa SMOOTHING_MAX, as do meio interpolam linear entre os dois.
SMOOTHING_MIN = 0.7   # banda mais grave (Sub-bass)
SMOOTHING_MAX = 0.95  # banda mais aguda (Air)

# attack/release assimetrico: o RELEASE (subida acima, por banda, ou SMOOTHING global pra
# amp/bass/mid/treble) so vale quando o valor esta DESCENDO. Quando esta SUBINDO (pico
# novo chegando), usa um smoothing mais baixo — reage mais rapido — igual a
# release*ATTACK_RATIO. Por isso o numero na tela muda sozinho: alterna entre attack e
# release conforme o som sobe/desce, nao fica travado num valor fixo por banda.
ATTACK_RATIO = 0.4

# auto-gain por banda: cada uma das 8 bandas finas tem seu proprio "teto recente" — sobe
# na hora quando aparece um pico novo, decai devagar por esse fator a cada chunk (~23ms).
# o nivel de cada banda e relativo a ESSE teto (nao ao pico entre as 8 bandas), pra uma
# banda estruturalmente mais forte (ex. Sub-bass) nao ficar travada perto de 1.0 so por
# ser mais alta que as outras. mais perto de 1.0 = teto desce mais devagar (memoria mais
# longa); mais baixo = esquece rapido, fica mais sensivel a picos recentes.
PEAK_DECAY = 0.999

# deteccao de batida (onset) no grave: acompanha uma media lenta do grave (baseline) e,
# quando o valor CRU pula bem acima dessa media, dispara um "envelope de percussao" —
# sobe pra 1.0 na hora (ataque instantaneo, nao tem o que suavizar aqui) e decai sozinho.
KICK_DECAY = 0.8          # usado so ANTES da primeira batida (sem intervalo medido ainda)
KICK_THRESHOLD = 1.5      # grave cru precisa passar X vezes a media recente pra contar como batida

# aquecimento: kick_baseline comeca em 0.0 e demora uns chunks pra representar o "chao" de
# verdade da musica — antes disso, qualquer som ja passa de "0 x THRESHOLD" e dispara falso
# positivo. Por ~20 chunks (~460ms) no INICIO do programa (so uma vez, nao repete a cada
# batida) o detector fica desligado, so acumulando baseline; depois disso liga e fica
# estavel. Custo: perde a bem primeira batida da musica, nunca mais depois.
KICK_WARMUP_CHUNKS = 20

# decay adaptativo ao ritmo: em vez de KICK_DECAY fixo pra sempre, mede o intervalo entre
# as ultimas 2 batidas detectadas e recalcula o decay pra caber nesse intervalo — musica
# rapida decai rapido (nao borra na proxima batida), lenta decai devagar (o pulso "dura"
# mais). Os limites abaixo protegem contra tempos extremos.
KICK_FADE_FLOOR = 0.05      # "considerado apagado" quando o envelope cai abaixo disso
KICK_DECAY_FRACTION = 0.7   # decai ate o FADE_FLOOR em X% do intervalo entre batidas
KICK_DECAY_MIN = 0.5        # decay mais rapido permitido (musica muito rapida)
KICK_DECAY_MAX = 0.95       # decay mais lento permitido (batida isolada, tempo espacado)
