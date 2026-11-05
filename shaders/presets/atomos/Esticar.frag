// fx: forca=0.4
// cat: textura
// mod: forca=pulsa
// ATOMOS · Esticar. Borrão de velocidade saindo do centro (zoom blur): a imagem parece vir pra cima de você. forca =
// comprimento do rastro (0 = nada). Faz a MÉDIA com a cobertura junto (Am), como o Desfocar.

uniform float u_fx_forca;

void main() {
    vec2 st = uv(), c = vec2(0.5);
    vec4 acc = vec4(0.0);
    for (int i = 0; i < 12; i++) {
        float k = float(i) / 11.0;
        acc += Am(c + (st - c) * (1.0 - k * u_fx_forca * 0.25));
    }
    acc /= 12.0;
    gl_FragColor = vec4(acc.rgb / max(acc.a, 1e-4), acc.a);
}
