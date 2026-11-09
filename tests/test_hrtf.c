/* Compare the direct HRTF response with the original impulse-response calculation. */
#include "../engine/resona_dsp.c"
#include <stdio.h>

static double reference_power(const hrtf_path *a, const hrtf_path *b, double fs, double f)
{
    hrtf_state sa = {0}, sb = {0};
    double ra = 0, ia = 0, rb = 0, ib = 0;
    for (int n = 0; n < 2048; n++) {
        float x = n == 0 ? 1.0f : 0.0f;
        float ya = hrtf_run(a, &sa, x), yb = hrtf_run(b, &sb, x);
        double ph = -2 * M_PI * f * n / fs;
        ra += ya * cos(ph); ia += ya * sin(ph);
        rb += yb * cos(ph); ib += yb * sin(ph);
    }
    return ra * ra + ia * ia + rb * rb + ib * ib;
}

int main(void)
{
    const double rates[] = {44100, 48000, 96000, 192000};
    const double frequencies[] = {100, 1000, 4000, 6000, 9000, 12000};
    for (unsigned r = 0; r < 4; r++)
        for (int angle = 10; angle <= 70; angle += 5) {
            hrtf_path a, b;
            double fs = rates[r], ipsi = 90 - angle, contra = 90 + angle;
            double itd = (bd_delay(contra * M_PI / 180) - bd_delay(ipsi * M_PI / 180)) * fs;
            hrtf_design_path(&a, fs, ipsi, angle, 0);
            hrtf_design_path(&b, fs, contra, 180 - angle, itd);
            for (unsigned f = 0; f < 6; f++) {
                double expected = reference_power(&a, &b, fs, frequencies[f]);
                double actual = hrtf_power(&a, &b, fs, frequencies[f]);
                if (!isfinite(actual) || fabs(actual - expected) > expected * 1e-4) {
                    fprintf(stderr, "HRTF mismatch: %.0f Hz, %d degrees, %.0f Hz: %g vs %g\n",
                            fs, angle, frequencies[f], actual, expected);
                    return 1;
                }
            }
        }
    puts("HRTF transfer function matches impulse reference");
    return 0;
}
