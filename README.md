# bepl
A simple video player with speed control that skips silence. 

If there is silence in the video that part will be played back faster at a faster rate. This is additional and can be run in parrallel with speeding up the non-silent parts in the video.

By default the player saves the playback position of videos and resumes at the saved possition.

This player can read a transport stream (ts) file as it is being written and should be able to read all video file formats that are supported by ffmpeg.

The player is very resource intensive. Performance issues might be resolved by lowering the framerate.

## Command line help
```
Usage: player.py [OPTIONS] FILE

Options:
  -s, --speed FLOAT               How fast to playback.  [default: 2]
  -b, --speedup-silence INTEGER   How much faster to play silence. This is in
                                  addition to speedup specified with --speed.
                                  [default: 10]

  --play-from INTEGER             Where to start playback in seconds.
                                  Overwrites loaded playback location.

  --frame-rate INTEGER            The framerate to play the video back at. Low
                                  values improve performance.  [default: 15]

  -r, --init-screen-res INTEGER...
                                  What resolution should the input be
                                  stretched to initially.  [default: 1920,
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
