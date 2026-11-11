// fx: limiar=0.5, borda=0.2, inverter=0
// cat: mascara
// in: src
// B: forma
// ATOMOS · Luma. Máscara vinda de OUTRA caixa (luma matte do compositing): onde a imagem B é clara, a caixa
// aparece. Ligue puxando o fio de uma caixa até a faixa de máscara desta. limiar = a partir de que brilho;
// borda = macia/dura; inverter = onde B é escura.

uniform float u_fx_limiar, u_fx_borda, u_fx_inverter;

void main() {
    vec2 st = uv();
    vec4 c = B(st);
    float b = dot(c.rgb, vec3(0.299, 0.587, 0.114)) * c.a;   // transparente = escuro
    float h = u_fx_borda * 0.5 + 1e-3;
    float m = smoothstep(u_fx_limiar - h, u_fx_limiar + h, b);
    m = mix(m, 1.0 - m, step(0.5, u_fx_inverter));
    gl_FragColor = vec4(vec3(m), 1.0);
}
