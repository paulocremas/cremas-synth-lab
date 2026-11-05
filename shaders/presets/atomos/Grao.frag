// fx: forca=0.3, tamanho=0.2
// cat: textura
// mod: forca=grave
// ATOMOS · Grão. Ruído de filme que muda a cada quadro. forca = quanto (0 = nada); tamanho = grão fino (0) a grosso (1).

uniform float u_fx_forca, u_fx_tamanho;

void main() {
    vec2 st = uv();
    vec2 cell = floor(st * vec2(aspecto(), 1.0) * 1080.0 / (1.0 + u_fx_tamanho * 7.0));   // tamanho em fracao da altura
    float n = hash(cell + floor(u_time * 24.0) * 17.0) - 0.5;
    vec4 c = A(st);
    gl_FragColor = vec4(clamp(c.rgb + n * u_fx_forca, 0.0, 1.0), c.a);
}
