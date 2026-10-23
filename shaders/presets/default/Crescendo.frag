// fx: sens=0.4, cor=0.8, espelho=0.7, ecos=0.7, giro=0.6, flash=0.3, layer=1.0
// cat: tempo
// INCREMENTAL: começa quase limpo e vai empilhando camadas enquanto a música segura energia;
// no break (som cai) desmonta em ~1.5 s. Lê duas memórias que o Python guarda pro shader:
//   u_build (0..1) = crescendo: sobe ~20 s com o som acima da média recente, cai rápido no break
//   u_beats        = contador de batidas: tudo anda UM PASSO por batida (u_beats - u_kick é
//                    contínuo: no hit o beats soma 1 e o kick vai a 1, depois o kick decai)
// Estágios conforme o build: cor (já em 0.2) → espelho (0.4) → ecos (0.6) → flash (0.85).
// Sliders: cor/espelho/ecos/flash = teto de cada estágio, giro = quanto gira por batida,
//          sens = quanto a batida mexe (giro, pulo dos ecos, flash).

#ifdef GL_ES
precision mediump float;
#endif

uniform vec2 u_resolution;
uniform float u_time;
uniform sampler2D u_texture_0;
uniform float u_kick;
uniform float u_beats;
uniform float u_build;

uniform float u_fx_sens;
uniform float u_fx_cor;
uniform float u_fx_espelho;
uniform float u_fx_ecos;
uniform float u_fx_giro;
uniform float u_fx_flash;
uniform float u_fx_layer;

vec3 hsv2rgb(vec3 c) {
    vec4 k = vec4(1.0, 2.0 / 3.0, 1.0 / 3.0, 3.0);
    vec3 p = abs(fract(c.xxx + k.xyz) * 6.0 - k.www);
    return c.z * mix(k.xxx, clamp(p - k.xxx, 0.0, 1.0), c.y);
}

// estágio: 0 antes de `at`, sobe até 1 em +0.2 de build
float stage(float at) { return smoothstep(at, at + 0.2, u_build); }

void main() {
    vec2 st = gl_FragCoord.xy / u_resolution;
    st.y = 1.0 - st.y;
    vec3 orig = texture2D(u_texture_0, st).rgb;
    float aspect = u_resolution.x / u_resolution.y;
    float step_ = u_beats - u_kick;   // "relógio de batidas" contínuo

    vec2 p = st - 0.5;
    p.x *= aspect;

    // ===== GIRO: um passo por batida (desliza, não pula) =====
    float ang = step_ * 0.06 * u_fx_giro * u_fx_sens * u_build;   // <- edita aqui: radianos por batida no build cheio
    p = mat2(cos(ang), -sin(ang), sin(ang), cos(ang)) * p;

    // ===== ESPELHO (build > 0.4): fatias aumentam com o build (2 → 8) =====
    float e = stage(0.4) * u_fx_espelho;
    if (e > 0.01) {
        float n = floor(2.0 + 6.0 * u_build);
        float slice = 6.2832 / n;
        float a = abs(mod(atan(p.y, p.x), slice) - slice * 0.5);
        p = mix(p, vec2(cos(a), sin(a)) * length(p), e);
    }

    // ===== ECOS (build > 0.6): cópias encolhendo pro centro, mais cópias com mais build =====
    // média ponderada (pesos somam 1) = não estoura o branco
    float ec = stage(0.6) * u_fx_ecos;
    vec3 col = vec3(0.0);
    float wsum = 0.0;
    for (int i = 0; i < 6; i++) {
        float fi = float(i);
        if (fi > ec * 5.0 + 0.01) break;
        vec2 q = p * (1.0 + fi * (0.06 + 0.04 * u_kick * u_fx_sens));   // <- edita aqui: distância entre ecos
        q.x /= aspect;
        float w = pow(0.65, fi);
        col += texture2D(u_texture_0, fract(q + 0.5)).rgb * w;
        wsum += w;
    }
    col /= wsum;

    // ===== COR (build > 0.2): tinge pelo brilho, matiz muda a cada batida =====
    float c = stage(0.2) * u_fx_cor;
    float lum = dot(col, vec3(0.299, 0.587, 0.114));
    vec3 tint = hsv2rgb(vec3(fract(floor(u_beats) * 0.13 + lum * 0.4), 0.75, lum));
    col = mix(col, tint, c * 0.8);

    // ===== FLASH (build > 0.85): pico da tensão, piscada colorida curta na batida =====
    float f = stage(0.85) * u_fx_flash * u_fx_sens * u_kick * u_kick;
    col = mix(col, hsv2rgb(vec3(fract(u_beats * 0.21), 0.6, 0.9)), f * 0.6);

    // bordas escurecem conforme enche = foco no centro
    col *= 1.0 - 0.35 * u_build * dot(p, p);

    gl_FragColor = vec4(mix(orig, clamp(col, 0.0, 1.0), u_fx_layer), 1.0);
}
