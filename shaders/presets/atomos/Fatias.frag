// fx: quantos=0.3, giro=0.5
// cat: geometria
// bipolar: giro
// ritmo: giro
// mod: giro=respira
// ATOMOS · Fatias. Repete uma fatia em volta do centro (caleidoscópio). quantos = de nada (0) a 16 fatias;
// giro = gira sozinho (0.5 = parado; abaixo/acima = um sentido/outro).

uniform float u_fx_quantos, u_fx_giro;

void main() {
    vec2 st = uv();
    float n = floor(1.0 + u_fx_quantos * 15.0);
    if (n < 1.5) { gl_FragColor = A(st); return; }
    vec2 p = asp(st);
    float s = 6.2831853 / n;
    float a = atan(p.y, p.x) + u_time * (u_fx_giro - 0.5) * 2.0;
    a = abs(mod(a, s) - s * 0.5);
    gl_FragColor = A(desasp(vec2(cos(a), sin(a)) * length(p)));
}
