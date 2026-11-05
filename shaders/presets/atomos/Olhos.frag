// fx: tamanho=0.5, borda=0.2, inverter=0
// cat: mascara
// ATOMOS · Olhos. Máscara de DENTRO dos olhos (até 4 rostos, IA Face Mesh): o contorno das pálpebras, olho
// aberto ou fechado. tamanho = 0.5 é o contorno certinho; menos encolhe pra dentro, mais cresce pra fora;
// borda = macia/dura; inverter = tudo menos os olhos.

uniform vec4 u_olho[64];         // rosto i, olho e: u_olho[(i*2+e)*8 + k] = pontos 2k (xy) e 2k+1 (zw) do contorno, uv topo->baixo
uniform float u_olho_on;
uniform float u_fx_tamanho, u_fx_borda, u_fx_inverter;

vec2 pt(int base, int j) {       // ponto j (0..15) do olho que comeca em base
    vec4 q = u_olho[base + j / 2];
    return (j - (j / 2) * 2 == 0 ? q.xy : q.zw) * u_resolution;
}

// distancia COM SINAL ate' o contorno (negativa dentro), em px
float contorno(vec2 p, int base) {
    float d = 1e9, s = 1.0;
    vec2 a = pt(base, 15);
    for (int j = 0; j < 16; j++) {
        vec2 b = pt(base, j), e = b - a, w = p - a;
        vec2 q = w - e * clamp(dot(w, e) / max(dot(e, e), 1e-6), 0.0, 1.0);
        d = min(d, dot(q, q));
        if ((a.y > p.y) != (b.y > p.y) && p.x < a.x + (p.y - a.y) * e.x / (e.y + 1e-9)) s = -s;   // cruzou: entrou/saiu
        a = b;
    }
    return s * sqrt(d);
}

void main() {
    vec2 st = uv();
    vec2 p = st * u_resolution;                   // em px: a borda sai igual em qualquer proporcao
    float m = 0.0;
    for (int k = 0; k < 8; k++) {                 // 4 rostos x 2 olhos
        int base = k * 8;
        float larg = length(pt(base, 8) - pt(base, 0));   // canto a canto do olho
        if (larg < 1.0) continue;                         // olho vazio (sem rosto)
        float d = contorno(p, base) - (u_fx_tamanho - 0.5) * 0.6 * larg;
        float h = (u_fx_borda * 0.25 + 0.01) * larg;
        m = max(m, 1.0 - smoothstep(-h, h, d));
    }
    m *= u_olho_on;
    m = mix(m, 1.0 - m, step(0.5, u_fx_inverter));
    gl_FragColor = vec4(vec3(m), 1.0);
}
