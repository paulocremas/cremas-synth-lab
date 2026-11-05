// fx: forca=1.0, matiz=0.0, paleta=0
// opcoes: paleta=arco-íris|fogo|mar|ácido
// cat: cor
// mod: matiz=anda
// ATOMOS · Paleta. O colorizador: cada brilho vira uma cor (preto → uma ponta da paleta, branco → a outra), com as
// paletas de cosseno do Inigo Quilez (o fogo é a rampa clássica preto → vermelho → amarelo → branco).
// Transforma cinza (Ruído, Rampa, Reação, Fluido) em matéria colorida.
// forca = quanto (0 = nada); matiz = gira a paleta (movido, as cores andam); paleta = qual.

uniform float u_fx_forca, u_fx_matiz, u_fx_paleta;

void main() {
    vec4 c = A(uv());
    float t = luma(c.rgb), m = floor(u_fx_paleta * 3.999);
    vec3 col;
    if (m < 0.5) col = paleta(t + u_fx_matiz, vec3(0.5), vec3(0.5), vec3(1.0), vec3(0.0, 0.33, 0.67));
    else if (m < 1.5) { float f = fract(t + u_fx_matiz); col = clamp(vec3(f * 3.0, f * 3.0 - 1.0, f * 3.0 - 2.0), 0.0, 1.0); }   // fogo: preto, vermelho, amarelo, branco
    else if (m < 2.5) col = paleta(t * 0.8 + u_fx_matiz, vec3(0.2, 0.4, 0.55), vec3(0.2, 0.3, 0.35), vec3(1.0, 1.0, 1.0), vec3(0.3, 0.2, 0.15)) * mix(0.3, 1.1, t);
    else col = paleta(t * 1.5 + u_fx_matiz, vec3(0.5), vec3(0.5), vec3(2.0, 1.0, 0.0), vec3(0.5, 0.2, 0.25));
    gl_FragColor = vec4(mix(c.rgb, clamp(col, 0.0, 1.0), u_fx_forca), c.a);
}
