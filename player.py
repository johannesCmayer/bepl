import os
import numpy as np
import click
import time
import pygame
import pygame.locals as pyloc
import librosa as lr
import ffmpeg
import logging
import re
import pyaudio
import subprocess
from collections import namedtuple
import threading

logging.basicConfig(level=logging.DEBUG)
log = logging.getLogger(__name__)
playlog = log.getChild('playback')


class PlayArgs:
    def __init__(self, mouse_pos, position_offset, speed, pause, exit):
        self.speed = speed
        self.exit = exit
        self.pause = pause
        self.mouse_pos = mouse_pos
        self.position_offset = position_offset

    def got_command(self):
        return self.pause or self.mouse_pos or self.position_offset or \
               self.exit


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
    exit = None
    speed = None
    for event in events:
        if event.type == pyloc.QUIT:
            exit = True
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                exit = True
            if event.key == pygame.K_SPACE:
                pause = True
            if event.key == pygame.K_LEFT:
                play_offset = -5
            elif event.key == pygame.K_RIGHT:
                play_offset = 5
            if event.key in [pygame.K_KP_PLUS, pygame.K_PLUS]:
                speed = 2
            elif event.key in [pygame.K_KP_MINUS, pygame.K_MINUS]:
                speed = 1
        if event.type == pygame.MOUSEBUTTONDOWN:
            mouse_pos = pygame.mouse.get_pos()
        # elif event.type == pyloc.VIDEORESIZE:
        #     screen = pygame.display.set_mode(event.dict['size'], pyloc.RESIZABLE)
        #     screen_resolution = event.dict['size']
    return PlayArgs(mouse_pos, play_offset, speed, pause, exit)


def stats_surf():
    pass


def play_from_pos(file, screen, screen_resolution, video_resolution,
                  pyaudio_instance, audio_sr,
                  frame_rate, speed, play_from, speedup_silence,
                  ffmpeg_loglevel):
    playlog.debug("Starting video stream.")
    v_width, v_height = video_resolution
    def create_read_file_proc(ss):
        read_proc = (
            ffmpeg
                .input(file, ss=ss, loglevel=ffmpeg_loglevel)
                .output('pipe:', format='rawvideo', pix_fmt='rgb24', vf=f"scale={video_resolution[0]}:{video_resolution[1]}")
                .run_async(pipe_stdout=True)
        )
        return read_proc

    read_proc = create_read_file_proc(play_from)

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


    shortening_timelength = BLOCK_LENGTH / audio_sr / speed * speedup_silence
    l = []
    dropped = []
    AUDIO_THRESHHOLD = 0.1

    def callback(in_data, frame_count, time_info, status):
        while len(l) < speedup_silence + 2:
            try:
                l.append(next(audio_iterator))
            except StopIteration:
                playlog.debug("Stopping audio playback stream end reached.")
                return None, pyaudio.paComplete

        if speedup_silence and \
                not (np.array([np.max(x) for x in l]) > AUDIO_THRESHHOLD).any():
            for _ in range(speedup_silence):
                l.pop(1)
            # l[0] = l[0] * np.linspace(1, 0, BLOCK_LENGTH)
            dropped.append(True)
            # INTERPOLATE_POINTS = 10
            # if INTERPOLATE_POINTS > 0:
            #     z[0:INTERPOLATE_POINTS] = np.linspace(x[0], 0, INTERPOLATE_POINTS)
            #     z[-INTERPOLATE_POINTS:] = np.linspace(0, l[0][-1], INTERPOLATE_POINTS)
            # l[0] = z * np.concatenate((x[::2], l[0][::2]))
            # data = l.pop()

            # l[0] *= np.linspace(1, 0, BLOCK_LENGTH)


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

    audio_out_stream = pyaudio_instance.open(
        format=pyaudio.paFloat32,
        channels=1,
        rate=audio_sr,
        frames_per_buffer=BLOCK_LENGTH,
        output=True,
        stream_callback=callback
    )

    def cleanup():
        audio_out_stream.close()
        audio_iterator.close()
        read_proc.kill()

    def video_position(curr_idx, frame_rate, play_from):
        return curr_idx / frame_rate + play_from

    playlog.debug("starting playback")
    start_time = time.time()
    curr_idx = 0
    playback_offset = 0
    curr2 = 0
    while True:
        ret = handle_events()
        if ret.got_command():
            cleanup()
            video_position = video_position(curr_idx, frame_rate, play_from)
            return False, video_position, ret
        playback_time = time.time() - start_time + playback_offset
        playback_offset += shortening_timelength * len(dropped)
        dropped.clear()

        frame_idx = int(playback_time * frame_rate * speed)
        # TODO Convert this to a seekable stream and use it to skip
        while curr_idx < int(playback_time * frame_rate * speed):
            read_proc.stdout.read(v_width * v_height * 3)
            curr_idx += 1
        in_bytes = read_proc.stdout.read(v_width * v_height * 3)
        curr_idx += 1
        if len(in_bytes) == 0:
            playlog.info("Steam empty, stopping playback")
            cleanup()
            video_position = video_position(curr_idx, frame_rate, play_from)
            return True, video_position, ret
        in_frame = (
            np
            .frombuffer(in_bytes, np.uint8)
            .reshape([v_height, v_width, 3])
            .transpose([1,0,2])
        )
        frame_surf = pygame.surfarray.make_surface(in_frame)
        if video_resolution == screen_resolution:
            screen.blit(frame_surf, (0,0))
        else:
            pygame.transform.scale(frame_surf, screen_resolution, screen)
        # TODO implement stats display
        # screen.blit(stats_surf(), (0, 0))
        pygame.display.flip()

    raise Exception("Invalid programm state")


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
@click.option('-b', '--speedup-silence', default=3, type=int,
              show_default=True,
              help="How much faster to play silence.")
@click.option('--ffmpeg-loglevel', default='warning', show_default=True,
              help="Set the loglevel of ffmpeg.")
def main(file, speed, start, frame_rate, audio_sr, screen_resolution,
         input_resolution, speedup_silence, ffmpeg_loglevel):
    pyaudio_instance = pyaudio.PyAudio()
    pygame.init()
    screen = pygame.display.set_mode(screen_resolution)
    pygame.display.set_caption('bepl')

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
        stream_ended, vid_pos, new_cmd = play_from_pos(**cmd)
        if new_cmd.exit:
            break
        cmd['play_from'] = vid_pos
        if new_cmd.pause:
            while True:
                new_cmd = handle_events()
                if new_cmd.got_command():
                    break
        if new_cmd.position_offset:
            cmd['play_from'] = \
                np.clip(vid_pos + new_cmd.position_offset, 0, input_length)
        if new_cmd.mouse_pos:
            cmd['play_from'] = \
                new_cmd.mouse_pos[0] / screen_resolution[0] * input_length

    pyaudio_instance.terminate()
    pygame.display.quit()


if __name__ == '__main__':
    main()
