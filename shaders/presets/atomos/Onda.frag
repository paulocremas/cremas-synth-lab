// fx: forca=0.3, tamanho=0.4, velocidade=0.6
// cat: distorcao
// ATOMOS · Onda. Ondas atravessam a imagem como bandeira. forca = altura da onda; tamanho = largura; velocidade = rapidez.
#ifdef GL_ES
precision mediump float;
#endif

uniform vec2 u_resolution;
uniform sampler2D u_texture_0;   // A: a corrente
uniform float u_time;
uniform float u_fx_forca, u_fx_tamanho, u_fx_velocidade;

void main() {
    vec2 st = gl_FragCoord.xy / u_resolution;
    st.y = 1.0 - st.y;
    float f = mix(40.0, 3.0, u_fx_tamanho), t = u_time * u_fx_velocidade * 6.0;
    vec2 d = vec2(sin(st.y * f + t), cos(st.x * f * 0.8 + t * 1.3)) * u_fx_forca * 0.04;
    gl_FragColor = vec4(texture2D(u_texture_0, st + d).rgb, 1.0);
}
