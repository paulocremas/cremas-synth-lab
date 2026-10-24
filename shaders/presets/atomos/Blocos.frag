// fx: tamanho=0.3
// cat: geometria
// ATOMOS · Blocos. Blocos grandes. tamanho = de 2 px (0) a 1/8 da tela (1).
#ifdef GL_ES
precision mediump float;
#endif

uniform vec2 u_resolution;
uniform sampler2D u_texture_0;   // A: a corrente
uniform float u_fx_tamanho;

void main() {
    vec2 st = gl_FragCoord.xy / u_resolution;
    st.y = 1.0 - st.y;
    vec2 b = mix(2.0, u_resolution.x / 8.0, u_fx_tamanho * u_fx_tamanho) / u_resolution;
    gl_FragColor = vec4(texture2D(u_texture_0, (floor(st / b) + 0.5) * b).rgb, 1.0);
}
