// fx: modo=0
// cat: geometria
// ATOMOS · Espelhar. Dobra a imagem no meio. modo = esquerda→direita (0), cima→baixo (0.5), os quatro cantos (1).
#ifdef GL_ES
precision mediump float;
#endif

uniform vec2 u_resolution;
uniform sampler2D u_texture_0;   // A: a corrente
uniform float u_fx_modo;

void main() {
    vec2 st = gl_FragCoord.xy / u_resolution;
    st.y = 1.0 - st.y;
    float m = floor(u_fx_modo * 2.999);
    vec2 p = st;
    if (m != 1.0) p.x = 0.5 - abs(p.x - 0.5);
    if (m != 0.0) p.y = 0.5 - abs(p.y - 0.5);
    gl_FragColor = vec4(texture2D(u_texture_0, p).rgb, 1.0);
}
