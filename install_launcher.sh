#!/bin/bash
# Cria um lançador de app (duplo-clique, sem terminal) pro src/native_synth.py.
# Roda uma vez: ./install_launcher.sh   — re-rodar atualiza o lançador.
# ponytail: um .desktop, não um binário congelado. native_synth.py depende de
# ffmpeg/parec/xrandr/wmctrl/import e do navegador — PyInstaller não bundla nada
# disso, só somaria manutenção. O que falta é um atalho, e isso é um .desktop.
set -e
cd "$(dirname "$0")"
DIR=$(pwd)
NAME=prisma-synth.desktop
APPS=~/.local/share/applications/$NAME

cat > "$APPS" <<EOF
[Desktop Entry]
Type=Application
Name=PRISMA synth
Comment=native_synth.py — síntese GLSL + áudio, com dashboard
Exec=bash -c "cd '$DIR' && ./watch_synth.sh > synth.log 2>&1"
Path=$DIR
Icon=$DIR/favicon.png
Terminal=false
Categories=AudioVideo;
EOF
chmod +x "$APPS"

# atalho no Desktop também
if [ -d ~/Desktop ]; then
  cp "$APPS" ~/Desktop/$NAME
  chmod +x ~/Desktop/$NAME
  gio set ~/Desktop/$NAME metadata::trusted true 2>/dev/null || true
fi
update-desktop-database ~/.local/share/applications 2>/dev/null || true

echo "Pronto."
echo " - menu do Cinnamon: procure 'PRISMA synth'"
echo " - ícone no Desktop: se pedir, botão direito -> 'Permitir execução'"
echo " - saída/erros da última execução: $DIR/synth.log"
