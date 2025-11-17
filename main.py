import subprocess
import pyperclip
import os
from PIL import Image

BASE_DIR = "songs"

# =====================================================
# CHANGE THIS TO CONTROL SYNC SPEED (2 = double speed)
# =====================================================
SPEED_FACTOR = 2      # ← you can set 3, 4, etc.
# =====================================================


def download_with_ytdlp(url, out_path):
    """Download any file with yt-dlp."""
    cmd = ["yt-dlp", "-o", out_path, url]
    subprocess.run(cmd, check=True)


def convert_to_png(input_path, output_path):
    """Convert downloaded image to PNG."""
    img = Image.open(input_path).convert("RGB")
    img.save(output_path, "PNG")


def create_mode():
    yt_link = input("Enter YouTube link: ").strip()
    name = input("Enter song name: ").strip()
    bg_link = input("Enter background image link (optional): ").strip()

    song_dir = os.path.join(BASE_DIR, name)
    os.makedirs(song_dir, exist_ok=True)

    # --------------------------
    # DOWNLOAD MP3
    # --------------------------
    print("Downloading audio...")
    audio_output = os.path.join(song_dir, "song.%(ext)s")

    cmd = [
        "yt-dlp",
        "-f", "ba",
        "-x",
        "--audio-format", "mp3",
        "-o", audio_output,
        yt_link
    ]
    subprocess.run(cmd, check=True)

    # --------------------------
    # OPTIONAL BACKGROUND IMAGE
    # --------------------------
    if bg_link != "":
        print("Downloading background...")
        tmp_bg = os.path.join(song_dir, "bg_temp")
        final_bg = os.path.join(song_dir, "background.png")

        try:
            download_with_ytdlp(bg_link, tmp_bg)

            print("Converting background to PNG...")
            convert_to_png(tmp_bg, final_bg)
        except Exception as e:
            print("Background image failed to download or convert:", e)
        finally:
            if os.path.exists(tmp_bg):
                os.remove(tmp_bg)
    else:
        print("No background image provided. Skipping...")

    # --------------------------
    # SAVE LYRICS
    # --------------------------
    input("Press return if lyrics are in clipboard...")
    lyrics = pyperclip.paste()

    with open(os.path.join(song_dir, "lyrics.txt"), "w", encoding="utf-8") as f:
        f.write(lyrics)

    print("Done.")


# =====================================================================
# PLAY / SYNC MODE (UPDATED)
# =====================================================================

import pygame
import time
import sys
import termios
import tty
import select
from colorama import Fore, Style, init

init()


def get_key():
    """Nonblocking key reader."""
    dr, _, _ = select.select([sys.stdin], [], [], 0)
    if dr:
        return sys.stdin.read(1)
    return None


def auto_select_song():
    """Pick first song that has song.mp3 & lyrics.txt but no synced.csv."""
    if not os.path.exists(BASE_DIR):
        return None

    for folder in sorted(os.listdir(BASE_DIR)):
        song_dir = os.path.join(BASE_DIR, folder)
        if not os.path.isdir(song_dir):
            continue

        song = os.path.join(song_dir, "song.mp3")
        lyr = os.path.join(song_dir, "lyrics.txt")
        sync = os.path.join(song_dir, "synced.csv")

        if os.path.exists(song) and os.path.exists(lyr) and not os.path.exists(sync):
            return folder

    return None


def sync_mode():
    name = input("Song name: ").strip()

    if name == "":
        name = auto_select_song()
        if name:
            print(f"autoselected: {name}")
        else:
            print("No unfinished song found.")
            return

    song_dir = os.path.join(BASE_DIR, name)

    song_path = os.path.join(song_dir, "song.mp3")
    lyrics_path = os.path.join(song_dir, "lyrics.txt")

    if not os.path.exists(song_path) or not os.path.exists(lyrics_path):
        print("Song or lyrics not found.")
        return

    # ----------------------------------------------------
    # LOAD & CLEAN LYRICS
    # ----------------------------------------------------
    with open(lyrics_path, "r", encoding="utf-8") as f:
        raw_lines = f.readlines()

    lyrics = []
    for line in raw_lines:
        line = line.strip()
        if not line:
            continue
        if "[" in line or "]" in line:
            continue
        lyrics.append(line)

    lyrics.insert(0, "…")   # first line

    if len(lyrics) == 0:
        print("Lyrics ended up empty after cleaning.")
        return

    # ----------------------------------------------------
    # LOAD AUDIO AT SPEED_FACTOR× SPEED
    # ----------------------------------------------------
    pygame.mixer.init()

    sound = pygame.mixer.Sound(song_path)

    import numpy as np
    arr = pygame.sndarray.array(sound)

    # basic integer skipping method
    step = int(SPEED_FACTOR)
    if step < 1:
        step = 1

    fast_arr = arr[::step].copy()
    fast_arr = np.ascontiguousarray(fast_arr, dtype=arr.dtype)

    fast_sound = pygame.sndarray.make_sound(fast_arr)
    fast_sound.play()

    start_time = time.time()
    index = 0
    timestamps = [None] * len(lyrics)

    timestamps[0] = 0  # first line always time 0

    def show():
        os.system("clear")
        start = max(0, index - 10)
        end = min(len(lyrics), index + 11)

        for i in range(start, end):
            line = lyrics[i]
            if i == index:
                print(Fore.RED + line + Style.RESET_ALL)
            else:
                print(line)

    # Raw terminal mode
    old_settings = termios.tcgetattr(sys.stdin)
    tty.setcbreak(sys.stdin.fileno())

    show()

    try:
        while True:
            key = get_key()

            # SPACE → next line
            if key == " ":
                if index < len(lyrics) - 1:
                    index += 1
                    timestamps[index] = int((time.time() - start_time) * 1000 * SPEED_FACTOR)
                    show()
                else:
                    break  # at last line → quit immediately

            # ENTER → quit immediately if on last line
            if key == "\n" and index == len(lyrics) - 1:
                break

            # BACKSPACE →
            if key == "\x7f":
                if index > 0:
                    index -= 1
                    show()

            time.sleep(0.02)

    finally:
        termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_settings)

    # ----------------------------------------------------
    # SAVE synced.csv
    # ----------------------------------------------------
    out_path = os.path.join(song_dir, "synced.csv")
    with open(out_path, "w", encoding="utf-8") as f:
        for t, line in zip(timestamps, lyrics):
            if t is None:
                t = ""
            f.write(f"{t};{line}\n")

    print("Saved:", out_path)


# =====================================================================
# MAIN
# =====================================================================

def main():
    action = input("action: ").strip()
    if action == "1":
        create_mode()
    elif action == "2":
        sync_mode()
    else:
        print("Unknown action.")


if __name__ == "__main__":
    main()
