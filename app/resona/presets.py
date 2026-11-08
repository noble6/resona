"""Sound profiles, listening-device overlays, EQ presets and app → profile rules."""

DEFAULTS = {
    "enable": 1, "preamp": 0, "output": 0,
    "eq_on": 1, **{f"eq{i}": 0 for i in range(10)},
    "bass_on": 1, "bass_amt": 0.45, "bass_freq": 100, "bass_punch": 0.3,
    "clar_on": 1, "clar_amt": 0.3,
    "voice_on": 0, "voice_amt": 0.5,
    "stage_on": 1, "stage_width": 1.25, "stage_depth": 0.2,
    "xfeed_on": 0, "xfeed_amt": 0.5,
    "amb_on": 0, "amb_mix": 0.2, "amb_size": 0.4, "amb_damp": 0.5,
    "lev_on": 0, "lev_amt": 0.6, "lev_target": -16,
    "loud_on": 1, "loud_amt": 0.6,
    "lim_on": 1, "lim_ceil": -0.5,
    "sysvol_db": 0,
    "ieq_on": 0, "ieq_amt": 0.5, "ieq_target": 0,
    "tube_on": 0, "tube_drive": 0.3,
    "hrtf_on": 0, "hrtf_angle": 30, "hrtf_amt": 1.0,
    "corr_on": 0, "corr_preamp": 0,
    "upmix_on": 1, "upmix_center": 0.7, "upmix_surr": 0.6, "upmix_lfe": 0.5,
    "layout": 0,
}

# keys that describe *the sound*, i.e. what profiles / per-device memory / user presets store
SOUND_KEYS = [k for k in DEFAULTS if k not in ("sysvol_db", "layout", "enable")]

IEQ_TARGETS = ["Balanced", "Warm", "Focused", "Bright"]

