// fx: matiz=0.0, largura=0.15, borda=0.3, inverter=0
// cat: cor
// entra: cima
// ATOMOS · Só a cor. Separa o que é da cor escolhida: na corrente o próximo nó age SÓ nela (a marca deste). Lê a
// entrada, então depois de um Matiz vale a cor JÁ trocada. Sozinho não muda a imagem. matiz = a cor (0 vermelho,
// 0.33 verde, 0.66 azul); largura = quão larga a faixa de cor; borda = recorte duro (0) ou macio (1);
// inverter = tudo MENOS a cor. Cinza/preto/branco não têm cor: ficam de fora (com inverter, dentro).

uniform float u_fx_matiz, u_fx_largura, u_fx_borda, u_fx_inverter;

vec3 hsv(vec3 c) {
    vec4 K = vec4(0.0, -1.0 / 3.0, 2.0 / 3.0, -1.0);
    vec4 p = mix(vec4(c.bg, K.wz), vec4(c.gb, K.xy), step(c.b, c.g));
    vec4 q = mix(vec4(p.xyw, c.r), vec4(c.r, p.yzx), step(p.x, c.r));
    float d = q.x - min(q.w, q.y);
    return vec3(abs(q.z + (q.w - q.y) / (6.0 * d + 1e-10)), d / (q.x + 1e-10), q.x);
}

void main() {
    vec2 st = uv();
    vec4 a = A(st);
    vec3 c = hsv(a.rgb);
    float d = abs(fract(c.x - u_fx_matiz + 0.5) - 0.5) * 2.0;   // 0 = a cor, 1 = a oposta
    float w = 0.02 + u_fx_largura * 0.5, h = u_fx_borda * w + 1e-3;
    float m = (1.0 - smoothstep(w - h, w + h, d)) * smoothstep(0.1, 0.25, c.y) * smoothstep(0.05, 0.15, c.z);
    m = mix(m, 1.0 - m, step(0.5, u_fx_inverter));
    gl_FragColor = vec4(a.rgb, a.a * m);
}
