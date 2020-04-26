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
import json
import os

logging.basicConfig(level=logging.DEBUG)
log = logging.getLogger(__name__)
playlog = log.getChild('playback')


class PlayArgs:
    def __init__(self, mouse_pos, position_offset, window_size, speed, pause,
                 exit):
        self.window_size = window_size
        self.speed = speed
        self.exit = exit
        self.pause = pause
        self.mouse_pos = mouse_pos
        self.position_offset = position_offset

    def got_command(self):
        return self.pause or self.mouse_pos or self.position_offset or \
               self.exit or self.speed or self.window_size


# TODO create timeline
# TODO  show remaining video runtime (with speedup and approximate frame drop
#  time saving)
# TODO Fix audiodistortions on speedup
# TODO allow fractional speed
# TODO make it that it works for audiofiles
# TODO Report when closed how much time was saved compared to watching the
#  video normally (display savings from silence skipping and speedup)
# TODO cerate command line documentation on controlls in window
# NICE you can stream youtube videos


def handle_events():
    events = pygame.event.get()
    play_offset = None
    mouse_pos = None
    pause = None
    exit = None
    speed = None
    window_size = None
    for event in events:
        if event.type == pyloc.QUIT:
            exit = True
        elif event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                exit = True
            elif event.key == pygame.K_SPACE:
                pause = True
            elif event.key == pygame.K_LEFT:
                play_offset = -5
            elif event.key == pygame.K_RIGHT:
                play_offset = 5
            elif event.key in [pygame.K_KP_PLUS, pygame.K_PLUS]:
                speed = 2
            elif event.key in [pygame.K_KP_MINUS, pygame.K_MINUS]:
                speed = 1
        elif event.type == pygame.MOUSEBUTTONDOWN:
            mouse_pos = pygame.mouse.get_pos()
        elif event.type == pyloc.VIDEORESIZE:
            window_size = event.dict['size']
    return PlayArgs(mouse_pos, play_offset, window_size, speed, pause, exit)


def stats_surf(playbacktime, total_media_length):
    pass


def create_ffmpeg_video_stream(file, ss, ffmpeg_loglevel, frame_rate):
    read_proc = (
        ffmpeg
            .input(file, ss=ss, loglevel=ffmpeg_loglevel)
            .output('pipe:', format='rawvideo', pix_fmt='rgb24', r=frame_rate)
            .run_async(pipe_stdout=True)
    )
    return read_proc

def create_ffmpeg_audio_stream(file, ss, ffmpeg_loglevel):
    read_proc = (
        ffmpeg
            .input(file, ss=ss, loglevel=ffmpeg_loglevel)
            .output('pipe:', format='f32le', acodec='pcm_f32le')
            .run_async(pipe_stdout=True)
    )
    return read_proc

def play_from_pos(file, screen, screen_resolution, video_resolution,
                  pyaudio_instance, audio_sr,
                  frame_rate, speed, play_from, speedup_silence,
                  ffmpeg_loglevel):
    v_width, v_height = video_resolution
    playlog.debug('Starting audio stream')
    audio_stream = create_ffmpeg_audio_stream(file, play_from, ffmpeg_loglevel)
    playlog.debug("Starting video stream.")
    video_stream = create_ffmpeg_video_stream(file, play_from, ffmpeg_loglevel,
                                              frame_rate)

    BLOCK_LENGTH = 1024 * 10
    AUDIO_DROP_SKIP_DURATION = \
        BLOCK_LENGTH / audio_sr / speed * speedup_silence / 2
    AUDIO_THRESHHOLD = 0.1

    buffer = []
    n_droped = [0]

    def callback_ff(in_data, frame_count, time_info, status):
        while len(buffer) < speedup_silence + 2:
            data = audio_stream.stdout.read(BLOCK_LENGTH * 4)
            if len(data) == 0:
                playlog.debug(
                    "Stopping audio playback stream end reached.")
                return None, pyaudio.paComplete
            data = np.frombuffer(data, np.float32)
            buffer.append(data)

        if speedup_silence and \
                not (np.array(
                    [np.max(x) for x in buffer]) > AUDIO_THRESHHOLD).any():
            for _ in range(speedup_silence):
                buffer.pop(1)
            # l[0] = l[0] * np.linspace(1, 0, BLOCK_LENGTH)
            n_droped[0] += 1
            # INTERPOLATE_POINTS = 10
            # if INTERPOLATE_POINTS > 0:
            #     z[0:INTERPOLATE_POINTS] = np.linspace(x[0], 0, INTERPOLATE_POINTS)
            #     z[-INTERPOLATE_POINTS:] = np.linspace(0, l[0][-1], INTERPOLATE_POINTS)
            # l[0] = z * np.concatenate((x[::2], l[0][::2]))
            # data = l.pop()

            # l[0] *= np.linspace(1, 0, BLOCK_LENGTH)

        if speed == 1:
            data = buffer.pop(0)
        elif speed == 2:
            x1 = buffer.pop(0)
            x2 = buffer.pop(0)
            arr = np.concatenate((x1, x2))
            data = lr.effects.time_stretch(arr, speed, center=False)
        else:
            raise Exception("Only 2 and 1 are currently supported speeds.")
        return data, pyaudio.paContinue


    audio_out_stream = pyaudio_instance.open(
        format=pyaudio.paFloat32,
        channels=1,
        rate=audio_sr*2,
        frames_per_buffer=BLOCK_LENGTH,
        output=True,
        stream_callback=callback_ff
    )

    def cleanup():
        audio_out_stream.close()
        audio_stream.kill()
        video_stream.kill()

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
        playback_offset += AUDIO_DROP_SKIP_DURATION * n_droped[0]
        n_droped[0] = 0

        frame_idx = int(playback_time * frame_rate * speed)
        if curr_idx >= frame_idx:
            continue
        while curr_idx < frame_idx:
            video_stream.stdout.read(v_width * v_height * 3)
            curr_idx += 1
        in_bytes = video_stream.stdout.read(v_width * v_height * 3)
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
                .transpose([1, 0, 2])
        )
        frame_surf = pygame.surfarray.make_surface(in_frame)
        if not video_resolution == screen_resolution:
            frame_surf = pygame.transform.scale(frame_surf, screen_resolution)
        screen.blit(frame_surf, (0, 0))
        # TODO implement stats display
        # screen.blit(stats_surf(), (0, 0))
        pygame.display.flip()

    raise Exception("Invalid programm state")

