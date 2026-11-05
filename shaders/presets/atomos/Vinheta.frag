// fx: forca=0.5, tamanho=0.5, borda=0.5
// cat: luz
// mod: forca=pulsa
// ATOMOS · Vinheta. Escurece as bordas e deixa o miolo. forca = quanto fecha (0 = nada); tamanho = miolo pequeno (0)
// a grande (1); borda = dura (0) ou macia (1). Só escurece: a cor da borda é um Tingir depois.

uniform float u_fx_forca, u_fx_tamanho, u_fx_borda;

void main() {
    vec4 c = A(uv());
    float r = length(asp(uv())), m0 = mix(0.1, 0.75, u_fx_tamanho), w = 0.02 + u_fx_borda * 0.5;
    float k = 1.0 - smoothstep(m0, m0 + w, r) * u_fx_forca;
    gl_FragColor = vec4(c.rgb * k, c.a);
}
