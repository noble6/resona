#!/bin/sh
# Install Resona for the current user (default) or system-wide: sudo env PREFIX=/usr ./install.sh
set -e
cd "$(dirname "$0")"
PREFIX="${PREFIX:-$HOME/.local}"

for dep in pipewire pactl python3; do
    command -v "$dep" >/dev/null || { echo "missing dependency: $dep" >&2; exit 1; }
done
python3 -c 'import ctypes, numpy; ctypes.CDLL("libatomic.so.1"); from PySide6 import QtCore, QtGui, QtNetwork, QtQml, QtQuick, QtWidgets; assert tuple(map(int, QtCore.qVersion().split(".")[:2])) >= (6, 7)' 2>/dev/null || {
    echo "missing deps or Qt < 6.7. Arch: pacman -S pyside6 python-numpy gcc-libs | Fedora: dnf install python3-pyside6 python3-numpy libatomic | Debian/Ubuntu: apt install python3-pyside6.qtquick python3-pyside6.qtwidgets python3-numpy libatomic1" >&2
    exit 1
}
python3 -c 'import cryptography' 2>/dev/null || \
    echo "note: python-cryptography is not installed, so in-app updates cannot verify release signatures. Arch: pacman -S python-cryptography | Fedora: dnf install python3-cryptography | Debian/Ubuntu: apt install python3-cryptography" >&2

make -C engine
exec python3 packaging/install.py "$PREFIX"
