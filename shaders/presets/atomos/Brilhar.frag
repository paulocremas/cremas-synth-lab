// fx: forca=0.5, limiar=0.6, tamanho=0.4
// cat: luz
// mod: forca=grave
// ATOMOS · Brilhar. O claro vaza e acende em volta (bloom), como luz forte na lente. forca = quanto (0 = nada);
// limiar = a partir de que brilho vaza; tamanho = halo curto (0) a longo (1).

uniform float u_fx_forca, u_fx_limiar, u_fx_tamanho;

void main() {
    vec2 st = uv();
    vec4 c = A(st);
    float r = mix(0.01, 0.08, u_fx_tamanho);
    vec3 g = vec3(0.0);
    for (int i = 0; i < 16; i++) {
        float k = float(i) + 0.5, a = k * 2.39996;
        vec2 o = vec2(cos(a), sin(a)) * r * sqrt(k / 16.0);
        vec3 s = A(st + vec2(o.x / aspecto(), o.y)).rgb;
        g += s * smoothstep(u_fx_limiar, u_fx_limiar + 0.2, luma(s));
    }
    gl_FragColor = vec4(clamp(c.rgb + g / 16.0 * u_fx_forca * 2.5, 0.0, 1.0), c.a);
}
