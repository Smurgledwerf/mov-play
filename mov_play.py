
"""Play movies in the terminal!"""

import argparse
import bz2
import json
import logging
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

sys.path.append(r'C:\rez\packages\python\Pillow\9.0.1\e7b64aebe77c11047a71e73bebf05e90cbb6361d\python')
sys.path.append(r'C:\rez\packages\test\pygame\2.1.2\platform-windows\python')

from PIL import Image

logging.basicConfig()
logger = logging.getLogger(__name__)

if os.path.exists(r'C:\Program Files\ffmpeg\bin'):
    FFMPEG_BIN = r'C:\Program Files\ffmpeg\bin'
else:
    # TODO: add a default ffmpeg location
    FFMPEG_BIN = ''
FFMPEG = os.path.join(FFMPEG_BIN, "ffmpeg.exe")

VALUES = " .,:;i1tfLCG08@"
PRECISION = 765.0 / len(VALUES)
CODE = ""


def main(files, ascii_mode=False, extract_audio=True, cleanup=True, fps=None,
         resolution=None, audio=None, loop=False, debug=False):
    """Play a movie in your (git-bash) terminal!

    :param list[str] files: list of paths to movie files, or 1 .bz2 file
        which will decompress and play
    :param bool ascii_mode: use ascii mode when converting
    :param bool extract_audio: extract audio from the mov files
    :param bool cleanup: cleanup the temp data
    :param float fps: the frame rate for playback
    :param list[int] resolution: the resolution for playback
    :param str audio: an audio file to play, used with a .bz2 file
    :param bool loop: loop playback
    :param bool debug: enable debug logging
    """
    if debug:
        logger.setLevel(logging.DEBUG)

    global CODE
    if ascii_mode:
        CODE = "\x1b[38;2;{red};{green};{blue}m{char}"
    else:
        CODE = "\x1b[48;2;{red};{green};{blue}m{char}"

    if len(files) == 1:
        if files[0].endswith('.bz2'):
            if resolution:
                # the arg is width, height but the command is rows, cols
                os.system("printf '\033[8;{};{}t'".format(resolution[1], resolution[0]))
            play_compressed(files[0], fps or 24, audio=audio, loop=loop)
            if not debug:
                os.system('clear')
            return

    directory = tempfile.mkdtemp()
    full_str = ''
    audios = []
    final_fps = fps
    for i, mov_file in enumerate(files):
        if not os.path.isfile(mov_file):
            logger.error(mov_file + ' is not a valid file')
            continue

        sys.stdout.write('Preparing {} ({}/{})\n'.format(
            os.path.basename(mov_file), i + 1, len(files)
        ))

        mov_str, audio, fps, width, height = process_mov(
            mov_file, directory, ascii_=ascii_mode,
            extract_audio=extract_audio, debug=debug
        )
        if audio:
            audios.append(audio)
        if final_fps is None:
            final_fps = fps
        elif final_fps != fps:
            logger.warning('Frame rate differs, playback might be weird.')
        full_str += mov_str

    final_audio = audio or get_audio(audios, directory)

    if not debug:
        os.system('clear')
    play(full_str, final_fps, audio=final_audio, loop=loop)

    if not debug:
        os.system('clear')

    if not cleanup:
        print('Writing data...')
        with bz2.open(os.path.join(directory, 'output.bz2'), 'wt') as f:
            f.write(full_str)
        with open(os.path.join(directory, 'data.json'), 'w') as f:
            f.write(json.dumps({'fps': final_fps, 'width': width, 'height': height}))
        print(directory)
    else:
        shutil.rmtree(directory)


