import os

import cv2 as cv
import numpy as np
import click
import time
import pygame
import pygame.locals as pyloc
import librosa as lr
import sounddevice as sd
import ffmpeg
import logging
from pyrubberband.pyrb import time_stretch
import re
import pyaudio

logging.basicConfig(level=logging.DEBUG)
log = logging.getLogger('log')

# TODO Make it so that you can set the speed
# TODO make it so that you can start from any playback positon
# TODO make it so that you can seek (restart play_from_pos)
# TODO Stream audio also with ffmpeg so that no new file needs to be generated
#  (then it should work with ts files that are currently being written)

# TODO this is very buggy
def handle_events():
    events = pygame.event.get()
    for event in events:
        if event.type == pyloc.QUIT:
            pygame.display.quit()
            exit(0)
        # elif event.type == pyloc.VIDEORESIZE:
        #     screen = pygame.display.set_mode(event.dict['size'], pyloc.RESIZABLE)
        #     screen_resolution = event.dict['size']


def play_from_pos(file, screen, screen_resolution, video_resolution, audio_sr,
                  framerate, speed=1, speed_on_silence=2, play_from=0):
    v_width, v_height = video_resolution
    read_proc = (
        ffmpeg
        .input(file)
        .output('pipe:', format='rawvideo', pix_fmt='rgb24')
        .run_async(pipe_stdout=True)
    )

    log.info("loading audio")
    audio_path = re.sub("\..*$", '.wav', file)
    if not os.path.isfile(audio_path):
        log.info("Need the audio as seperate wav, generating now.")
        (
            ffmpeg
            .input(file)
            .output(audio_path)
            .run()
        )

    BLOCK_LENGTH = 256*1
    FRAME_LENGTH = 1
    audio_iterator = lr.core.stream(audio_path, BLOCK_LENGTH, FRAME_LENGTH, 1,
                                    offset=play_from, fill_value=0)


    shortening_timelength = BLOCK_LENGTH / audio_sr
    l = []
    dropped = []
    AUDIO_THRESHHOLD = 0.1

    FADE_LENGTH = BLOCK_LENGTH//2
    m = np.zeros(BLOCK_LENGTH)
    # m[:FADE_LENGTH] = np.linspace(1, 0, FADE_LENGTH)
    # m[-FADE_LENGTH:] = np.linspace(0, 1, FADE_LENGTH)

    def callback(in_data, frame_count, time_info, status):
        while len(l) < 4:
            l.append(next(audio_iterator))

        if not (np.max(l[0]) > AUDIO_THRESHHOLD or \
                np.max(l[1]) > AUDIO_THRESHHOLD or \
                np.max(l[2]) > AUDIO_THRESHHOLD or \
                np.max(l[3]) > AUDIO_THRESHHOLD):
            x = l.pop(0)
            l[0] = m * np.concatenate((x[::2], l[0][::2]))
            dropped.append(True)

        data = l.pop(0)
        if len(data) == 0:
            return None, pyaudio.paComplete
        return data, pyaudio.paContinue

    p = pyaudio.PyAudio()
    stream = p.open(format=pyaudio.paFloat32,
                    channels=1,
                    rate=audio_sr,
                    frames_per_buffer=BLOCK_LENGTH,
                    output=True,
                    stream_callback=callback
                    )

    log.info("starting playback")
    start_time = time.time()
    curr_idx = 0
    playback_offset = 0
    while True:
        log.debug(f"Playback offset {playback_offset}")
        handle_events()
        playback_time_o = time.time() - start_time
        # print(playback_time_o)
        playback_time = playback_time_o + playback_offset
        # print(f'offset {playback_time}')
        playback_offset += shortening_timelength * len(dropped)
        dropped.clear()
        # print(playback_offset)


        frame_idx_no_offset = int(playback_time_o * framerate * speed + play_from * framerate)
        frame_idx = int(playback_time * framerate * speed + play_from * framerate)
        # print(f'frame no offset {frame_idx_no_offset}, with offset {frame_idx}')
        while curr_idx <= frame_idx:
            in_bytes = read_proc.stdout.read(v_width * v_height * 3)
            curr_idx += 1
            # print(f'curr_idx {curr_idx}, frame_idx {frame_idx}')
        if len(in_bytes) == 0:
            log.info("Steam empty, stopping playback")
            break
        in_frame = (
            np
            .frombuffer(in_bytes, np.uint8)
            .reshape([v_height, v_width, 3])
        )
        frame_surf = pygame.surfarray.make_surface(np.transpose(in_frame, [1,0,2]))
        pygame.transform.scale(frame_surf, screen_resolution, screen)
        pygame.display.flip()

    stream.close()


@click.command()
@click.option('-f', '--file',
              type=click.Path(True, dir_okay=False, resolve_path=True),
              required=True, help="The file to playback.")
@click.option('-s', '--speed', type=float, default=1, show_default=True,
              help='How fast to playback.')
@click.option('--start', type=int, default=0, show_default=True,
              help='Where to start playback in seconds.')
@click.option('--frame-rate', type=int, default=60, show_default=True,
              help='The framerate of the input video.')
@click.option('--audio-sr', type=int, default=0, show_default=True,
              help='The sample rate of the input audio. If set to 0 it is'
                   'infered')
@click.option('-r', '--screen-resolution', type=int, nargs=2,
              default=(1920, 1080),
              show_default=True, help='The resolution to display the video in.')
@click.option('-r', '--input-resolution', type=int, nargs=2,
              default=(1920, 1080),
              show_default=True, help='The resolution of the input video file.')
def main(file, speed, start, frame_rate, audio_sr, screen_resolution,
         input_resolution):
    pygame.init()
    screen = pygame.display.set_mode(screen_resolution)
    if audio_sr == 0:
        audio_sr = lr.get_samplerate(file)
        log.debug(f'Audio sample-rate of {audio_sr} inferred.')
    play_from_pos(file=file, screen=screen,
                  screen_resolution=screen_resolution,
                  video_resolution=input_resolution, audio_sr=audio_sr,
                  framerate=frame_rate, speed=speed, play_from=start)


if __name__ == '__main__':
    main()