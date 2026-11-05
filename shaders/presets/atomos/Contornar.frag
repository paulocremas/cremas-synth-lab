// fx: limiar=0.15, borda=0.5
// cat: forma
// mod: limiar=respira
// ATOMOS · Contornar. Desenha SÓ as linhas das bordas, brancas, por cima do que vem antes (alfa = linha).
// Um Tingir depois pinta tudo; pra pintar só as linhas, solte o Tingir EM CIMA do Contornar (paralelo).
// limiar = a partir de que diferença vira linha; borda = linha dura (0) ou macia (1).

uniform float u_fx_limiar, u_fx_borda;

float lum(vec2 p) { return luma(A(p).rgb); }

void main() {
    vec2 st = uv();
    vec2 e = vec2(1.0 / (720.0 * aspecto()), 1.0 / 720.0);   // fracao da tela: a mesma linha em 720p e no telao
    float gx = lum(st + vec2(e.x, 0.0)) - lum(st - vec2(e.x, 0.0));
    float gy = lum(st + vec2(0.0, e.y)) - lum(st - vec2(0.0, e.y));
    float g = length(vec2(gx, gy)) * 4.0;
    float w = 0.02 + u_fx_borda * 0.3;
    gl_FragColor = vec4(vec3(1.0), smoothstep(u_fx_limiar - w, u_fx_limiar + w, g));
}
