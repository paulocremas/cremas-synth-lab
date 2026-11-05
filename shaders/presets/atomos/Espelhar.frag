// fx: modo=0
// opcoes: modo=lados|cima/baixo|quatro
// cat: geometria
// ATOMOS · Espelhar. Dobra a imagem no meio. modo = lados (esquerda→direita), cima/baixo ou quatro (os quatro cantos).

uniform float u_fx_modo;

void main() {
    vec2 st = uv();
    float m = floor(u_fx_modo * 2.999);
    vec2 p = st;
    if (m != 1.0) p.x = 0.5 - abs(p.x - 0.5);
    if (m != 0.0) p.y = 0.5 - abs(p.y - 0.5);
    gl_FragColor = A(p);
}
