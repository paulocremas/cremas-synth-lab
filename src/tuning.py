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
# SMOOTHING/ATTACK_RATIO = globais — usados so por bass/mid/treble classico e pelo
# espectrograma (nao sao uma banda especifica). O amp e as 8 faixas finas tem os seus
# proprios, logo abaixo (popup "engrenagem" de cada um no dash).
SMOOTHING = 0.87

# attack/release assimetrico: o RELEASE (os valores abaixo) so vale quando o sinal esta
# DESCENDO. SUBINDO, usa release*ATTACK_RATIO (reage mais rapido). Por isso o "smooth" na
# tela oscila sozinho: alterna entre attack e release conforme o som sobe/desce.
ATTACK_RATIO = 0.4

# --- dinamica POR FAIXA de mixagem (as 8 finas Sub-bass..Air, na ordem de FREQ_BAND_HZ) ---
# antes era um ramp interpolado entre dois extremos (SMOOTHING_MIN..MAX) + os globais acima;
# agora cada faixa tem o SEU release/attack/auto-gain, editado pelo popup da faixa no dash
# (POST /tweaks reescreve estas 3 listas). Sempre 8 valores cada; o range Hz da faixa fica
# em FREQ_BAND_HZ. Ver SMOOTHING / ATTACK_RATIO / PEAK_DECAY para o que cada um significa.
BAND_SMOOTHING  = [0.95, 0.95, 0.95, 0.95, 0.95, 0.95, 0.95, 0.95]  # RELEASE por faixa
BAND_ATTACK     = [0.4, 0.4, 0.4, 0.4, 0.4, 0.4, 0.4, 0.4]          # fator attack/release por faixa
BAND_PEAK_DECAY = [0.999, 0.999, 0.999, 0.999, 0.999, 0.999, 0.999, 0.999]  # memoria do teto por faixa

# --- amp (RMS do sinal inteiro) — knobs proprios (popup "engrenagem" no cabecalho AMP) ---
# comecam iguais aos globais. amp_final = min(1, RMS * AMP_SCALE), depois attack/release
# com AMP_SMOOTHING / AMP_ATTACK_RATIO no lugar de SMOOTHING / ATTACK_RATIO.
AMP_SCALE = 4.0            # sobe se o amp vive baixo, desce se estoura (gruda em 1.0)
AMP_SMOOTHING = 0.87
AMP_ATTACK_RATIO = 0.4

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
KICK_DECAY = 0.9          # usado so ANTES da primeira batida (sem intervalo medido ainda)
KICK_THRESHOLD = 2.1      # grave cru precisa passar X vezes a media recente pra contar como batida

# aquecimento: kick_baseline comeca em 0.0 e demora uns chunks pra representar o "chao" de
# verdade da musica — antes disso, qualquer som ja passa de "0 x THRESHOLD" e dispara falso
# positivo. Por ~20 chunks (~460ms) no INICIO do programa (so uma vez, nao repete a cada
# batida) o detector fica desligado, so acumulando baseline; depois disso liga e fica
# estavel. Custo: perde a bem primeira batida da musica, nunca mais depois.
KICK_WARMUP_CHUNKS = 38

# decay adaptativo ao ritmo: em vez de KICK_DECAY fixo pra sempre, mede o intervalo entre
# as ultimas 2 batidas detectadas e recalcula o decay pra caber nesse intervalo — musica
# rapida decai rapido (nao borra na proxima batida), lenta decai devagar (o pulso "dura"
# mais). Os limites abaixo protegem contra tempos extremos.
KICK_FADE_FLOOR = 0.17      # "considerado apagado" quando o envelope cai abaixo disso
KICK_DECAY_FRACTION = 0.6   # decai ate o FADE_FLOOR em X% do intervalo entre batidas
KICK_DECAY_MIN = 0.54        # decay mais rapido permitido (musica muito rapida)
KICK_DECAY_MAX = 0.95       # decay mais lento permitido (batida isolada, tempo espacado)

# shader ativo (aba "Visuals" do dash). Caminho relativo a shaders/: "image.frag" (base) ou
# "presets/<set>/<nome>.frag". Trocar aqui e salvar aplica na hora — o main loop ve o
# mtime/caminho e recompila, sem restart.
SHADER = "presets/default/Silhueta.frag"

# SETS de shader = subpastas em shaders/presets/, incluindo presets/default/. "default" e' so o
# fallback: sempre existe, nao some (apagar pelo dash = esvaziar a pasta). SHADER_SET escolhe
# qual set a galeria da aba Visuals mostra e de qual set valem os atalhos (SHADER_KEYS[SHADER_SET]).
SHADER_SET = "default"

# atalho de teclado -> shader, POR SET: {set: {caminho_do_shader: tecla}}. So valem os do
# SHADER_SET ativo. Apertar a tecla na janela do native_synth OU em qualquer lugar do dash
# troca pro shader. Vinculado pela engrenagem de cada preset (POST /shader-key).
SHADER_KEYS = {
    "default": {
        "image.frag": "1"
    }
}

