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
import signal

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


# TODO resisable window
# TODO Make it so that you can install via pip (the executable) (use setuptools? look at click documentation)
# TODO create tests for different file types
# FIXME Fix audiodistortions when skipping audio
# TODO allow fractional speed
# TODO make it that it works for audiofiles
# TODO cerate command line documentation on controlls in window
# TODO add speed modifiers in timeline
# IFNEEDED create audio syncpoints. Prestart new audio and video streams
#  (or only one of them) and then switch to them at a specific sync point
#  (some point in time)
# NICE you can stream youtube videos

class EventManager:
    def __init__(self):
        signal.signal(signal.SIGINT, self.set_exit)
        signal.signal(signal.SIGTERM, self.set_exit)
        self.exit = None
        self.time_last_mouse_move = 0
        self.last_mouse_pos = None
        self.last_vid_resize = None

    def set_exit(self, signum, frame):
        self.exit = True
        log.debug('Exit flag set')

    def handle_events(self):
        events = pygame.event.get()
        play_offset = None
        pause = None
        speed = None
        window_size = None
        mouse_button = None
        screen_adjusted = False
        mouse_pos = pygame.mouse.get_pos()
        if mouse_pos != self.last_mouse_pos:
            self.last_mouse_pos = mouse_pos
            self.time_last_mouse_move = time.time()
            self.mouse_moved = True
        else:
            self.mouse_moved = False
        for event in events:
            if event.type == pyloc.QUIT:
                self.set_exit(None, None)
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    self.set_exit(None, None)
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
                mouse_button = True
            if event.type == pyloc.VIDEORESIZE:
                self.last_vid_resize = event.dict['size']
                screen_adjusted = True
                print(f'resize: {self.last_vid_resize}')

        if not screen_adjusted and self.last_vid_resize:
            window_size = self.last_vid_resize
            self.last_vid_resize = None
        pygame.display.flip()
        return PlayArgs(mouse_pos if mouse_button else None, play_offset,
                        window_size, speed, pause,
                        self.exit)


class AudioPlayer:
    def __init__(self, pyaudio_instance, audio_sr, speed, speedup_silence,
                 file, play_from, ffmpeg_loglevel):
        self.pyaudio_instance = pyaudio_instance
        self.audio_sr = audio_sr
        self.speed = speed
        self.speedup_silence = speedup_silence
        self.file = file
        self.play_from = play_from
        self.ffmpeg_loglevel = ffmpeg_loglevel

        self.BLOCK_LENGTH = 1024 * 10
        self.AUDIO_DROP_SKIP_DURATION = \
            self.BLOCK_LENGTH / audio_sr / speed * speedup_silence / 2
        self.AUDIO_THRESHHOLD = 0.1

        self.buffer = []
        self.n_droped = [0]

        self.audio_stream = create_ffmpeg_audio_stream(file, play_from,
                                                       ffmpeg_loglevel)
        self.audio_out_stream = pyaudio_instance.open(
            format=pyaudio.paFloat32,
            channels=1,
            rate=audio_sr * 2,
            frames_per_buffer=self.BLOCK_LENGTH,
            output=True,
            stream_callback=self.callback_ff
        )
        playlog.debug('Audioplayer started')

    def callback_ff(self, in_data, frame_count, time_info, status):
        while len(self.buffer) < self.speedup_silence + 2:
            data = self.audio_stream.stdout.read(self.BLOCK_LENGTH * 4)
            if len(data) == 0:
                playlog.debug(
                    "Stopping audio playback stream end reached.")
                return None, pyaudio.paComplete
            data = np.frombuffer(data, np.float32)
            self.buffer.append(data)

        if self.speedup_silence and \
                not (np.array(
                    [np.max(x) for x in
                     self.buffer]) > self.AUDIO_THRESHHOLD).any():
            for _ in range(self.speedup_silence):
                x = self.buffer.pop(1)
            # lr.effects.time_stretch(np.concatenate(), self.speed, center=False)
            self.n_droped[0] += 1

        if self.speed == 1:
            data = self.buffer.pop(0)
        elif self.speed == 2:
            x1 = self.buffer.pop(0)
            x2 = self.buffer.pop(0)
            arr = np.concatenate((x1, x2))
            data = lr.effects.time_stretch(arr, self.speed, center=False)
        else:
            raise Exception("Only 2 and 1 are currently supported speeds.")
        return data, pyaudio.paContinue

    def close(self):
        self.audio_out_stream.close()
        self.audio_stream.kill()


def sec_to_time_str(x):
    m, s = divmod(x, 60)
    h, m = divmod(m, 60)
    return f'{int(h):02}:{int(m):02}:{int(s):02}'


