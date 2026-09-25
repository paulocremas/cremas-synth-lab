// fx: temperatura=0.5, matiz=0.5, exposicao=0.5, contraste=0.5, realces=0.5, sombras=0.5, brancos=0.5, pretos=0.5, claridade=0.5, neblina=0.5, vibracao=0.5, saturacao=0.5
// Efeito ISOLADO, sem áudio: o painel "Básico" do Lightroom, um knob por controle. Todo knob
// nasce em 0.5 = neutro (a imagem sai igual); 0 = -100 do Lightroom, 1 = +100. Duplo-clique
// no knob volta pro 0.5. A ordem das etapas segue a do Lightroom: balanço de branco ->
// exposição -> tons (contraste, realces/sombras, brancos/pretos) -> presença (claridade,
// neblina, vibração, saturação). Tudo em RGB linear aproximado (gamma 2.2), como o LR.

#ifdef GL_ES
precision mediump float;
#endif

uniform vec2 u_resolution;
uniform sampler2D u_texture_0;

uniform float u_fx_temperatura; // azul <-> amarelo
uniform float u_fx_matiz;       // verde <-> magenta
uniform float u_fx_exposicao;   // ±2 stops
uniform float u_fx_contraste;
uniform float u_fx_realces;     // recupera/estoura as altas
uniform float u_fx_sombras;     // abre/fecha as baixas
uniform float u_fx_brancos;     // ponto branco
uniform float u_fx_pretos;      // ponto preto
uniform float u_fx_claridade;   // contraste local (meios-tons)
uniform float u_fx_neblina;     // "dehaze": >0.5 tira névoa, <0.5 põe
uniform float u_fx_vibracao;    // satura mais o que está pouco saturado, poupa pele
uniform float u_fx_saturacao;

float luma(vec3 c) { return dot(c, vec3(0.2126, 0.7152, 0.0722)); }

// imagem na posição p, já linearizada (mesma leitura pro pixel e pros vizinhos da claridade)
vec3 lin(vec2 p) { return pow(texture2D(u_texture_0, p).rgb, vec3(2.2)); }

void main() {
    vec2 st = gl_FragCoord.xy / u_resolution;
    st.y = 1.0 - st.y;
    vec3 col = lin(st);

    // knob 0..1 -> -1..+1 (0 = neutro)
    float temp = u_fx_temperatura * 2.0 - 1.0;
    float tint = u_fx_matiz * 2.0 - 1.0;
    float expo = u_fx_exposicao * 2.0 - 1.0;
    float cont = u_fx_contraste * 2.0 - 1.0;
    float high = u_fx_realces * 2.0 - 1.0;
    float shad = u_fx_sombras * 2.0 - 1.0;
    float whit = u_fx_brancos * 2.0 - 1.0;
    float blak = u_fx_pretos * 2.0 - 1.0;
    float clar = u_fx_claridade * 2.0 - 1.0;
    float haze = u_fx_neblina * 2.0 - 1.0;
    float vibr = u_fx_vibracao * 2.0 - 1.0;
    float satu = u_fx_saturacao * 2.0 - 1.0;

    // ===== BALANÇO DE BRANCO — ganho por canal (temperatura = eixo azul/amarelo, matiz = verde/magenta)
    vec3 wb = vec3(1.0 + 0.30 * temp, 1.0, 1.0 - 0.30 * temp);   // <- edita aqui: alcance da temperatura
    wb *= vec3(1.0 + 0.15 * tint, 1.0 - 0.25 * tint, 1.0 + 0.15 * tint); // <- edita aqui: alcance do matiz
    col *= wb / luma(wb);   // normaliza: mudar a cor não muda o brilho

    // ===== EXPOSIÇÃO — em stops, multiplicação no linear (igual abrir o diafragma)
    col *= exp2(expo * 2.0);                                     // <- edita aqui: ±2 stops

    // ===== NEBLINA (dehaze) — tira/põe um véu cinza: subtrai o "piso" de luz e reescala
    float veil = 0.08 * haze;                                    // <- edita aqui: força
    col = (col - veil) / (1.0 - veil);
    col = mix(col, col * col * 1.4, max(haze, 0.0) * 0.25);      // tirar névoa também aprofunda

    // tons em espaço perceptual (gamma) — é onde realces/sombras/contraste "parecem" certos
    col = pow(max(col, 0.0), vec3(1.0 / 2.2));
    float y = luma(col);

    // ===== BRANCOS / PRETOS — movem os pontos extremos (levels)
    float bp = -0.10 * blak;                                     // pretos +: levanta o preto
    float wp = 1.0 - 0.20 * whit;                                // brancos +: estoura antes
    col = (col - bp) / max(wp - bp, 0.05);

    // ===== REALCES / SOMBRAS — curva que só pega a faixa alta / baixa (máscara suave por luma)
    float mh = smoothstep(0.45, 1.0, y);
    float ms = 1.0 - smoothstep(0.0, 0.55, y);
    col += col * mh * 0.45 * high;                               // <- edita aqui: força dos realces
    col += (1.0 - col) * ms * 0.35 * shad * (1.0 - y);           // <- edita aqui: força das sombras

    // ===== CONTRASTE — curva S em volta do meio-cinza
    col = clamp(col, 0.0, 1.0);
    vec3 s = col * col * (3.0 - 2.0 * col);                      // S
    col = cont >= 0.0 ? mix(col, s, cont) : mix(col, vec3(0.5), -cont * 0.5);

    // ===== CLARIDADE — contraste local: pixel - média da vizinhança, pesado nos meios-tons
    if (abs(clar) > 0.001) {
        vec2 px = 6.0 / u_resolution;                            // <- edita aqui: raio (pixels)
        vec3 blur = vec3(0.0);
        for (int i = 0; i < 8; i++) {
            float a = float(i) * 0.785398;
            blur += pow(lin(st + px * vec2(cos(a), sin(a))), vec3(1.0 / 2.2));
            blur += pow(lin(st + px * 2.5 * vec2(cos(a + 0.39), sin(a + 0.39))), vec3(1.0 / 2.2));
        }
        blur /= 16.0;
        float mid = 1.0 - abs(luma(col) * 2.0 - 1.0);            // 1 no meio-cinza, 0 nas pontas
        col += (col - blur) * clar * 1.5 * mid;                  // <- edita aqui: força
    }

    // ===== VIBRAÇÃO / SATURAÇÃO
    y = luma(col);
    float sat = max(col.r, max(col.g, col.b)) - min(col.r, min(col.g, col.b));
    float skin = (1.0 - smoothstep(0.0, 0.1, abs(col.r - col.g - 0.12))) * step(col.b, col.g); // tons de pele
    float v = vibr * (1.0 - sat) * (1.0 - 0.6 * skin);           // pouco saturado = mais efeito
    col = mix(vec3(y), col, 1.0 + v * 1.2);
    col = mix(vec3(y), col, 1.0 + satu);                         // 0 = P&B, 1 = dobro

    gl_FragColor = vec4(clamp(col, 0.0, 1.0), 1.0);
}
