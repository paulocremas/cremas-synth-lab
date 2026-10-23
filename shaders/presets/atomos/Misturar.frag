// fx: quanto=0.5, modo=0
// cat: mistura
// in: src
// ATOMOS · Misturar. Junta a entrada B na corrente (B = outra raia da mesa; sem B = a fonte crua).
// quanto = 0 so' a corrente … 1 so' B; modo = normal, soma, tela, multiplicar, diferenca (em degraus).
#ifdef GL_ES
precision mediump float;
#endif

uniform vec2 u_resolution;
uniform sampler2D u_texture_0;   // a corrente
uniform sampler2D u_texture_1;   // B
uniform float u_fx_quanto, u_fx_modo;

void main() {
    vec2 st = gl_FragCoord.xy / u_resolution;
    st.y = 1.0 - st.y;
    vec3 a = texture2D(u_texture_0, st).rgb, b = texture2D(u_texture_1, st).rgb;
    float m = floor(u_fx_modo * 4.999);
    vec3 c = m < 0.5 ? b : m < 1.5 ? min(a + b, 1.0) : m < 2.5 ? 1.0 - (1.0 - a) * (1.0 - b)
           : m < 3.5 ? a * b : abs(a - b);
    gl_FragColor = vec4(mix(a, c, u_fx_quanto), 1.0);
}
