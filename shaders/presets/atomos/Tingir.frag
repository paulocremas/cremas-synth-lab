// fx: matiz=0.6, forca=0.8
// cat: cor
// ATOMOS · Tingir. Pinta a imagem de UMA cor, guardando o claro e o escuro (duotone de uma cor só).
// matiz = a cor; forca = quanto da cor original some.
#ifdef GL_ES
precision mediump float;
#endif

uniform vec2 u_resolution;
uniform sampler2D u_texture_0;   // A: a corrente
uniform float u_fx_matiz, u_fx_forca;

vec3 hsv(float h) { return clamp(abs(fract(h + vec3(0.0, 2.0, 1.0) / 3.0) * 6.0 - 3.0) - 1.0, 0.0, 1.0); }

void main() {
    vec2 st = gl_FragCoord.xy / u_resolution;
    st.y = 1.0 - st.y;
    vec3 c = texture2D(u_texture_0, st).rgb;
    float l = dot(c, vec3(0.299, 0.587, 0.114));
    gl_FragColor = vec4(mix(c, hsv(u_fx_matiz) * l * 1.6, u_fx_forca), 1.0);
}
