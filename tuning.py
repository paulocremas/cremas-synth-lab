"""Constantes de calibracao do native_synth.py.

Editar e salvar este arquivo aplica NA HORA, sem reiniciar o programa — o audio_thread
fica de olho no mtime e recarrega sozinho (mesmo esquema de hot-reload do image.frag,
so que pro lado Python em vez do shader).
"""

# limiares de frequencia do bass/mid/treble classico (tambem definem a cor azul/ciano/
# magenta no monitor)
BASS_MID_HZ = 150
MID_TREBLE_HZ = 4000

# range (Hz) [lo, hi] de cada uma das 8 faixas de mixagem finas (Sub-bass..Air) que controlam
# u_subbass..u_air. Editado pela secao "Ranges das faixas" no dash de audio.
# HZ_OVERLAP: 0 = crossover (faixas contiguas — mexer num limite move o vizinho, nao ha
# sobreposicao); 1 = livre (cada faixa tem seu lo/hi; podem se sobrepor ou deixar buraco).
# BANDS_ENABLED: 0 desliga as 8 faixas (u_subbass..u_air ficam 0 no shader; o dash continua
# mostrando os numeros crus, so nao alimenta mais o shader) — pro checkbox "ativar" no dash.
HZ_OVERLAP = 0
BANDS_ENABLED = 1

# OUT_ANALYSIS_ENABLED: liga a leitura da imagem sintetizada (pos-shader) pros mesmos
# medidores do Source Image (cor dominante, brilho, grids, histogramas), ~5x/s — tab
# "Output Image" no dash. Desliga por padrao: e' leitura de GPU (glReadPixels), custa
# CPU/GPU a mais mesmo raro; liga so quando for de fato calibrar/usar essa aba.
OUT_ANALYSIS_ENABLED = 1
FREQ_BAND_HZ = [
    [21, 88],  # Sub-bass
    [88, 342],  # Low-mid
    [342, 1313],  # Midrange
    [1313, 3130],  # High-mid
    [3130, 4815],  # Presence
    [4815, 7684],  # Treble
    [7684, 11233],  # Brilliance
    [11233, 20000],  # Air
]

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
SMOOTHING = 0.87

# as 8 bandas finas (Sub-bass..Air) NAO usam o SMOOTHING acima — cada uma usa um valor
# de RELEASE interpolado entre esses dois extremos, conforme a posicao dela (grave->agudo)
# na lista FREQ_BANDS: grave decai rapido (RELEASE baixo, pega a proxima batida rapido),
# agudo fica estavel (RELEASE alto, menos tremido/ruidoso). Sub-bass usa SMOOTHING_MIN,
# Air usa SMOOTHING_MAX, as do meio interpolam linear entre os dois.
SMOOTHING_MIN = 0.95   # banda mais grave (Sub-bass)
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
KICK_THRESHOLD = 2.6      # grave cru precisa passar X vezes a media recente pra contar como batida

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
KICK_DECAY_MIN = 0.54        # decay mais rapido permitido (musica muito rapida)
KICK_DECAY_MAX = 0.95       # decay mais lento permitido (batida isolada, tempo espacado)

# canais por INSTRUMENTO (lista de tamanho livre, ate 8 — adiciona/remove pelo dash, aba
# Audio -> Canais) — paralelo as 8 faixas de frequencia acima, nao substitui: e outro jeito de
# alimentar o shader, por stem em vez de por Hz. Cada entrada: {"name", "src", "output"}.
# "src" vazio = canal ocioso (sem parec); com o nome de uma source do PulseAudio, ganha parec
# proprio (native_synth.channel_thread). "output" vazio = canal so aparece no array
# u_chan/u_chan_hit do shader; com o nome de uma variavel existente (kick, amp, bass, mid,
# treble, subbass, lowmid, midrange, highmid, presence, treble_hi, brilho, air) o canal
# SUBSTITUI o valor calculado por ela ENQUANTO tiver "src" bound — sem src, a variavel
# original (FFT do mix principal) continua normal, sem fallback implicito por nome.
CHANNELS = [
]
