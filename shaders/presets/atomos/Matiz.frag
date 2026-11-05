// fx: giro=0.25
// cat: cor
// mod: giro=anda
// ATOMOS · Matiz. Gira todas as cores no círculo (vermelho vira verde...). giro = quanto gira (0 e 1 = nada).

uniform float u_fx_giro;

void main() {
    vec4 c = A(uv());
    const vec3 k = vec3(0.57735);
    float a = u_fx_giro * 6.2831853;
    gl_FragColor = vec4(clamp(c.rgb * cos(a) + cross(k, c.rgb) * sin(a) + k * dot(k, c.rgb) * (1.0 - cos(a)), 0.0, 1.0), c.a);
}
