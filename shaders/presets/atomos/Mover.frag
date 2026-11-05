// fx: x=0.5, y=0.5
// cat: geometria
// bipolar: x, y
// mod: x=acaso
// ATOMOS · Mover. Empurra a imagem pro lado e pra cima/baixo (o que sai de um lado volta pelo outro). x e y: 0.5 =
// no lugar. Sozinho fica parado: um controlador no x/y faz tremer (acaso), deslizar (serra) ou balançar (seno).

uniform float u_fx_x, u_fx_y;

void main() {
    gl_FragColor = A(fract(uv() - vec2(u_fx_x - 0.5, 0.5 - u_fx_y)));
}
