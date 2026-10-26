// fx: matiz=0.33, limiar=0.15, borda=0.3
// cat: mascara
// ATOMOS · Cor. Máscara de uma cor da entrada (chroma key). matiz = a cor (0 vermelho, 0.33 verde,
// 0.66 azul); limiar = quão larga a faixa de cor; borda = macia/dura. Cinza/preto/branco ficam de fora.
#ifdef GL_ES
precision mediump float;
#endif

uniform vec2 u_resolution;
uniform sampler2D u_texture_0;   // a entrada da caixa
uniform float u_fx_matiz, u_fx_limiar, u_fx_borda;

vec3 hsv(vec3 c) {
    vec4 K = vec4(0.0, -1.0 / 3.0, 2.0 / 3.0, -1.0);
    vec4 p = mix(vec4(c.bg, K.wz), vec4(c.gb, K.xy), step(c.b, c.g));
    vec4 q = mix(vec4(p.xyw, c.r), vec4(c.r, p.yzx), step(p.x, c.r));
    float d = q.x - min(q.w, q.y);
    return vec3(abs(q.z + (q.w - q.y) / (6.0 * d + 1e-10)), d / (q.x + 1e-10), q.x);
}

void main() {
    vec2 st = gl_FragCoord.xy / u_resolution;
    st.y = 1.0 - st.y;
    vec3 c = hsv(texture2D(u_texture_0, st).rgb);
    float d = abs(fract(c.x - u_fx_matiz + 0.5) - 0.5) * 2.0;   // 0 = a cor, 1 = a oposta
    float w = 0.02 + u_fx_limiar * 0.5, h = u_fx_borda * w + 1e-3;
    float m = (1.0 - smoothstep(w - h, w + h, d)) * smoothstep(0.1, 0.25, c.y) * smoothstep(0.05, 0.15, c.z);
    gl_FragColor = vec4(vec3(m), 1.0);
}
