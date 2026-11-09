/* Offline verification of resona.so: loads it like PipeWire does (dlopen + LADSPA). */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <fcntl.h>
#include <math.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <time.h>
#include <unistd.h>
#include "ladspa_abi.h"
#include "resona_shm.h"

static const LADSPA_Descriptor *D2, *D8;
static resona_shm_t *M;
static int fails;
#define CHECK(c, ...) do { if (c) printf("  ok   "); else { printf("  FAIL "); fails++; } printf(__VA_ARGS__); printf("\n"); } while (0)

static void neutral(void)
{
    memset(M->params, 0, sizeof M->params);
    M->params[P_ENABLE] = 1; M->params[P_EQ_ON] = 1; M->params[P_STAGE_WIDTH] = 1;
    M->params[P_BASS_FREQ] = 100; M->params[P_LEV_TARGET] = -16; M->params[P_LIM_CEIL] = -0.5f;
    M->params[P_AMB_SIZE] = 0.4f; M->params[P_AMB_DAMP] = 0.5f; M->params[P_HRTF_ANGLE] = 30;
    M->corr_count = 0;
    M->param_seq++;
}
static void maxed(void)
{
    for (int i = 0; i < P_COUNT; i++) M->params[i] = 1;
    for (int b = 0; b < 10; b++) M->params[P_EQ0 + b] = 15;
    M->params[P_PREAMP] = 12; M->params[P_OUTPUT] = 12; M->params[P_BASS_FREQ] = 250;
    M->params[P_STAGE_WIDTH] = 2; M->params[P_LEV_TARGET] = -6; M->params[P_LIM_CEIL] = -1;
    M->params[P_SYSVOL_DB] = -60; M->params[P_HRTF_ANGLE] = 45; M->params[P_IEQ_TARGET] = 1;
    M->params[P_CORR_PREAMP] = 6; M->params[P_LAYOUT] = 15;
    M->corr_count = 3;
    M->corr[0] = (resona_corr_t){CORR_PK, 100, 12, 1, 0, 0, 0, 0, 0, 0};
    M->corr[1] = (resona_corr_t){CORR_HSC, 8000, 10, 0.7f, 0, 0, 0, 0, 0, 0};
    M->corr[2] = (resona_corr_t){CORR_LSC, 60, 10, 0.7f, 0, 0, 0, 0, 0, 0};
    M->param_seq++;
}

#define MAXO 8
typedef struct { const LADSPA_Descriptor *d; LADSPA_Handle h; unsigned nout; float *il, *ir, *o[MAXO]; } Inst;
static Inst mk(const LADSPA_Descriptor *d, unsigned long fs, unsigned n)
{
    Inst I = {d, d->instantiate(d, fs), (unsigned)d->PortCount - 2, calloc(n, 4), calloc(n, 4), {0}};
    for (unsigned c = 0; c < I.nout; c++) I.o[c] = calloc(n, 4);
    d->activate(I.h);
    return I;
}
static void rm(Inst *I)
{
    I->d->cleanup(I->h); free(I->il); free(I->ir);
    for (unsigned c = 0; c < I->nout; c++) free(I->o[c]);
}
static void process(Inst *I, unsigned n, unsigned chunk)
{
    for (unsigned off = 0; off < n; off += chunk) {
        unsigned c = n - off < chunk ? n - off : chunk;
        I->d->connect_port(I->h, 0, I->il + off); I->d->connect_port(I->h, 1, I->ir + off);
        for (unsigned k = 0; k < I->nout; k++) I->d->connect_port(I->h, 2 + k, I->o[k] + off);
        I->d->run(I->h, c);
    }
}
static double rms(const float *x, unsigned a, unsigned b)
{ double s = 0; for (unsigned i = a; i < b; i++) s += (double)x[i] * x[i]; return sqrt(s / (b - a)); }
static double tone(const float *x, unsigned a, unsigned b, double f, double fs)
{
    double re = 0, im = 0;
    for (unsigned i = a; i < b; i++) { re += x[i] * cos(2 * M_PI * f * i / fs); im += x[i] * sin(2 * M_PI * f * i / fs); }
    return 2 * sqrt(re * re + im * im) / (b - a);
}
static unsigned rng = 1;
static float noise(void) { rng = rng * 1664525u + 1013904223u; return ((rng >> 8) / 16777216.0f) * 2 - 1; }

