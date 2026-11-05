// fx: forca=0.4, tamanho=0.3
// cat: textura
// mod: forca=pulsa
// ATOMOS · Afiar. O oposto do Desfocar: realça as bordas e os detalhes (máscara de nitidez). forca = quanto (0 =
// nada); tamanho = detalhe fino (0) a contorno grosso (1).

uniform float u_fx_forca, u_fx_tamanho;

void main() {
    vec2 st = uv();
    vec4 c = A(st);
    float r = mix(0.002, 0.012, u_fx_tamanho);
    vec3 b = vec3(0.0);
    for (int i = 0; i < 8; i++) {
        float a = float(i) * 0.785398;
        b += A(st + vec2(cos(a) * r / aspecto(), sin(a) * r)).rgb;
    }
    gl_FragColor = vec4(clamp(c.rgb + (c.rgb - b / 8.0) * u_fx_forca * 3.0, 0.0, 1.0), c.a);
}
