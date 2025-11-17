import os
import subprocess
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from tqdm import tqdm

BASE_DIR = "songs"
FINISHED_DIR = "finished"

TEXT_OFFSET_MS = 1000   # show text 1s before timestamp
LINE_SPACING = 12       # spacing between wrapped lines


def read_synced_csv(csv_path):
    timestamps = []
    lines = []
    with open(csv_path, "r", encoding="utf-8") as f:
        for raw in f:
            raw = raw.rstrip("\n")
            if not raw:
                continue

            parts = raw.split(";", 1)
            t_str = parts[0].strip()
            lyric = parts[1].strip() if len(parts) > 1 else ""

            if lyric:
                timestamps.append(int(t_str) if t_str else None)
                lines.append(lyric)

    return timestamps, lines


def break_line(line, max_chars=32):
    if len(line) <= max_chars:
        return [line]

    mid = len(line) // 2
    left_space = line.rfind(" ", 0, mid)
    right_space = line.find(" ", mid)

    if left_space == -1 and right_space == -1:
        return [line[:max_chars].strip(), line[max_chars:].strip()]

    if left_space == -1:
        split_at = right_space
    elif right_space == -1:
        split_at = left_space
    else:
        split_at = left_space if (mid - left_space) < (right_space - mid) else right_space

    return [line[:split_at].strip(), line[split_at:].strip()]


def get_audio_duration_ms(audio_path):
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        audio_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    duration_sec = float(result.stdout.strip())
    return int(duration_sec * 1000)


def load_background(bg_path, width, height):
    if not bg_path or not os.path.exists(bg_path):
        return None

    try:
        img = Image.open(bg_path).convert("RGB")
        img = img.resize((width, height), Image.LANCZOS)
        img = img.filter(ImageFilter.GaussianBlur(8))
        dark = Image.new("RGB", (width, height), (0, 0, 0))
        img = Image.blend(img, dark, 0.35)
        return img
    except Exception:
        print("Warning: Could not load background. Using black.")
        return None


def draw_text_block_centered(draw, center_y, lines, font, fill, width):
    line_heights = []
    for part in lines:
        bbox = draw.textbbox((0, 0), part, font=font)
        h = bbox[3] - bbox[1]
        line_heights.append(h)

    total_height = sum(line_heights) + (len(lines) - 1) * LINE_SPACING
    top = center_y - total_height // 2
    y = top

    for part, h in zip(lines, line_heights):
        bbox = draw.textbbox((0, 0), part, font=font)
        w = bbox[2] - bbox[0]
        x = (width - w) // 2
        draw.text((x, y), part, font=font, fill=fill)
        y += h + LINE_SPACING


def generate_frames(lines, first_gap_ms, frames_dir, bg_path):
    frames_dir = os.path.abspath(frames_dir)
    os.makedirs(frames_dir, exist_ok=True)

    width, height = 1280, 720

    try:
        font_main = ImageFont.truetype("DejaVuSans-Bold.ttf", 60)
        font_next = ImageFont.truetype("DejaVuSans.ttf", 40)
    except Exception:
        font_main = ImageFont.load_default()
        font_next = ImageFont.load_default()

    background = load_background(bg_path, width, height)

    # Create a true blank background frame (blurred bg, no text)
    blank_img = background.copy() if background else Image.new("RGB", (width, height), (0, 0, 0))
    blank_img.save(os.path.join(frames_dir, "blank.png"))

    frame_index = 1

    # First gap frame: no current line, only "next" in grey
    if first_gap_ms > 0:
        img = background.copy() if background else Image.new("RGB", (width, height), (0, 0, 0))
        draw = ImageDraw.Draw(img)

        next_wrapped = break_line(lines[0])
        draw_text_block_centered(
            draw=draw,
            center_y=height // 2,
            lines=next_wrapped,
            font=font_next,
            fill=(150, 150, 150),
            width=width
        )

        img.save(os.path.join(frames_dir, f"{frame_index}.png"))
        frame_index += 1

    # Normal frames
    for idx, line in enumerate(tqdm(lines, desc="Generating frames")):
        img = background.copy() if background else Image.new("RGB", (width, height), (0, 0, 0))
        draw = ImageDraw.Draw(img)

        main_wrapped = break_line(line)

        # Main block slightly above center
        draw_text_block_centered(
            draw=draw,
            center_y=height // 2 - 40,
            lines=main_wrapped,
            font=font_main,
            fill=(255, 255, 255),
            width=width
        )

        # Next block below
        if idx + 1 < len(lines):
            next_wrapped = break_line(lines[idx + 1])
            draw_text_block_centered(
                draw=draw,
                center_y=height // 2 + 120,
                lines=next_wrapped,
                font=font_next,
                fill=(150, 150, 150),
                width=width
            )

        img.save(os.path.join(frames_dir, f"{frame_index}.png"))
        frame_index += 1

    return frame_index - 1


