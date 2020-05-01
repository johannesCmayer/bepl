# bepl
**bepl** is a video player written in python with speed control that skips silence. Run with ```python player.py``` in the correct environment.

If there is silence in the video that part will be played back faster at a faster rate. This is additional and can be run in parrallel with speeding up the non-silent parts in the video.

By default the player saves the playback position of videos and resumes at the saved possition.

This player can read a transport stream (ts) files while they are is being written and should be able to read all video file formats that are supported by ffmpeg.

The player is very resource intensive. Performance issues might be resolved by lowering the playback framerate.

## Command line help
```
Usage: player.py [OPTIONS] FILE

  Runtime commands

        Space           Pause playback

        left_arrow      Seek backwards 5 seconds

        right_arrow     Seek forward 5 seconds

        mouse_click     Jump to position in timeline at mouse position

        plus            Increase playback speed 10%

        minus           Decrease playback speed 10%

        r               toogle between set speed and speed 1

        Esc             Exit the application

Options:
  -s, --speed FLOAT               How fast to playback.  [default: 1.8]
  -b, --silence-speedup INTEGER   How much faster to play silence. This is in
                                  addition to the speedup specified with --speed.
                                  [default: 5]

  -v, --volume FLOAT              Playback volume of audio.  [default: 1]
  --audio-channel INTEGER         The audio channel to play back.  [default:
                                  0]

  --play-from INTEGER             Where to start playback in seconds.
                                  Overwrites loaded playback location.

  --frame-rate INTEGER            The framerate to play the video back at. Low
                                  values improve performance.  [default: 15]

  -r, --init-screen-res INTEGER...
                                  What resolution should the input be
                                  stretched to initially.  [default: 1885,
                                  1012]

  -r, --max-screen-res INTEGER...
                                  The maximum resolution that the screen can
                                  take.  [default: 1920, 1080]

  --no-save-pos                   Disable loading and saving of the playback
                                  position.

  --ffmpeg-loglevel TEXT          Set the loglevel of ffmpeg.  [default:
                                  warning]

  --help                          Show this message and exit.
```
## Similar projects
[skip-silence](https://github.com/vantezzen/skip-silence)

[jumpcutter](https://github.com/carykh/jumpcutter)
