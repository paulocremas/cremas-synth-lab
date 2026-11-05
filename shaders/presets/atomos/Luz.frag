// fx: brilho=0.6, contraste=0.6
// cat: luz
// bipolar: brilho, contraste
// mod: brilho=pulsa
// ATOMOS · Luz. Clareia/escurece e abre/fecha o contraste. brilho e contraste: 0.5 = igual.

uniform float u_fx_brilho, u_fx_contraste;

void main() {
    vec4 c = A(uv());
    vec3 o = (c.rgb - 0.5) * pow(4.0, u_fx_contraste * 2.0 - 1.0) + 0.5 + (u_fx_brilho - 0.5);
    gl_FragColor = vec4(clamp(o, 0.0, 1.0), c.a);
}
