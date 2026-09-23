#!/bin/bash
# Gera dist/prisma_<versao>_amd64.deb — instalador completo do PRISMA!:
#   /opt/prisma (binario + fontes), comando `prisma`, atalho "PRISMA!" no menu,
#   e as dependencias de sistema (ffmpeg, parec, xrandr...) puxadas pelo apt.
# Instalar: sudo apt install ./dist/prisma_<versao>_amd64.deb   (remover: sudo apt remove prisma)
# Dados do usuario ficam em ~/.local/share/prisma/ (ver packaging/launcher.py).
set -e
cd "$(dirname "$0")/.."
packaging/build.sh
VER="0.$(git rev-list --count HEAD)+$(git rev-parse --short HEAD)"
PKG=build/deb
rm -rf "$PKG"
mkdir -p "$PKG/DEBIAN" "$PKG/opt" "$PKG/usr/bin" "$PKG/usr/share/applications" "$PKG/usr/share/pixmaps"
cp -r dist/prisma "$PKG/opt/prisma"
ln -s /opt/prisma/prisma "$PKG/usr/bin/prisma"
cp favicon.png "$PKG/usr/share/pixmaps/prisma.png"
cat > "$PKG/usr/share/applications/prisma.desktop" <<DESKTOP
[Desktop Entry]
Type=Application
Name=PRISMA!
Comment=Sintese de imagem reagindo ao audio
Exec=prisma
Icon=prisma
Terminal=false
Categories=AudioVideo;Graphics;
DESKTOP
cat > "$PKG/DEBIAN/control" <<CONTROL
Package: prisma
Version: $VER
Architecture: amd64
Maintainer: cremas <cremascopaulo@gmail.com>
Depends: ffmpeg, pulseaudio-utils, x11-xserver-utils
Recommends: wmctrl, x11-utils, imagemagick, v4l-utils, xdg-utils
Section: video
Priority: optional
Description: PRISMA! - sintese de imagem GLSL reagindo ao audio
 Captura webcam/tela/midia + audio do sistema, faz FFT e alimenta um shader
 GLSL em tempo real. Dashboard HTML em http://127.0.0.1:8765.
CONTROL
OUT="dist/prisma_${VER}_amd64.deb"
fakeroot dpkg-deb --build -Zxz "$PKG" "$OUT" >/dev/null
echo "ok: $OUT"
