// fx: tamanho=0.5, borda=0.3, inverter=0
// cat: mascara
// ATOMOS · Mãos. Máscara das duas mãos de uma pessoa (IA BlazePose): um círculo em cada, que segue o gesto.
// tamanho = raio (a palma a um bom halo); borda = macia/dura; inverter = tudo menos as mãos. Precisa ver o corpo.

uniform vec3 u_corpo[33];        // x, y (uv topo->baixo), visibilidade; mao = pulso 15/16, mindinho 17/18, indicador 19/20
uniform float u_corpo_on;
uniform float u_fx_tamanho, u_fx_borda, u_fx_inverter;

float mao(vec2 p, vec3 pulso, vec3 mind, vec3 ind, float h) {
    vec2 c = (pulso.xy + mind.xy + ind.xy) / 3.0 * u_resolution;
    float r = length((ind.xy - pulso.xy) * u_resolution) * mix(0.8, 3.0, u_fx_tamanho) + 1.0;
    return (1.0 - smoothstep(1.0 - h, 1.0 + h, length(p - c) / r)) * step(0.5, pulso.z);
}

void main() {
    vec2 st = uv();
    vec2 p = st * u_resolution;
    float h = u_fx_borda * 0.5 + 0.02;
    float m = max(mao(p, u_corpo[15], u_corpo[17], u_corpo[19], h), mao(p, u_corpo[16], u_corpo[18], u_corpo[20], h));
    m *= u_corpo_on;
    m = mix(m, 1.0 - m, step(0.5, u_fx_inverter));
    gl_FragColor = vec4(vec3(m), 1.0);
}
