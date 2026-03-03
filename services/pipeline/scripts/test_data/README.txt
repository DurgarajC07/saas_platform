Place a 16-bit PCM WAV file sampled at 16 kHz mono here.
The benchmark script (benchmark_pipeline.py) looks for:

    scripts/test_data/hello_how_are_you.wav

If not found it falls back to a 2-second synthetic 440 Hz sine tone.

To record a clip on Linux:
    arecord -f S16_LE -r 16000 -c 1 hello_how_are_you.wav
