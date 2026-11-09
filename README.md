<div align="center">

<img src="app/icons/resona.svg" width="96" alt="Resona logo">

# Resona

### The sound enhancer Linux never had.

Spatial audio, psychoacoustic bass, Intelligent EQ, headphone correction for about 8,800 models,<br>
surround upmixing for HDMI and optical, and Hi-Res playback, all in one native PipeWire engine<br>
with a Material 3 Expressive interface.

[![CI](https://github.com/noble6/resona/actions/workflows/ci.yml/badge.svg)](https://github.com/noble6/resona/actions/workflows/ci.yml)
![License](https://img.shields.io/badge/license-GPL--3.0-8B5CF6)
![PipeWire](https://img.shields.io/badge/PipeWire-native-22D3B6)
![DSP](https://img.shields.io/badge/DSP-C%20%C2%B7%20lock--free-FF5E7E)
![Latency](https://img.shields.io/badge/latency-1.5%20ms-FFB224)

<img src="docs/demo.gif" width="860" alt="Resona demo: a morphing power button and a live before/after spectrum">

</div>

---

Windows laptops ship with Dolby Atmos, DTS:X or a Realtek console. Android has Dolby, ViPER and JamesDSP. On Linux you hand-wire plugin chains in EasyEffects and hope.

**Resona is one switch.** Pick a profile (Music, Movie, Gaming, Voice, Night) and tell it whether you're on headphones, speakers or a laptop. It shapes everything you hear, system-wide, through its own realtime DSP engine.

## Features

| | |
|---|---|
| **Spatial HRTF** | Binaural virtual speakers for headphones (Brown–Duda structural head model: head shadow, interaural delay, pinna cues), equalized to stay tonally neutral |
| **DeepBass** | Psychoacoustic *missing-fundamental* bass. Harmonics your brain hears as sub-bass, so even laptop speakers sound big. Four voicings: **Balanced**, **Sub Boost** (real rumble at 40 to 60 Hz), **Punchy** (transient kick on every drum hit, less mud) and **Warm** (full low mids, soft even harmonics) |
| **Intelligent EQ** | Listens to what's playing and steers the long-term tonal balance toward a target (Balanced, Warm, Focused, Bright), song by song and scene by scene |
| **Surround upmix** | Stereo → 5.1 / 7.1 for HDMI receivers, analog 5.1 and **S/PDIF Dolby Digital (AC3)**. Correlation-steered dialogue centre, decorrelated surrounds, band-limited LFE |
| **Headphone correction** | Search **AutoEq's ~8,800 measured headphones** and apply one in a click. Imports EqualizerAPO / AutoEq `.txt` and **ViPER DDC `.vdc`** |
| **Convolver** | Load any IR: ViPER/JamesDSP **`.irs`**, room impulses, HRIRs. Mono, stereo or true-stereo, with dry/wet mix |
| **Smart Leveler** | Ends volume jumps between songs, ads and scenes, and is volume-aware so it never fights your volume knob |
| **Adaptive Loudness** | Equal-loudness compensation from the *actual* playback level: full bass at low volume |
| **Voice Focus** | Lifts presence in the centre channel only, so dialogue cuts through effects |
| **Clarity** | High-frequency harmonic exciter plus air shelf. Restores what lossy streaming takes away |
| **Tube Warmth** | Biased even-harmonic saturation: the glow of a valve amp |
| **3D Stage & Ambience** | Bass-safe M/S widening, asymmetric early reflections, 4-line FDN room |
| **Limiter** | Lookahead brickwall, linked across all 8 channels. Nothing ever clips |
| **10-band EQ** | Draggable curve over a live spectrum, plus 14 presets |

### Knows your hardware

- **Detects every card, codec and connector.** For example: *Realtek ALCS1200A, 24-bit, up to 192 kHz, Line Out connected, S/PDIF available*
- **Reads your display's audio capabilities (EDID/ELD)** over HDMI/DP: what your TV or receiver accepts
- **One-tap output modes**: stereo, analog 5.1, HDMI 5.1/7.1, S/PDIF optical, Dolby Digital AC3 encode
- **Hi-Res mode**: PipeWire follows each song's native rate (44.1, 88.2, 96, 192 kHz…) instead of resampling everything to 48 kHz
- **Studio-grade resampler** (quality 14) for every app
- **Bluetooth codec switching** (LDAC / aptX / AAC / SBC, whatever your adapter offers)

### Smart, like a phone

- **Per-device memory.** Headphones, speakers, HDMI and Bluetooth each keep their own sound
- **Per-app profiles.** Movie for mpv/VLC, Music for Spotify, Gaming for Steam/Wine, Voice for Discord, and you can add your own
- **Catches every app.** Games that open your speakers directly (FMOD/Wwise titles such as War Thunder) get routed through Resona automatically, so effects and the volume keys apply to them too
- **Follows your output.** Plug in headphones or switch devices from the tray and Resona moves with you
- **Hold to compare.** Instant A/B against the untouched signal
- **Presets** you can save, import and share as JSON
- **Updates itself** from GitHub releases: only when you ask, weekly or monthly. Automatic installs wait for a quiet moment, so music or a game is never cut off

## Screenshots

| Sound | Equalizer |
|---|---|
| ![](docs/screenshots/home.png) | ![](docs/screenshots/eq.png) |
| **Space** | **Correction** |
| ![](docs/screenshots/space.png) | ![](docs/screenshots/correction.png) |
| **Hardware** | **Dynamics** |
| ![](docs/screenshots/hardware.png) | ![](docs/screenshots/dynamics.png) |

The interface is Material 3 Expressive, hand-built in QML: shape-morphing controls (cookie, flower, burst and clover polar shapes), wavy sliders that ripple while audio plays, springy motion, and dynamic color that re-tones the whole UI from one seed.

## How it compares

| | **Resona** | EasyEffects | JamesDSP (Linux) |
|---|:-:|:-:|:-:|
| One-click profiles + device modes | Yes | Manual chains | Partial |
| Binaural HRTF virtual speakers (no IR file needed) | Yes | Needs IR file | Needs IR file |
| Psychoacoustic bass | Yes | Yes (plugin) | Yes |
| Intelligent (content-adaptive) EQ | Yes | No | No |
| Stereo → 5.1/7.1 upmix + AC3 / HDMI output modes | Yes | No | No |
| Volume-aware leveler + loudness compensation | Yes | Partial | Partial |
| AutoEq search built in | Yes | Yes import | Yes |
| ViPER DDC + IRS convolver | Yes | IR only | Yes |
| Hardware / codec / HDMI ELD inspector, Hi-Res toggle | Yes | No | No |
| Per-device memory + per-app profiles | Yes | Yes (device) | Partial |
| Engine CPU (everything on, 48 kHz) | **~1 % of one core** | depends on chain | low |

EasyEffects is still the right tool if you want an arbitrary plugin rack. Resona is for everyone who just wants their audio to sound great.

## Install

```sh
git clone https://github.com/noble6/resona && cd resona
./install.sh          # installs into ~/.local, no root needed
resona                # or open "Resona" from your app menu
```

Requirements: PipeWire with `pipewire-pulse` and WirePlumber (the default on every modern distro), Python ≥ 3.10, PySide6 (Qt ≥ 6.7), numpy, libatomic, a C compiler.

```sh
sudo pacman -S pyside6 python-numpy gcc make                       # Arch / CachyOS / Manjaro
sudo dnf install python3-pyside6 python3-numpy libatomic gcc make  # Fedora
sudo apt install python3-pyside6.qtquick python3-pyside6.qtwidgets python3-numpy libatomic1 gcc make # Debian 13 / Ubuntu 24.10+
```

Arch users can also build `packaging/aur/PKGBUILD`.

Closing the window keeps Resona running in the tray. *Quit* from the tray restores your original output. `./uninstall.sh` removes everything.

## How it works

```
apps ──► "Resona Sound" virtual sink ─► PipeWire filter-chain (own process, RT priority)
                                            │
                     [optional convolver] ──┤
                                            ▼
                               resona.so  (LADSPA · C · lock-free · 32-bit float)
                               label "resona" (2→2) or "resona_surround" (2→8)
                                            │  ▲
                        meters, spectrum,   │  │  parameters, correction filters
                        Intelligent EQ      ▼  │  (no restarts, sample-accurate smoothing)
                               /dev/shm/resona-$UID  ◄──►  Resona UI (PySide6 + QML)
                                            │
                                            ▼
                                your real output: headphones · speakers · HDMI · S/PDIF · USB · BT
```

See **[docs/DSP.md](docs/DSP.md)** for a walk through every block, with the math. Because the engine is plain LADSPA, `resona.so` also loads in any LADSPA host.

## Tested

```sh
make -C engine test                  # 60+ offline DSP checks at 44.1 / 48 / 96 / 192 kHz
python3 tests/test_units.py --net    # parsers, presets ↔ engine contract, live AutoEq + real JamesDSP DDC
python3 tests/test_pipewire.py       # live PipeWire: passthrough, live EQ, AutoEq, 5.1 upmix, convolver
python3 tests/test_routing_live.py   # default-sink takeover, device following, volume sync, restore
python3 tests/test_capture_live.py   # games that bypass the default device get routed back through Resona
```

Some of what these suites verify: bit-transparent output with effects neutral; EQ within 0.01 dB; a limiter that never exceeds its ceiling on full-scale noise in 2 or 8 channels; NaN/Inf-safe processing; HRTF tonal balance within ±1.5 dB with a 270 µs interaural delay; Intelligent EQ taming a boomy mix; dialogue steered to the centre speaker while hard-panned instruments stay put.

## Shortcuts

`Ctrl+1…7` switch pages · `Space` toggles effects · scroll on any slider or EQ point for fine steps · double-click an EQ point to zero it

## Contributing

PRs are welcome, especially new profiles, translations, distro packages and DSP ideas. Start with [CONTRIBUTING.md](CONTRIBUTING.md). Run the test suites before sending DSP changes.

## Credits

- **[AutoEq](https://github.com/jaakkopasanen/AutoEq)** by Jaakko Pasanen (MIT): the headphone measurements and correction filters, fetched on demand
- **[JamesDSP](https://github.com/Audio4Linux/JDSP4Linux)** (GPL-3.0): reference for the ViPER-DDC file format and the IRS ecosystem
- **C. P. Brown & R. O. Duda**, *A Structural Model for Binaural Sound Synthesis* (IEEE TSAP, 1998): the HRTF model
- **R. Bristow-Johnson**, *Audio EQ Cookbook*: biquad designs
- **[Roboto Flex](https://github.com/googlefonts/roboto-flex)** (OFL-1.1) and **Material Symbols** (Apache-2.0)
- Inspired by what Dolby Atmos, DTS and the Android audio-mod scene (ViPER4Android, JamesDSP, LunarisDolby) offer users

Resona contains **no proprietary code**. Every algorithm is implemented from scratch or from public research. Dolby, DTS and Realtek are trademarks of their respective owners; Resona is not affiliated with them.

## License

GPL-3.0-or-later. See [LICENSE](LICENSE).
