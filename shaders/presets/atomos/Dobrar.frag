// fx: forca=0.35, modo=0
// opcoes: modo=brilho|cor
// cat: luz
// mod: forca=grave
// ATOMOS · Dobrar. O wavefolder do sintetizador: o brilho passa do branco e DOBRA de volta, várias vezes — um
// degradê vira curvas de nível (topografia), um rosto vira anéis. forca = quantas dobras (0 = nada); modo = dobra
// o brilho (guarda a cor) ou cada cor separada (psicodélico).

uniform float u_fx_forca, u_fx_modo;

vec3 fold(vec3 x, float g) { return 1.0 - abs(1.0 - mod(x * g, 2.0)); }

void main() {
    vec4 c = A(uv());
    float g = 1.0 + u_fx_forca * 9.0;
    vec3 o;
    if (floor(u_fx_modo * 1.999) < 0.5) {
        float l = luma(c.rgb), f = fold(vec3(l), g).x;
        o = l > 1e-3 ? c.rgb * (f / l) : vec3(f);
        o = mix(o, vec3(f), clamp(max(max(o.r, o.g), o.b) - 1.0, 0.0, 1.0));   // cor que estoura: puxa pro cinza dobrado
    } else {
        o = fold(c.rgb, g);
    }
    gl_FragColor = vec4(clamp(o, 0.0, 1.0), c.a);
}
