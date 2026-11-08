# Contributing to Resona

Thanks for helping make Linux sound better! 🎧

## Layout
- `engine/`: the C DSP (LADSPA). Realtime rules: no allocation, locks or syscalls in `run()`.
- `app/resona/`: Python backend (PipeWire plumbing, hardware detection, AutoEq/DDC/IR parsing, presets).
- `app/qml/`: the Material 3 Expressive UI. Components live in `qml/components/`.
- `tests/`: offline DSP tests (C), unit tests and live PipeWire tests (Python).

## Before you open a PR
```sh
make -C engine test
python3 tests/test_units.py
python3 tests/test_pipewire.py        # needs a running PipeWire session; silent (null sinks)
```
To check UI changes headlessly:
`RESONA_SCREENSHOT=/tmp/shots RESONA_TEST_TARGET=<null sink> QT_QPA_PLATFORM=offscreen python3 app/main.py`

## Good first contributions
- New sound profiles or EQ presets (`app/resona/presets.py`)
- App → profile rules for more players and games (`APP_RULES_DEFAULT`)
- Distro packages (Flatpak, Fedora COPR, Debian), translations
- DSP ideas: open an issue with a short description and, ideally, a reference

## Notes
- Mirror any change to `engine/resona_shm.h` in `app/resona/shm.py`; the tests check that they match.
- QML gotcha: theme roles must not be named `onSomething` (it clashes with signal handlers). Use `ink*`.
- Licensing: contributions are GPL-3.0-or-later. Never add proprietary code or binaries.
