// fx: zoom=0.5, giro=0.5, velocidade=0.5
// cat: geometria
// ATOMOS · Rodar. Aproxima e gira a imagem em volta do centro. zoom: 0.5 = igual; giro = ângulo fixo;
// velocidade = gira sozinho (0.5 = parado; abaixo/acima = um sentido/outro).
#ifdef GL_ES
precision mediump float;
#endif

uniform vec2 u_resolution;
uniform sampler2D u_texture_0;   // A: a corrente
uniform float u_time;
uniform float u_fx_zoom, u_fx_giro, u_fx_velocidade;

void main() {
    vec2 st = gl_FragCoord.xy / u_resolution;
    st.y = 1.0 - st.y;
    vec2 p = st - 0.5;
    p.x *= u_resolution.x / u_resolution.y;
    float a = (u_fx_giro - 0.5) * 6.2831853 + u_time * (u_fx_velocidade - 0.5) * 2.0;
    p = mat2(cos(a), -sin(a), sin(a), cos(a)) * p / pow(4.0, u_fx_zoom - 0.5);
    p.x /= u_resolution.x / u_resolution.y;
    gl_FragColor = vec4(texture2D(u_texture_0, fract(p + 0.5)).rgb, 1.0);
}
