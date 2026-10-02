// fx: colorvibe, layer
// Efeito ISOLADO (um por arquivo — misturar vem depois). Gira o matiz da imagem aos poucos
// (satura + roda a roda de cores) e tinge com um "plasma" clássico (soma de senos em
// posição+tempo) — só que cada canal de cor do plasma é literalmente pilotado por uma faixa
// diferente da música (R=grave, G=médio, B=agudo). u_amp (volume geral) acelera tudo.

#ifdef GL_ES
precision mediump float;
#endif

uniform vec2 u_resolution;
uniform float u_time;
uniform sampler2D u_texture_0;
uniform float u_amp;    // 0..1, volume geral — velocidade do plasma e do giro de matiz
uniform float u_bass;   // 0..1, grave — canal R do plasma
uniform float u_mid;    // 0..1, medio — canal G do plasma + saturacao/velocidade do giro
uniform float u_treble; // 0..1, agudo — canal B do plasma

uniform float u_fx_colorvibe;
uniform float u_fx_layer;

vec3 rgb2hsv(vec3 c) {
    vec4 k = vec4(0.0, -1.0 / 3.0, 2.0 / 3.0, -1.0);
    vec4 p = mix(vec4(c.bg, k.wz), vec4(c.gb, k.xy), step(c.b, c.g));
    vec4 q = mix(vec4(p.xyw, c.r), vec4(c.r, p.yzx), step(p.x, c.r));
    float d = q.x - min(q.w, q.y);
    float e = 1.0e-10;
    return vec3(abs(q.z + (q.w - q.y) / (6.0 * d + e)), d / (q.x + e), q.x);
}
vec3 hsv2rgb(vec3 c) {
    vec4 k = vec4(1.0, 2.0 / 3.0, 1.0 / 3.0, 3.0);
    vec3 p = abs(fract(c.xxx + k.xyz) * 6.0 - k.www);
    return c.z * mix(k.xxx, clamp(p - k.xxx, 0.0, 1.0), c.y);
}

void main() {
    vec2 st = gl_FragCoord.xy / u_resolution;
    st.y = 1.0 - st.y;
    vec3 orig = texture2D(u_texture_0, st).rgb;
    vec3 col = orig;

    // ===== COR PSICODÉLICA — gira o matiz + tinge com um plasma RGB=grave/médio/agudo =====
    float colorvibe_amt = u_fx_colorvibe; // <- edita aqui. 0 = cor original, 1 = psicodélico total
    if (colorvibe_amt > 0.0) {
        vec3 hsv = rgb2hsv(col);
        hsv.y = clamp(hsv.y * (1.0 + 0.7 * u_mid), 0.0, 1.0);       // <- edita aqui: força da saturação
        hsv.x = fract(hsv.x + u_time * 0.05 * (0.2 + u_mid));       // <- edita aqui: velocidade do giro
        vec3 shifted = hsv2rgb(hsv);

        float speed = 0.6 + 1.8 * u_amp;                            // <- edita aqui: velocidade do plasma
        float p1 = sin(st.x * 8.0 + u_time * speed + u_bass * 6.0);
        float p2 = sin(st.y * 8.0 - u_time * speed * 1.3 + u_mid * 6.0);
        float p3 = sin((st.x + st.y) * 8.0 + u_time * speed * 0.7 + u_treble * 6.0);
        vec3 plasma = 0.5 + 0.5 * vec3(p1, p2, p3);

        col = mix(col, shifted * plasma * 1.4, colorvibe_amt);
    }

    // ===== CAMADA: mistura o efeito com a imagem crua (mesmo esquema do image.frag) =====
    float layer = u_fx_layer; // <- edita aqui. 0 = só original, 1 = só efeito
    col = mix(orig, col, layer);

    gl_FragColor = vec4(col, 1.0);
}
