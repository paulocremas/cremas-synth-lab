// fx: quantos=0.4, tamanho=0.3, velocidade=0.4
// cat: gerador
// ritmo: velocidade
// mod: tamanho=pulsa
// ATOMOS · Pontos. Bolinhas brancas que sobem pela tela, por cima do que vem antes (alfa = bolinha).
// quantos = densidade; tamanho = raio; velocidade = rapidez.

uniform float u_fx_quantos, u_fx_tamanho, u_fx_velocidade;

void main() {
    vec2 p = gl_FragCoord.xy / u_resolution.y;
    float n = mix(4.0, 30.0, u_fx_quantos);
    p.y -= u_time * u_fx_velocidade * 0.3;
    vec2 c = floor(p * n), f = fract(p * n) - 0.5;
    vec2 o = vec2(hash(c), hash(c + 7.1)) - 0.5;
    float r = mix(0.05, 0.45, u_fx_tamanho) * step(0.4, hash(c + 3.3));
    gl_FragColor = vec4(vec3(1.0), 1.0 - smoothstep(r * 0.7, r, length(f - o * (0.9 - r))));
}
