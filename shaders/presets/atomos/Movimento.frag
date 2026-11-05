// fx: forca=0.5, suave=0.5
// cat: gerador
// estado: canais=4, passos=1, escala=0.2
// ATOMOS · Movimento. Onde a imagem SE MEXE e pra onde (fluxo óptico barato: diferença entre quadros ÷ relevo,
// Horn-Schunck de uma volta): dá um VETOR (R = x, G = y, 0.5 = parado; B = rapidez). Ligue num Deslocar ou Fluido
// com direção "vetor": a tinta é empurrada pelo gesto. forca = sensibilidade; suave = tremido (0) a liso e lento (1).

uniform float u_fx_forca, u_fx_suave;

float lu(vec2 p) { return luma(A(p).rgb); }

void main() {
    vec2 st = uv();
    vec4 e = E(st);
    if (u_vista > 0.5) {
        vec2 f = clamp(e.gb * (0.5 + u_fx_forca * 6.0), -1.0, 1.0);
        gl_FragColor = vec4(0.5 + f.x * 0.5, 0.5 - f.y * 0.5, length(f), 1.0);
        return;
    }
    vec2 d = vec2(1.0 / (160.0 * aspecto()), 1.0 / 160.0);   // passo do relevo: fracao da tela
    float c = (lu(st) + lu(st + d * vec2(1.0, 0.0)) + lu(st - d * vec2(1.0, 0.0)) + lu(st + d * vec2(0.0, 1.0)) + lu(st - d * vec2(0.0, 1.0))) * 0.2;
    float p = e.r;                                           // o brilho do passo anterior (guardado)
    vec2 g = vec2(lu(st + d * vec2(2.0, 0.0)) - lu(st - d * vec2(2.0, 0.0)), lu(st + d * vec2(0.0, 2.0)) - lu(st - d * vec2(0.0, 2.0)));
    float it = c - p;
    vec2 v = e.a > 0.5 ? -it * g / (dot(g, g) + 0.002) * 0.25 : vec2(0.0);   // 1o passo (estado vazio): parado
    vec2 nb = (E(st + d * vec2(2.0, 0.0)).gb + E(st - d * vec2(2.0, 0.0)).gb + E(st + d * vec2(0.0, 2.0)).gb + E(st - d * vec2(0.0, 2.0)).gb) * 0.25;
    float k = abs(it) > 0.002 ? mix(0.5, 0.06, u_fx_suave) : 0.0;           // quadro repetido (fonte a 30): segura
    vec2 f = mix(mix(e.gb, nb, 0.5), v, k) * decai(mix(0.05, 0.6, u_fx_suave));
    gl_FragColor = vec4(c, clamp(f, -4.0, 4.0), 1.0);
}