def process_mov(mov_file, directory, ascii_=False, extract_audio=True,
                debug=False):
    """Process the mov file into the terminal color syntax and audio file.

    Args:
        mov_file (str): path to the mov file
        directory (srt): directory to export images and audio
        ascii_ (bool): use the ascii mode
        extract_audio (bool): export the audio
        debug (bool): show debug messages

    Returns:
        str, str, int: movie as a string, audio file path, fps
    """
    mov_name = os.path.splitext(os.path.basename(mov_file))[0]
    subdir = os.path.join(directory, mov_name)
    os.mkdir(subdir)

    width, height, fps = calculate_resolution(mov_file)

    unshoot(mov_file, subdir, width, height)

    full_str = convert_to_str(subdir, width, height,
                              ascii_=ascii_, debug=debug)

    audio = None
    if extract_audio:
        logger.debug('extracting audio for: %s', mov_file)
        # TODO: error handling if there is no audio
        audio = os.path.join(subdir, 'audio.wav')
        cmd = [FFMPEG, '-i', mov_file, audio]
        logger.debug(cmd)
        p = subprocess.Popen(cmd, stderr=subprocess.PIPE)
        retcode = p.wait()

    return full_str, audio, fps, width, height


def calculate_resolution(file_path):
    """Calculate the final resolution of the movie.

    Args:
        file_path (str): path to a mov file

    Returns:
        int, int, int: width, height, frames/second
    """
    # mov stats
    width, height, fps = get_stats(file_path)

    # terminal stats
    rows, cols = os.popen('stty size', 'r').read().split()
    rows = int(rows) - 1
    cols = int(cols)
    # each cell is 9 by 18
    term_width = cols * 9
    term_height = rows * 18

    # calculate final resolution
    mov_ratio = float(width) / float(height)
    logger.debug('mov {}x{}'.format(width, height))
    logger.debug(mov_ratio)
    term_ratio = float(term_width) / float(term_height)
    logger.debug('term {}x{}'.format(term_width, term_height))
    logger.debug(term_ratio)
    if mov_ratio > term_ratio:
        # movie is wider than the terminal
        final_width = term_width
        final_height = int(term_width / mov_ratio)
    else:
        # terminal is wider than the movie
        final_width = int(term_height * mov_ratio)
        final_height = term_height

    logger.debug('final {}x{}'.format(final_width, final_height))
    logger.debug(float(final_width) / float(final_height))

    img_rows = final_height // 18
    img_cols = final_width // 9
    logger.debug('cells {}x{}'.format(img_cols, img_rows))

    return img_cols, img_rows, fps


def get_stats(mov_file):
    """Get the stats of the mov file.

    Args:
        mov_file (str): path to a mov file

    Returns:
        int, int, int: width, height, frames/second
    """
    cmd = [os.path.join(FFMPEG_BIN, "ffprobe.exe"), '-i', mov_file]
    logger.debug(cmd)
    p = subprocess.Popen(cmd, stderr=subprocess.PIPE)
    # output = p.stderr.read()
    retcode = p.wait()
    # output.decode('utf-8')
    expr = re.compile(', (\d+x\d+) .*, ([\d.]+) fps, ')
    # for line in output.split('\n'):
    for line in iter(p.stderr.readline, ''):
        match = expr.search(str(line))
        if match:
            resolution = match.group(1).split('x')
            width = int(resolution[0])
            height = int(resolution[1])
            fps = float(match.group(2))
            break
    else:
        raise RuntimeError("Could not determine resolution of mov file!")

    return width, height, fps


def unshoot(mov_file, directory, width, height):
    """Unshoot the movie into a sequence of images.

    Args:
        mov_file (str): path to a mov file
        directory (str): directory to export to
        width (int): the width of the images
        height (int): the height of the images
    """
    jpegs = os.path.join(directory, 'lol.%4d.jpg')
    # multiply width and height to avoid horrible jpeg compression
    cmd = [FFMPEG, '-i', mov_file, '-s', '{}x{}'.format(width * 4, height * 4), jpegs]
    logger.debug(cmd)
    p = subprocess.Popen(cmd, stderr=subprocess.PIPE)
    output = p.stderr.read()
    retcode = p.wait()
    # TODO: error handling if it fails


