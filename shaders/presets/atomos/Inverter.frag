// cat: luz
// ATOMOS · Inverter. Negativo: claro vira escuro e cada cor vira a oposta. Meio-termo = a opacidade da peça.
#ifdef GL_ES
precision mediump float;
#endif

uniform vec2 u_resolution;
uniform sampler2D u_texture_0;   // A: a corrente

void main() {
    vec2 st = gl_FragCoord.xy / u_resolution;
    st.y = 1.0 - st.y;
    gl_FragColor = vec4(1.0 - texture2D(u_texture_0, st).rgb, 1.0);
}
