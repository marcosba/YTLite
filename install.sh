#!/bin/sh
# Instala YTLite en el HOME del usuario (no requiere root, salvo para apt).
set -e
cd "$(dirname "$0")"
DEST="$HOME/.local/share/ytlite"
mkdir -p "$DEST" "$HOME/.local/bin" "$HOME/.local/share/applications"
cp ytlite.py "$DEST/ytlite.py"
chmod +x "$DEST/ytlite.py"
ln -sf "$DEST/ytlite.py" "$HOME/.local/bin/ytlite"
sed "s|@HOME@|$HOME|g" ytlite.desktop > "$HOME/.local/share/applications/ytlite.desktop"
echo "Instalado. Dependencias del sistema (si faltan):"
echo "  sudo apt install mpv python3-tk ffmpeg libnotify-bin"
echo "Primer uso: abrí YTLite y andá a Herramientas > Actualizar yt-dlp"
echo "Si no aparece en el menú: desktop-menu --write-out-global  (antiX) o reiniciá el gestor de ventanas."
