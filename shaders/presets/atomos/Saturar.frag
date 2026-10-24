// fx: saturacao=0.8
// cat: cor
// ATOMOS · Saturar. Mais ou menos cor. saturacao = 0 cinza, 0.5 igual, 1 o dobro.
#ifdef GL_ES
precision mediump float;
#endif

uniform vec2 u_resolution;
uniform sampler2D u_texture_0;   // A: a corrente
uniform float u_fx_saturacao;

void main() {
    vec2 st = gl_FragCoord.xy / u_resolution;
    st.y = 1.0 - st.y;
    vec3 c = texture2D(u_texture_0, st).rgb;
    float l = dot(c, vec3(0.299, 0.587, 0.114));
    gl_FragColor = vec4(clamp(mix(vec3(l), c, u_fx_saturacao * 2.0), 0.0, 1.0), 1.0);
}
