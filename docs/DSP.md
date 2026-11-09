# Resona DSP engine

`engine/resona_dsp.c` is a LADSPA plugin with two labels: `resona` (2→2) and `resona_surround` (2→8).
PipeWire's filter-chain hosts it. Parameters and correction filters arrive through shared memory
(`engine/resona_shm.h`). `run()` never allocates, locks or makes syscalls. Denormals are flushed (FTZ/DAZ),
and any non-finite sample resets the state instead of propagating.

Processing runs in 32-sample control blocks. Parameters are smoothed with a 30 ms one-pole, so every
change is click-free. Safety-critical values (limiter ceiling, system volume) snap instantly.

## Chain

| # | Block | Algorithm |
|---|---|---|
| 1 | Preamp | linear gain |
| 2 | **Smart Leveler** | Feed-forward AGC. The detector is a 120 Hz high-passed mean-square (≈K-weighting) with a 400 ms window. PipeWire applies sink volume *before* the plugin, so the UI reports the volume and the leveler measures `content = level − volume`. It never fights the volume knob. Gated below −55 dBFS; ±12 dB range; 50 ms emergency attack, 300 ms attack, 2.5 s release |
| 3 | **Intelligent EQ** | 10 constant-Q band-pass analysers (Q 1.4) feed 2.5 s mean-square band energies. Deviation from a target spectral shape (Balanced/Warm/Focused/Bright, relative to the 125 Hz–4 kHz mean) drives 10 peaking filters at −0.6× the deviation, limited to −6…+4.5 dB with a 3 s glide. Empty bands are ignored, and gains hold during silence |
| 4 | 10-band EQ | RBJ peaking biquads, Q 1.1, ±15 dB |
| 5 | **Adaptive Loudness** | `deficit = clamp(−6 − (level + leveler + 18), 0, 40)` dB drives a 90 Hz low shelf (0.32×) and a 9 kHz high shelf (0.12×). This approximates ISO 226 equal-loudness compensation from the actual playback level |
| 6 | **Voice Focus** | M/S split; +8 dB·amount presence peak at 2.4 kHz on Mid only; Side −35 %·amount |
| 7 | **Tube Warmth** | `y = (tanh(d(x+b)) − tanh(db)) / (d·sech²(db))` with bias b = 0.18. The asymmetric curve produces even harmonics; the normalisation keeps small-signal gain at 1; an 8 Hz DC blocker follows |
| 8 | **DeepBass** | Low shelf "punch" at f₀. Mono content is LR4-low-passed at f₀ and envelope-normalised (2 ms attack / 60 ms release). The shaper `0.65|n| + 0.45n³` generates 2nd + 3rd harmonics. The envelope is restored, then band-passed f₀…5f₀ and added back. The ear reconstructs the missing fundamental. Four voicings change the boost filter, the even/odd harmonic mix and the dynamics: *Balanced* (shelf at f₀, `0.65|n| + 0.45n³`), *Sub Boost* (peak at f₀/2, clamped to 35…90 Hz, Q 1, up to +11 dB, fewer harmonics), *Punchy* (peak near f₀ with Q 1.2, odd-heavy shaper, a −3 dB cut at 280 Hz, and a transient kick: a 12 dB/oct low band is added in proportion to how far a 0.8 ms/30 ms envelope runs ahead of a 40 ms/250 ms one) and *Warm* (broad shelf at 2f₀, mostly 2nd harmonic) |
| 9 | **Clarity** | 3 kHz HP band, envelope-normalised, squared-sign shaping (`n·|n|`) → 4.5 kHz HP, plus a 10 kHz air shelf |
| 10 | **3D Stage** | M/S width applied only to Side above 180 Hz, so bass stays mono and phase-safe. Five asymmetric, alternating-polarity early reflections per ear (5–27 ms, 5.5 kHz LP) give externalisation |
| 11a | Crossfeed | BS2B-style: 700 Hz one-pole LP of the opposite channel, 0.28 ms delay, level-normalised |
| 11b | **Spatial HRTF** | Brown–Duda structural model per path (ipsi/contra) for virtual speakers at ±θ: head shadow `H(s) = (1 + αs/2ω₀)/(1 + s/2ω₀)` with α(θ) from the incidence angle, bilinear-transformed. Woodworth/Brown–Duda ITD as a fractional delay. Five pinna echoes (ρ = ½, −1, ½, −¼, ¼, tamed to 55 %). The pair is equalised at init: unity power at 1 kHz, and a 3 kHz shelf cancels the average 4–12 kHz tilt. Measured result: ±1.5 dB tonal balance, 270 µs ITD, ~15 dB ILD for hard-panned sources |
| 12 | **Ambience** | 4-line Householder FDN (31.7–49.1 ms × size), RT60 0.35–2.75 s, damping LP in the loop, 220 Hz HP on the input. With surround outputs, the wet signal goes mostly to the surrounds |
| 13 | **Correction EQ** | Up to 24 biquads: PK / LSC / HSC / LP / HP designed with RBJ formulas (AutoEq & EqualizerAPO semantics), or raw coefficients from ViPER DDC files. Raw sections are stability-checked (`|a2| < 1`, `|a1| < 1 + a2`) and unstable ones skipped |
| 14 | Output gain + bypass | bypass crossfades to the dry signal in 30 ms |
| 15 | **Surround upmix** | 20 ms running L/R power and cross-power give correlation `c` and balance. Centre gain `g = amount · c² · evenness`, so correlated, centred content (dialogue) moves to FC while panned content stays in the fronts (`FL = L − gM`). Surrounds = Side, 120 Hz–7 kHz band-passed, delayed 12 ms (Haas, so the fronts keep localisation), decorrelated with different all-passes and opposite polarity per side. 7.1 rears get a further 20 ms, 5 kHz LP feed. LFE = LR4 120 Hz low-pass of Mid. The layout comes from the target sink's channel map, so 2.1/4.0/5.0/5.1/7.1 all work |
| 16 | **Limiter** | 1.5 ms lookahead; a monotonic-deque sliding-window minimum of the required gain, linked across all output channels; attack ≈ lookahead/4, 80 ms release, plus a final hard clamp at the ceiling |

## Shared memory (v3)

The UI publishes atomic 32-bit words while `control_seq` is odd, then marks the
snapshot complete with an even sequence. The engine copies controls once and
checks that sequence again. If a write overlaps the copy, the engine keeps its
previous controls; the audio callback never waits or retries.

| offset | field |
|---|---|
| 0 | magic `RSNA`, version, param_seq, sample_rate |
| 16 | `float params[128]` (see the `P_*` enum) |
| 528 | heartbeat, ring_pos, in/out peaks, leveler/limiter/loudness/content dB |
| 568 | `float ieq_db[10]`: live Intelligent EQ gains |
| 608 | out_channels, corr_count |
| 616 | control_seq, reserved |
| 640 | `corr[24] {type, freq, gain, q, b0, b1, b2, a1, a2, pad}` |
| 1600 | `ring_in[4096]`, `ring_out[4096]`: mono taps for the analyser |

`tests/test_dsp.c` prints these offsets and `tests/test_units.py` checks that the Python mirror matches the C enum.
