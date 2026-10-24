// fx: giro=0.25
// cat: cor
// ATOMOS · Matiz. Gira todas as cores no círculo (vermelho vira verde...). giro = quanto gira (0 e 1 = nada).
#ifdef GL_ES
precision mediump float;
#endif

uniform vec2 u_resolution;
uniform sampler2D u_texture_0;   // A: a corrente
uniform float u_fx_giro;

void main() {
    vec2 st = gl_FragCoord.xy / u_resolution;
    st.y = 1.0 - st.y;
    vec3 c = texture2D(u_texture_0, st).rgb;
    const vec3 k = vec3(0.57735);
    float a = u_fx_giro * 6.2831853;
    gl_FragColor = vec4(clamp(c * cos(a) + cross(k, c) * sin(a) + k * dot(k, c) * (1.0 - cos(a)), 0.0, 1.0), 1.0);
}
