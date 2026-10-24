// fx: quantos=0.4, tamanho=0.3, velocidade=0.4
// cat: gerador
// ATOMOS · Pontos. Bolinhas brancas que sobem pela tela, por cima do que vem antes (alfa = bolinha).
// quantos = densidade; tamanho = raio; velocidade = rapidez.
#ifdef GL_ES
precision mediump float;
#endif

uniform vec2 u_resolution;
uniform sampler2D u_texture_0;   // A: a corrente
uniform float u_time;
uniform float u_fx_quantos, u_fx_tamanho, u_fx_velocidade;

float h(vec2 p) { return fract(sin(dot(p, vec2(12.9898, 78.233))) * 43758.5453); }

void main() {
    vec2 uv = gl_FragCoord.xy / u_resolution.y;
    float n = mix(4.0, 30.0, u_fx_quantos);
    uv.y -= u_time * u_fx_velocidade * 0.3;
    vec2 c = floor(uv * n), f = fract(uv * n) - 0.5;
    vec2 o = vec2(h(c), h(c + 7.1)) - 0.5;
    float r = mix(0.05, 0.45, u_fx_tamanho) * step(0.4, h(c + 3.3));
    float a = 1.0 - smoothstep(r * 0.7, r, length(f - o * (0.9 - r)));
    gl_FragColor = vec4(vec3(1.0), a);
}
