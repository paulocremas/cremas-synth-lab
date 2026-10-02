#!/bin/bash
# Gera dist/prisma/ — pasta autocontida com o binario `prisma` (Linux) / `prisma.exe` (Windows,
# rodando no Git Bash — e' o que o CI faz). Os fontes vao soltos ao lado do binario, no mesmo
# layout do repo (src/, shaders/, transitions/, models/, dash*.html). Na abertura o launcher
# copia pra pasta de dados do usuario e roda de la (ver packaging/launcher.py).
# VERSION = $PRISMA_VERSION (CI: a tag, ex. v0.2.0) ou `git describe` (build local = dev).
# Uso: [DIST=pasta] packaging/build.sh   (PYTHON = python com numpy pygame PyOpenGL opencv pyinstaller;
#      padrao .venv/bin/python; no Windows tambem PyAudioWPatch, e o ffmpeg em $FFMPEG_DIR)
set -e
cd "$(dirname "$0")/.."
PY=${PYTHON:-.venv/bin/python}
DIST=${DIST:-dist}   # pasta de saida (teste local fora do dist/ que o atalho usa)
EXTRA=()
mkdir -p build
case "$(uname -s)" in MINGW*|MSYS*|CYGWIN*) WIN=1 ;; *) WIN= ;; esac
if [ -n "$WIN" ]; then
  "$PY" -c "from PIL import Image; Image.open('favicon.png').save('build/prisma.ico', sizes=[(16,16),(32,32),(48,48),(64,64),(128,128),(256,256)])"
  EXTRA=(--windowed --icon "$PWD/build/prisma.ico")
fi
"$PY" -m PyInstaller --noconfirm --clean --log-level ERROR \
  --name prisma --onedir "${EXTRA[@]}" \
  --collect-submodules OpenGL \
  --distpath "$DIST" --workpath build --specpath build \
  packaging/launcher.py
D=$DIST/prisma
mkdir -p "$D/src"
cp src/*.py "$D/src/"
cp dash.html dash2.html favicon.png "$D/"
cp -r shaders transitions models "$D/"
mkdir -p "$D/media"   # midia do usuario fica na pasta de dados, nao aqui
if [ -n "$WIN" ] && [ -n "$FFMPEG_DIR" ]; then
  mkdir -p "$D/ffmpeg" && cp "$FFMPEG_DIR"/ffmpeg.exe "$FFMPEG_DIR"/ffprobe.exe "$D/ffmpeg/"
fi
echo "${PRISMA_VERSION:-$(git describe --tags --always --dirty 2>/dev/null || echo dev)}" > "$D/VERSION"
echo "ok: $D ($(cat "$D/VERSION"))"