EQ_PRESETS = {
    "Flat":        [0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
    "Bass Boost":  [6, 5, 3.5, 1.5, 0, 0, 0, 0, 0, 0],
    "Warm":        [3, 2.5, 1.5, 0.5, 0, -0.5, -1, -1, 0, 0.5],
    "V-Shape":     [4.5, 3.5, 1.5, -0.5, -2, -2, -0.5, 1.5, 3.5, 4.5],
    "Vocal":       [-2, -1.5, -0.5, 1, 2.5, 3, 2.5, 1.5, 0, -1],
    "Treble":      [0, 0, 0, 0, 0, 0.5, 1.5, 3, 4.5, 5.5],
    "Rock":        [4, 3, 1.5, -0.5, -1, 0, 1.5, 3, 3.5, 3.5],
    "Electronic":  [5, 4, 1.5, 0, -1.5, 0, 0.5, 1.5, 3.5, 4],
    "Hip-Hop":     [5.5, 4.5, 2, 1.5, -0.5, -0.5, 1, 0, 1, 2],
    "Jazz":        [2.5, 2, 1, 1.5, -1, -1, 0, 1, 2, 2.5],
    "Classical":   [3, 2.5, 1.5, 1, -0.5, -0.5, 0, 1.5, 2, 2.5],
    "Acoustic":    [3, 2.5, 2, 1, 1.5, 1, 2, 2.5, 2, 1],
    "Podcast":     [-6, -4, -1, 1, 2, 2.5, 2.5, 1.5, 0, -2],
    "Footsteps":   [-2, -2, -1, 0, 0, 1, 3.5, 4.5, 2.5, 0],
}

# name: (description, shape, params)
PROFILES = {
    "Dynamic": ("Balanced lift for everything", "cookie9", {
        "bass_on": 1, "bass_amt": 0.45, "bass_punch": 0.3, "clar_on": 1, "clar_amt": 0.3,
        "voice_on": 0, "stage_on": 1, "stage_width": 1.25, "stage_depth": 0.2,
        "amb_on": 0, "lev_on": 0, "loud_on": 1, "loud_amt": 0.6, "lim_ceil": -0.5,
        "ieq_on": 1, "ieq_amt": 0.4, "ieq_target": 0, "tube_on": 0, "eq": "Flat",
    }),
    "Music": ("Rich, wide and detailed", "flower8", {
        "bass_on": 1, "bass_amt": 0.55, "bass_punch": 0.35, "clar_on": 1, "clar_amt": 0.35,
        "voice_on": 0, "stage_on": 1, "stage_width": 1.4, "stage_depth": 0.3,
        "amb_on": 0, "lev_on": 0, "loud_on": 1, "loud_amt": 0.6, "lim_ceil": -0.5,
        "ieq_on": 1, "ieq_amt": 0.35, "ieq_target": 1, "tube_on": 1, "tube_drive": 0.2, "eq": "Warm",
    }),
    "Movie": ("Cinematic stage, clear dialogue", "burst12", {
        "bass_on": 1, "bass_amt": 0.6, "bass_punch": 0.45, "clar_on": 1, "clar_amt": 0.25,
        "voice_on": 1, "voice_amt": 0.45, "stage_on": 1, "stage_width": 1.6, "stage_depth": 0.55,
        "amb_on": 1, "amb_mix": 0.16, "amb_size": 0.6, "amb_damp": 0.55,
        "lev_on": 1, "lev_amt": 0.5, "lev_target": -16, "loud_on": 1, "loud_amt": 0.7, "lim_ceil": -0.5,
        "ieq_on": 1, "ieq_amt": 0.3, "ieq_target": 2, "tube_on": 0, "eq": "V-Shape",
        "upmix_center": 0.8, "upmix_surr": 0.7, "upmix_lfe": 0.6,
    }),
    "Gaming": ("Pinpoint footsteps & positioning", "clover4", {
        "bass_on": 1, "bass_amt": 0.3, "bass_punch": 0.2, "clar_on": 1, "clar_amt": 0.5,
        "voice_on": 1, "voice_amt": 0.2, "stage_on": 1, "stage_width": 1.7, "stage_depth": 0.4,
        "amb_on": 0, "lev_on": 1, "lev_amt": 0.35, "lev_target": -16, "loud_on": 1, "loud_amt": 0.5,
        "lim_ceil": -0.5, "ieq_on": 0, "tube_on": 0, "eq": "Footsteps",
        "upmix_center": 0.5, "upmix_surr": 0.8, "upmix_lfe": 0.4,
    }),
    "Voice": ("Podcasts, calls & lectures", "pill", {
        "bass_on": 0, "clar_on": 1, "clar_amt": 0.25, "voice_on": 1, "voice_amt": 0.8,
        "stage_on": 1, "stage_width": 0.9, "stage_depth": 0.0, "amb_on": 0,
        "lev_on": 1, "lev_amt": 0.8, "lev_target": -16, "loud_on": 1, "loud_amt": 0.5, "lim_ceil": -1,
        "ieq_on": 1, "ieq_amt": 0.5, "ieq_target": 2, "tube_on": 0, "eq": "Podcast",
        "upmix_center": 1.0, "upmix_surr": 0.2, "upmix_lfe": 0.2,
    }),
    "Night": ("Quiet listening, no surprises", "moon", {
        "bass_on": 1, "bass_amt": 0.35, "bass_punch": 0.1, "clar_on": 1, "clar_amt": 0.2,
        "voice_on": 1, "voice_amt": 0.4, "stage_on": 1, "stage_width": 1.1, "stage_depth": 0.1,
        "amb_on": 0, "lev_on": 1, "lev_amt": 1.0, "lev_target": -22, "loud_on": 1, "loud_amt": 0.9,
        "lim_ceil": -3, "ieq_on": 1, "ieq_amt": 0.4, "ieq_target": 0, "tube_on": 0, "eq": "Flat",
        "upmix_lfe": 0.25,
    }),
    "Pure": ("Untouched. Just the limiter", "circle", {
        "bass_on": 0, "clar_on": 0, "voice_on": 0, "stage_on": 0, "stage_width": 1.0, "stage_depth": 0.0,
        "amb_on": 0, "lev_on": 0, "loud_on": 0, "xfeed_on": 0, "hrtf_on": 0, "ieq_on": 0, "tube_on": 0,
        "lim_ceil": -0.3, "eq": "Flat", "upmix_on": 0,
    }),
}

# Listening-device overlays: applied after the profile.
DEVICE_MODES = {
    "headphones": {"bass_freq": 90},
    "speakers": {"xfeed_on": 0, "hrtf_on": 0, "bass_freq": 90},
    # small laptop drivers can't move air below ~150 Hz: lean on psychoacoustic bass
    "laptop": {"xfeed_on": 0, "hrtf_on": 0, "bass_freq": 170, "_bass_amt_min": 0.7, "_width_boost": 0.15},
}
# headphone spatial flavour per profile: virtual speakers (HRTF) for films & games, crossfeed for music
HEADPHONE_SPATIAL = {"Movie": "hrtf", "Gaming": "hrtf", "Music": "xfeed", "Dynamic": "xfeed", "Night": "xfeed"}

# Per-app automatic profiles (matched against application.process.binary / application.name)
APP_RULES_DEFAULT = {
    "spotify": "Music", "rhythmbox": "Music", "elisa": "Music", "strawberry": "Music", "cider": "Music",
    "tidal-hifi": "Music", "amberol": "Music", "lollypop": "Music", "deadbeef": "Music", "audacious": "Music",
    "mpv": "Movie", "vlc": "Movie", "celluloid": "Movie", "totem": "Movie", "haruna": "Movie", "kodi": "Movie",
    "stremio": "Movie", "jellyfin": "Movie", "plex": "Movie", "smplayer": "Movie",
    "steam": "Gaming", "wine": "Gaming", "wine64-preloader": "Gaming", "gamescope": "Gaming", "lutris": "Gaming",
    "heroic": "Gaming", "aces": "Gaming", "war thunder": "Gaming", "retroarch": "Gaming", "minecraft": "Gaming", "java": "Gaming",
    "discord": "Voice", "vesktop": "Voice", "zoom": "Voice", "teams": "Voice", "skype": "Voice",
    "telegram-desktop": "Voice", "signal-desktop": "Voice", "slack": "Voice",
}


def profile_params(name: str, device: str) -> dict:
    _, _, p = PROFILES.get(name, PROFILES["Dynamic"])
    out = {k: v for k, v in p.items() if k != "eq"}
    eq = EQ_PRESETS.get(p.get("eq", "Flat"), EQ_PRESETS["Flat"])
    out.update({f"eq{i}": g for i, g in enumerate(eq)})
    dev = DEVICE_MODES.get(device, {})
    for k, v in dev.items():
        if not k.startswith("_"):
            out[k] = v
    if device == "headphones" and name != "Pure":
        mode = HEADPHONE_SPATIAL.get(name)
        out["hrtf_on"] = 1 if mode == "hrtf" else 0
        out["xfeed_on"] = 1 if mode == "xfeed" else 0
        out["xfeed_amt"] = 0.45
    if name != "Pure":
        if "_bass_amt_min" in dev and out.get("bass_on"):
            out["bass_amt"] = max(out.get("bass_amt", 0), dev["_bass_amt_min"])
            out["bass_punch"] = min(out.get("bass_punch", 0), 0.15)
        if "_width_boost" in dev and out.get("stage_on"):
            out["stage_width"] = min(2.0, out.get("stage_width", 1) + dev["_width_boost"])
    else:
        out["xfeed_on"] = 0
    return out
