/* Concurrent publication must never expose a mixed control snapshot. */
#include "../engine/resona_dsp.c"
#include <pthread.h>
#include <sched.h>
#include <stdio.h>

static resona_shm_t shared;
static unsigned done;

static void *publish(void *unused)
{
    (void)unused;
    for (unsigned i = 1; i <= 20000; i++) {
        uint32_t guard = i * 2 - 1;
        float value = (float)(i % 2 + 1), type = CORR_RAW;
        __atomic_store_n(&shared.control_seq, guard, __ATOMIC_SEQ_CST);
        __atomic_store(&shared.params[P_EQ0], &value, __ATOMIC_RELAXED);
        sched_yield();
        __atomic_store(&shared.params[P_EQ1], &value, __ATOMIC_RELAXED);
        __atomic_store(&shared.corr[0].type, &type, __ATOMIC_RELAXED);
        __atomic_store(&shared.corr[0].b0, &value, __ATOMIC_RELAXED);
        __atomic_store_n(&shared.corr_count, 1, __ATOMIC_RELAXED);
        __atomic_store_n(&shared.param_seq, i, __ATOMIC_RELAXED);
        __atomic_store_n(&shared.control_seq, guard + 1, __ATOMIC_SEQ_CST);
        sched_yield();
    }
    __atomic_store_n(&done, 1, __ATOMIC_RELEASE);
    return NULL;
}

int main(void)
{
    Resona r = {0};
    r.shm = &shared; r.fs = 48000; r.first = 1;
    pthread_t writer;
    if (pthread_create(&writer, NULL, publish, NULL)) return 1;
    unsigned snapshots = 0;
    do {
        read_controls(&r);
        if (r.corr_n) {
            if (r.pt[P_EQ0] != r.pt[P_EQ1] || r.pt[P_EQ0] != r.corr_c[0].b0) {
                fputs("torn control snapshot\n", stderr);
                pthread_join(writer, NULL);
                return 1;
            }
            snapshots++;
            r.first = 0;
        }
    } while (!__atomic_load_n(&done, __ATOMIC_ACQUIRE));
    pthread_join(writer, NULL);
    read_controls(&r);
    if (r.last_seq != 20000 || r.pt[P_EQ0] != r.corr_c[0].b0) return 1;
    printf("Control snapshots stayed consistent (%u reads)\n", snapshots);
    return 0;
}
