// fx: forca=0.3, tamanho=0.2
// cat: textura
// ATOMOS · Grão. Ruído de filme que muda a cada quadro. forca = quanto; tamanho = grão fino (0) a grosso (1).
#ifdef GL_ES
precision mediump float;
#endif

uniform vec2 u_resolution;
uniform sampler2D u_texture_0;   // A: a corrente
uniform float u_time;
uniform float u_fx_forca, u_fx_tamanho;

float h(vec2 p) { return fract(sin(dot(p, vec2(12.9898, 78.233))) * 43758.5453); }

void main() {
    vec2 st = gl_FragCoord.xy / u_resolution;
    st.y = 1.0 - st.y;
    vec2 cell = floor(gl_FragCoord.xy / (1.0 + u_fx_tamanho * 7.0));
    float n = h(cell + floor(u_time * 24.0) * 17.0) - 0.5;
    gl_FragColor = vec4(clamp(texture2D(u_texture_0, st).rgb + n * u_fx_forca, 0.0, 1.0), 1.0);
}
