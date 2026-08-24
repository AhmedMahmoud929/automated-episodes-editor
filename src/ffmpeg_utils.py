"""FFmpeg helpers for episode video production."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from intro import _clean_alpha_edges, _remove_black_background, prepare_logo_with_transparency


class FFmpegNotFoundError(RuntimeError):
    """Raised when ffmpeg/ffprobe are unavailable."""


@dataclass
class AudioEnhancementOptions:
    """Audio processing toggles applied to the main episode audio."""

    remove_noise: bool = False
    voice_booster: bool = False
    normalize: bool = False
    bass_boost: bool = False

    @property
    def enabled(self) -> bool:
        return self.remove_noise or self.voice_booster or self.normalize or self.bass_boost


def parse_time_to_seconds(value: str | int | float) -> float:
    """Parse a time value into seconds.

    Supported formats:
    - Raw seconds: ``90``, ``90.5``
    - ``MM:SS`` or ``MM:SS.ss`` (e.g. ``02:35``, ``02:35.5``)
    - ``MM:SS:f`` fractional seconds with a third segment:
      - 1 digit = tenths (``02:35:5`` → 155.5 s)
      - 2 digits = hundredths (``02:35:50`` → 155.50 s)
      - 3 digits = milliseconds (``02:35:500`` → 155.500 s)
    - ``HH:MM:SS`` or ``HH:MM:SS.ss`` when the first segment is ``0``/``00``
      (e.g. ``00:02:35``, ``00:02:35.5``)
    """
    if isinstance(value, (int, float)):
        return float(value)

    text = str(value).strip()
    if not text:
        raise ValueError("Time value cannot be empty.")

    if text.replace(".", "", 1).isdigit():
        return float(text)

    parts = [part.strip() for part in text.split(":")]
    if len(parts) == 2:
        minutes, seconds = parts
        return int(minutes) * 60 + float(seconds)

    if len(parts) == 3:
        first, second, third = parts
        if third.isdigit() and first not in ("0", "00"):
            third_len = len(third)
            if third_len == 1:
                return int(first) * 60 + int(second) + int(third) / 10
            if third_len == 2:
                return int(first) * 60 + int(second) + int(third) / 100
            if third_len == 3:
                return int(first) * 60 + int(second) + int(third) / 1000

        return int(first) * 3600 + int(second) * 60 + float(third)

    raise ValueError(
        f"Invalid time format: {value!r}. "
        "Use seconds, MM:SS, MM:SS:fraction, or HH:MM:SS (with 00 hours prefix)."
    )


@dataclass
class CutSegment:
    start: float
    end: float

    @classmethod
    def from_dict(cls, data: dict) -> CutSegment:
        start = parse_time_to_seconds(data["start"])
        end = parse_time_to_seconds(data["end"])
        if end <= start:
            raise ValueError(f"Cut end must be after start: {data['start']} → {data['end']}")
        return cls(start=start, end=end)


def find_ffmpeg() -> str:
    path = shutil.which("ffmpeg")
    if not path:
        raise FFmpegNotFoundError(
            "FFmpeg is not installed or not in PATH. "
            "Install it with: winget install --id Gyan.FFmpeg -e"
        )
    return path


def find_ffprobe() -> str:
    path = shutil.which("ffprobe")
    if not path:
        raise FFmpegNotFoundError(
            "ffprobe is not installed or not in PATH. "
            "Install FFmpeg with: winget install --id Gyan.FFmpeg -e"
        )
    return path


def _parse_ffmpeg_time(line: str) -> float | None:
    match = re.search(r"time=(\d+):(\d+):(\d+(?:\.\d+)?)", line)
    if not match:
        return None
    hours, minutes, seconds = match.groups()
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def run_ffmpeg(
    args: list[str],
    *,
    check: bool = True,
    total_duration: float | None = None,
    progress_callback: Callable[[float], None] | None = None,
) -> subprocess.CompletedProcess[str]:
    ffmpeg = find_ffmpeg()
    use_progress = progress_callback is not None and total_duration and total_duration > 0

    command = [ffmpeg, "-hide_banner", "-loglevel", "info" if use_progress else "error", "-y", *args]

    if not use_progress:
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        if check and result.returncode != 0:
            raise RuntimeError(
                "FFmpeg command failed.\n"
                f"Command: {' '.join(command)}\n"
                f"stderr: {result.stderr.strip()}"
            )
        return result

    process = subprocess.Popen(
        command,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    stderr_lines: list[str] = []
    assert process.stderr is not None

    while True:
        line = process.stderr.readline()
        if not line:
            if process.poll() is not None:
                break
            continue

        stderr_lines.append(line)
        elapsed = _parse_ffmpeg_time(line)
        if elapsed is not None:
            progress_callback(min(100.0, (elapsed / total_duration) * 100))

    return_code = process.wait()
    progress_callback(100.0)

    stderr = "".join(stderr_lines).strip()
    result = subprocess.CompletedProcess(command, return_code, "", stderr)
    if check and return_code != 0:
        raise RuntimeError(
            "FFmpeg command failed.\n"
            f"Command: {' '.join(command)}\n"
            f"stderr: {stderr}"
        )
    return result


def get_media_duration(path: Path) -> float:
    ffprobe = find_ffprobe()
    command = [
        ffprobe,
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "json",
        str(path),
    ]
    result = subprocess.run(command, capture_output=True, text=True, check=True)
    payload = json.loads(result.stdout)
    return float(payload["format"]["duration"])


def has_audio_stream(path: Path) -> bool:
    ffprobe = find_ffprobe()
    command = [
        ffprobe,
        "-v",
        "error",
        "-select_streams",
        "a",
        "-show_entries",
        "stream=index",
        "-of",
        "csv=p=0",
        str(path),
    ]
    result = subprocess.run(command, capture_output=True, text=True, check=True)
    return bool(result.stdout.strip())


def compute_keep_segments(duration: float, cuts: list[CutSegment]) -> list[tuple[float, float]]:
    """Return time ranges to keep after removing cut segments."""
    if not cuts:
        return [(0.0, duration)]

    sorted_cuts = sorted(cuts, key=lambda cut: cut.start)
    keep: list[tuple[float, float]] = []
    cursor = 0.0

    for cut in sorted_cuts:
        start = max(0.0, cut.start)
        end = min(duration, cut.end)
        if start >= end:
            continue
        if start > cursor:
            keep.append((cursor, start))
        cursor = max(cursor, end)

    if cursor < duration:
        keep.append((cursor, duration))

    return keep


def apply_video_cuts(
    input_path: Path,
    cuts: list[CutSegment],
    output_path: Path,
    *,
    fps: int = 30,
    progress_callback: Callable[[float], None] | None = None,
) -> Path:
    """Remove cut segments from a video and write a trimmed copy."""
    if not cuts:
        shutil.copy2(input_path, output_path)
        return output_path

    duration = get_media_duration(input_path)
    keep_segments = compute_keep_segments(duration, cuts)
    if not keep_segments:
        raise ValueError("All content would be removed by the configured cuts.")

    has_audio = has_audio_stream(input_path)
    video_filters: list[str] = []
    audio_filters: list[str] = []
    concat_inputs: list[str] = []

    for index, (start, end) in enumerate(keep_segments):
        video_filters.append(
            f"[0:v]trim=start={start}:end={end},setpts=PTS-STARTPTS[v{index}]"
        )
        if has_audio:
            audio_filters.append(
                f"[0:a]atrim=start={start}:end={end},asetpts=PTS-STARTPTS[a{index}]"
            )
        concat_inputs.append(f"[v{index}]")

    segment_count = len(keep_segments)
    video_filters.append(f"{''.join(concat_inputs)}concat=n={segment_count}:v=1:a=0[vcat]")
    video_filters.append(f"[vcat]fps={fps},setpts=PTS-STARTPTS[vout]")

    if has_audio:
        audio_concat_inputs = "".join(f"[a{index}]" for index in range(segment_count))
        audio_filters.append(f"{audio_concat_inputs}concat=n={segment_count}:v=0:a=1[aout]")
        filter_complex = ";".join(video_filters + audio_filters)
        maps = ["-map", "[vout]", "-map", "[aout]"]
    else:
        filter_complex = ";".join(video_filters)
        maps = ["-map", "[vout]"]

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_duration = sum(end - start for start, end in keep_segments)
    run_ffmpeg(
        [
            "-i",
            str(input_path),
            "-filter_complex",
            filter_complex,
            *maps,
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "20",
            *(["-c:a", "aac", "-b:a", "192k"] if has_audio else []),
            str(output_path),
        ],
        total_duration=output_duration,
        progress_callback=progress_callback,
    )
    return output_path


def build_audio_enhancement_filter(options: AudioEnhancementOptions) -> str:
    """Build an FFmpeg audio filter chain from enhancement options."""
    filters: list[str] = []

    if options.remove_noise:
        filters.append("afftdn=nf=-25:nt=w")

    if options.voice_booster:
        filters.extend(
            [
                "equalizer=f=300:width_type=h:width=200:g=3",
                "equalizer=f=1000:width_type=h:width=500:g=4",
                "equalizer=f=3000:width_type=h:width=1000:g=2",
                "acompressor=threshold=-20dB:ratio=3:attack=5:release=50",
            ]
        )

    if options.bass_boost:
        filters.append("bass=g=5")

    if options.normalize:
        filters.append("loudnorm=I=-16:TP=-1.5:LRA=11")

    return ",".join(filters)


def _overlay_position(position: str, margin: int) -> str:
    positions = {
        "bottom_right": f"W-w-{margin}:H-h-{margin}",
        "bottom_left": f"{margin}:H-h-{margin}",
        "top_right": f"W-w-{margin}:{margin}",
        "top_left": f"{margin}:{margin}",
    }
    return positions.get(position, positions["bottom_right"])


def prepare_watermark_png(
    logo_path: Path,
    output_path: Path,
    *,
    scale: float,
    opacity: float,
    frame_width: int,
) -> Path:
    logo = prepare_logo_with_transparency(logo_path)
    target_width = max(1, int(frame_width * scale))
    ratio = target_width / logo.width
    target_height = max(1, int(logo.height * ratio))
    logo = logo.resize((target_width, target_height), resample=3)
    logo = _remove_black_background(logo.convert("RGBA"))

    alpha = logo.split()[3]
    alpha = alpha.point(lambda value: int(value * opacity))
    logo.putalpha(alpha)
    logo = _clean_alpha_edges(logo)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    logo.save(output_path, format="PNG")
    return output_path


def build_episode_video(
    *,
    intro_image: Path,
    main_video: Path,
    watermark_png: Path | None,
    output_path: Path,
    settings: dict,
    audio_enhancement: AudioEnhancementOptions | None = None,
    progress_callback: Callable[[float], None] | None = None,
) -> Path:
    width, height = settings["resolution"]
    fps = settings["fps"]
    intro_duration = float(settings["intro_duration"])
    outro_duration = float(settings["outro_duration"])
    fade_duration = float(settings["fade_duration"])
    watermark_enabled = settings["watermark"]["enabled"] and watermark_png is not None
    enhancement = audio_enhancement or AudioEnhancementOptions()

    main_duration = get_media_duration(main_video)
    fade_out_start = max(0.0, main_duration - fade_duration)
    offset_intro_main = intro_duration - fade_duration
    offset_main_outro = intro_duration + main_duration - (2 * fade_duration)
    total_duration = intro_duration + main_duration + outro_duration - (2 * fade_duration)

    scale_pad = (
        f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,"
        f"format=yuv420p,fps={fps}"
    )

    outro_input_index = 3 if watermark_enabled else 2

    intro_frames = max(1, int(intro_duration * fps) - 1)

    filters: list[str] = [
        (
            f"[0:v]{scale_pad},loop=loop={intro_frames}:size=1:start=0,"
            f"trim=duration={intro_duration},setpts=PTS-STARTPTS[intro]"
        ),
        f"[1:v]{scale_pad},setpts=PTS-STARTPTS[main_scaled]",
    ]

    if watermark_enabled:
        margin = settings["watermark"]["margin"]
        position = _overlay_position(settings["watermark"]["position"], margin)
        filters.append(f"[2:v]format=rgba,fps={fps}[wm]")
        filters.append(
            f"[main_scaled][wm]overlay={position}:format=auto:alpha=premultiplied[main_with_wm]"
        )
        main_label = "main_with_wm"
    else:
        main_label = "main_scaled"

    filters.extend(
        [
            (
                f"[{main_label}]fade=t=in:st=0:d={fade_duration},"
                f"fade=t=out:st={fade_out_start}:d={fade_duration},"
                f"setpts=PTS-STARTPTS[main]"
            ),
            (
                f"[{outro_input_index}:v]{scale_pad},trim=duration={outro_duration},setpts=PTS-STARTPTS[outro]"
            ),
            f"[intro][main]xfade=transition=fade:duration={fade_duration}:offset={offset_intro_main}[v01]",
            f"[v01][outro]xfade=transition=fade:duration={fade_duration}:offset={offset_main_outro}[vout]",
        ]
    )

    audio_delay_ms = int(max(0.0, intro_duration - fade_duration) * 1000)
    if has_audio_stream(main_video):
        audio_parts: list[str] = []
        if enhancement.enabled:
            audio_parts.append(build_audio_enhancement_filter(enhancement))
        audio_parts.extend(
            [
                f"adelay={audio_delay_ms}|{audio_delay_ms}",
                f"afade=t=in:st=0:d={fade_duration}",
                f"apad=whole_dur={total_duration}",
            ]
        )
        filters.append(f"[1:a]{','.join(audio_parts)}[aout]")
    else:
        filters.append(
            f"anullsrc=channel_layout=stereo:sample_rate=48000,atrim=duration={total_duration}[aout]"
        )

    filter_complex = ";".join(filters)

    args = [
        "-framerate",
        str(fps),
        "-i",
        str(intro_image),
        "-i",
        str(main_video),
    ]

    if watermark_enabled:
        args.extend(["-i", str(watermark_png)])

    args.extend(
        [
            "-f",
            "lavfi",
            "-i",
            f"color=c=black:s={width}x{height}:r={fps}:d={outro_duration}",
            "-filter_complex",
            filter_complex,
            "-map",
            "[vout]",
            "-map",
            "[aout]",
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "20",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-t",
            str(total_duration),
            "-movflags",
            "+faststart",
            str(output_path),
        ]
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    run_ffmpeg(
        args,
        total_duration=total_duration,
        progress_callback=progress_callback,
    )
    return output_path