# nivel 0..1 de cada efeito nomeado no cabecalho "// fx:" do shader ativo — a aba "Efeitos" do
# dash tem um potenciometro por efeito e grava aqui. Efeito ausente deste dict = 1.0 (cheio).
# O shader multiplica a intensidade de cada efeito por u_fx_<nome>. Ponto unico onde um
# midi_thread futuro escreveria (state['fx']) pra um pot fisico mexer no efeito.
FX = {
    "tint": 1.0,
    "wave": 1.0,
    "flow": 1.0,
    "rgbsplit": 1.0,
    "channels": 1.0,
    "scanlines": 1.0,
    "grain": 1.0,
    "vignette": 1.0,
    "grayscale": 1.0,
    "layer": 1.0,
    "liquid": 0.0,
    "colorvibe": 0.0,
    "particles": 0.0,
    "smoke": 1.0,
    "aura": 0.0,
    "pulse": 0.0,
}

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

# galeria de midia (aba "Visuals" do dash) — imagens e videos locais que viram o INPUT de
# imagem, no lugar da webcam/tela. Video roda em loop. Arquivos em media/ (na raiz do repo).
# Cada entrada: {"name", "file", "kind": "image"|"video", "fit": "fill"|"fit", "transition"}.
#   name = id unico DENTRO do set (e o rotulo).
#   file = caminho relativo a media/, sempre "<set>/x.png" (inclusive "default/x.png"). Os SETS
#          de midia sao subpastas em media/ (espelho de shaders/presets/<set>/), inclusive
#          media/default/; a lista de sets vem do disco, nao de um bloco aqui.
#   fit  = "fill" cobre o output cortando o excesso; "fit" encaixa inteiro com barras.
#   transition = como ENTRAR nessa midia: "" usa TRANSITION_DEFAULT, "none" = corte seco,
#                "<arquivo>.glsl" = um arquivo de transitions/ (galeria "Transições" no dash).
# Selecionar (clicar / dropdown "Media" / tecla de MEDIA_KEYS) faz native_synth respawnar o
# ffmpeg apontando pro arquivo. Gravado pelo dash (POST /media, /media-add, /media-del).
MEDIA = [
    {"name": "paulocremas-og-image", "file": "teste/paulocremas-og-image.png", "kind": "image", "fit": "fill", "transition": ""},
    {"name": "2026-08-27_20-07", "file": "default/2026-08-27_20-07.png", "kind": "image", "fit": "fill", "transition": "dip_black.glsl"},
    {"name": "2026-09-0309-42-09", "file": "default/2026-09-0309-42-09.mp4", "kind": "video", "fit": "fill", "transition": "wipe.glsl"},
    {"name": "2026-09-0909-55-45", "file": "default/2026-09-0909-55-45.mp4", "kind": "video", "fit": "fill", "transition": "crossfade.glsl"},
    {"name": "YTDowncom_YouTube_Animals-On-Trampolines-Compilation_Media_Yp40RfTWRAs_001_1080p", "file": "default/YTDowncom_YouTube_Animals-On-Trampolines-Compilation_Media_Yp40RfTWRAs_001_1080p.mp4", "kind": "video", "fit": "fill", "transition": ""},
]

# TRANSIÇÕES de mídia — galeria "Transições" na aba Visuals, espelho da galeria de shader mas
# com arquivos transitions/*.glsl (estilo gl-transitions: uma func `vec4 transition(vec2 uv)`
# usando getFromColor/getToColor/progress; cabeçalho "// ms: N" = duração). Ao trocar de
# mídia, native_synth roda esse .glsl num passe GPU (FBO) que mistura a imagem que sai com a
# que entra, e ALIMENTA o shader normal — o preset nem sabe. TRANSITION_DEFAULT = a usada
# quando o item tem "transition": "". "none" = corte seco. Gravado pelo dash.
TRANSITION_DEFAULT = "dip_black.glsl"

# set de midia ATIVO (a galeria mostra so ele; valem MEDIA_KEYS[MEDIA_SET]). A lista de sets
# de midia vem das subpastas de media/.
MEDIA_SET = "default"

# atalho de teclado -> midia, POR SET: {set: {name_da_midia: tecla}}. Mesma logica de
# SHADER_KEYS. Vinculado pela engrenagem de cada item (POST /media-key).
MEDIA_KEYS = {
    "default": {
        "2026-08-27_20-07": "8",
        "2026-09-0309-42-09": "9",
        "2026-09-0909-55-45": "7",
        "YTDowncom_YouTube_Animals-On-Trampolines-Compilation_Media_Yp40RfTWRAs_001_1080p": "0"
    }
}

# POOL de video quente: mantem um ffmpeg decodificando por VIDEO do set de midia ativo, cada
# um na sua thread (native_synth._pool_reader). Trocar entre eles e' custo ~0 (so aponta pro
# frame ja pronto) em vez de matar+subir ffmpeg (~200-400ms). Preco: N decodes h264
# simultaneos de CPU/RAM — 0 desliga (volta ao respawn por troca, com o handoff da opcao 1).
# VIDEO_POOL_MAX limita quantos entram (os com tecla no set ativo primeiro, depois ordem do
# MEDIA). Imagem parada nunca entra no pool (ja vem do _still_cache).
VIDEO_POOL = 1
VIDEO_POOL_MAX = 4
