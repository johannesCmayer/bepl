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

# TODO when mouse click sikp to percent of video where percent is mause.x / screen.x
# TODO on file ends reared -> handle gracefully (instead of crash)
# TODO create timeline
# TODO  show remaining video runtime
# TODO allow fractional speed
# TODO make it so that you can skip 5s forward or back
# TODO pause video
# TODO Stream audio also with ffmpeg so that no new file needs to be generated
#  (then it should work with ts files that are currently being written)
# TODO Fix audiodistortions on speedup
# NICE you can stream youtube videos


# TODO this is very buggy
def handle_events():
    events = pygame.event.get()
    ret = None
    for event in events:
        if event.type == pyloc.QUIT:
            pygame.display.quit()
            exit(0)
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                pygame.display.quit()
                exit(0)
            if event.key == pygame.K_LEFT:
                ret = -5
            elif event.key == pygame.K_RIGHT:
                ret = 5
        # elif event.type == pyloc.VIDEORESIZE:
        #     screen = pygame.display.set_mode(event.dict['size'], pyloc.RESIZABLE)
        #     screen_resolution = event.dict['size']
    return ret


def play_from_pos(file, screen, screen_resolution, video_resolution,
                  pyaudio_instance, audio_sr,
                  frame_rate, speed, play_from, speedup_silence):
    v_width, v_height = video_resolution
    read_proc = (
        ffmpeg
            .input(file, ss=play_from)
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

    BLOCK_LENGTH = 256 * 20
    FRAME_LENGTH = 1
    audio_iterator = lr.core.stream(audio_path, BLOCK_LENGTH, FRAME_LENGTH, 1,
                                    offset=play_from, fill_value=0)

    shortening_timelength = BLOCK_LENGTH / audio_sr / speed
    l = []
    dropped = []
    AUDIO_THRESHHOLD = 0.1

    def callback(in_data, frame_count, time_info, status):
        while len(l) < 4:
            l.append(next(audio_iterator))

        if speedup_silence and not (np.max(l[0]) > AUDIO_THRESHHOLD or
                                    np.max(l[1]) > AUDIO_THRESHHOLD or
                                    np.max(l[2]) > AUDIO_THRESHHOLD or
                                    np.max(l[3]) > AUDIO_THRESHHOLD):
            x = l.pop(0)
            z = np.zeros(BLOCK_LENGTH)
            # INTERPOLATE_POINTS = 10
            # if INTERPOLATE_POINTS > 0:
            #     z[0:INTERPOLATE_POINTS] = np.linspace(x[0], 0, INTERPOLATE_POINTS)
            #     z[-INTERPOLATE_POINTS:] = np.linspace(0, l[0][-1], INTERPOLATE_POINTS)
            # l[0] = z * np.concatenate((x[::2], l[0][::2]))
            # data = l.pop()
            data = z
            dropped.append(True)

        if speed == 1:
            data = l.pop(0)
        elif speed == 2:
            x1 = l.pop(0)
            x2 = l.pop(0)
            arr = np.concatenate((x1, x2))
            data = lr.effects.time_stretch(arr, speed, center=False)
        else:
            raise Exception("Only 2 and 1 are currently supported speeds.")

        return data, pyaudio.paContinue

    audio_out_stream = pyaudio_instance.open(format=pyaudio.paFloat32,
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
        ret = handle_events()
        if ret:
            audio_out_stream.close()
            return ret
        playback_time = time.time() - start_time + playback_offset
        # print(f'offset {playback_time}')
        playback_offset += shortening_timelength * len(dropped)
        dropped.clear()
        # print(playback_offset)

        frame_idx = int(playback_time * frame_rate * speed)
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
        frame_surf = pygame.surfarray.make_surface(
            np.transpose(in_frame, [1, 0, 2]))
        pygame.transform.scale(frame_surf, screen_resolution, screen)
        pygame.display.flip()

    audio_out_stream.close()


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
                   'inferred.')
@click.option('-r', '--screen-resolution', type=int, nargs=2,
              default=(1920, 1080),
              show_default=True,
              help='The resolution to display the video in.')
@click.option('--input-resolution', type=int, nargs=2,
              default=(1920, 1080),
              show_default=True,
              help='The resolution of the input video file.')
@click.option('-b', '--speedup-silence', is_flag=True, default=True,
              show_default=True,
              help="Should prats of the video containing silence be sped up.")
def main(file, speed, start, frame_rate, audio_sr, screen_resolution,
         input_resolution, speedup_silence):
    print(speedup_silence)
    pyaudio_instance = pyaudio.PyAudio()
    pygame.init()
    screen = pygame.display.set_mode(screen_resolution)
    if audio_sr == 0:
        audio_sr = lr.get_samplerate(file)
        log.debug(f'Audio sample-rate of {audio_sr} inferred.')
    cmd = {'file': file,
           'screen': screen,
           'screen_resolution': screen_resolution,
           'video_resolution': input_resolution,
           'audio_sr': audio_sr,
           'frame_rate': frame_rate,
           'speed': speed,
           'play_from': start,
           'speedup_silence': speedup_silence,
           'pyaudio_instance': pyaudio_instance,
           }
    while True:
        # TODO return the time where video was currently at
        new_cmd = play_from_pos(**cmd)
        cmd['play_from'] += 5

    pyaudio_instance.terminate()


if __name__ == '__main__':
    main()
