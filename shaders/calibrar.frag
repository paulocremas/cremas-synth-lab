// fx: temperatura=0.5, matiz=0.5, exposicao=0.5, contraste=0.5, realces=0.5, sombras=0.5, brancos=0.5, pretos=0.5, claridade=0.5, neblina=0.5, vibracao=0.5, saturacao=0.5, vermelho=0.5, verde=0.5, azul=0.5, gama=0.5
// CALIBRAÇÃO DA SAÍDA (telão/projetor) — último passe do loop GL, depois das fontes e da
// transição de set: a imagem final inteira passa por aqui antes de ir pra tela. Fora da pilha
// de efeitos (não aparece na mesa); knobs na aba Output Image, valores em tuning.OUTPUT_GRADE.
// Mesmo painel "Básico" do Lightroom do presets/default/Revelar.frag (0.5 = neutro) + o que
// um telão costuma pedir: ganho por canal (vermelho/verde/azul — acerta o branco do projetor)
// e gama (curva de meios-tons do aparelho). u_test = 1 troca a imagem por um padrão de teste
// (barras de cor, rampa de cinza, degraus perto do preto e do branco), que passa pela mesma
// correção — é nele que se calibra.
// A textura aqui é a saída já montada, na orientação do GL (sem o st.y = 1.0 - st.y dos presets).

#ifdef GL_ES
precision mediump float;
#endif

uniform vec2 u_resolution;
uniform sampler2D u_texture_0;
uniform int u_test;
uniform float u_dim;             // MASTER do dash v2: 0 = inteiro, 1 = blackout (0 = padrao do GL -> neutro)

uniform float u_fx_temperatura;
uniform float u_fx_matiz;
uniform float u_fx_exposicao;
uniform float u_fx_contraste;
uniform float u_fx_realces;
uniform float u_fx_sombras;
uniform float u_fx_brancos;
uniform float u_fx_pretos;
uniform float u_fx_claridade;
uniform float u_fx_neblina;
uniform float u_fx_vibracao;
uniform float u_fx_saturacao;
uniform float u_fx_vermelho;    // ganho do canal R (0.5 = 1x; 0 = 0.5x, 1 = 1.5x)
uniform float u_fx_verde;
uniform float u_fx_azul;
uniform float u_fx_gama;        // 0.5 = 1.0; 0 = 0.5 (clareia meios-tons), 1 = 2.0 (escurece)

float luma(vec3 c) { return dot(c, vec3(0.2126, 0.7152, 0.0722)); }

// padrão de teste em p (0..1, y = 0 embaixo). De cima pra baixo: barras de cor 75%, rampa
// contínua de cinza, 11 degraus (0..100%), degraus perto do preto (0..10%) e do branco (90..100%).
vec3 testPattern(vec2 p) {
    float y = 1.0 - p.y;
    if (y < 0.40) {
        int i = int(floor(p.x * 7.0));
        vec3 bars[7];
        bars[0] = vec3(0.75); bars[1] = vec3(0.75, 0.75, 0.0); bars[2] = vec3(0.0, 0.75, 0.75);
        bars[3] = vec3(0.0, 0.75, 0.0); bars[4] = vec3(0.75, 0.0, 0.75); bars[5] = vec3(0.75, 0.0, 0.0);
        bars[6] = vec3(0.0, 0.0, 0.75);
        for (int k = 0; k < 7; k++) if (k == i) return bars[k];
        return vec3(0.0);
    }
    if (y < 0.55) return vec3(p.x);
    if (y < 0.70) return vec3(floor(p.x * 11.0) / 10.0);
    if (y < 0.85) return vec3(floor(p.x * 11.0) / 100.0);
    return vec3(0.9 + floor(p.x * 11.0) / 100.0);
}

vec3 src(vec2 p) {
    return u_test == 1 ? testPattern(p) : texture2D(u_texture_0, p).rgb;
}
vec3 lin(vec2 p) { return pow(src(p), vec3(2.2)); }

void main() {
    vec2 st = gl_FragCoord.xy / u_resolution;
    vec3 col = lin(st);

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

    // ===== BALANÇO DE BRANCO
    vec3 wb = vec3(1.0 + 0.30 * temp, 1.0, 1.0 - 0.30 * temp);
    wb *= vec3(1.0 + 0.15 * tint, 1.0 - 0.25 * tint, 1.0 + 0.15 * tint);
    col *= wb / luma(wb);

    // ===== EXPOSIÇÃO (±2 stops)
    col *= exp2(expo * 2.0);

    // ===== NEBLINA
    float veil = 0.08 * haze;
    col = (col - veil) / (1.0 - veil);
    col = mix(col, col * col * 1.4, max(haze, 0.0) * 0.25);

    col = pow(max(col, 0.0), vec3(1.0 / 2.2));
    float y = luma(col);

    // ===== BRANCOS / PRETOS
    float bp = -0.10 * blak;
    float wp = 1.0 - 0.20 * whit;
    col = (col - bp) / max(wp - bp, 0.05);

    // ===== REALCES / SOMBRAS
    float mh = smoothstep(0.45, 1.0, y);
    float ms = 1.0 - smoothstep(0.0, 0.55, y);
    col += col * mh * 0.45 * high;
    col += (1.0 - col) * ms * 0.35 * shad * (1.0 - y);

    // ===== CONTRASTE
    col = clamp(col, 0.0, 1.0);
    vec3 s = col * col * (3.0 - 2.0 * col);
    col = cont >= 0.0 ? mix(col, s, cont) : mix(col, vec3(0.5), -cont * 0.5);

    // ===== CLARIDADE
    if (abs(clar) > 0.001) {
        vec2 px = 6.0 / u_resolution;
        vec3 blur = vec3(0.0);
        for (int i = 0; i < 8; i++) {
            float a = float(i) * 0.785398;
            blur += pow(lin(st + px * vec2(cos(a), sin(a))), vec3(1.0 / 2.2));
            blur += pow(lin(st + px * 2.5 * vec2(cos(a + 0.39), sin(a + 0.39))), vec3(1.0 / 2.2));
        }
        blur /= 16.0;
        float mid = 1.0 - abs(luma(col) * 2.0 - 1.0);
        col += (col - blur) * clar * 1.5 * mid;
    }

    // ===== VIBRAÇÃO / SATURAÇÃO
    y = luma(col);
    float sat = max(col.r, max(col.g, col.b)) - min(col.r, min(col.g, col.b));
    float skin = (1.0 - smoothstep(0.0, 0.1, abs(col.r - col.g - 0.12))) * step(col.b, col.g);
    float v = vibr * (1.0 - sat) * (1.0 - 0.6 * skin);
    col = mix(vec3(y), col, 1.0 + v * 1.2);
    col = mix(vec3(y), col, 1.0 + satu);

    // ===== CALIBRAÇÃO DO APARELHO — por último, é a correção "física" do telão
    col = clamp(col, 0.0, 1.0);
    col *= vec3(u_fx_vermelho, u_fx_verde, u_fx_azul) + 0.5;     // ganho por canal (0.5..1.5x)
    col = pow(clamp(col, 0.0, 1.0), vec3(exp2(u_fx_gama * 2.0 - 1.0)));  // gama 0.5..2.0

    // ===== MASTER (dash v2) — escurece tudo, inclusive o padrão de teste
    col *= 1.0 - clamp(u_dim, 0.0, 1.0);

    gl_FragColor = vec4(clamp(col, 0.0, 1.0), 1.0);
}
