// fx: forca=0.3, angulo=0.25
// cat: mistura
// in: src
// ATOMOS · Deslocar. Uma imagem ENTORTA a outra (o modulate do Hydra): o brilho da entrada B empurra
// os pixels da corrente. Sem B ligada = a propria fonte crua (relevo). forca = quanto empurra;
// angulo = pra onde (0 = direita, 0.25 = cima, ...).
#ifdef GL_ES
precision mediump float;
#endif

uniform vec2 u_resolution;
uniform sampler2D u_texture_0;   // a corrente
uniform sampler2D u_texture_1;   // B: quem entorta
uniform float u_fx_forca, u_fx_angulo;

void main() {
    vec2 st = gl_FragCoord.xy / u_resolution;
    st.y = 1.0 - st.y;
    float b = dot(texture2D(u_texture_1, st).rgb, vec3(0.299, 0.587, 0.114)) - 0.5;
    float a = u_fx_angulo * 6.2831853;
    vec2 d = vec2(cos(a), -sin(a)) * b * u_fx_forca * 0.3;
    gl_FragColor = vec4(texture2D(u_texture_0, st + d).rgb, 1.0);
}
