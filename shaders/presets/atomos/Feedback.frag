// fx: rastro=0.85, zoom=0.5, giro=0.5, matiz=0.5
// cat: tempo
// in: fb
// ATOMOS · Feedback. A imagem volta em cima dela mesma com 1 frame de atraso (o LocalIn/LocalOut do
// SuperCollider): o que vem antes na corrente deixa RASTRO. rastro = quanto o frame velho dura;
// zoom/giro = o rastro cresce/encolhe e gira (0.5 = parado); matiz = o rastro muda de cor a cada volta.
#ifdef GL_ES
precision mediump float;
#endif

uniform vec2 u_resolution;
uniform sampler2D u_texture_0;   // a corrente
uniform sampler2D u_texture_1;   // a saida desta raia no frame anterior (ins: fb)
uniform float u_fx_rastro, u_fx_zoom, u_fx_giro, u_fx_matiz;

vec3 hue(vec3 c, float h) {   // gira o matiz (rotacao no eixo cinza)
    const vec3 k = vec3(0.57735);
    float a = h * 6.2831853;
    return c * cos(a) + cross(k, c) * sin(a) + k * dot(k, c) * (1.0 - cos(a));
}

void main() {
    vec2 st = gl_FragCoord.xy / u_resolution;
    st.y = 1.0 - st.y;
    vec3 cur = texture2D(u_texture_0, st).rgb;
    vec2 p = st - 0.5;
    float a = (u_fx_giro - 0.5) * 0.1;
    p = mat2(cos(a), -sin(a), sin(a), cos(a)) * p / (1.0 + (u_fx_zoom - 0.5) * 0.08);
    vec3 old = hue(texture2D(u_texture_1, p + 0.5).rgb, (u_fx_matiz - 0.5) * 0.1) * u_fx_rastro;
    gl_FragColor = vec4(max(cur, clamp(old, 0.0, 1.0)), 1.0);
}
