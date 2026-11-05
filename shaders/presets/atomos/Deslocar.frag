// fx: forca=0.3, direcao=0.375, angulo=0.25
// cat: mistura
// in: src
// opcoes: direcao=fixa|relevo|redemoinho|vetor
// mod: forca=pulsa
// ATOMOS · Deslocar. Uma imagem ENTORTA a outra (o modulate do Hydra): a entrada B empurra os pixels da corrente.
// Sem B ligada = a própria fonte crua. forca = quanto empurra (0 = nada); direcao = de onde sai o empurrão: fixa (o
// angulo, na medida do brilho de B), relevo (desce do claro pro escuro de B), redemoinho (gira em volta do claro) ou
// vetor (B já é um vetor: R = x, G = y, 0.5 = parado — o Movimento e o Fluido). angulo = pra onde, no modo fixa.

uniform float u_fx_forca, u_fx_direcao, u_fx_angulo;

void main() {
    vec2 st = uv();
    float m = floor(u_fx_direcao * 3.999);
    vec2 v = dirOf(u_texture_1, st, m, u_fx_angulo);
    if (m < 0.5) v *= (luma(B(st).rgb) - 0.5) * 2.0;
    vec2 d = v * u_fx_forca * 0.15;
    gl_FragColor = A(st + vec2(d.x / aspecto(), d.y));
}