# =============================================================================
# STARTUP
# =============================================================================

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
@click.argument('file',
                type=click.Path(True, dir_okay=False, resolve_path=True))
@click.option('-s', '--speed', type=float, default=2, show_default=True,
              help='How fast to playback.')
@click.option('--play-from', type=int, default=None, show_default=True,
              help='Where to start playback in seconds.')
@click.option('--frame-rate', type=int, default=20, show_default=True,
              help='The framerate to play the video back at. Low values '
                   'improve performance.')
@click.option('-r', '--screen-resolution', type=int, nargs=2,
              default=(1920, 1080),
              show_default=True,
              help='The resolution to display the video in.')
@click.option('-b', '--speedup-silence', default=3, type=int,
              show_default=True,
              help="How much faster to play silence.")
@click.option('--no-save-pos', is_flag=True,
              help='Disable loading and saving of the playback position.')
@click.option('--ffmpeg-loglevel', default='warning', show_default=True,
              help="Set the loglevel of ffmpeg.")
def main(file, speed, play_from, frame_rate, screen_resolution,
         speedup_silence, no_save_pos, ffmpeg_loglevel):
    VIDEO_PLAYBACK_SAVE_FILE = \
        f'{os.path.dirname(__file__)}/playback_positions.json'
    log.debug(f'Video pos save file {VIDEO_PLAYBACK_SAVE_FILE}')
    pyaudio_instance = pyaudio.PyAudio()
    pygame.init()
    screen = pygame.display.set_mode(screen_resolution, pygame.RESIZABLE)
    pygame.display.set_caption('bepl')

    audio_sr = lr.get_samplerate(file)
    log.debug(f'Audio sample-rate of {audio_sr} inferred.')
    input_resolution = get_file_resolution(file)
    log.debug(f'Video resolution infered {input_resolution}')
    input_length = get_file_length(file)

    if not play_from:
        play_from = load_playback_pos(VIDEO_PLAYBACK_SAVE_FILE, file)

    cmd = {'file': file,
           'screen': screen,
           'screen_resolution': screen_resolution,
           'video_resolution': input_resolution,
           'audio_sr': audio_sr,
           'frame_rate': frame_rate,
           'speed': speed,
           'play_from': play_from,
           'speedup_silence': speedup_silence,
           'pyaudio_instance': pyaudio_instance,
           'ffmpeg_loglevel': ffmpeg_loglevel,
           }
    while True:
        stream_ended, vid_pos, new_cmd = play_from_pos(**cmd)
        if new_cmd.exit:
            if not no_save_pos:
                save_playback_pos(VIDEO_PLAYBACK_SAVE_FILE, file, vid_pos)
            break
        cmd['play_from'] = vid_pos
        if new_cmd.pause:
            while True:
                new_cmd = handle_events()
                if new_cmd.got_command():
                    break
        if new_cmd.window_size:
            cmd['screen_resolution'] = new_cmd.window_size
            screen = pygame.display.set_mode(screen_resolution, pygame.RESIZABLE)
            cmd['screen'] = screen
            print(cmd['screen_resolution'])
        if new_cmd.speed:
            cmd['speed'] = new_cmd.speed
        if new_cmd.position_offset:
            cmd['play_from'] = \
                np.clip(vid_pos + new_cmd.position_offset, 0, input_length)
        if new_cmd.mouse_pos:
            cmd['play_from'] = \
                new_cmd.mouse_pos[0] / screen_resolution[0] * input_length

    pyaudio_instance.terminate()
    pygame.display.quit()


def load_playback_pos(save_file, video_file, seek_back=2):
    if not os.path.isfile(save_file):
        return 0
    with open(save_file) as f:
        data = json.load(f)
        if video_file in data.keys():
            play_from = data[video_file]
        else:
            play_from = 0
    log.debug(f'Loaded playback time of {video_file}')
    return max(0, play_from - seek_back)


def save_playback_pos(save_file, video_file, vid_pos):
    new_save = {video_file: vid_pos}
    data = {}
    if os.path.isfile(save_file):
        with open(save_file, 'r') as f:
            data = json.load(f)
    data.update(new_save)
    with open(save_file, 'w') as f:
        json.dump(data, f)
    log.debug(f'Saved playback time of {video_file}')


if __name__ == '__main__':
    main()
