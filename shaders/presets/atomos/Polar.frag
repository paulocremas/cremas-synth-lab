// fx: forca=0.6, sentido=0, giro=0.5
// opcoes: sentido=enrolar|desenrolar
// cat: geometria
// bipolar: giro
// mod: giro=anda
// ATOMOS · Polar. Reto vira circular: enrolar faz as linhas horizontais virarem ANÉIS e as verticais, RAIOS (o
// topo da imagem vai pro centro); desenrolar faz o contrário (anéis viram listras). forca = quanto (0 = nada; no
// meio, a imagem se curva); giro = gira os anéis (0.5 = parado).

uniform float u_fx_forca, u_fx_sentido, u_fx_giro;

void main() {
    vec2 st = uv();
    vec2 q;
    if (floor(u_fx_sentido * 1.999) < 0.5) {
        vec2 p = asp(st);
        q = vec2(fract(atan(p.y, p.x) / 6.2831853 + 0.5 + u_fx_giro - 0.5), length(p) * 2.0);
    } else {
        float a = (st.x - u_fx_giro) * 6.2831853, r = st.y * 0.5;
        q = desasp(vec2(-cos(a), -sin(a)) * r);
    }
    gl_FragColor = A(mix(st, q, u_fx_forca));
}
