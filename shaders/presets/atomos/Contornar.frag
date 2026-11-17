// fx: limiar=0.15, espessura=0.1, borda=0.3, fundo=0
// opcoes: fundo=imagem|preto
// cat: forma
// mod: limiar=respira
// ATOMOS · Contornar. As linhas das bordas, brancas. fundo = imagem (as linhas POR CIMA do que vem antes) ou preto (só as
// linhas). Na corrente o próximo nó age SÓ nas linhas (a marca dele): Contornar → Vinheta = a vinheta só nas linhas.
// limiar = quanta diferença vira linha (0 = tudo vira linha, 1 = só os contornos mais fortes);
// espessura = linha fina (0) a grossa (1); borda = linha dura, recortada (0) a macia, que acende aos poucos (1).

uniform float u_fx_limiar, u_fx_espessura, u_fx_borda, u_fx_fundo;

float lum(vec2 p) { return luma(A(p).rgb); }

// forca da borda em p, sempre FINA (1.5 px na ref. de 720 linhas): a espessura vem depois, engordando a linha
float edge(vec2 p) {
    vec2 ex = vec2(1.5 / 720.0 / aspecto(), 0.0), ey = vec2(0.0, 1.5 / 720.0);
    return length(vec2(lum(p + ex) - lum(p - ex), lum(p + ey) - lum(p - ey))) * 4.0;
}

void main() {
    vec2 st = uv();
    float g = edge(st);
    if (u_fx_espessura > 0.001) {   // engorda: o mais forte de 2 aneis de 8 em volta (raio ate 10 px na ref. 720)
        float r = u_fx_espessura * 10.0 / 720.0;
        for (int i = 0; i < 8; i++) {
            float a = float(i) * 0.7853982;
            vec2 d = vec2(cos(a) / aspecto(), sin(a)) * r;
            g = max(g, max(edge(st + d), edge(st + d * 0.5)));
        }
    }
    float w = 0.01 + u_fx_borda * 0.6;
    float a = smoothstep(u_fx_limiar - w * 0.3, u_fx_limiar + w, g);
    if (floor(u_fx_fundo * 1.999) > 0.5) gl_FragColor = vec4(vec3(a), 1.0);   // preto: so' as linhas (cobre a entrada inteira)
    else gl_FragColor = vec4(vec3(1.0), a);                                   // imagem: a linha por cima (alfa = linha)
}
