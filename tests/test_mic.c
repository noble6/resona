/* Offline checks for the "resona_mic" plugin at several sample rates. */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <stddef.h>
#include <fcntl.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <time.h>
#include <unistd.h>

#include "ladspa_abi.h"
#include "resona_mic_shm.h"

static const LADSPA_Descriptor *D;
static resona_mic_shm_t *M;
static int fails;
#define CHECK(c, ...) do { if (c) printf("  ok   "); else { printf("  FAIL "); fails++; } printf(__VA_ARGS__); printf("\n"); } while (0)

static void set(int mode, float ns, float clarity, int agc, int hpf)
{
    M->control_seq++;
    memset(M->params, 0, sizeof M->params);
    M->params[MP_ENABLE] = 1; M->params[MP_NS] = ns; M->params[MP_CLARITY] = clarity;
    M->params[MP_AGC] = agc; M->params[MP_AGC_TARGET] = -18; M->params[MP_HPF] = hpf;
    M->params[MP_VOICE] = mode;
    M->param_seq++;
    M->control_seq++;
}
static void param(int i, float v) { M->control_seq++; M->params[i] = v; M->param_seq++; M->control_seq++; }

typedef struct { LADSPA_Handle h; float *in, *out; unsigned n; } Inst;
static Inst mk(unsigned long fs, unsigned n)
{
    Inst I = {D->instantiate(D, fs), calloc(n, 4), calloc(n, 4), n};
    D->activate(I.h);
    return I;
}
static void rm(Inst *I) { D->cleanup(I->h); free(I->in); free(I->out); }
static void process(Inst *I, unsigned chunk)
{
    for (unsigned off = 0; off < I->n; off += chunk) {
        unsigned c = I->n - off < chunk ? I->n - off : chunk;
        D->connect_port(I->h, 0, I->in + off); D->connect_port(I->h, 1, I->out + off);
        D->run(I->h, c);
    }
}
static double rms(const float *x, unsigned a, unsigned b)
{ double s = 0; for (unsigned i = a; i < b; i++) s += (double)x[i] * x[i]; return sqrt(s / (b - a) + 1e-30); }
static double tone(const float *x, unsigned a, unsigned b, double f, double fs)
{
    double re = 0, im = 0;
    for (unsigned i = a; i < b; i++) { re += x[i] * cos(2 * M_PI * f * i / fs); im += x[i] * sin(2 * M_PI * f * i / fs); }
    return 2 * sqrt(re * re + im * im) / (b - a);
}
static unsigned rng = 7;
static float noise(void) { rng = rng * 1664525u + 1013904223u; return ((rng >> 8) / 16777216.0f) * 2 - 1; }
static double db(double x) { return 20 * log10(x + 1e-12); }

/* a voice-like harmonic sound: 140 Hz fundamental with formant-ish harmonics */
static float voice(unsigned i, double fs)
{
    double t = i / fs, s = 0;
    for (int h = 1; h <= 12; h++) s += sin(2 * M_PI * 140 * h * t) * (h < 4 ? 1.0 : 0.6 / h) ;
    return (float)(s * 0.08);
}

