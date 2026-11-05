// fx: quantos=0.3, angulo=0.25, velocidade=0.3
// cat: gerador
// ritmo: velocidade
// mod: quantos=passos
// ATOMOS · Listras. Faixas brancas que correm por cima do que vem antes (alfa = faixa).
// quantos = quantas faixas; angulo = direção; velocidade = rapidez.

uniform float u_fx_quantos, u_fx_angulo, u_fx_velocidade;

void main() {
    vec2 p = gl_FragCoord.xy / u_resolution.y;
    float a = u_fx_angulo * 3.14159265;
    float x = dot(p, vec2(cos(a), sin(a))) * mix(3.0, 40.0, u_fx_quantos) - u_time * u_fx_velocidade * 4.0;
    gl_FragColor = vec4(vec3(1.0), smoothstep(0.35, 0.5, abs(fract(x) - 0.5)));
}
