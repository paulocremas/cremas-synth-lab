#!/bin/bash
# Instala o PRISMA! no usuario (sem sudo): entrada no menu de aplicativos + comando `prisma`.
# Aponta pro dist/prisma/ deste repo (binario PyInstaller; alternativa sem build: ../install_launcher.sh) — rodar packaging/build.sh antes.
set -e
cd "$(dirname "$0")/.."
DIST="$PWD/dist/prisma"
[ -x "$DIST/prisma" ] || { echo "falta $DIST/prisma — rode packaging/build.sh"; exit 1; }
mkdir -p ~/.local/bin ~/.local/share/applications
ln -sf "$DIST/prisma" ~/.local/bin/prisma
cat > ~/.local/share/applications/prisma.desktop <<DESKTOP
[Desktop Entry]
Type=Application
Name=PRISMA!
Comment=Sintese de imagem reagindo ao audio
Exec=$DIST/prisma
Path=$DIST
Icon=$DIST/favicon.png
Terminal=false
StartupWMClass=prisma
Categories=AudioVideo;Graphics;
DESKTOP
update-desktop-database ~/.local/share/applications 2>/dev/null || true
echo "ok: PRISMA! no menu de aplicativos; comando 'prisma' em ~/.local/bin"
