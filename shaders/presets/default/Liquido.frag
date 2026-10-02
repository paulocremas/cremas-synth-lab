// fx: liquid, layer
// Efeito ISOLADO (um por arquivo — misturar vem depois). Ondula a leitura da imagem como
// água: ruído suave (value noise) em vez de seno puro, porque ruído FLUI e seno só "vibra"
// no lugar. 2 camadas de ruído em escalas/velocidades diferentes = mais orgânico que 1 só.

#ifdef GL_ES
precision mediump float;
#endif

uniform vec2 u_resolution;
uniform float u_time;
uniform sampler2D u_texture_0;
uniform float u_amp;     // 0..1, volume geral — velocidade do fluxo (música alta = flui mais rápido)
uniform float u_subbass; // 0..1, grave puro — força da ondulação

uniform float u_fx_liquid;
uniform float u_fx_layer;

float random(vec2 p) {
    return fract(sin(dot(p, vec2(12.9898, 78.233))) * 43758.5453);
}

// ruído suave (value noise, interpolação smoothstep entre 4 hashes de grade)
float vnoise(vec2 p) {
    vec2 i = floor(p);
    vec2 f = fract(p);
    float a = random(i);
    float b = random(i + vec2(1.0, 0.0));
    float c = random(i + vec2(0.0, 1.0));
    float d = random(i + vec2(1.0, 1.0));
    vec2 u = f * f * (3.0 - 2.0 * f);
    return mix(a, b, u.x) + (c - a) * u.y * (1.0 - u.x) + (d - b) * u.x * u.y;
}

void main() {
    vec2 st = gl_FragCoord.xy / u_resolution;
    st.y = 1.0 - st.y;
    vec3 orig = texture2D(u_texture_0, st).rgb;

    // ===== LÍQUIDO — ondula a leitura da imagem como água (2 camadas de ruído) =====
    float liquid_amt = u_fx_liquid; // <- edita aqui. 0 = desligado, 1 = cheio
    if (liquid_amt > 0.0) {
        float speed = 0.04 + 0.6 * u_amp;                        // <- edita aqui: velocidade base do fluxo
        vec2 flow_uv = st * 3.0 + u_time * speed;
        float nx = 0.7 * vnoise(flow_uv) + 0.3 * vnoise(flow_uv * 2.5 - u_time * speed * 0.7);
        float ny = 0.7 * vnoise(flow_uv + 100.0) + 0.3 * vnoise(flow_uv * 2.5 + 100.0 - u_time * speed * 0.7);
        float wobble = 0.015 + 0.05 * u_subbass;                  // <- edita aqui: força do fluido
        st += (vec2(nx, ny) - 0.5) * wobble * liquid_amt;
    }

    vec3 col = texture2D(u_texture_0, st).rgb;

    // ===== CAMADA: mistura o efeito com a imagem crua (mesmo esquema do image.frag) =====
    float layer = u_fx_layer; // <- edita aqui. 0 = só original, 1 = só efeito
    col = mix(orig, col, layer);

    gl_FragColor = vec4(col, 1.0);
}
