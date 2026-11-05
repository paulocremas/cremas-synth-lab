// fx: forca=1.0, corte=0.5, borda=0.15
// cat: luz
// mod: corte=respira
// ATOMOS · Limiar. O keyer: tudo que passa do corte vira BRANCO, o resto PRETO (a chave do sintetizador de vídeo).
// Junto de Paleta pinta zonas; junto de Dobrar, linhas. forca = quanto vira chave (0 = nada); corte = a partir de que
// brilho; borda = dura (0) ou macia (1).

uniform float u_fx_forca, u_fx_corte, u_fx_borda;

void main() {
    vec4 c = A(uv());
    float h = u_fx_borda * 0.5 + 0.004;
    float k = smoothstep(u_fx_corte - h, u_fx_corte + h, luma(c.rgb));
    gl_FragColor = vec4(mix(c.rgb, vec3(k), u_fx_forca), c.a);
}
