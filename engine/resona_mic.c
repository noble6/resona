/*
 * Resona microphone engine: LADSPA label "resona_mic" (1 in -> 1 out), hosted by its own
 * PipeWire filter-chain that publishes a "Resona Microphone" virtual source.
 *
 * Chain: input gain -> rumble filter -> spectral noise suppression -> voice clarity
 *        -> auto level -> voice changer -> peak limiter
 *
 * Noise suppression is an STFT (sqrt-Hann, 50 % overlap, ~10.7 ms frames) with a
 * minimum-tracking noise estimate per bin and a smoothed Wiener-style gain with a floor,
 * so steady noise (fans, hum, hiss) drops while speech passes. With strength 0 the gain
 * is exactly 1 and the frame pipeline reconstructs the input (constant latency, no jumps
 * when the slider moves). Voice changer: dual-tap delay-line pitch shifter with sin^2
 * crossfades, ring modulation, band-limited radio drive and a filtered echo.
 *
 * Parameters arrive through their own shared memory (resona_mic_shm.h); run() is
 * allocation-free and lock-free.
 *
 * SPDX-License-Identifier: GPL-3.0-or-later
 */
#define _GNU_SOURCE
#include <fcntl.h>
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <unistd.h>
#if defined(__SSE__)
#include <xmmintrin.h>
#endif

#include "ladspa_abi.h"
#include "resona_mic_shm.h"

#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif

#define MIC_BLOCK 32
#define FFT_MAX 2048
#define NBIN_MAX (FFT_MAX / 2 + 1)

enum { V_OFF, V_DEEP, V_CHIPMUNK, V_ROBOT, V_RADIO, V_ALIEN, V_CAVE, V_COUNT };

static const float MDEFAULTS[MP_COUNT] = {
    [MP_ENABLE] = 1, [MP_GAIN] = 0, [MP_HPF] = 1, [MP_NS] = 0.5f, [MP_CLARITY] = 0.4f,
    [MP_AGC] = 1, [MP_AGC_TARGET] = -18, [MP_VOICE] = 0, [MP_PITCH] = 0,
};

/* ---------------------------------------------------------------- small DSP helpers */
typedef struct { float b0, b1, b2, a1, a2; } mbq_c;
typedef struct { float z1, z2; } mbq_s;
enum { MB_PEAK, MB_LSHELF, MB_HSHELF, MB_LP, MB_HP };

static inline float mbq(const mbq_c *c, mbq_s *s, float x)
{
    float y = c->b0 * x + s->z1;
    s->z1 = c->b1 * x - c->a1 * y + s->z2;
    s->z2 = c->b2 * x - c->a2 * y;
    return y;
}

static void mbq_design(mbq_c *c, int type, double fs, double f, double q, double gdb)
{
    if (f > fs * 0.45) f = fs * 0.45;
    double A = pow(10.0, gdb / 40.0), w = 2 * M_PI * f / fs, cw = cos(w), sw = sin(w), al = sw / (2 * q);
    double b0, b1, b2, a0, a1, a2;
    switch (type) {
    case MB_PEAK:
        b0 = 1 + al * A; b1 = -2 * cw; b2 = 1 - al * A; a0 = 1 + al / A; a1 = -2 * cw; a2 = 1 - al / A; break;
    case MB_LSHELF: {
        double s2 = 2 * sqrt(A) * al;
        b0 = A * ((A + 1) - (A - 1) * cw + s2); b1 = 2 * A * ((A - 1) - (A + 1) * cw); b2 = A * ((A + 1) - (A - 1) * cw - s2);
        a0 = (A + 1) + (A - 1) * cw + s2; a1 = -2 * ((A - 1) + (A + 1) * cw); a2 = (A + 1) + (A - 1) * cw - s2; break;
    }
    case MB_HSHELF: {
        double s2 = 2 * sqrt(A) * al;
        b0 = A * ((A + 1) + (A - 1) * cw + s2); b1 = -2 * A * ((A - 1) + (A + 1) * cw); b2 = A * ((A + 1) + (A - 1) * cw - s2);
        a0 = (A + 1) - (A - 1) * cw + s2; a1 = 2 * ((A - 1) - (A + 1) * cw); a2 = (A + 1) - (A - 1) * cw - s2; break;
    }
    case MB_LP:
        b0 = (1 - cw) / 2; b1 = 1 - cw; b2 = (1 - cw) / 2; a0 = 1 + al; a1 = -2 * cw; a2 = 1 - al; break;
    default: /* MB_HP */
        b0 = (1 + cw) / 2; b1 = -(1 + cw); b2 = (1 + cw) / 2; a0 = 1 + al; a1 = -2 * cw; a2 = 1 - al; break;
    }
    c->b0 = (float)(b0 / a0); c->b1 = (float)(b1 / a0); c->b2 = (float)(b2 / a0);
    c->a1 = (float)(a1 / a0); c->a2 = (float)(a2 / a0);
}

