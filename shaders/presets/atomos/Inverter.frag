// cat: luz
// mod: opacity=pulsa
// ATOMOS · Inverter. Negativo: claro vira escuro e cada cor vira a oposta. Meio-termo = a opacidade da peça.

void main() {
    vec4 c = A(uv());
    gl_FragColor = vec4(1.0 - c.rgb, c.a);
}
