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
uniform float u_subbass;  // 0-250Hz
uniform float u_lowmid;   // 250-500Hz
uniform float u_midrange; // 500Hz-2kHz
uniform float u_highmid;  // 2-4kHz
uniform float u_presence; // 4-6kHz
uniform float u_treble_hi; // 6-10kHz
uniform float u_brilho;   // 10-16kHz
uniform float u_air;      // acima de 16kHz

void main() {
    vec2 st = gl_FragCoord.xy / u_resolution;
    st.y = 1.0 - st.y;

    // ===== EFEITO 1: ONDA — distorce a coordenada de leitura (imagem "derrete"/ondula) =====
    float wave_amount = 0.3 * u_subbass * u_kick; // <- edita aqui. 0 = desligado. testa 0.01 a 0.05
    st.x += sin(st.y * 10. + u_time * 1.) * wave_amount * 0.5;
    // st.y += sin(st.x * 10.0 + u_time * 2.5) * wave_amount * 0.5;

    gl_FragColor = texture2D(u_texture_0, st);
}
