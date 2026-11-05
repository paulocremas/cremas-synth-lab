// fx: tamanho=0.4, velocidade=0.3, borda=0.3
// cat: gerador
// ritmo: velocidade
// mod: velocidade=respira
// ATOMOS · Células. Bolhas que se empurram (voronoi): cada ponto de uma rede tem a sua célula, e as células
// andam e se deformam. Cinza opaco: claro no meio da célula, escuro nas paredes — Paleta pinta, Limiar recorta,
// Deslocar (relevo) entorta a imagem pelas bolhas. tamanho = células miúdas (0) a grandes (1); velocidade = quanto
// andam; borda = parede fina e dura (0) a macia (1).

uniform float u_fx_tamanho, u_fx_velocidade, u_fx_borda;

void main() {
    vec2 p = asp(uv()) * mix(16.0, 2.5, u_fx_tamanho);
    vec2 i = floor(p), f = fract(p);
    float d1 = 9.0, d2 = 9.0, t = u_time * u_fx_velocidade;
    for (int y = -1; y <= 1; y++) for (int x = -1; x <= 1; x++) {
        vec2 g = vec2(float(x), float(y));
        vec2 o = vec2(hash(i + g), hash(i + g + 19.7));
        o = 0.5 + 0.4 * sin(t + 6.2831853 * o);
        float d = length(g + o - f);
        if (d < d1) { d2 = d1; d1 = d; } else if (d < d2) d2 = d;
    }
    float wall = smoothstep(0.0, mix(0.03, 0.4, u_fx_borda), d2 - d1);   // 0 na parede, 1 longe dela
    gl_FragColor = vec4(vec3(wall * (1.0 - 0.6 * d1)), 1.0);
}
