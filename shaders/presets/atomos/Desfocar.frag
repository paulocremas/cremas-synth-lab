// fx: tamanho=0.3
// cat: textura
// ATOMOS · Desfocar. Embaça. tamanho = raio do borrão (16 amostras em espiral).
#ifdef GL_ES
precision mediump float;
#endif

uniform vec2 u_resolution;
uniform sampler2D u_texture_0;   // A: a corrente
uniform float u_fx_tamanho;

void main() {
    vec2 st = gl_FragCoord.xy / u_resolution;
    st.y = 1.0 - st.y;
    float r = u_fx_tamanho * 0.03;
    vec3 acc = vec3(0.0);
    for (int i = 0; i < 16; i++) {
        float k = float(i) + 0.5, a = k * 2.39996;
        acc += texture2D(u_texture_0, st + vec2(cos(a), sin(a)) * r * sqrt(k / 16.0)).rgb;
    }
    gl_FragColor = vec4(acc / 16.0, 1.0);
}