/* band level (dB) of x via 2nd-order bandpass at f */
static double band_db(const float *x, unsigned a, unsigned b, double f, double fs)
{
    double w = 2 * M_PI * f / fs, al = sin(w) / (2 * 2.0), a0 = 1 + al;
    double b0 = al / a0, b2 = -al / a0, a1 = -2 * cos(w) / a0, a2 = (1 - al) / a0;
    double x1 = 0, x2 = 0, y1 = 0, y2 = 0, s = 0;
    for (unsigned i = 0; i < b; i++) {
        double y = b0 * x[i] + b2 * x2 - a1 * y1 - a2 * y2;
        x2 = x1; x1 = x[i]; y2 = y1; y1 = y;
        if (i >= a) s += y * y;
    }
    return 10 * log10(s / (b - a) + 1e-20);
}

int main(int argc, char **argv)
{
    char shm_path[] = "/tmp/resona-test-XXXXXX";
    int fd = mkstemp(shm_path); close(fd);
    setenv("RESONA_SHM", shm_path, 1);

    void *so = dlopen(argc > 1 ? argv[1] : "./resona.so", RTLD_NOW);
    if (!so) { printf("dlopen: %s\n", dlerror()); return 1; }
    const LADSPA_Descriptor *(*get)(unsigned long) = (void *)dlsym(so, "ladspa_descriptor");
    D2 = get(0); D8 = get(1);
    printf("plugins: %s [%s] %lu ports, %s [%s] %lu ports\n", D2->Name, D2->Label, D2->PortCount, D8->Name, D8->Label, D8->PortCount);
    printf("shm layout: v%u params@%zu heartbeat@%zu ring_pos@%zu in_peak@%zu out_peak@%zu leveler@%zu limiter@%zu "
           "loudness@%zu content@%zu ieq@%zu out_ch@%zu corr_count@%zu corr@%zu ring_in@%zu ring_out@%zu size=%zu\n",
           RESONA_VERSION, offsetof(resona_shm_t, params), offsetof(resona_shm_t, heartbeat), offsetof(resona_shm_t, ring_pos),
           offsetof(resona_shm_t, in_peak), offsetof(resona_shm_t, out_peak), offsetof(resona_shm_t, leveler_db),
           offsetof(resona_shm_t, limiter_gr_db), offsetof(resona_shm_t, loudness_db), offsetof(resona_shm_t, content_db),
           offsetof(resona_shm_t, ieq_db), offsetof(resona_shm_t, out_channels), offsetof(resona_shm_t, corr_count),
           offsetof(resona_shm_t, corr), offsetof(resona_shm_t, ring_in), offsetof(resona_shm_t, ring_out), sizeof(resona_shm_t));

    unsigned long rates[] = {44100, 48000, 96000, 192000};
    for (int ri = 0; ri < 4; ri++) {
        unsigned long fs = rates[ri];
        unsigned n = fs * 4;
        printf("\n== %lu Hz ==\n", fs);
        Inst tmp = mk(D2, fs, 16);
        int fdm = open(shm_path, O_RDWR);
        M = mmap(NULL, sizeof(resona_shm_t), PROT_READ | PROT_WRITE, MAP_SHARED, fdm, 0);
        close(fdm);
        rm(&tmp);
        unsigned la = (unsigned)(0.0015 * fs); if (la < 8) la = 8;

        /* 1. transparency */
        neutral();
        Inst I = mk(D2, fs, n);
        for (unsigned i = 0; i < n; i++) { I.il[i] = 0.3f * sinf(2 * M_PI * 440 * i / fs); I.ir[i] = 0.2f * sinf(2 * M_PI * 1234 * i / fs); }
        process(&I, n, 1024);
        double err = 0;
        for (unsigned i = fs; i < n; i++) err = fmax(err, fabs(I.o[0][i] - I.il[i - la]) + fabs(I.o[1][i] - I.ir[i - la]));
        CHECK(err < 1e-4, "neutral settings are transparent (err %.1e, latency %.2f ms)", err, la * 1000.0 / fs);
        rm(&I);

        /* 2. EQ accuracy */
        neutral(); M->params[P_EQ5] = 6; M->param_seq++;
        I = mk(D2, fs, n);
        for (unsigned i = 0; i < n; i++) I.il[i] = I.ir[i] = 0.1f * sinf(2 * M_PI * 1000 * i / fs);
        process(&I, n, 512);
        double g = 20 * log10(tone(I.o[0], fs, n, 1000, fs) / 0.1);
        CHECK(fabs(g - 6) < 0.2, "EQ 1 kHz +6 dB -> %+.2f dB", g);
        rm(&I);

        /* 3. everything maxed: finite + under ceiling, stereo and 7.1 */
        for (int which = 0; which < 2; which++) {
            maxed();
            I = mk(which ? D8 : D2, fs, n);
            for (unsigned i = 0; i < n; i++) { I.il[i] = noise(); I.ir[i] = noise(); }
            process(&I, n, 256);
            int finite = 1; float pk = 0;
            for (unsigned c = 0; c < I.nout; c++)
                for (unsigned i = 0; i < n; i++) { if (!isfinite(I.o[c][i])) finite = 0; pk = fmaxf(pk, fabsf(I.o[c][i])); }
            CHECK(finite && pk <= powf(10, -1 / 20.0f) + 1e-6, "%s maxed on full-scale noise: finite, peak %.2f dBFS (ceiling -1)",
                  which ? "7.1" : "stereo", 20 * log10f(pk));
            rm(&I);
        }

        /* 4. NaN/Inf injection */
        neutral();
        I = mk(D2, fs, n);
        for (unsigned i = 0; i < n; i++) I.il[i] = I.ir[i] = 0.1f * sinf(2 * M_PI * 300 * i / fs);
        I.il[1000] = NAN; I.ir[2000] = INFINITY;
        process(&I, n, 128);
        int fin = 1; for (unsigned i = 0; i < n; i++) if (!isfinite(I.o[0][i]) || !isfinite(I.o[1][i])) fin = 0;
        CHECK(fin, "NaN/Inf input is sanitized");
        rm(&I);

        /* 5. DeepBass harmonics */
        neutral(); M->params[P_BASS_ON] = 1; M->params[P_BASS_AMT] = 1; M->param_seq++;
        I = mk(D2, fs, n);
        for (unsigned i = 0; i < n; i++) I.il[i] = I.ir[i] = 0.3f * sinf(2 * M_PI * 50 * i / fs);
        process(&I, n, 512);
        double h2 = tone(I.o[0], fs, n, 100, fs), h3 = tone(I.o[0], fs, n, 150, fs);
        CHECK(h2 > 0.01 && h3 > 0.005, "DeepBass harmonics: 2nd %.1f dB, 3rd %.1f dB", 20 * log10(h2 / .3), 20 * log10(h3 / .3));
        rm(&I);

        /* 5b. Bass voicings: Sub Boost, Punchy, Warm */
        {
            double g45[4], g150[4], h2r[4], kick[4];
            for (int t = 0; t < 4; t++) {
                /* filter only (harmonics off): steady tones at 45 and 150 Hz */
                neutral(); M->params[P_BASS_ON] = 1; M->params[P_BASS_PUNCH] = 1; M->params[P_BASS_TYPE] = t; M->param_seq++;
                I = mk(D2, fs, n);
                for (unsigned i = 0; i < n; i++) I.il[i] = I.ir[i] = 0.02f * sinf(2 * M_PI * 45 * i / fs) + 0.02f * sinf(2 * M_PI * 150 * i / fs);
                process(&I, n, 512);
                g45[t] = 20 * log10(tone(I.o[0], fs, n, 45, fs) / 0.02); g150[t] = 20 * log10(tone(I.o[0], fs, n, 150, fs) / 0.02);
                rm(&I);
                /* harmonics only: even/odd balance from a 50 Hz tone */
                neutral(); M->params[P_BASS_ON] = 1; M->params[P_BASS_AMT] = 1; M->params[P_BASS_TYPE] = t; M->param_seq++;
                I = mk(D2, fs, n);
                for (unsigned i = 0; i < n; i++) I.il[i] = I.ir[i] = 0.3f * sinf(2 * M_PI * 50 * i / fs);
                process(&I, n, 512);
                h2r[t] = 20 * log10(tone(I.o[0], fs, n, 100, fs) / (tone(I.o[0], fs, n, 150, fs) + 1e-9));
                rm(&I);
                /* transients: gated 60 Hz bursts, onset level relative to the sustained part */
                neutral(); M->params[P_BASS_ON] = 1; M->params[P_BASS_AMT] = 1; M->params[P_BASS_PUNCH] = 0.5f;
                M->params[P_BASS_TYPE] = t; M->param_seq++;
                I = mk(D2, fs, n);
                unsigned per = fs / 2, on = (unsigned)(0.3 * fs);
                for (unsigned i = 0; i < n; i++) I.il[i] = I.ir[i] = (i % per) < on ? 0.2f * sinf(2 * M_PI * 60 * (i % per) / fs) : 0;
                process(&I, n, 512);
                double att = 0, sus = 0;
                for (unsigned b = per * 2; b + per <= n; b += per) {
                    att += rms(I.o[0], b + la, b + la + fs / 40);
                    sus += rms(I.o[0], b + la + (unsigned)(0.18 * fs), b + la + (unsigned)(0.28 * fs));
                }
                kick[t] = 20 * log10(att / sus);
                rm(&I);
            }
            CHECK(g45[1] > g45[0] + 1 && g45[1] - g150[1] > 6, "Sub Boost lifts the sub octave: 45 Hz %+.1f dB (balanced %+.1f), 150 Hz %+.1f dB",
                  g45[1], g45[0], g150[1]);
            CHECK(kick[2] > kick[0] + 1.5, "Punchy adds transient kick: onset %+.1f dB vs sustain (balanced %+.1f dB)", kick[2], kick[0]);
            CHECK(h2r[3] > h2r[2] + 6, "Warm favours even harmonics: H2/H3 %.1f dB (punchy %.1f dB)", h2r[3], h2r[2]);
            CHECK(g150[3] > g150[1] + 3, "Warm reaches the low mids: 150 Hz %+.1f dB (sub %+.1f dB)", g150[3], g150[1]);
        }

        /* 6. Leveler */
        neutral(); M->params[P_LEV_ON] = 1; M->params[P_LEV_AMT] = 1; M->param_seq++;
        I = mk(D2, fs, n);
        for (unsigned i = 0; i < n; i++) I.il[i] = I.ir[i] = 0.01414f * sinf(2 * M_PI * 1000 * i / fs);
        process(&I, n, 1024);
        double lg = 20 * log10(rms(I.o[0], n - fs / 2, n) / rms(I.il, n - fs / 2, n));
        CHECK(lg > 8 && lg < 12.5, "Leveler lifts -40 dBFS input by %.1f dB", lg);
        rm(&I);

        /* 7. bypass */
        maxed(); M->params[P_ENABLE] = 0; M->param_seq++;
        I = mk(D2, fs, n);
        for (unsigned i = 0; i < n; i++) I.il[i] = I.ir[i] = 0.5f * sinf(2 * M_PI * 777 * i / fs);
        process(&I, n, 1024);
        err = 0; for (unsigned i = fs; i < n; i++) err = fmax(err, fabs(I.o[0][i] - I.il[i - la]));
        CHECK(err < 1e-4, "bypass is transparent (err %.1e)", err);
        rm(&I);

        /* 8. HRTF: tonally neutral for centre content, real ITD/ILD for hard-panned content */
        neutral(); M->params[P_HRTF_ON] = 1; M->params[P_HRTF_AMT] = 1; M->param_seq++;
        I = mk(D2, fs, n);
        for (unsigned i = 0; i < n; i++) { float v = noise() * 0.2f; I.il[i] = v; I.ir[i] = noise() * 0.2f; }
        process(&I, n, 512);
        double worst = 0;
        const double fb[] = {100, 250, 500, 1000, 2000, 4000, 8000, 12000};
        double ref = band_db(I.o[0], fs, n, 1000, fs) - band_db(I.il, fs, n, 1000, fs);
        for (int k = 0; k < 8; k++) {
            double d = band_db(I.o[0], fs, n, fb[k], fs) - band_db(I.il, fs, n, fb[k], fs) - ref;
            if (fabs(d) > fabs(worst)) worst = d;
        }
        CHECK(fabs(worst) < 4.0, "HRTF keeps tonal balance (worst band deviation %+.1f dB, 100 Hz–12 kHz)", worst);
        rm(&I);
        I = mk(D2, fs, n);
        for (unsigned i = 0; i < n; i++) { I.il[i] = (i % (fs / 4)) == 100 ? 0.9f : 0; I.ir[i] = 0; }
        process(&I, n, 512);
        int pl = 0, pr = 0; float ml = 0, mr = 0;
        for (unsigned i = fs; i < fs + fs / 8; i++) {
            if (fabsf(I.o[0][i]) > ml) { ml = fabsf(I.o[0][i]); pl = i; }
            if (fabsf(I.o[1][i]) > mr) { mr = fabsf(I.o[1][i]); pr = i; }
        }
        double itd_us = (pr - pl) * 1e6 / fs;
        CHECK(itd_us > 150 && itd_us < 450 && mr < ml, "HRTF hard-left click: far ear %.0f µs later, %.1f dB quieter", itd_us, 20 * log10(mr / ml));
        rm(&I);

        /* 9. Intelligent EQ pulls a bass-heavy mix back toward target */
        neutral(); M->params[P_IEQ_ON] = 1; M->params[P_IEQ_AMT] = 1; M->params[P_IEQ_TARGET] = 0; M->param_seq++;
        unsigned n8 = fs * 8;
        I = mk(D2, fs, n8);
        { /* pink noise (Kellet) + a +12 dB boom around 100 Hz */
            float b0 = 0, b1 = 0, b2 = 0, b3 = 0, b4 = 0, b5 = 0, b6 = 0, lp1 = 0, lp2 = 0;
            float k = 1 - expf(-2 * M_PI * 150.0f / fs);
            for (unsigned i = 0; i < n8; i++) {
                float w = noise();
                b0 = 0.99886f * b0 + w * 0.0555179f; b1 = 0.99332f * b1 + w * 0.0750759f;
                b2 = 0.96900f * b2 + w * 0.1538520f; b3 = 0.86650f * b3 + w * 0.3104856f;
                b4 = 0.55000f * b4 + w * 0.5329522f; b5 = -0.7616f * b5 - w * 0.0168980f;
                float pink = (b0 + b1 + b2 + b3 + b4 + b5 + b6 + w * 0.5362f) * 0.05f; b6 = w * 0.115926f;
                lp1 += (pink - lp1) * k; lp2 += (lp1 - lp2) * k;
                I.il[i] = I.ir[i] = pink + 3.0f * lp2;
            }
        }
        process(&I, n8, 512);
        CHECK(M->ieq_db[1] < -1.5f && M->ieq_db[2] < -1.5f && M->ieq_db[7] > -1.0f,
              "Intelligent EQ tames a boomy mix: 64 Hz %+.1f, 125 Hz %+.1f, 4 kHz %+.1f dB",
              M->ieq_db[1], M->ieq_db[2], M->ieq_db[7]);
        rm(&I);

        /* 10. Tube Warmth adds even harmonics */
        neutral(); M->params[P_TUBE_ON] = 1; M->params[P_TUBE_DRIVE] = 0.6f; M->param_seq++;
        I = mk(D2, fs, n);
        for (unsigned i = 0; i < n; i++) I.il[i] = I.ir[i] = 0.4f * sinf(2 * M_PI * 1000 * i / fs);
        process(&I, n, 512);
        double t1 = tone(I.o[0], fs, n, 1000, fs), t2 = tone(I.o[0], fs, n, 2000, fs);
        CHECK(t2 / t1 > 0.01 && t2 / t1 < 0.3, "Tube 2nd harmonic %.1f dB re fundamental", 20 * log10(t2 / t1));
        rm(&I);

        /* 11. Correction EQ: designed PK, raw DDC biquad, unstable raw rejected */
        neutral(); M->params[P_CORR_ON] = 1; M->params[P_CORR_PREAMP] = -3;
        M->corr_count = 7;
        M->corr[0] = (resona_corr_t){CORR_PK, 2000, 6, 2, 0, 0, 0, 0, 0, 0};
        { /* raw: same filter designed in double here, at 500 Hz +4 dB */
            double A = pow(10, 4 / 40.0), w = 2 * M_PI * 500 / fs, al = sin(w) / 2.0, a0 = 1 + al / A;
            M->corr[1] = (resona_corr_t){CORR_RAW, 0, 0, 0, (float)((1 + al * A) / a0), (float)(-2 * cos(w) / a0),
                                         (float)((1 - al * A) / a0), (float)(-2 * cos(w) / a0), (float)((1 - al / A) / a0), 0};
        }
        M->corr[2] = (resona_corr_t){CORR_RAW, 0, 0, 0, 1, 0, 0, -2.5f, 1.8f, 0};
        M->corr[3] = (resona_corr_t){CORR_PK, NAN, 6, 1, 0, 0, 0, 0, 0, 0};
        M->corr[4] = (resona_corr_t){CORR_PK, 1000, 6, INFINITY, 0, 0, 0, 0, 0, 0};
        M->corr[5] = (resona_corr_t){CORR_PK, 1000, NAN, 1, 0, 0, 0, 0, 0, 0};
        M->corr[6] = (resona_corr_t){NAN, 1000, 6, 1, 0, 0, 0, 0, 0, 0};
        M->param_seq++;
        I = mk(D2, fs, n);
        for (unsigned i = 0; i < n; i++) I.il[i] = I.ir[i] = 0.05f * (sinf(2 * M_PI * 2000 * i / fs) + sinf(2 * M_PI * 500 * i / fs));
        process(&I, n, 512);
        double c1 = 20 * log10(tone(I.o[0], fs, n, 2000, fs) / 0.05), c2 = 20 * log10(tone(I.o[0], fs, n, 500, fs) / 0.05);
        CHECK(fabs(c1 - 3) < 0.4 && fabs(c2 - 1) < 0.6, "Correction EQ: PK %+.2f dB (exp +3), raw %+.2f dB (exp ~+1), unstable section skipped", c1, c2);
        rm(&I);

        /* 12. Surround upmix (5.1 sides): centre steering, panned content stays put, LFE band-limited */
        neutral(); M->params[P_UPMIX_ON] = 1; M->params[P_UPMIX_CENTER] = 1; M->params[P_UPMIX_SURR] = 1;
        M->params[P_UPMIX_LFE] = 1; M->params[P_LAYOUT] = 1 | 2 | 4; M->param_seq++;
        I = mk(D8, fs, n);
        for (unsigned i = 0; i < n; i++) I.il[i] = I.ir[i] = 0.3f * sinf(2 * M_PI * 440 * i / fs);
        process(&I, n, 512);
        double fc = rms(I.o[2], fs, n), fl = rms(I.o[0], fs, n);
        CHECK(fc > 4 * fl, "centred voice goes to FC (FC %.1f dB louder than FL)", 20 * log10(fc / (fl + 1e-9)));
        rm(&I);
        I = mk(D8, fs, n);
        for (unsigned i = 0; i < n; i++) { I.il[i] = 0.3f * sinf(2 * M_PI * 440 * i / fs); I.ir[i] = 0; }
        process(&I, n, 512);
        fc = rms(I.o[2], fs, n); fl = rms(I.o[0], fs, n);
        CHECK(fc < 0.1 * fl, "hard-left guitar stays in FL (FC %.1f dB below)", 20 * log10(fc / fl));
        rm(&I);
        I = mk(D8, fs, n);
        for (unsigned i = 0; i < n; i++) { float a = noise() * 0.2f, b = noise() * 0.2f; I.il[i] = a; I.ir[i] = b; }
        process(&I, n, 512);
        double sl = rms(I.o[6], fs, n), lfe = rms(I.o[3], fs, n);
        double lfe_rej = band_db(I.o[3], fs, n, 2000, fs) - band_db(I.il, fs, n, 2000, fs);
        CHECK(sl > 0.02 && lfe > 0.001 && lfe_rej < -40, "diffuse sound fills surrounds (SL %.1f dBFS), LFE rejects 2 kHz by %.0f dB",
              20 * log10(sl), -lfe_rej);
        rm(&I);

        /* 13. CPU */
        for (int which = 0; which < 2; which++) {
            maxed();
            I = mk(which ? D8 : D2, fs, n);
            for (unsigned i = 0; i < n; i++) { I.il[i] = 0.2f * sinf(i * 0.01f); I.ir[i] = 0.2f * cosf(i * 0.013f); }
            struct timespec t0, t1x; clock_gettime(CLOCK_MONOTONIC, &t0);
            process(&I, n, 256);
            clock_gettime(CLOCK_MONOTONIC, &t1x);
            double secs = (t1x.tv_sec - t0.tv_sec) + (t1x.tv_nsec - t0.tv_nsec) * 1e-9;
            printf("  info everything on (%s): %.2f%% of one core\n", which ? "7.1" : "stereo", secs / 4 * 100);
            rm(&I);
        }
        munmap(M, sizeof(resona_shm_t));
    }
    unlink(shm_path);
    printf("\n%s (%d failures)\n", fails ? "FAILED" : "ALL PASSED", fails);
    return fails != 0;
}
