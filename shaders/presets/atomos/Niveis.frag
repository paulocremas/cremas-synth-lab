// fx: quantos=0.25
// cat: luz
// ATOMOS · Níveis. Poucos tons, como serigrafia (posterizar). quantos = de 2 (0) a 16 (1) tons por cor.
#ifdef GL_ES
precision mediump float;
#endif

uniform vec2 u_resolution;
uniform sampler2D u_texture_0;   // A: a corrente
uniform float u_fx_quantos;

void main() {
    vec2 st = gl_FragCoord.xy / u_resolution;
    st.y = 1.0 - st.y;
    float n = floor(2.0 + u_fx_quantos * 14.0);
    gl_FragColor = vec4(floor(texture2D(u_texture_0, st).rgb * n + 0.5) / n, 1.0);
}
