// fx: tamanho=0.3
// cat: geometria
// mod: tamanho=pulsa
// ATOMOS · Blocos. Blocos grandes. tamanho = de nada (0) a 1/8 da altura da tela (1).

uniform float u_fx_tamanho;

void main() {
    vec2 st = uv();
    float b = u_fx_tamanho * u_fx_tamanho * 0.125;   // lado do bloco em fracao da ALTURA
    if (b * u_resolution.y < 1.0) { gl_FragColor = A(st); return; }
    vec2 c = vec2(b / aspecto(), b);
    gl_FragColor = A((floor(st / c) + 0.5) * c);
}
