CC ?= cc
CFLAGS ?= -O2 -ffast-math -fno-finite-math-only
override CFLAGS += -std=c11 -Wall -Wextra -fPIC -fvisibility=hidden
TEST_CFLAGS ?= -O2 -Wall

all: resona.so

resona.so: resona_dsp.c resona_shm.h ladspa_abi.h
	$(CC) $(CFLAGS) -shared -o $@ resona_dsp.c -lm

test: resona.so ../tests/test_dsp.c ../tests/test_hrtf.c ../tests/test_shm.c
	$(CC) $(TEST_CFLAGS) -o ../tests/test_dsp ../tests/test_dsp.c -I. -ldl -lm
	../tests/test_dsp ./resona.so
	$(CC) $(TEST_CFLAGS) -o ../tests/test_hrtf ../tests/test_hrtf.c -lm
	../tests/test_hrtf
	$(CC) $(TEST_CFLAGS) -o ../tests/test_shm ../tests/test_shm.c -lm -pthread
	../tests/test_shm

clean:
	rm -f resona.so ../tests/test_dsp ../tests/test_hrtf ../tests/test_shm
.PHONY: all test clean
