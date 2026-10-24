// fx: quantos=0.3, giro=0.5
// cat: geometria
// ATOMOS · Fatias. Repete uma fatia em volta do centro. quantos = de 2 a 16 fatias; giro = gira (0.5 = parado).
#ifdef GL_ES
precision mediump float;
#endif

uniform vec2 u_resolution;
uniform sampler2D u_texture_0;   // A: a corrente
uniform float u_time;
uniform float u_fx_quantos, u_fx_giro;

void main() {
    vec2 st = gl_FragCoord.xy / u_resolution;
    st.y = 1.0 - st.y;
    vec2 p = st - 0.5;
    p.x *= u_resolution.x / u_resolution.y;
    float n = floor(2.0 + u_fx_quantos * 14.0), s = 6.2831853 / n;
    float a = atan(p.y, p.x) + u_time * (u_fx_giro - 0.5) * 2.0;
    a = abs(mod(a, s) - s * 0.5);
    vec2 q = vec2(cos(a), sin(a)) * length(p);
    q.x /= u_resolution.x / u_resolution.y;
    gl_FragColor = vec4(texture2D(u_texture_0, q + 0.5).rgb, 1.0);
}
