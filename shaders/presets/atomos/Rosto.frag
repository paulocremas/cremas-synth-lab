// fx: tamanho=0.5, borda=0.3, inverter=0
// cat: mascara
// ATOMOS · Rosto. Máscara dos rostos (até 4, IA YuNet): uma elipse em cada. tamanho = do rosto justo (0) a 2x,
// com cabelo e pescoço (1); borda = macia/dura; inverter = tudo menos os rostos. Sem rosto à vista = vazia.

uniform vec4 u_rosto[4];         // cx, cy, largura, altura em uv da fonte, topo->baixo; largura 0 = vazio
uniform float u_rosto_on;        // 1 = achou; cai ate' 0 em ~meio segundo quando perde
uniform float u_fx_tamanho, u_fx_borda, u_fx_inverter;

void main() {
    vec2 st = uv();
    float k = mix(0.55, 1.1, u_fx_tamanho);       // meia caixa x k = raio da elipse
    float h = u_fx_borda * 0.5 + 0.02;
    float m = 0.0;
    for (int i = 0; i < 4; i++) {
        vec4 f = u_rosto[i];
        float d = length((st - f.xy) / (f.zw * k + 1e-4));   // 1 = na beira da elipse
        m = max(m, (1.0 - smoothstep(1.0 - h, 1.0 + h, d)) * step(1e-4, f.z));
    }
    m *= u_rosto_on;
    m = mix(m, 1.0 - m, step(0.5, u_fx_inverter));
    gl_FragColor = vec4(vec3(m), 1.0);
}