int main(int argc, char **argv)
{
    char path[] = "/tmp/resona-mic-test-XXXXXX";
    int fd = mkstemp(path); close(fd);
    setenv("RESONA_MIC_SHM", path, 1);
    void *so = dlopen(argc > 1 ? argv[1] : "./resona.so", RTLD_NOW);
    if (!so) { printf("dlopen: %s\n", dlerror()); return 1; }
    const LADSPA_Descriptor *(*get)(unsigned long) = (void *)dlsym(so, "ladspa_descriptor");
    D = get(2);
    CHECK(D && !strcmp(D->Label, "resona_mic") && D->PortCount == 2 && !get(3), "descriptor 2 is resona_mic (1 in, 1 out)");
    if (!D) return 1;
    /* the Python mirror (app/resona/mic.py) hard-codes these offsets */
    CHECK(offsetof(resona_mic_shm_t, params) == 16 && offsetof(resona_mic_shm_t, sample_rate) == 80 &&
          offsetof(resona_mic_shm_t, heartbeat) == 84 && offsetof(resona_mic_shm_t, in_peak) == 88 &&
          offsetof(resona_mic_shm_t, agc_db) == 100 && sizeof(resona_mic_shm_t) == 144,
          "mic shared-memory layout matches the Python mirror (size %zu)", sizeof(resona_mic_shm_t));

    unsigned long rates[] = {44100, 48000, 96000};
    for (int ri = 0; ri < 3; ri++) {
        unsigned long fs = rates[ri];
        unsigned n = fs * 4;
        printf("\n== %lu Hz ==\n", fs);
        Inst tmp = mk(fs, 16);
        int fdm = open(path, O_RDWR);
        M = mmap(NULL, sizeof(resona_mic_shm_t), PROT_READ | PROT_WRITE, MAP_SHARED, fdm, 0);
        close(fdm);
        rm(&tmp);

        /* 1. disabled = untouched */
        set(0, 0, 0, 0, 0); param(MP_ENABLE, 0);
        Inst I = mk(fs, n);
        for (unsigned i = 0; i < n; i++) I.in[i] = 0.3f * noise();
        process(&I, 128);
        int same = 1; for (unsigned i = 0; i < n; i++) if (I.out[i] != I.in[i]) same = 0;
        CHECK(same, "disabled: bit-exact passthrough");
        rm(&I);

        /* 2. enabled, everything neutral: transparent after a constant latency */
        set(0, 0, 0, 0, 0);
        I = mk(fs, n);
        for (unsigned i = 0; i < n; i++) I.in[i] = 0.3f * noise();
        process(&I, 100);
        unsigned lat = 0; double best = 0;
        for (unsigned L = 0; L < 4096; L++) {
            double c = 0; for (unsigned i = fs; i < fs + 4096; i++) c += I.out[i + L] * I.in[i];
            if (c > best) { best = c; lat = L; }
        }
        double err = 0; for (unsigned i = fs; i < n - lat; i++) err = fmax(err, fabs(I.out[i + lat] - I.in[i]));
        CHECK(err < 1e-4 && lat * 1000.0 / fs < 12, "neutral: transparent (err %.1e), latency %.1f ms", err, lat * 1000.0 / fs);
        rm(&I);

        /* 3. noise suppression: fan-like noise drops, speech survives */
        set(0, 1.0f, 0, 0, 1);
        I = mk(fs, n);
        for (unsigned i = 0; i < n; i++) {
            int talking = (i / (fs / 2)) % 2 == 0;         /* 0.5 s talk, 0.5 s pause, ends on a pause */
            I.in[i] = 0.01f * noise() + (talking ? voice(i, fs) : 0);
        }
        process(&I, 256);
        /* compare the last pause and the last talk segment to the same input segments */
        unsigned t0 = 6 * (fs / 2) + fs / 10, t1 = 7 * (fs / 2) - fs / 20;     /* talk 3.0-3.5 s */
        unsigned p0 = 7 * (fs / 2) + fs / 10, p1 = 8 * (fs / 2) - fs / 20;     /* pause 3.5-4.0 s */
        double noise_drop = db(rms(I.out, p0, p1)) - db(rms(I.in, p0, p1));
        double voice_change = db(rms(I.out, t0, t1)) - db(rms(I.in, t0, t1));
        CHECK(noise_drop < -15 && fabs(voice_change) < 2.5, "noise suppression: background %.1f dB, speech %+.1f dB",
              noise_drop, voice_change);
        CHECK(M->nr_db < -3, "noise suppression meter reports %.1f dB", M->nr_db);
        rm(&I);

        /* 4. rumble filter */
        set(0, 0, 0, 0, 1);
        I = mk(fs, n);
        for (unsigned i = 0; i < n; i++) I.in[i] = 0.2f * sinf(2 * M_PI * 30 * i / fs) + 0.2f * sinf(2 * M_PI * 1000 * i / fs);
        process(&I, 128);
        double hum = db(tone(I.out, fs, n, 30, fs) / 0.2), keep = db(tone(I.out, fs, n, 1000, fs) / 0.2);
        CHECK(hum < -20 && fabs(keep) < 0.5, "rumble filter: 30 Hz %.1f dB, 1 kHz %+.2f dB", hum, keep);
        rm(&I);

        /* 5. auto level brings a quiet talker to the target */
        set(0, 0, 0, 1, 1);
        I = mk(fs, n);
        for (unsigned i = 0; i < n; i++) I.in[i] = voice(i, fs) * 0.12f;   /* about -40 dBFS RMS */
        process(&I, 256);
        double lvl = db(rms(I.out, n - fs, n));
        CHECK(fabs(lvl - (-18)) < 3, "auto level: %.1f dBFS in -> %.1f dBFS out (target -18), gain %+.1f dB",
              db(rms(I.in, n - fs, n)), lvl, M->agc_db);
        rm(&I);

        /* 6. limiter */
        set(0, 0, 0, 0, 0); param(MP_GAIN, 24);
        I = mk(fs, n);
        for (unsigned i = 0; i < n; i++) I.in[i] = 0.9f * noise();
        process(&I, 128);
        float pk = 0; for (unsigned i = 0; i < n; i++) pk = fmaxf(pk, fabsf(I.out[i]));
        CHECK(pk <= 0.8913f, "limiter: +24 dB into full-scale noise peaks at %.2f dBFS", db(pk));
        rm(&I);

        /* 7. pitch shifting: chipmunk +12 doubles, deep -12 halves */
        for (int up = 1; up >= 0; up--) {
            set(up ? 2 : 1, 0, 0, 0, 0); param(MP_PITCH, up ? 12 : -12);
            I = mk(fs, n);
            for (unsigned i = 0; i < n; i++) I.in[i] = 0.2f * sinf(2 * M_PI * 400 * i / fs);
            process(&I, 128);
            double f_new = up ? 800 : 200;
            double moved = db(tone(I.out, fs, n, f_new, fs)), stayed = db(tone(I.out, fs, n, 400, fs));
            CHECK(moved - stayed > 15, "%s: 400 Hz -> %g Hz is %.1f dB above the original", up ? "chipmunk +12" : "deep -12",
                  f_new, moved - stayed);
            rm(&I);
        }

        /* 8. robot: ring-modulation sidebands */
        set(3, 0, 0, 0, 0);
        I = mk(fs, n);
        for (unsigned i = 0; i < n; i++) I.in[i] = 0.2f * sinf(2 * M_PI * 400 * i / fs);
        process(&I, 128);
        double side = db(tone(I.out, fs, n, 455, fs) + tone(I.out, fs, n, 345, fs)), orig = db(tone(I.out, fs, n, 400, fs));
        CHECK(side > orig, "robot: sidebands %.1f dB vs carrier %.1f dB", side, orig);
        rm(&I);

        /* 9. radio: band-limited */
        set(4, 0, 0, 0, 0);
        I = mk(fs, n);
        for (unsigned i = 0; i < n; i++) I.in[i] = 0.05f * sinf(2 * M_PI * 100 * i / fs) + 0.05f * sinf(2 * M_PI * 1200 * i / fs);
        process(&I, 128);
        double lo = db(tone(I.out, fs, n, 100, fs)), mid = db(tone(I.out, fs, n, 1200, fs));
        CHECK(mid - lo > 20, "radio: 100 Hz is %.1f dB below 1.2 kHz", mid - lo);
        rm(&I);

        /* 10. cave: an echo 220 ms later */
        set(6, 0, 0, 0, 0);
        I = mk(fs, n);
        I.in[fs / 2] = 0.5f;
        process(&I, 128);
        unsigned direct = 0; for (unsigned i = 1; i < n; i++) if (fabsf(I.out[i]) > fabsf(I.out[direct])) direct = i;
        unsigned echo = direct + (unsigned)(0.22 * fs);
        float e = 0; for (unsigned i = echo - 50; i < echo + 50; i++) e = fmaxf(e, fabsf(I.out[i]));
        CHECK(e > 0.1f, "cave: echo of %.2f at 220 ms", e);
        rm(&I);

        /* 11. every mode survives garbage and stays finite */
        int fin = 1;
        for (int mode = 0; mode < 7; mode++) {
            set(mode, 1, 1, 1, 1); param(MP_PITCH, 7); param(MP_GAIN, 24);
            I = mk(fs, fs);
            for (unsigned i = 0; i < fs; i++) I.in[i] = noise();
            I.in[100] = NAN; I.in[200] = INFINITY; I.in[300] = -INFINITY; I.in[400] = 1e30f;
            process(&I, 97);
            for (unsigned i = 0; i < fs; i++) if (!isfinite(I.out[i]) || fabsf(I.out[i]) > 0.8913f) fin = 0;
            rm(&I);
        }
        CHECK(fin, "all voice modes: NaN/Inf-safe and within the limiter ceiling");

        /* 12. cost with everything on */
        set(5, 1, 1, 1, 1); param(MP_PITCH, 4);
        I = mk(fs, n);
        for (unsigned i = 0; i < n; i++) I.in[i] = voice(i, fs) + 0.01f * noise();
        struct timespec a, b; clock_gettime(CLOCK_MONOTONIC, &a);
        process(&I, 256);
        clock_gettime(CLOCK_MONOTONIC, &b);
        double sec = (b.tv_sec - a.tv_sec) + (b.tv_nsec - a.tv_nsec) * 1e-9;
        printf("  info everything on: %.2f%% of one core\n", 100.0 * sec / (n / (double)fs));
        rm(&I);
        munmap(M, sizeof(resona_mic_shm_t));
    }
    unlink(path);
    printf("\n%s (%d failures)\n", fails ? "FAILED" : "ALL PASSED", fails);
    return fails != 0;
}
