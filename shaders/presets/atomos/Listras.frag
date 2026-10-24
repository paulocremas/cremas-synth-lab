// fx: quantos=0.3, angulo=0.25, velocidade=0.3
// cat: gerador
// ATOMOS · Listras. Faixas brancas que correm por cima do que vem antes (alfa = faixa).
// quantos = quantas faixas; angulo = direção; velocidade = rapidez.
#ifdef GL_ES
precision mediump float;
#endif

uniform vec2 u_resolution;
uniform sampler2D u_texture_0;   // A: a corrente
uniform float u_time;
uniform float u_fx_quantos, u_fx_angulo, u_fx_velocidade;

void main() {
    vec2 uv = gl_FragCoord.xy / u_resolution.y;
    float a = u_fx_angulo * 3.14159265;
    float x = dot(uv, vec2(cos(a), sin(a))) * mix(3.0, 40.0, u_fx_quantos) - u_time * u_fx_velocidade * 4.0;
    float s = smoothstep(0.35, 0.5, abs(fract(x) - 0.5));
    gl_FragColor = vec4(vec3(1.0), s);
}
