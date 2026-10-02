#!/bin/bash
# Gera dist/prisma_<versao>_amd64.deb — instalador completo do PRISMA!:
#   /opt/prisma (binario + fontes), comando `prisma`, atalho "PRISMA!" no menu,
#   e as dependencias de sistema (ffmpeg, parec, xrandr...) puxadas pelo apt.
# Instalar: sudo apt install ./dist/prisma_<versao>_amd64.deb   (remover: sudo apt remove prisma)
# Dados do usuario ficam em ~/.local/share/prisma/ (ver packaging/launcher.py).
set -e
cd "$(dirname "$0")/.."
DIST=${DIST:-dist}; export DIST
packaging/build.sh
VER=$(cat "$DIST/prisma/VERSION")            # tag (v0.2.0) no CI; build local = git describe
VER=${VER#v}; [[ "$VER" =~ ^[0-9] ]] || VER="0.0.0+$VER"   # versao do .deb tem que comecar com digito
VER=${VER//-/\~}                         # 0.1.0-beta.1 -> 0.1.0~beta.1 (dpkg: ~ vem ANTES da final)
PKG=build/deb
rm -rf "$PKG"
mkdir -p "$PKG/DEBIAN" "$PKG/opt" "$PKG/usr/bin" "$PKG/usr/share/applications" "$PKG/usr/share/pixmaps"
cp -r "$DIST/prisma" "$PKG/opt/prisma"
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
StartupWMClass=prisma
Categories=AudioVideo;Graphics;
DESKTOP
cat > "$PKG/DEBIAN/control" <<CONTROL
Package: prisma
Version: $VER
Architecture: amd64
Maintainer: cremas <cremascopaulo@gmail.com>
Depends: ffmpeg, pulseaudio-utils, x11-xserver-utils
Recommends: wmctrl, x11-utils, imagemagick, v4l-utils, xdg-utils, policykit-1
Section: video
Priority: optional
Description: PRISMA! - sintese de imagem GLSL reagindo ao audio
 Captura webcam/tela/midia + audio do sistema, faz FFT e alimenta um shader
 GLSL em tempo real. Dashboard HTML em http://127.0.0.1:8765.
CONTROL
OUT="$DIST/prisma_${VER}_amd64.deb"
fakeroot dpkg-deb --build -Zxz "$PKG" "$OUT" >/dev/null
echo "ok: $OUT"
