#!/bin/bash
# Gera dist/prisma/ — pasta autocontida com o binario `prisma` (nao precisa de venv).
# Os fontes vao soltos ao lado do binario, no mesmo layout do repo
# (src/, shaders/, transitions/, dash.html). Na 1a abertura o launcher copia pra
# ~/.local/share/prisma/ e roda de la (hot-reload + dados do usuario ficam la, fora do dist/).
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
cp dash.html dash2.html favicon.png "$D/"
cp -r shaders transitions "$D/"
mkdir -p "$D/media"   # midia do usuario fica em ~/.local/share/prisma/media, nao aqui
echo "ok: $D/prisma"
