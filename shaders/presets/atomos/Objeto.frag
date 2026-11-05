// fx: limiar=0.4, borda=0.3, inverter=0
// cat: mascara
// ATOMOS · Objeto. Máscara das coisas que a IA reconhece (NanoDet: 80 tipos, de garrafa a cadeira; pessoa fica
// de fora: é o Corpo/Assunto): a caixa de cada uma. limiar = a partir de que certeza; borda = macia/dura;
// inverter = tudo menos os objetos.

uniform vec4 u_obj[8];           // x0, y0, x1, y1 em uv da fonte, topo->baixo
uniform float u_obj_p[8];        // certeza 0..1 (0 = vazio)
uniform float u_obj_on;
uniform float u_fx_limiar, u_fx_borda, u_fx_inverter;

void main() {
    vec2 st = uv();
    float h = u_fx_borda * 0.5 + 0.02;
    float m = 0.0;
    for (int i = 0; i < 8; i++) {
        vec4 b = u_obj[i];
        vec2 c = (b.xy + b.zw) * 0.5, r = (b.zw - b.xy) * 0.5 + 1e-4;
        vec2 q = abs(st - c) / r;                  // 1 = na beira da caixa
        float d = max(q.x, q.y);
        m = max(m, (1.0 - smoothstep(1.0 - h * 0.5, 1.0 + h * 0.5, d)) * step(u_fx_limiar * 0.9 + 0.05, u_obj_p[i]));
    }
    m *= u_obj_on;
    m = mix(m, 1.0 - m, step(0.5, u_fx_inverter));
    gl_FragColor = vec4(vec3(m), 1.0);
}