def convert_to_str(directory, width, height, ascii_=False, debug=False):
    """Convert the images in the directory to a str of terminal colors.

    Args:
        directory (str): directory to look for images in
        width (int): the width of the movie
        height (int): the height of the movie
        ascii_ (bool): use the ascii code
        debug (bool): debug option

    Returns:
        str: the sequence of images as terminal colors
    """
    full_str = ''
    prev = 0
    files = os.listdir(directory)
    frames = float(len(files))
    for i, img_file in enumerate(files):
        percent = int((i / frames) * 100)
        if percent >= prev + 10:
            sys.stdout.write('Processing... {}%\r'.format(percent))
            sys.stdout.flush()
            prev = percent
        img_path = os.path.join(directory, img_file)
        image = Image.open(img_path)
        image = image.resize((width, height))
        img_str = translate_pixmap(image, ascii_=ascii_)
        full_str += img_str + "\x1b[H"

    return full_str


def translate_pixmap(image, ascii_=False):
    """Translate the image into a string of terminal colors.

    Args:
        image (Pillow.Image): the image to convert to a str
        ascii_ (bool): whether or not to use the ascii codes

    Returns:
        str: the frame as a string of terminal color codes
    """
    width, height = image.size
    pixmap = image.load()
    endline = "\x1b[0m\n"
    img_str = ''
    for row in range(height):
        for col in range(width):
            red, green, blue = pixmap[col, row]
            if ascii_:
                # calculate the ascii value from pixel intensity
                # intensity = red + green + blue
                # index = min(int(round(intensity / PRECISION)), len(VALUES) - 1)
                intensity = (red + green + blue) / 765.0
                # use a logarithmic scale so there are more bright pixels
                scaled = math.log((intensity*15) + 1, 2) / 4.0
                index = min(int(scaled * len(VALUES)), len(VALUES) - 1)
                char = VALUES[index]
            else:
                char = ' '
            img_str += CODE.format(red=red, green=green, blue=blue, char=char)
        img_str += endline

    return img_str


def get_audio(audio_files, directory):
    """Get the correct audio for the .mov file(s). If there are multiple audio
    files, they will be concatenated together.

    Args:
        audio_files (list[str]): list of paths to the audio files
        directory (str): the temp directory to output the concatenation

    Returns:
        str: path to the audio file
    """
    audio_path = os.path.join(directory, 'audio.wav')
    if not audio_files:
        audio = None
    elif len(audio_files) == 1:
        os.rename(audio_files[0], audio_path)
        audio = audio_path
    else:
        logger.debug('concatenating {} audio files'.format(len(audio_files)))
        file_list = os.path.join(directory, 'audios.txt')
        with open(file_list, 'w') as f:
            for a in audio_files:
                f.write("file '{}'\n".format(a))

        cmd = [FFMPEG, '-f', 'concat', '-safe', '0', '-i', file_list, '-c', 'copy', audio_path]
        logger.debug(cmd)
        p = subprocess.Popen(cmd, stderr=subprocess.PIPE)
        retcode = p.wait()
        audio = audio_path

    return audio


def play(mov_str, fps, audio=None, loop=False):
    """Play the movie str in the terminal.

    Args:
        mov_str (str): the movie as a string
        fps (int): the frames per second
        audio (str): path to an audio file
        loop (bool): loop playback until interrupted
    """
    if audio:
        import pygame
        pygame.init()
        pygame.mixer.music.load(audio)

    again = True
    time_per_frame = 1.0 / fps
    while again:
        buf = ''
        frame = 0
        next_frame = 0
        begin = time.time()
        try:
            if audio:
                pygame.mixer.music.play()
            for line in mov_str.split('\n'):
                # is is the beginning of the next frame, write the buffer
                if line.startswith('\x1b[H'):
                    frame += 1
                    sys.stdout.write(buf)
                    buf = ''
                    elapsed = time.time() - begin
                    repose = (frame * time_per_frame) - elapsed
                    if repose > 0.0:
                        time.sleep(repose)
                    next_frame = elapsed / time_per_frame
                if frame >= next_frame:
                    buf += line + '\n'
        except KeyboardInterrupt:
            again = False
        else:
            again = loop
        finally:
            # clean up the audio process if it's running
            if audio:
                pygame.mixer.music.stop()
                pygame.mixer.music.unload()


