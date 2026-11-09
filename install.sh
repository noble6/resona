#!/bin/sh
# Install Resona for the current user (default) or system-wide: sudo env PREFIX=/usr ./install.sh
set -e
cd "$(dirname "$0")"
PREFIX="${PREFIX:-$HOME/.local}"

for dep in pipewire pactl python3; do
    command -v "$dep" >/dev/null || { echo "missing dependency: $dep" >&2; exit 1; }
done
python3 -c 'import numpy; from PySide6 import QtCore, QtGui, QtNetwork, QtQml, QtQuick, QtWidgets; assert tuple(map(int, QtCore.qVersion().split(".")[:2])) >= (6, 7)' 2>/dev/null || {
    echo "missing Python deps or Qt < 6.7. Arch: pacman -S pyside6 python-numpy | Fedora: dnf install python3-pyside6 python3-numpy | Debian/Ubuntu: apt install python3-pyside6.qtquick python3-pyside6.qtwidgets python3-numpy" >&2
    exit 1
}

make -C engine
install -Dm755 engine/resona.so "$PREFIX/lib/resona/resona.so"
rm -rf "$PREFIX/share/resona"
mkdir -p "$PREFIX/share/resona"
cp -r app/main.py app/resona app/qml app/fonts app/icons "$PREFIX/share/resona/"
find "$PREFIX/share/resona" -name __pycache__ -prune -exec rm -rf {} +

install -Dm755 /dev/stdin "$PREFIX/bin/resona" <<SH
#!/bin/sh
export RESONA_PLUGIN="$PREFIX/lib/resona/resona.so"
exec python3 "$PREFIX/share/resona/main.py" "\$@"
SH
install -Dm644 app/icons/resona.svg "$PREFIX/share/icons/hicolor/scalable/apps/resona.svg"
install -Dm644 /dev/stdin "$PREFIX/share/applications/resona.desktop" <<DESK
[Desktop Entry]
Type=Application
Name=Resona
GenericName=Sound Enhancer
Comment=Spatial sound, DeepBass, smart EQ and loudness for PipeWire
Exec=$PREFIX/bin/resona
Icon=resona
Categories=AudioVideo;Audio;Mixer;
Keywords=equalizer;eq;bass;dolby;dts;surround;spatial;audio;effects;pipewire;
StartupWMClass=resona
DESK
command -v update-desktop-database >/dev/null && update-desktop-database -q "$PREFIX/share/applications" || true
echo "Resona installed to $PREFIX. Launch it from your app menu or run: resona"
