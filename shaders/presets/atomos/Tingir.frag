// fx: forca=0.8, matiz=0.6
// cat: cor
// mod: matiz=respira
// ATOMOS · Tingir. Pinta a imagem de UMA cor, guardando o claro e o escuro (duotone de uma cor só).
// forca = quanto da cor original some (0 = nada); matiz = a cor.

uniform float u_fx_matiz, u_fx_forca;

vec3 hsv(float h) { return clamp(abs(fract(h + vec3(0.0, 2.0, 1.0) / 3.0) * 6.0 - 3.0) - 1.0, 0.0, 1.0); }

void main() {
    vec4 c = A(uv());
    gl_FragColor = vec4(clamp(mix(c.rgb, hsv(u_fx_matiz) * luma(c.rgb) * 1.6, u_fx_forca), 0.0, 1.0), c.a);
}
