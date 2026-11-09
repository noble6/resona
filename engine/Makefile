CC ?= cc
CFLAGS ?= -O2 -ffast-math -fno-finite-math-only
override CFLAGS += -std=c11 -Wall -Wextra -fPIC -fvisibility=hidden

all: resona.so

resona.so: resona_dsp.c resona_shm.h ladspa_abi.h
	$(CC) $(CFLAGS) -shared -o $@ resona_dsp.c -lm

test: resona.so ../tests/test_dsp.c
	$(CC) -O2 -Wall -o ../tests/test_dsp ../tests/test_dsp.c -I. -ldl -lm
	../tests/test_dsp ./resona.so

clean:
	rm -f resona.so ../tests/test_dsp
.PHONY: all test clean
