#ifdef GL_ES
precision mediump float;
#endif

uniform vec2 u_resolution;
uniform float u_time;
uniform sampler2D u_texture_0;
uniform float u_amp;    // 0..1, volume médio geral (todas as frequências somadas)
uniform float u_bass;   // 0..1, energia abaixo de 150Hz (grave/kick)
uniform float u_mid;    // 0..1, energia entre 150Hz e 4kHz (voz/melodia)
uniform float u_treble; // 0..1, energia acima de 4kHz (hi-hat/agudo)
uniform float u_kick;   // 0..1, NÃO é nível — é batida: pula pra 1.0 na hora do grave forte e decai sozinho
uniform vec3 u_dominant; // cor RGB (0..1 cada) mais frequente do frame atual, calculada no Python

// faixas finas de mixagem/EQ (0..1, relativo ao pico ENTRE ELAS — sempre alguma bate 1.0)
uniform float u_subbass;
uniform float u_lowmid;
uniform float u_midrange;
uniform float u_highmid;
uniform float u_presence;
uniform float u_treble_hi;
uniform float u_brilho;
uniform float u_air;

// canais por INSTRUMENTO (lista de tamanho livre no dash, ate 8 — aba Audio -> Canais) —
// paralelo as faixas acima, nao as substitui. Cada canal pode ter uma "saida" escolhida no
// dash que SUBSTITUI uma das variaveis acima (u_kick, u_amp, u_subbass...) por essa cima
// enquanto tiver stem ligado — nesse caso o array abaixo e so mais um jeito de ver o mesmo
// numero. Slot sem canal configurado fica 0.
uniform float u_chan[8];      // nivel 0..1 por canal
uniform float u_chan_hit[8];  // onset 0..1 por canal (so quem tem stem ligado dispara)

// ruído branco pontual — equivale a WhiteNoise do SC: hash de uma posição -> 0..1
float random(vec2 p) {
    return fract(sin(dot(p, vec2(12.9898, 78.233))) * 43758.5453);
}

void main() {
    vec2 st = gl_FragCoord.xy / u_resolution;
    st.y = 1.0 - st.y;
    vec2 st0 = st; // UV congelada ANTES de qualquer efeito — a imagem "seca" pro EFEITO 8

    // ===== EFEITO 1: ONDA — distorce a coordenada de leitura (imagem "derrete"/ondula) =====
    float wave_amount = 0.03 * u_subbass * u_kick; // <- edita aqui. 0 = desligado. testa 0.01 a 0.05
    st.x += sin(st.y * 0.05 + u_time * 0.1) * wave_amount * 0.5;
    // st.y += sin(st.x * 0.10 + u_time * 2.5) * wave_amount * 0.5;

    // ===== EFEITO 7: FLOW EMITTER — um ponto "emite" e empurra a leitura da UV pra fora =====
    // stateless (sem buffer de partículas): pulsos concêntricos + ruído = fluxo saindo do emissor
    vec2 em = vec2(0.5, 0.5);                      // <- edita aqui: posição do emissor (0..1 na tela)
    vec2 ev = st - em;
    float er = length(ev) + 1e-4;
    float flow_amt = (0.003 * 10.0 * u_kick) + 0.02 * u_subbass;         // <- edita aqui. 0 = desligado
    float turb = 0.5 + random(floor(st * 60.0 + u_time));           // campo de ruído = turbulência
    float pulse = fract(er * 4.0 - u_time * (0.3 + u_kick));       // anéis saindo do emissor
    st += (ev / er) * flow_amt * turb * pulse;

    // ===== EFEITO 2: RGB SPLIT — lê cada canal com um deslocamento diferente (fantasmas coloridos) =====
    // 'split' = distância entre os fantasmas; abre no kick
    float split = 0.02 * u_subbass * u_kick;         // <- edita aqui. 0 = desligado. testa 0.002 a 0.03
    float r = texture2D(u_texture_0, st + vec2(split, 0.0)).r;
    float g = texture2D(u_texture_0, st).g;
    float b = texture2D(u_texture_0, st - vec2(split, 0.0)).b;
    vec3 col = vec3(r, g, b);

    // ===== EFEITO 9: CANAIS — canal 0 da um flash no hit; 1..3 somam um tint sutil =====
    // so acende se voce criar canais no dash (aba Audio -> Canais) — lista comeca vazia.
    // se o canal 0 tiver "saida" = kick, o flash aqui e o MESMO numero que move u_kick acima
    col += vec3(u_chan[1], u_chan[2], u_chan[3]) * 0.05;  // <- edita aqui. 0 = desligado
    col *= 1.0 + 0.15 * u_chan_hit[0];                    // <- edita aqui. 0 = desligado

    // ===== EFEITO 3: SCANLINES — oscilador NO ESPAÇO (sin de st.y): linhas horizontais =====
    // freq = quantas linhas cabem na tela; amplitude sobe com o mid
    float scan_freq = 20.0;                       // <- edita aqui (nº de linhas)
    float scan_amt  = 0.15 * u_mid;                // <- edita aqui. 0 = desligado
    col *= 1.0 - scan_amt * (0.5 + 0.5 * sin(st.y * scan_freq * 6.2831));

    // ===== EFEITO 4: GRÃO — ruído branco somado por pixel, pisca com o agudo =====
    float grain_amt = 0.06 + 0.015 * u_treble;      // <- edita aqui. 0 = desligado
    col += (random(gl_FragCoord.xy + u_time) - 0.5) * grain_amt;

    // ===== EFEITO 5: VINHETA — filtro espacial radial: escurece quanto mais longe do centro =====
    float vig = 1.4;                               // <- edita aqui. 0 = desligado, 1 = borda preta
    vec2 d = st - 20.5;
    col *= 0.1 - vig * dot(d, d) * 2.0;

    // ===== EFEITO 6: GRAYSCALE — colapsa RGB num só valor (luminância perceptual, Rec. 601) =====
    float gray = dot(col, vec3(0.299 * u_treble, 0.587, 0.114 * u_subbass)); // <- edita aqui. 0 = desligado, 1 = P&B total
    float gray_mix = -15.0 * u_highmid;                          // <- edita aqui. 0 = colorido, 1 = P&B total
    col = mix(col, vec3(gray), gray_mix);

    // ===== EFEITO 8: OPACIDADE DA CAMADA — funde a pilha de efeitos com a imagem crua =====
    vec3 orig = texture2D(u_texture_0, st0).rgb;
    float layer = 0.6;    // <- edita aqui. 0 = só original de fundo, 1 = só efeito, 0.5 = meio a meio
    col = mix(orig, col, layer);

    gl_FragColor = vec4(col, 1.0);
}