def write_concat_file(frames_dir, timestamps, total_frames, song_duration_ms, concat_path):
    frames_dir = os.path.abspath(frames_dir)

    # Effective start times with early offset
    eff = [max(0, t - TEXT_OFFSET_MS) for t in timestamps]

    with open(concat_path, "w", encoding="utf-8") as f:

        # Initial gap handling
        if eff[0] > 0:
            gap_dur = eff[0] / 1000.0
            first_frame = os.path.join(frames_dir, "1.png")
            f.write(f"file '{first_frame}'\n")
            f.write(f"duration {gap_dur}\n")
            shift = 1
        else:
            shift = 0

        # Process each lyric
        for i in range(len(timestamps)):
            start = eff[i]
            if i < len(timestamps) - 1:
                next_start = eff[i + 1]
            else:
                next_start = song_duration_ms

            duration_ms = max(100, next_start - start)
            frame_num = i + 1 + shift
            frame_file = os.path.join(frames_dir, f"{frame_num}.png")

            # FINAL LINE SPECIAL HANDLING
            if i == len(timestamps) - 1:
                three_sec = 5000
                lyric_frame = frame_file

                # Part 1: show lyric frame for min(3s, full duration)
                first_part_ms = min(duration_ms, three_sec)
                f.write(f"file '{lyric_frame}'\n")
                f.write(f"duration {first_part_ms / 1000.0}\n")

                # Part 2: remaining time as blank background (no text)
                leftover = duration_ms - first_part_ms
                if leftover > 0:
                    blank_frame = os.path.join(frames_dir, "blank.png")
                    f.write(f"file '{blank_frame}'\n")
                    f.write(f"duration {leftover / 1000.0}\n")
                    # ffmpeg concat quirk: repeat last frame
                    f.write(f"file '{blank_frame}'\n")
                else:
                    # if no leftover, just repeat lyric frame once
                    f.write(f"file '{lyric_frame}'\n")

                break

            # Normal lines
            duration = duration_ms / 1000.0
            f.write(f"file '{frame_file}'\n")
            f.write(f"duration {duration}\n")


def auto_select_song_for_render():
    """Pick the first song directory that has synced.csv but is not yet rendered."""
    if not os.path.exists(BASE_DIR):
        return None

    for folder in sorted(os.listdir(BASE_DIR)):
        song_dir = os.path.join(BASE_DIR, folder)
        if not os.path.isdir(song_dir):
            continue

        song = os.path.join(song_dir, "song.mp3")
        sync = os.path.join(song_dir, "synced.csv")

        finished_path = os.path.join(FINISHED_DIR, f"{folder}.mp4")

        if os.path.exists(song) and os.path.exists(sync) and not os.path.exists(finished_path):
            return folder

    return None


def generate_video():
    name = input("Song name: ").strip()

    # Autoselect if user presses enter
    if name == "":
        name = auto_select_song_for_render()
        if name:
            print(f"autoselected: {name}")
        else:
            print("No song found that needs rendering.")
            return

    song_dir = os.path.join(BASE_DIR, name)
    audio_path = os.path.abspath(os.path.join(song_dir, "song.mp3"))
    csv_path = os.path.abspath(os.path.join(song_dir, "synced.csv"))

    video_dir = os.path.abspath(os.path.join(song_dir, "video"))
    frames_dir = os.path.abspath(os.path.join(video_dir, "frames"))
    concat_path = os.path.join(video_dir, "frames.txt")

    os.makedirs(video_dir, exist_ok=True)
    os.makedirs(FINISHED_DIR, exist_ok=True)

    finished_path = os.path.abspath(os.path.join(FINISHED_DIR, f"{name}.mp4"))

    timestamps, lines = read_synced_csv(csv_path)
    duration_ms = get_audio_duration_ms(audio_path)

    # Background automatically from songs/<name>/background.png if it exists
    bg_path = os.path.join(song_dir, "background.png")
    if not os.path.exists(bg_path):
        bg_path = None

    # First gap based on early-offset effective time of first line
    eff_first = max(0, timestamps[0] - TEXT_OFFSET_MS)
    first_gap_ms = eff_first

    total_frames = generate_frames(lines, first_gap_ms, frames_dir, bg_path)
    write_concat_file(frames_dir, timestamps, total_frames, duration_ms, concat_path)

    print("Running ffmpeg...")
    cmd = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0",
        "-i", concat_path,
        "-i", audio_path,
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-shortest",
        finished_path
    ]
    subprocess.run(cmd, check=True)

    print("Done:", finished_path)


if __name__ == "__main__":
    generate_video()
