import cv2 as cv
import numpy as np
import click
import os
import time
import matplotlib.pyplot as plt
import matplotlib
import pygame
import librosa as lr
import sounddevice as sd
import ffmpeg

matplotlib.use('tkagg')

# TODOs
# - Try to decode video with ffmpeg and stream the result into ram into a queue that is then rendered
#   - Possibly do the same for audio
# - overdraw the pygame screen only with the decompressed delta to the last frame
# - Possibly decompress the entire video before playback (maybe save as motionjpgs)
# - Preload data constantly (possibly in another process, or thread)

@click.command()
@click.option('-f', '--file',
              type=click.Path(True, dir_okay=False, resolve_path=True),
              help="The file to playback.")
def main(file, speed=1.2):
    FRAMERATE = 60
    AUDIO_SR = 44100
    pygame.init()
    resolution = (640, 480)
    screen = pygame.display.set_mode(resolution)


    cap = cv.VideoCapture(file)
    buffer_size = 1000
    frames = []
    # while cap.isOpened():
        # if not cap.grab():
        #     break
        # ret, frame = cap.retrieve()
    out, _ = (
        ffmpeg
            .input(file)
            .output('pipe:', format='rawvideo', pix_fmt='rgb24')
            .run(capture_stdout=True)
    )
    height = 1920
    width = 1080
    frames = (
        np
            .frombuffer(out, np.uint8)
            .reshape([-1, height, width, 3])
    )
    # for frame_number in range(600):
    #     frame, x = (ffmpeg
    #                 .input(file)
    #                 .filter('select', f'gte(n,{frame_number})')
    #                 .output('pipe:', vframes=1, format='image2', vcodec='mjpeg')
    #                 .run(capture_stdout=True)
    #     )
    #     frames.append(frame)


    audio, n = lr.load(file, sr=AUDIO_SR / speed)
    sd.play(audio)

    start_time = time.time()

    n_frames = len(frames)
    while n_frames > 0:
        f_time = time.time() - start_time
        frame_idx = int(f_time * FRAMERATE * speed)
        frame_idx = min(frame_idx, n_frames - 1)
        frame_surf = pygame.surfarray.make_surface(frames[frame_idx])
        screen.blit(frame_surf, (0, 0))
        pygame.display.flip()
    cap.release()
    cv.destroyAllWindows()


if __name__ == '__main__':
    main()