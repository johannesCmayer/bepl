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
from collections import namedtuple
import subprocess

logging.basicConfig(level=logging.DEBUG)
log = logging.getLogger(__name__)
playlog = log.getChild('playback')

PlayArgs = namedtuple('PlayArgs', 'mouse_pos position_offset pause')


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


def handle_events():
    events = pygame.event.get()
    play_offset = None
    mouse_pos = None
    pause = None
    for event in events:
        if event.type == pyloc.QUIT:
            pygame.display.quit()
            exit(0)
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                pygame.display.quit()
                exit(0)
            if event.key == pygame.K_SPACE:
                pause = True
            if event.key == pygame.K_LEFT:
                play_offset = -5
            elif event.key == pygame.K_RIGHT:
                play_offset = 5
        if event.type == pygame.MOUSEBUTTONDOWN:
            mouse_pos = pygame.mouse.get_pos()
        # elif event.type == pyloc.VIDEORESIZE:
        #     screen = pygame.display.set_mode(event.dict['size'], pyloc.RESIZABLE)
        #     screen_resolution = event.dict['size']
    return PlayArgs(mouse_pos, play_offset, pause)


def stats_surf():
    pass


def play_from_pos(file, screen, screen_resolution, video_resolution,
                  pyaudio_instance, audio_sr,
                  frame_rate, speed, play_from, speedup_silence,
                  ffmpeg_loglevel):
    playlog.debug("Starting video stream.")
    v_width, v_height = video_resolution
    read_proc = (
        ffmpeg
            .input(file, ss=play_from, loglevel=ffmpeg_loglevel)
            .output('pipe:', format='rawvideo', pix_fmt='rgb24')
            .run_async(pipe_stdout=True)
    )

    audio_path = re.sub("\..*$", '.wav', file)
    if not os.path.isfile(audio_path):
        playlog.info("Need the audio as seperate wav, generating now.")
        (
            ffmpeg
                .input(file, loglevel=ffmpeg_loglevel)
                .output(audio_path)
                .run()
        )

    playlog.debug('Starting audio stream')
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

        if speedup_silence and not \
                (np.max(l[0]) > AUDIO_THRESHHOLD or
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

    playlog.debug("starting playback")
    start_time = time.time()
    curr_idx = 0
    playback_offset = 0
    while True:
        ret = handle_events()
        if any([x is not None for x in ret]):
            audio_out_stream.close()
            video_position = curr_idx / frame_rate + play_from
            return video_position, ret
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
            playlog.info("Steam empty, stopping playback")
            break
        in_frame = (
            np
                .frombuffer(in_bytes, np.uint8)
                .reshape([v_height, v_width, 3])
        )
        frame_surf = pygame.surfarray.make_surface(
            np.transpose(in_frame, [1, 0, 2]))
        pygame.transform.scale(frame_surf, screen_resolution, screen)
        # TODO implement stats display
        # screen.blit(stats_surf(), (0, 0))
        pygame.display.flip()

    audio_out_stream.close()


def get_file_resolution(file):
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                        f"-show_entries", "stream=width,height",
                        f"-of", "csv=s=x:p=0", file],
                       stdout=subprocess.PIPE,
                       stderr=subprocess.STDOUT)
    res = re.match(r'(\d+)x(\d+)\n?', r.stdout.decode('utf-8'))
    if not res:
        raise Exception(f"Could not infer resolution from ffprobe output {r}.")
    return int(res.group(1)), int(res.group(2))


def get_file_length(file):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                        "format=duration", "-of",
                        "default=noprint_wrappers=1:nokey=1", file],
                       stdout=subprocess.PIPE,
                       stderr=subprocess.STDOUT)
    return float(r.stdout)


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
@click.option('--audio-sr', type=int,
              help='The sample rate of the input audio. Infered when not set.')
@click.option('-r', '--screen-resolution', type=int, nargs=2,
              default=(1920, 1080),
              show_default=True,
              help='The resolution to display the video in.')
@click.option('--input-resolution', type=int, nargs=2,
              help='The resolution of the input video file.')
@click.option('-b', '--speedup-silence', is_flag=True, default=True,
              show_default=True,
              help="Should prats of the video containing silence be sped up.")
@click.option('--ffmpeg-loglevel', default='warning', show_default=True,
              help="Set the loglevel of ffmpeg.")
def main(file, speed, start, frame_rate, audio_sr, screen_resolution,
         input_resolution, speedup_silence, ffmpeg_loglevel):
    pyaudio_instance = pyaudio.PyAudio()
    pygame.init()
    screen = pygame.display.set_mode(screen_resolution)

    if not audio_sr:
        audio_sr = lr.get_samplerate(file)
        log.info(f'Audio sample-rate of {audio_sr} inferred.')
    if not input_resolution:
        input_resolution = get_file_resolution(file)
    input_length = get_file_length(file)

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
           'ffmpeg_loglevel': ffmpeg_loglevel,
           }
    while True:
        # TODO return the time where video was currently at
        vid_pos, new_cmd = play_from_pos(**cmd)
        cmd['play_from'] = vid_pos
        if new_cmd.position_offset:
            cmd['play_from'] = \
                np.clip(vid_pos + new_cmd.position_offset, 0, input_length)
        if new_cmd.mouse_pos:
            cmd['play_from'] = \
                new_cmd.mouse_pos[0] / screen_resolution[0] * input_length
        if new_cmd.pause:
            while True:
                new_new_cmd = handle_events()
                if new_new_cmd.pause:
                    break

    pyaudio_instance.terminate()


if __name__ == '__main__':
    main()
