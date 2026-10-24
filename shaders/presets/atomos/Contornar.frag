// fx: limiar=0.15, borda=0.5
// cat: forma
// ATOMOS · Contornar. Desenha SÓ as linhas das bordas, brancas, por cima do que vem antes (alfa = linha).
// Um Tingir depois pinta tudo; pra pintar só as linhas, solte o Tingir EM CIMA do Contornar (paralelo).
// limiar = a partir de que diferença vira linha; borda = linha dura (0) ou macia (1).
#ifdef GL_ES
precision mediump float;
#endif

uniform vec2 u_resolution;
uniform sampler2D u_texture_0;   // A: a corrente
uniform float u_fx_limiar, u_fx_borda;

float lum(vec2 p) { return dot(texture2D(u_texture_0, p).rgb, vec3(0.299, 0.587, 0.114)); }

void main() {
    vec2 st = gl_FragCoord.xy / u_resolution;
    st.y = 1.0 - st.y;
    vec2 e = 1.0 / u_resolution;
    float gx = lum(st + vec2(e.x, 0.0)) - lum(st - vec2(e.x, 0.0));
    float gy = lum(st + vec2(0.0, e.y)) - lum(st - vec2(0.0, e.y));
    float g = length(vec2(gx, gy)) * 4.0;
    float w = 0.02 + u_fx_borda * 0.3;
    float a = smoothstep(u_fx_limiar - w, u_fx_limiar + w, g);
    gl_FragColor = vec4(vec3(1.0), a);
}