def play_compressed(zip_file, fps, audio=None, loop=False):
    """Play the compressed .bz2 file in the terminal. If loop is True, it
    _should_ only decompress once, and then use normal play with the full_str.

    Args:
        zip_file (str): path to a .bz2 file
        fps (int): the frames per second
        audio (str): path to an audio file
        loop (bool): loop playback until interrupted
    """
    p = None
    if audio:
        import pygame
        pygame.init()
        pygame.mixer.music.load(audio)

    time_per_frame = 1.0 / fps
    buf = ''
    full_str = ''
    frame = 0
    next_frame = 0
    begin = time.time()
    try:
        with bz2.open(zip_file, 'rt') as bz_file:
            for line in bz_file:
                # it is the beginning of the next frame, write the buffer
                if line.startswith('\x1b[H'):
                    # delay starting the audio until the first frame is ready
                    if audio and not p:
                        pygame.mixer.music.play()
                        p = True
                    frame += 1
                    sys.stdout.write(buf)
                    full_str += buf
                    buf = ''
                    elapsed = time.time() - begin
                    repose = (frame * time_per_frame) - elapsed
                    if repose > 0.0:
                        time.sleep(repose)
                    next_frame = elapsed / time_per_frame
                if frame >= next_frame:
                    buf += line
    except KeyboardInterrupt:
        loop = False
    finally:
        # clean up the audio process if it's running
        if audio and p:
            pygame.mixer.music.stop()
            pygame.mixer.music.unload()

    if loop:
        play(full_str, fps, audio=audio, loop=loop)


def parse_args():
    """Parse the command-line arguments.

    Returns:
        args
    """
    parser = argparse.ArgumentParser('Play a movie in the terminal!')

    parser.add_argument(
        '--lod', type=str, default='low', choices=['high', 'med', 'low'],
        help="The level of detail for the movie."
    )

    parser.add_argument('--loop', action='store_true', help='Loop playback.')

    parser.add_argument(
        '--fps', type=float,
        help='Override the frames per second. If a .bz2 file is passed with no '
             'fps argument, it will assume 24 fps.'
    )

    parser.add_argument(
        '--resolution', type=int, nargs=2,
        help="The playback width and height. This is normally calculated based "
             "on the input file(s), but is needed when a .bz2 file is passed. "
    )

    parser.add_argument('--audio', type=str, help='Path to an audio file to use.')

    parser.add_argument('--no-audio', action='store_true', help="Don't extract audio.")

    parser.add_argument(
        '--no-cleanup', action='store_true',
        help="Don't delete the tmp files. This will also compress the output "
             "to a .bz2 file and save the settings to data.json"
    )

    parser.add_argument('--debug', action='store_true', help='Log debug level.')

    parser.add_argument('--demo', action='store_true', help='Show mov_play in action.')

    parser.add_argument(
        'files', type=str, nargs='*',
        help="One or more paths to the .mov files. If you pass 1 .bz2 file, "
             "it will attempt to decompress and play."
    )

    args = parser.parse_args()

    if args.demo:
        demo()
        sys.exit(0)

    main(args.files, ascii_mode=args.lod == 'med', extract_audio=not args.no_audio, cleanup=not args.no_cleanup,
         fps=args.fps, resolution=args.resolution, audio=args.audio, loop=args.loop, debug=args.debug)


def demo():
    here = os.path.dirname(__file__)
    main([os.path.join(here, 'data/output.bz2')], fps=29.97, resolution=[168, 48], audio=os.path.join(here, 'data/audio.wav'))


if __name__ == '__main__':
    parse_args()
