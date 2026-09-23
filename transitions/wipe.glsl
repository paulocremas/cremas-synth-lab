// ms: 500
// Cortina da esquerda pra direita, com uma borda suave de 6%.
vec4 transition(vec2 uv) {
    float edge = smoothstep(uv.x - 0.06, uv.x + 0.06, progress);
    return mix(getFromColor(uv), getToColor(uv), edge);
}
