import pyaudio
import numpy as np
import time

pyaudio_instance = pyaudio.PyAudio()

FRAMES = 256
SR = 44100



pyaudio_out_stream = pyaudio_instance.open(
        format=pyaudio.paFloat32,
        channels=1,
        rate=SR,
        frames_per_buffer=FRAMES,
        output=True,
    )

i = 0
while True:
        samp = np.sin(np.arange(i, i + FRAMES*100) * np.pi * 440 / SR)
        i += FRAMES
        pyaudio_out_stream.write(samp)


# p = pyaudio.PyAudio()
#
# volume = 0.5     # range [0.0, 1.0]
# fs = 44100       # sampling rate, Hz, must be integer
# duration = 1.0   # in seconds, may be float
# f = 440.0 * 2        # sine frequency, Hz, may be float
#
# # generate samples, note conversion to float32 array
# samples = (np.sin(2*np.pi*np.arange(fs*duration)*f/fs)).astype(np.float32)
#
# # for paFloat32 sample values must be in range [-1.0, 1.0]
# stream = p.open(format=pyaudio.paFloat32,
#                 channels=1,
#                 rate=fs,
#                 output=True)
#
# # play. May repeat with different volume values (if done interactively)
#
# isamples = (np.sin(2*np.pi*np.arange(fs*duration)*f/fs)).astype(np.float32).tobytes()
# stream.write(isamples)
#
# stream.stop_stream()
# stream.close()
#
# p.terminate()