// fx: limiar=0.5, borda=0.1, inverter=0
// cat: mistura
// in: src
// ATOMOS · Máscara. A corrente so' aparece onde a entrada B e' clara (o resto fica preto). Sem B ligada
// = a propria fonte crua. limiar = a partir de que brilho aparece inteira (0 = tudo); borda = macia/dura; inverter = so' no escuro.

uniform float u_fx_limiar, u_fx_borda, u_fx_inverter;

void main() {
    vec2 st = uv();
    float b = dot(B(st).rgb, vec3(0.299, 0.587, 0.114));
    float m = smoothstep(u_fx_limiar - u_fx_borda - 1e-3, u_fx_limiar, b);   // limiar 0 = tudo aparece (neutro)
    m = mix(m, 1.0 - m, step(0.5, u_fx_inverter));
    gl_FragColor = vec4(A(st).rgb * m, A(st).a);   // filtro: devolve o alfa que leu
}
