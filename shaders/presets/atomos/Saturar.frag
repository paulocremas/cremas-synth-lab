// fx: saturacao=0.8
// cat: cor
// bipolar: saturacao
// mod: saturacao=grave
// ATOMOS · Saturar. Mais ou menos cor. saturacao = 0 cinza, 0.5 igual, 1 o dobro.

uniform float u_fx_saturacao;

void main() {
    vec4 c = A(uv());
    gl_FragColor = vec4(clamp(mix(vec3(luma(c.rgb)), c.rgb, u_fx_saturacao * 2.0), 0.0, 1.0), c.a);
}
