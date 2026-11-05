// fx: quanto=0.5, modo=0
// opcoes: modo=normal|soma|tela|multiplicar|diferença
// cat: mistura
// in: src
// ATOMOS · Misturar. Junta a entrada B na corrente (B = outra caixa; sem B = a fonte crua).
// quanto = 0 só a corrente … 1 só B; modo = normal, soma, tela, multiplicar ou diferença.

uniform float u_fx_quanto, u_fx_modo;

void main() {
    vec2 st = uv();
    vec4 ca = A(st);
    vec3 a = ca.rgb, b = B(st).rgb;
    float m = floor(u_fx_modo * 4.999);
    vec3 c = m < 0.5 ? b : m < 1.5 ? min(a + b, 1.0) : m < 2.5 ? 1.0 - (1.0 - a) * (1.0 - b)
           : m < 3.5 ? a * b : abs(a - b);
    gl_FragColor = vec4(mix(a, c, u_fx_quanto), ca.a);
}
