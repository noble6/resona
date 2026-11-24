/*
 * Resona microphone: shared memory between the mic engine (label "resona_mic") and the UI.
 * Kept separate from the playback block so neither layout constrains the other.
 * The UI writes params[] inside an odd/even control_seq window and bumps param_seq.
 * Mirrored in app/resona/shm.py (MicState).
 * SPDX-License-Identifier: GPL-3.0-or-later
 */
#ifndef RESONA_MIC_SHM_H
#define RESONA_MIC_SHM_H
#include <stdint.h>

#define RESONA_MIC_MAGIC   0x434D5352u /* "RSMC" */
#define RESONA_MIC_VERSION 1u
#define RESONA_MIC_NPARAMS 16

enum {
    MP_ENABLE = 0,   /* 0 = untouched passthrough */
    MP_GAIN,         /* input gain, dB (-12..24) */
    MP_HPF,          /* rumble filter on/off */
    MP_NS,           /* noise suppression strength 0..1 (0 = off) */
    MP_CLARITY,      /* voice clarity 0..1 */
    MP_AGC,          /* auto level on/off */
    MP_AGC_TARGET,   /* auto level target, dBFS RMS (-30..-10) */
    MP_VOICE,        /* voice changer: 0 off 1 deep 2 chipmunk 3 robot 4 radio 5 alien 6 cave */
    MP_PITCH,        /* semitones for deep / chipmunk / alien (-12..12) */
    MP_COUNT
};

typedef struct {
    uint32_t magic;
    uint32_t version;
    uint32_t param_seq;
    uint32_t control_seq;      /* odd while the UI is writing */
    float    params[RESONA_MIC_NPARAMS];
    /* engine -> UI */
    uint32_t sample_rate;
    uint32_t heartbeat;
    float    in_peak;          /* before input gain */
    float    out_peak;
    float    nr_db;            /* average noise-suppression attenuation */
    float    agc_db;           /* auto-level gain applied */
    float    reserved[10];
} resona_mic_shm_t;

#endif
