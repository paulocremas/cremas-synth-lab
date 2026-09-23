// fx: particles, layer
// Efeito ISOLADO (um por arquivo — misturar vem depois). Pontinhos coloridos flutuando por
// cima da cena — ADITIVO, então não mexe na UV de leitura da imagem (o fundo nunca fica
// escondido por causa deles). Busca nas 9 células vizinhas (3x3) pra cada partícula poder
// derivar sem "pular" quando cruza a borda da própria célula.

#ifdef GL_ES
precision mediump float;
#endif

uniform vec2 u_resolution;
uniform float u_time;
uniform sampler2D u_texture_0;
uniform float u_treble;   // 0..1, agudo — velocidade da deriva
uniform float u_mid;      // 0..1, medio — velocidade do giro de matiz de cada partícula
uniform float u_kick;     // 0..1, pula na batida e decai sozinho — pulso de tamanho
uniform float u_presence; // 0..1, faixa ~4-6kHz — tamanho base de cada partícula

uniform float u_fx_particles;
uniform float u_fx_layer;

float random(vec2 p) {
    return fract(sin(dot(p, vec2(12.9898, 78.233))) * 43758.5453);
}

vec3 hsv2rgb(vec3 c) {
    vec4 k = vec4(1.0, 2.0 / 3.0, 1.0 / 3.0, 3.0);
    vec3 p = abs(fract(c.xxx + k.xyz) * 6.0 - k.www);
    return c.z * mix(k.xxx, clamp(p - k.xxx, 0.0, 1.0), c.y);
}

vec3 particles(vec2 uv) {
    vec3 acc = vec3(0.0);
    float grid = 12.0;                      // <- edita aqui: densidade (nº de células por eixo)
    vec2 cell = floor(uv * grid);
    float speed = 0.3 + 0.9 * u_treble;     // <- edita aqui: agudo acelera a deriva
    for (int y = -1; y <= 1; y++) {
        for (int x = -1; x <= 1; x++) {
            vec2 c = cell + vec2(float(x), float(y));
            float rnd = random(c);
            vec2 drift = 0.45 * vec2(sin(u_time * speed * 0.6 + rnd * 6.2831),
                                      cos(u_time * speed * 0.5 + rnd * 6.2831));
            vec2 center = (c + 0.5 + drift) / grid;
            float kick_pulse = 1.0 + 1.3 * u_kick * random(c + 1.7); // cada uma reage um pouco diferente
            float size = (0.003 + 0.01 * u_presence) * kick_pulse;   // <- edita aqui: tamanho base
            float d = length(uv - center);
            float core = smoothstep(size, 0.0, d);
            float halo = smoothstep(size * 4.0, 0.0, d) * 0.3;       // brilho suave ao redor do núcleo
            float hue = fract(rnd + u_time * 0.15 + u_mid * 0.3);    // matiz girando sozinho = psicodélico
            acc += hsv2rgb(vec3(hue, 0.95, 1.0)) * (core + halo);
        }
    }
    return acc;
}

void main() {
    vec2 st = gl_FragCoord.xy / u_resolution;
    st.y = 1.0 - st.y;
    vec3 orig = texture2D(u_texture_0, st).rgb;

    // ===== PARTÍCULAS — soma o glow colorido em cima da imagem =====
    vec3 col = orig + particles(st) * u_fx_particles * (0.4 + 0.8 * u_presence);

    // ===== CAMADA: mistura o efeito com a imagem crua (mesmo esquema do image.frag) =====
    float layer = u_fx_layer; // <- edita aqui. 0 = só original, 1 = só efeito
    col = mix(orig, col, layer);

    gl_FragColor = vec4(col, 1.0);
}
