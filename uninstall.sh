#!/bin/sh
PREFIX="${PREFIX:-$HOME/.local}"
pkill -f "$PREFIX/share/resona/main.py" 2>/dev/null
rm -rf "$PREFIX/share/resona" "$PREFIX/lib/resona"
rm -f "$PREFIX/bin/resona" "$PREFIX/share/applications/resona.desktop" \
      "$PREFIX/share/icons/hicolor/scalable/apps/resona.svg" "${XDG_CONFIG_HOME:-$HOME/.config}/autostart/resona.desktop"
echo "Resona removed (settings kept in ${XDG_CONFIG_HOME:-$HOME/.config}/resona)"
