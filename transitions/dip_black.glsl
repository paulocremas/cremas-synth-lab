// ms: 600
// Fade-out pro preto e fade-in da nova (dip to black).
vec4 transition(vec2 uv) {
    vec4 black = vec4(0.0, 0.0, 0.0, 1.0);
    if (progress < 0.5)
        return mix(getFromColor(uv), black, progress * 2.0);
    return mix(black, getToColor(uv), progress * 2.0 - 1.0);
}