def get_stats_surf(playbar_offset_pix, screen_resolution, playbacktime,
                   total_media_length, speed):
    FONT_SIZE = 20
    FONT_COLOR = (200, 200, 200)
    font = pygame.font.SysFont(None, FONT_SIZE)

    x, y = screen_resolution[0], 1080 // 20
    pos = screen_resolution[0] - x, screen_resolution[1] - y
    surf = pygame.Surface((x, y))
    surf.set_alpha(200)
    ratio_played = playbacktime / total_media_length
    outline = pygame.Rect(playbar_offset_pix[0], playbar_offset_pix[1],
                          x - playbar_offset_pix[0] * 2,
                          y - playbar_offset_pix[1] * 2)
    progress = outline.copy()
    progress.width = outline.width * ratio_played
    OUTLINE_THICKNESS = 2
    outline.height -= OUTLINE_THICKNESS / 2
    outline.width -= OUTLINE_THICKNESS / 2
    a = 50
    pygame.draw.rect(surf, (a, a, a), outline, OUTLINE_THICKNESS)
    pygame.draw.rect(surf, (255, 255, 255), progress)


    # TIMINGS
    PADING = 3
    text = font.render(f' {sec_to_time_str(playbacktime)}', True, FONT_COLOR)
    surf.blit(text, (PADING, PADING))

    time_remaining = sec_to_time_str(
        (total_media_length - playbacktime) / speed)
    text = font.render(f'-{time_remaining}', True, FONT_COLOR)
    surf.blit(text, (PADING, y / 2 - PADING - FONT_SIZE / 5))

    text = font.render(f' {sec_to_time_str(total_media_length)}', True,
                       FONT_COLOR)
    surf.blit(text, (PADING, y - PADING - FONT_SIZE / 1.5))
    return surf, pos


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
                  ffmpeg_loglevel, event_manager, input_length,
                  playbar_offset_pix):
    v_width, v_height = video_resolution
    playlog.debug("Starting video stream.")
    video_stream = create_ffmpeg_video_stream(file, play_from, ffmpeg_loglevel,
                                              frame_rate)

    audio_player = AudioPlayer(pyaudio_instance, audio_sr, speed,
                               speedup_silence, file, play_from,
                               ffmpeg_loglevel)

    def cleanup():
        audio_player.close()
        video_stream.kill()

    def get_video_position(curr_idx, frame_rate, play_from):
        return curr_idx / frame_rate + play_from

    playlog.debug("starting playback")
    start_time = time.time()
    curr_idx = 0
    playback_offset = 0
    while True:
        ret = event_manager.handle_events()
        video_position = get_video_position(curr_idx, frame_rate, play_from)
        if ret.got_command():
            cleanup()
            return False, video_position, ret
        playback_time = time.time() - start_time + playback_offset
        playback_offset += audio_player.AUDIO_DROP_SKIP_DURATION * \
                           audio_player.n_droped[0]
        audio_player.n_droped[0] = 0

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
            return True, video_position, ret
        in_frame = (
            np
                .frombuffer(in_bytes, np.uint8)
                .reshape([v_height, v_width, 3])
                .transpose([1, 0, 2])
        )
        frame_surf = pygame.surfarray.make_surface(in_frame)
        # if not video_resolution == screen_resolution:
        frame_surf = pygame.transform.scale(frame_surf, screen_resolution)
        screen.blit(frame_surf, (0, 0))
        if time.time() - event_manager.time_last_mouse_move < 2:
            stats_surf, pos = get_stats_surf(playbar_offset_pix,
                                             screen_resolution, video_position,
                                             input_length, speed)
            screen.blit(stats_surf, pos)
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
              help='Where to start playback in seconds. Overwrites loaded'
                   'playback location.')
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
    screen = pygame.display.set_mode(screen_resolution,
                                     pygame.HWSURFACE | pygame.DOUBLEBUF | pygame.RESIZABLE)
    pygame.display.set_caption('bepl')

    audio_sr = lr.get_samplerate(file)
    log.debug(f'Audio sample-rate of {audio_sr} inferred.')
    input_resolution = get_file_resolution(file)
    log.debug(f'Video resolution infered {input_resolution}')
    input_length = get_file_length(file)

    if not play_from and not no_save_pos:
        play_from = load_playback_pos(VIDEO_PLAYBACK_SAVE_FILE, file)

    PLAYBAR_OFFSET_PIX = (70, 10)

    event_manager = EventManager()

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
           'event_manager': event_manager,
           'input_length': input_length,
           'playbar_offset_pix': PLAYBAR_OFFSET_PIX
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
                new_cmd = event_manager.handle_events()
                if new_cmd.got_command():
                    break
        if new_cmd.window_size:
            screen_resolution = new_cmd.window_size
            cmd['screen_resolution'] = screen_resolution
        if new_cmd.speed:
            cmd['speed'] = new_cmd.speed
        if new_cmd.position_offset:
            cmd['play_from'] = \
                np.clip(vid_pos + new_cmd.position_offset, 0, input_length)
        if new_cmd.mouse_pos:
            zeroed = new_cmd.mouse_pos[0] - PLAYBAR_OFFSET_PIX[0]
            scaled = zeroed / (
                    screen_resolution[0] - PLAYBAR_OFFSET_PIX[0] * 2)
            cmd['play_from'] = np.clip(scaled * input_length,
                                       0,
                                       input_length - 0.5)

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
