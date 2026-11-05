// fx: forca=0.3, angulo=0.0
// cat: distorcao
// mod: forca=pulsa
// ATOMOS · Separar. Desencaixa o vermelho e o azul (aberração cromática, a lente barata). forca = distância
// (0 = nada); angulo = pra que lado separa.

uniform float u_fx_forca, u_fx_angulo;

void main() {
    vec2 st = uv();
    float a = u_fx_angulo * 6.2831853;
    vec2 d = vec2(cos(a) / aspecto(), sin(a)) * u_fx_forca * 0.02;
    vec4 r = A(st + d), g = A(st), b = A(st - d);
    gl_FragColor = vec4(r.r, g.g, b.b, max(g.a, max(r.a, b.a)));
}
