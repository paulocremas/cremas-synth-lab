// fx: forca=0.8, padrao=0, semeia=0.5
// opcoes: padrao=coral|mitose|labirinto|bolhas
// cat: gerador
// in: src
// B: semente
// estado: canais=2, passos=8, escala=0.35
// mod: forca=respira
// ATOMOS · Reação. Duas "tintas" que reagem e se espalham (Gray-Scott, Karl Sims): onde há semente CRESCE uma forma
// viva — coral, células se dividindo, labirinto, bolhas. Semente = onde a entrada B é clara (ligue a máscara das
// Mãos, um Limiar, outra caixa; sem B = a fonte crua) e o evento semear (pontos espalhados). limpar = apaga tudo e
// recomeça. forca = rapidez (0 = congela); padrao = a forma; semeia = quanto a entrada B planta sem parar.
// Cinza opaco (onde a forma está = claro): pinte com Paleta; pra ver por cima, modo soma/tela.

uniform float u_fx_forca, u_fx_padrao, u_fx_semeia;

void main() {
    vec2 st = uv();
    vec4 c = E(st);
    if (u_vista > 0.5) { gl_FragColor = vec4(vec3(smoothstep(0.05, 0.35, c.g)), 1.0); return; }
    if (u_fx_forca < 0.005) { gl_FragColor = c; return; }
    vec2 e = px();
    vec2 l = -c.rg;   // laplaciano 3x3 (0.2 nos lados, 0.05 nas diagonais); o estado guarda (1 - A, B): zerado = vazio
    l += 0.2 * (E(st + vec2(e.x, 0.0)).rg + E(st - vec2(e.x, 0.0)).rg + E(st + vec2(0.0, e.y)).rg + E(st - vec2(0.0, e.y)).rg);
    l += 0.05 * (E(st + e).rg + E(st - e).rg + E(st + vec2(e.x, -e.y)).rg + E(st + vec2(-e.x, e.y)).rg);
    float m = floor(u_fx_padrao * 3.999);
    vec2 fk = m < 0.5 ? vec2(0.0545, 0.062) : m < 1.5 ? vec2(0.0367, 0.0649) : m < 2.5 ? vec2(0.029, 0.057) : vec2(0.039, 0.058);
    float a = 1.0 - c.r, b = c.g, r = a * b * b, dt = u_fx_forca;
    float na = a + (-l.x - r + fk.x * (1.0 - a)) * dt;   // laplaciano de A = -(laplaciano de 1 - A)
    float nb = b + (0.5 * l.y + r - (fk.x + fk.y) * b) * dt;
    float s = smoothstep(0.55, 0.75, luma(B(st).rgb)) * u_fx_semeia;
    nb = max(nb, s * 0.5);
    if (u_semear > 0.5 && hash(floor(asp(st) * 24.0)) > 0.93) nb = max(nb, 0.8);
    gl_FragColor = vec4(1.0 - clamp(na, 0.0, 1.0), clamp(nb, 0.0, 1.0), 0.0, 1.0);
}
