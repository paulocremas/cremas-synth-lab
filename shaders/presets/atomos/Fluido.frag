// fx: forca=0.5, direcao=0.875, rastro=0.5
// opcoes: direcao=fixa|relevo|redemoinho|vetor
// cat: gerador
// in: src
// B: quem empurra
// estado: canais=4, passos=1, fases=14, escala=0.25
// mod: forca=pulsa
// ATOMOS · Fluido. Tinta num líquido (Stable Fluids, Jos Stam): a entrada B EMPURRA o líquido e onde ela empurra
// aparece tinta, que gira, enrola e some devagar. direcao = de onde vem o empurrão: fixa (o vento), relevo/
// redemoinho (as formas de B) ou vetor (B já é movimento: ligue o Movimento da câmera = a mão mexe a fumaça).
// forca = quanto empurra (0 = parado); rastro = quanto a tinta dura. Cinza opaco: pinte com Paleta. (O líquido não
// se comprime: um empurrão de "relevo" puro quase some na pressão — o redemoinho e o vetor é que giram.)
// limpar = água limpa.

uniform float u_fx_forca, u_fx_direcao, u_fx_rastro;

vec4 Q(vec2 s) { return E(s); }

void main() {
    vec2 st = uv();
    vec2 e = px();
    vec4 c = Q(st);
    if (u_vista > 0.5) { gl_FragColor = vec4(vec3(clamp(c.a, 0.0, 1.0)), 1.0); return; }
    if (u_fase < 0.5) {                       // 1) leva tudo pela correnteza (semi-Lagrangiano) + empurrao + tinta
        vec2 back = st - c.rg * e;
        vec4 a = Q(back);
        float m = floor(u_fx_direcao * 3.999);
        vec2 f = dirOf(u_texture_1, st, m, 0.0);
        if (m < 0.5) f *= luma(B(st).rgb);
        f *= u_fx_forca * 0.3;
        vec2 v = a.rg * decai(0.6) + f;
        float ink = max(a.a * decai(0.1 + u_fx_rastro * u_fx_rastro * 6.0) - u_dt * 0.004, min(1.0, length(f) * 4.0));
        gl_FragColor = vec4(clamp(v, -8.0, 8.0), c.b, clamp(ink, 0.0, 1.5));
    } else if (u_fase < 12.5) {               // 2) pressao (Jacobi): o liquido nao se comprime
        float div = 0.5 * (Q(st + vec2(e.x, 0.0)).r - Q(st - vec2(e.x, 0.0)).r + Q(st + vec2(0.0, e.y)).g - Q(st - vec2(0.0, e.y)).g);
        float p = (Q(st + vec2(e.x, 0.0)).b + Q(st - vec2(e.x, 0.0)).b + Q(st + vec2(0.0, e.y)).b + Q(st - vec2(0.0, e.y)).b - div) * 0.25;
        gl_FragColor = vec4(c.rg, p, c.a);
    } else {                                  // 3) tira a parte que comprime
        vec2 g = 0.5 * vec2(Q(st + vec2(e.x, 0.0)).b - Q(st - vec2(e.x, 0.0)).b, Q(st + vec2(0.0, e.y)).b - Q(st - vec2(0.0, e.y)).b);
        gl_FragColor = vec4(c.rg - g, c.b * 0.98, c.a);
    }
}
