// fx: brilho=0.6, contraste=0.6
// cat: luz
// ATOMOS · Luz. Clareia/escurece e abre/fecha o contraste. brilho e contraste: 0.5 = igual.
#ifdef GL_ES
precision mediump float;
#endif

uniform vec2 u_resolution;
uniform sampler2D u_texture_0;   // A: a corrente
uniform float u_fx_brilho, u_fx_contraste;

void main() {
    vec2 st = gl_FragCoord.xy / u_resolution;
    st.y = 1.0 - st.y;
    vec3 c = texture2D(u_texture_0, st).rgb;
    c = (c - 0.5) * pow(4.0, u_fx_contraste * 2.0 - 1.0) + 0.5 + (u_fx_brilho - 0.5);
    gl_FragColor = vec4(clamp(c, 0.0, 1.0), 1.0);
}