static inline float mclamp(float x, float a, float b) { return x < a ? a : (x > b ? b : x); }
static inline float mdb2lin(float d) { return powf(10.0f, d * 0.05f); }
static float mtc(double fs, double seconds) { return (float)(1.0 - exp(-1.0 / (seconds * fs))); }
static unsigned mpow2(unsigned v) { unsigned p = 1; while (p < v) p <<= 1; return p; }

/* ---------------------------------------------------------------- state */
typedef struct {
    double fs;
    resona_mic_shm_t *shm; int shm_is_local;
    const float *in; float *out;
    float pt[MP_COUNT], ps[MP_COUNT];
    uint32_t last_seq; int first;

    float gain_lin;
    mbq_c hp; mbq_s hp_s[2];
    /* noise suppression */
    unsigned N, hop, nbin, fpos;
    float win[FFT_MAX], ibuf[FFT_MAX], obuf[FFT_MAX], ofifo[FFT_MAX / 2];
    float re[FFT_MAX], im[FFT_MAX], twr[FFT_MAX / 2], twi[FFT_MAX / 2];
    unsigned rev[FFT_MAX];
    float psd[NBIN_MAX], noise[NBIN_MAX], g[NBIN_MAX];
    unsigned frames; float nr_db, noise_rise;
    /* clarity */
    mbq_c cl_pres, cl_mud, cl_air; mbq_s cl_pres_s, cl_mud_s, cl_air_s; float cl_applied;
    /* auto level */
    float agc_ms, agc_db, agc_lin, agc_det, agc_att, agc_rel;
    /* voice changer */
    float *pdly; unsigned pmask, pw; float pphase, pwin;
    float *edly; unsigned emask, ew, elen; mbq_c e_lp; mbq_s e_lp_s;
    mbq_c r_hp, r_lp, deep_shelf; mbq_s r_hp_s[2], r_lp_s[2], deep_s;
    float comb[512]; unsigned cpos, clen;
    double osc, osc2; int vc_applied;
    /* limiter */
    float lim_env, lim_rel;
    float in_pk, out_pk;
} Mic;

/* ---------------------------------------------------------------- shared memory */
static void mic_shm_defaults(resona_mic_shm_t *m)
{
    memset(m->params, 0, sizeof m->params);
    memcpy(m->params, MDEFAULTS, sizeof MDEFAULTS);
    m->control_seq = 0;
    m->version = RESONA_MIC_VERSION;
    __atomic_store_n(&m->magic, RESONA_MIC_MAGIC, __ATOMIC_RELEASE);
}

