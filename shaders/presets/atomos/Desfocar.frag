// fx: tamanho=0.3
// cat: textura
// mod: tamanho=abaixa
// ATOMOS · Desfocar. Embaça. tamanho = raio do borrão (0 = nada; 16 amostras em espiral). Faz a MÉDIA com a
// cobertura junto (Am): a borda de uma peça que desenha só linhas não escurece.

uniform float u_fx_tamanho;

void main() {
    vec2 st = uv();
    float r = u_fx_tamanho * 0.03;
    vec4 acc = vec4(0.0);
    for (int i = 0; i < 16; i++) {
        float k = float(i) + 0.5, a = k * 2.39996;
        vec2 o = vec2(cos(a), sin(a)) * r * sqrt(k / 16.0);
        acc += Am(st + vec2(o.x / aspecto(), o.y));
    }
    acc /= 16.0;
    gl_FragColor = vec4(acc.rgb / max(acc.a, 1e-4), acc.a);
}
