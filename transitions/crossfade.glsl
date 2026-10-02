// ms: 400
// Transição de mídia (estilo gl-transitions). Recebe:
//   getFromColor(uv) = imagem que SAI (A)   getToColor(uv) = imagem que ENTRA (B)
//   progress = 0.0 -> 1.0 ao longo de `ms` (cabeçalho acima; ausente = 400)
// Devolve o pixel misturado em `uv` (0..1). GLSL ES 1.00 (texture2D, sem #version).
vec4 transition(vec2 uv) {
    return mix(getFromColor(uv), getToColor(uv), progress);
}