static void mic_shm_open(Mic *r)
{
    char path[256];
    const char *env = getenv("RESONA_MIC_SHM");
    if (env && *env) snprintf(path, sizeof path, "%s", env);
    else snprintf(path, sizeof path, "/dev/shm/resona-mic-%u", (unsigned)getuid());
    int fd = open(path, O_RDWR | O_CREAT | O_CLOEXEC, 0600);
    if (fd >= 0) {
        struct stat st;
        if (fstat(fd, &st) == 0 && (size_t)st.st_size < sizeof(resona_mic_shm_t))
            if (ftruncate(fd, sizeof(resona_mic_shm_t)) != 0) { close(fd); fd = -1; }
    }
    if (fd >= 0) {
        void *p = mmap(NULL, sizeof(resona_mic_shm_t), PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
        close(fd);
        if (p != MAP_FAILED) {
            r->shm = p; r->shm_is_local = 0;
            if (r->shm->magic != RESONA_MIC_MAGIC || r->shm->version != RESONA_MIC_VERSION) mic_shm_defaults(r->shm);
            return;
        }
    }
    r->shm = calloc(1, sizeof(resona_mic_shm_t));
    r->shm_is_local = 1;
    mic_shm_defaults(r->shm);
}

static void mic_read_controls(Mic *r)
{
    resona_mic_shm_t *m = r->shm;
    uint32_t guard = __atomic_load_n(&m->control_seq, __ATOMIC_SEQ_CST);
    if (guard & 1u) return;
    uint32_t seq = __atomic_load_n(&m->param_seq, __ATOMIC_RELAXED);
    if (seq == r->last_seq && !r->first) return;
    float p[MP_COUNT];
    for (int i = 0; i < MP_COUNT; i++) __atomic_load(&m->params[i], &p[i], __ATOMIC_RELAXED);
    __atomic_thread_fence(__ATOMIC_ACQUIRE);
    if (__atomic_load_n(&m->control_seq, __ATOMIC_SEQ_CST) != guard) return;
    r->last_seq = seq;
    for (int i = 0; i < MP_COUNT; i++) if (isfinite(p[i])) r->pt[i] = p[i];
}

/* ---------------------------------------------------------------- FFT (radix-2, in place) */
static void fft_setup(Mic *r)
{
    unsigned n = r->N, bits = 0;
    while ((1u << bits) < n) bits++;
    for (unsigned i = 0; i < n; i++) {
        unsigned x = i, y = 0;
        for (unsigned b = 0; b < bits; b++) { y = (y << 1) | (x & 1); x >>= 1; }
        r->rev[i] = y;
    }
    for (unsigned i = 0; i < n / 2; i++) {
        r->twr[i] = (float)cos(2 * M_PI * i / n);
        r->twi[i] = (float)-sin(2 * M_PI * i / n);
    }
}

static void fft(Mic *r, int inverse)
{
    unsigned n = r->N;
    float *re = r->re, *im = r->im;
    for (unsigned i = 0; i < n; i++) {
        unsigned j = r->rev[i];
        if (j > i) { float t = re[i]; re[i] = re[j]; re[j] = t; t = im[i]; im[i] = im[j]; im[j] = t; }
    }
    for (unsigned len = 2; len <= n; len <<= 1) {
        unsigned half = len / 2, step = n / len;
        for (unsigned i = 0; i < n; i += len)
            for (unsigned k = 0; k < half; k++) {
                float wr = r->twr[k * step], wi = inverse ? -r->twi[k * step] : r->twi[k * step];
                unsigned a = i + k, b = a + half;
                float xr = re[b] * wr - im[b] * wi, xi = re[b] * wi + im[b] * wr;
                re[b] = re[a] - xr; im[b] = im[a] - xi;
                re[a] += xr; im[a] += xi;
            }
    }
}

/* one STFT frame: ibuf holds the last N input samples */
static void ns_frame(Mic *r, float strength)
{
    unsigned N = r->N, nb = r->nbin;
    for (unsigned i = 0; i < N; i++) { r->re[i] = r->ibuf[i] * r->win[i]; r->im[i] = 0; }
    fft(r, 0);
    if (strength > 0.001f) {
        float beta = 1.0f + 3.0f * strength;
        float floor_g = mdb2lin(-(8.0f + 22.0f * strength));
        double num = 0, den = 0;
        for (unsigned k = 0; k < nb; k++) {
            float p = r->re[k] * r->re[k] + r->im[k] * r->im[k];
            r->psd[k] = r->frames ? 0.8f * r->psd[k] + 0.2f * p : p;
            if (r->frames < 8) r->noise[k] = r->frames ? fminf(r->noise[k], r->psd[k]) : r->psd[k];
            else r->noise[k] = fminf(r->noise[k] * r->noise_rise, r->psd[k] + 1e-20f);
            float gk = 1.0f - beta * 1.5f * r->noise[k] / (r->psd[k] + 1e-20f);
            if (gk < floor_g) gk = floor_g;
            r->g[k] = gk > r->g[k] ? 0.6f * gk + 0.4f * r->g[k] : 0.3f * gk + 0.7f * r->g[k];
            num += (double)p * r->g[k] * r->g[k]; den += p;
        }
        r->nr_db = den > 1e-12 ? (float)(10.0 * log10(num / den + 1e-12)) : 0.0f;
        if (r->frames < 1000000) r->frames++;
        for (unsigned k = 0; k < nb; k++) {
            /* 5-tap smoothing across frequency tames isolated "musical noise" bins */
            float gs = r->g[k];
            if (k > 1 && k + 2 < nb)
                gs = 0.1f * r->g[k - 2] + 0.2f * r->g[k - 1] + 0.4f * r->g[k] + 0.2f * r->g[k + 1] + 0.1f * r->g[k + 2];
            r->re[k] *= gs; r->im[k] *= gs;
            if (k > 0 && k < N / 2) { r->re[N - k] = r->re[k]; r->im[N - k] = -r->im[k]; }
        }
    } else {
        r->nr_db = 0;
        r->frames = 0;
        for (unsigned k = 0; k < nb; k++) r->g[k] = 1.0f;
    }
    fft(r, 1);
    float scale = 1.0f / (float)N;
    for (unsigned i = 0; i < N; i++) r->obuf[i] += r->re[i] * scale * r->win[i];
    /* the first hop samples are complete */
    memcpy(r->ofifo, r->obuf, r->hop * sizeof(float));
    memmove(r->obuf, r->obuf + r->hop, (N - r->hop) * sizeof(float));
    memset(r->obuf + N - r->hop, 0, r->hop * sizeof(float));
    memmove(r->ibuf, r->ibuf + r->hop, (N - r->hop) * sizeof(float));
}

/* ---------------------------------------------------------------- voice changer */
static inline float pdly_read(const Mic *r, float d)
{
    if (d < 0) d = 0;
    unsigned di = (unsigned)d;
    float fr = d - (float)di;
    float a = r->pdly[(r->pw - 1 - di) & r->pmask], b = r->pdly[(r->pw - 2 - di) & r->pmask];
    return a + (b - a) * fr;
}

static inline float pitch_shift(Mic *r, float x, float ratio)
{
    r->pdly[r->pw & r->pmask] = x;
    r->pw++;
    float W = r->pwin, p1 = r->pphase, p2 = p1 + 0.5f;
    if (p2 >= 1.0f) p2 -= 1.0f;
    float w1 = sinf((float)M_PI * p1); w1 *= w1;
    float w2 = sinf((float)M_PI * p2); w2 *= w2;
    float y = pdly_read(r, p1 * W) * w1 + pdly_read(r, p2 * W) * w2;
    r->pphase += (1.0f - ratio) / W;
    if (r->pphase >= 1.0f) r->pphase -= 1.0f;
    if (r->pphase < 0.0f) r->pphase += 1.0f;
    return y;
}

static void vc_configure(Mic *r, int mode)
{
    if (mode == r->vc_applied) return;
    r->vc_applied = mode;
    memset(r->r_hp_s, 0, sizeof r->r_hp_s); memset(r->r_lp_s, 0, sizeof r->r_lp_s);
    memset(&r->deep_s, 0, sizeof r->deep_s); memset(r->comb, 0, sizeof r->comb);
    memset(&r->e_lp_s, 0, sizeof r->e_lp_s);
    memset(r->edly, 0, (r->emask + 1) * sizeof(float));
    memset(r->pdly, 0, (r->pmask + 1) * sizeof(float));
    r->pphase = 0;
}

/* ---------------------------------------------------------------- lifecycle */
static void mic_reset(Mic *r)
{
    memset(r->hp_s, 0, sizeof r->hp_s);
    memset(r->ibuf, 0, sizeof r->ibuf); memset(r->obuf, 0, sizeof r->obuf); memset(r->ofifo, 0, sizeof r->ofifo);
    for (unsigned k = 0; k < NBIN_MAX; k++) { r->g[k] = 1.0f; r->psd[k] = 0; r->noise[k] = 0; }
    r->fpos = 0; r->frames = 0; r->nr_db = 0;
    memset(&r->cl_pres_s, 0, sizeof r->cl_pres_s); memset(&r->cl_mud_s, 0, sizeof r->cl_mud_s);
    memset(&r->cl_air_s, 0, sizeof r->cl_air_s);
    r->agc_ms = 0; r->agc_db = 0; r->agc_lin = 1;
    r->lim_env = 0; r->in_pk = r->out_pk = 0;
    r->vc_applied = -1; vc_configure(r, 0);
    r->osc = r->osc2 = 0;
    r->first = 1;
}

static LADSPA_Handle mic_instantiate(const LADSPA_Descriptor *d, unsigned long rate)
{
    (void)d;
    Mic *r = calloc(1, sizeof(Mic));
    if (!r) return NULL;
    r->fs = (double)rate;
    mic_shm_open(r);
    memcpy(r->pt, MDEFAULTS, sizeof r->pt);
    memcpy(r->ps, MDEFAULTS, sizeof r->ps);
    /* ~10.7 ms frames at any rate */
    r->N = rate <= 50000 ? 512 : (rate <= 100000 ? 1024 : 2048);
    r->hop = r->N / 2; r->nbin = r->N / 2 + 1;
    for (unsigned i = 0; i < r->N; i++) r->win[i] = (float)sin(M_PI * (i + 0.5) / r->N);  /* sqrt-Hann */
    fft_setup(r);
    r->noise_rise = (float)pow(10.0, 1.5 / 10.0 / (r->fs / r->hop));  /* noise floor may rise 1.5 dB/s */
    mbq_design(&r->hp, MB_HP, r->fs, 80, 0.7071, 0);
    r->cl_applied = -1;
    r->agc_att = mtc(r->fs, 0.08); r->agc_rel = mtc(r->fs, 1.2); r->agc_det = mtc(r->fs, 0.3);
    r->lim_rel = (float)exp(-1.0 / (0.08 * r->fs));
    r->pwin = (float)(0.04 * r->fs);
    r->pmask = mpow2((unsigned)(r->pwin * 2) + 8) - 1;
    r->elen = (unsigned)(0.22 * r->fs);
    r->emask = mpow2(r->elen + 8) - 1;
    r->clen = (unsigned)(0.006 * r->fs); if (r->clen >= 512) r->clen = 511;
    r->pdly = calloc(r->pmask + 1, sizeof(float));
    r->edly = calloc(r->emask + 1, sizeof(float));
    if (!r->pdly || !r->edly) {
        free(r->pdly); free(r->edly);
        if (r->shm_is_local) free(r->shm); else munmap(r->shm, sizeof(resona_mic_shm_t));
        free(r);
        return NULL;
    }
    mbq_design(&r->r_hp, MB_HP, r->fs, 400, 0.7071, 0);
    mbq_design(&r->r_lp, MB_LP, r->fs, 3000, 0.7071, 0);
    mbq_design(&r->deep_shelf, MB_LSHELF, r->fs, 200, 0.7071, 3.0);
    mbq_design(&r->e_lp, MB_LP, r->fs, 3000, 0.7071, 0);
    r->shm->sample_rate = (uint32_t)rate;
    mic_reset(r);
    return r;
}

static void mic_connect(LADSPA_Handle h, unsigned long port, LADSPA_Data *data)
{
    Mic *r = h;
    if (port == 0) r->in = data; else if (port == 1) r->out = data;
}

static void mic_activate(LADSPA_Handle h) { mic_reset((Mic *)h); }

static void mic_control(Mic *r, unsigned len)
{
    mic_read_controls(r);
    float c = 1.0f - expf(-(float)len / (0.02f * (float)r->fs));
    for (int i = 0; i < MP_COUNT; i++) {
        float d = r->pt[i] - r->ps[i];
        r->ps[i] = (r->first || fabsf(d) < 1e-5f) ? r->pt[i] : r->ps[i] + d * c;
    }
    /* switches and modes never glide */
    r->ps[MP_ENABLE] = r->pt[MP_ENABLE]; r->ps[MP_HPF] = r->pt[MP_HPF]; r->ps[MP_AGC] = r->pt[MP_AGC];
    r->ps[MP_VOICE] = r->pt[MP_VOICE]; r->ps[MP_PITCH] = r->pt[MP_PITCH];
    r->first = 0;
    float cl = mclamp(r->ps[MP_CLARITY], 0, 1);
    if (fabsf(cl - r->cl_applied) > 0.002f) {
        mbq_design(&r->cl_pres, MB_PEAK, r->fs, 3200, 0.9, 6.0 * cl);
        mbq_design(&r->cl_mud, MB_PEAK, r->fs, 260, 1.0, -4.0 * cl);
        mbq_design(&r->cl_air, MB_HSHELF, r->fs, 9000, 0.7071, 2.5 * cl);
        r->cl_applied = cl;
    }
}

static void mic_run(LADSPA_Handle h, unsigned long n)
{
    Mic *r = h;
#if defined(__SSE__)
    unsigned csr = _mm_getcsr();
    _mm_setcsr(csr | 0x8040); /* FTZ | DAZ */
#endif
    const float *in = r->in;
    float *out = r->out;
    if (!in || !out) goto done;
    for (unsigned long off = 0; off < n;) {
        unsigned len = (unsigned)(n - off < MIC_BLOCK ? n - off : MIC_BLOCK);
        mic_control(r, len);
        const float *p = r->ps;
        float in_pk = 0, out_pk = 0;
        if (p[MP_ENABLE] < 0.5f) {
            for (unsigned i = 0; i < len; i++) {
                float x = in[off + i];
                if (!isfinite(x)) x = 0;
                out[off + i] = x;
                float a = fabsf(x); if (a > in_pk) in_pk = a;
            }
            out_pk = in_pk;
            r->nr_db = 0; r->agc_db = 0;
        } else {
            float gain = mdb2lin(mclamp(p[MP_GAIN], -12, 24));
            int hpf = p[MP_HPF] >= 0.5f, agc = p[MP_AGC] >= 0.5f;
            float ns = mclamp(p[MP_NS], 0, 1), cl = r->cl_applied;
            float target = mclamp(p[MP_AGC_TARGET], -30, -10);
            int mode = (int)mclamp(p[MP_VOICE], 0, V_COUNT - 1);
            float semis = mclamp(p[MP_PITCH], -12, 12);
            vc_configure(r, mode);
            float ratio = powf(2.0f, semis / 12.0f);
            const float lim_ceil = 0.891f; /* -1 dBFS */
            for (unsigned i = 0; i < len; i++) {
                float x = in[off + i];
                if (!isfinite(x)) x = 0;
                float a = fabsf(x); if (a > in_pk) in_pk = a;
                x *= gain;
                if (hpf) x = mbq(&r->hp, &r->hp_s[1], mbq(&r->hp, &r->hp_s[0], x));

                /* noise suppression: constant-latency frame pipeline */
                r->ibuf[r->N - r->hop + r->fpos] = x;
                x = r->ofifo[r->fpos];
                if (++r->fpos == r->hop) { r->fpos = 0; ns_frame(r, ns); }

                if (cl > 0.002f) {
                    x = mbq(&r->cl_mud, &r->cl_mud_s, x);
                    x = mbq(&r->cl_pres, &r->cl_pres_s, x);
                    x = mbq(&r->cl_air, &r->cl_air_s, x);
                }

                /* auto level: follows speech, holds through silence */
                r->agc_ms += (x * x - r->agc_ms) * r->agc_det;
                if (agc) {
                    float lvl = 10.0f * log10f(r->agc_ms + 1e-12f);
                    if (lvl > -55.0f) {
                        float want = mclamp(target - lvl, -10.0f, 20.0f);
                        r->agc_db += (want - r->agc_db) * (want < r->agc_db ? r->agc_att : r->agc_rel);
                    }
                } else {
                    r->agc_db += (0.0f - r->agc_db) * r->agc_att;
                }
                x *= mdb2lin(r->agc_db);

                /* voice changer */
                switch (mode) {
                case V_DEEP:
                    x = mbq(&r->deep_shelf, &r->deep_s, pitch_shift(r, x, ratio));
                    break;
                case V_CHIPMUNK:
                    x = pitch_shift(r, x, ratio);
                    break;
                case V_ROBOT: {
                    r->osc += 55.0 / r->fs; if (r->osc >= 1.0) r->osc -= 1.0;
                    float rm = x * sinf(2.0f * (float)M_PI * (float)r->osc);
                    float y = 0.75f * rm + 0.25f * x;
                    float cy = y + 0.55f * r->comb[(r->cpos + 512 - r->clen) & 511];
                    r->comb[r->cpos] = cy; r->cpos = (r->cpos + 1) & 511;
                    x = cy * 0.7f;
                    break;
                }
                case V_RADIO: {
                    float y = mbq(&r->r_hp, &r->r_hp_s[1], mbq(&r->r_hp, &r->r_hp_s[0], x));
                    y = mbq(&r->r_lp, &r->r_lp_s[1], mbq(&r->r_lp, &r->r_lp_s[0], y));
                    x = tanhf(3.0f * y) * (1.0f / 1.5f);
                    break;
                }
                case V_ALIEN: {
                    r->osc += 5.5 / r->fs; if (r->osc >= 1.0) r->osc -= 1.0;
                    float wob = sinf(2.0f * (float)M_PI * (float)r->osc);
                    float y = pitch_shift(r, x, powf(2.0f, (semis + 1.2f * wob) / 12.0f));
                    r->osc2 += 30.0 / r->fs; if (r->osc2 >= 1.0) r->osc2 -= 1.0;
                    x = y * (0.65f + 0.35f * sinf(2.0f * (float)M_PI * (float)r->osc2));
                    break;
                }
                case V_CAVE: {
                    float e = r->edly[(r->ew - r->elen) & r->emask];
                    r->edly[r->ew & r->emask] = x + 0.42f * mbq(&r->e_lp, &r->e_lp_s, e);
                    r->ew++;
                    x = x + 0.4f * e;
                    break;
                }
                default: break;
                }

                /* peak limiter (no lookahead: gain follows the envelope of this very sample) */
                float ax = fabsf(x);
                r->lim_env = ax > r->lim_env ? ax : r->lim_env * r->lim_rel;
                if (r->lim_env > lim_ceil) x *= lim_ceil / r->lim_env;
                if (!isfinite(x)) x = 0;
                out[off + i] = x;
                ax = fabsf(x); if (ax > out_pk) out_pk = ax;
            }
        }
        r->in_pk = fmaxf(in_pk, r->in_pk * 0.9f);
        r->out_pk = fmaxf(out_pk, r->out_pk * 0.9f);
        off += len;
    }
    r->shm->in_peak = r->in_pk;
    r->shm->out_peak = r->out_pk;
    r->shm->nr_db = r->nr_db;
    r->shm->agc_db = r->agc_db;
    __atomic_fetch_add(&r->shm->heartbeat, 1u, __ATOMIC_RELAXED);
done:
#if defined(__SSE__)
    _mm_setcsr(csr);
#endif
    return;
}

static void mic_cleanup(LADSPA_Handle h)
{
    Mic *r = h;
    free(r->pdly); free(r->edly);
    if (r->shm_is_local) free(r->shm);
    else munmap(r->shm, sizeof(resona_mic_shm_t));
    free(r);
}

static const LADSPA_PortDescriptor mic_ports[2] = {LADSPA_PORT_INPUT | LADSPA_PORT_AUDIO,
                                                   LADSPA_PORT_OUTPUT | LADSPA_PORT_AUDIO};
static const char *const mic_port_names[2] = {"In", "Out"};
static const LADSPA_PortRangeHint mic_hints[2];

static const LADSPA_Descriptor mic_descriptor = {
    .UniqueID = 0x534E43, .Label = "resona_mic",
    .Properties = LADSPA_PROPERTY_HARD_RT_CAPABLE | LADSPA_PROPERTY_INPLACE_BROKEN,
    .Name = "Resona Microphone", .Maker = "noble6", .Copyright = "GPL-3.0-or-later",
    .PortCount = 2, .PortDescriptors = mic_ports, .PortNames = mic_port_names, .PortRangeHints = mic_hints,
    .instantiate = mic_instantiate, .connect_port = mic_connect, .activate = mic_activate,
    .run = mic_run, .cleanup = mic_cleanup,
};

const LADSPA_Descriptor *resona_mic_descriptor(void) { return &mic_descriptor; }
