#!/bin/bash
# Gera dist/prisma/ — pasta autocontida com o binario `prisma` (nao precisa de venv).
# Os fontes vao copiados soltos ao lado do binario, no mesmo layout do repo
# (src/, shaders/, transitions/, media/, dash.html) — hot-reload continua valendo ali.
# Uso: packaging/build.sh   (precisa de .venv com numpy pygame PyOpenGL pyinstaller)
set -e
cd "$(dirname "$0")/.."
.venv/bin/pyinstaller --noconfirm --clean --log-level ERROR \
  --name prisma --onedir \
  --collect-submodules OpenGL \
  --distpath dist --workpath build --specpath build \
  packaging/launcher.py
D=dist/prisma
mkdir -p "$D/src"
cp src/*.py "$D/src/"
cp dash.html favicon.png "$D/"
cp -r shaders transitions "$D/"
[ -d media ] && cp -r media "$D/" || mkdir -p "$D/media"
echo "ok: $D/prisma"
