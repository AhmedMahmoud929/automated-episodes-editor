"""Interactive CLI for episode video generation."""

from __future__ import annotations

from pathlib import Path

from console import (
    console,
    create_episode_table,
    create_progress,
    print_error,
    print_header,
    print_info,
    print_section,
    print_success,
    print_summary_table,
    print_warning,
)
from ffmpeg_utils import AudioEnhancementOptions
from pipeline import load_config, process_episodes
from rich.prompt import Confirm, Prompt


DEFAULT_SETTINGS: dict = {
    "resolution": [1920, 1080],
    "fps": 30,
    "intro_duration": 3.0,
    "outro_duration": 2.0,
    "fade_duration": 1.0,
    "watermark": {
        "enabled": True,
        "logo": "assets/logo.png",
        "opacity": 0.45,
        "scale": 0.12,
        "margin": 24,
        "position": "bottom_right",
    },
    "intro": {
        "background": "#F2F2F2",
        "primary_color": "#2D4739",
        "title_color": "#2D4739",
        "line_color": "#B5B5B5",
        "subtitle_color": "#757575",
        "tag_text_color": "#FFFFFF",
        "number_text_color": "#FFFFFF",
        "production_text_color": "#8A8A8A",
        "footer_box_fill": "#F7F7F7",
        "footer_box_border": "#D4D4D4",
        "logo_main": "assets/logo.png",
        "logo_partner": "assets/alfaiza.webp",
        "font": "fonts/Rubik-Bold.ttf",
        "tag_font": "fonts/Rubik-Regular.ttf",
        "subtitle_font": "fonts/Rubik-Regular.ttf",
        "number_font": "fonts/Rubik-Bold.ttf",
        "production_font": "fonts/Rubik-Regular.ttf",
        "font_size": 96,
        "tag_font_size": 30,
        "subtitle_font_size": 34,
        "number_font_size": 30,
        "production_font_size": 22,
        "logo_main_width": 360,
        "logo_partner_width": 130,
        "edge_margin": 72,
        "number_circle_radius": 34,
        "tag_text": "دورة تدريبية",
        "production_text": "إنتاج وتنفيذ",
    },
}


def _discover_videos(search_dirs: list[Path]) -> list[Path]:
    extensions = {".mp4", ".mov", ".mkv", ".avi", ".webm"}
    videos: list[Path] = []
    seen: set[Path] = set()

    for directory in search_dirs:
        if not directory.exists():
            continue
        for path in sorted(directory.iterdir()):
            if path.is_file() and path.suffix.lower() in extensions:
                resolved = path.resolve()
                if resolved not in seen:
                    seen.add(resolved)
                    videos.append(path)

    return sorted(videos, key=lambda path: path.name.lower())


def _build_episode_from_video(video_path: Path, project_root: Path) -> dict:
    relative_input = video_path.relative_to(project_root).as_posix()
    stem = video_path.stem
    return {
        "id": stem,
        "input": relative_input,
        "title": stem.replace("_", " "),
        "output": f"output/{stem}_final.mp4",
        "cuts": [],
    }


def _select_episodes_from_config(config: dict) -> tuple[list[dict], str | None]:
    episodes = config["episodes"]
    if not episodes:
        raise ValueError("No episodes defined in config.")

    print_section("Select Episode")
    rows: list[tuple[str, str, str]] = []
    for index, episode in enumerate(episodes, start=1):
        cuts_count = len(episode.get("cuts", []))
        cuts_label = f" · [warning]{cuts_count} cut(s)[/warning]" if cuts_count else ""
        rows.append((str(index), episode["id"], f"{episode['title']}{cuts_label}"))

    console.print(create_episode_table("Episodes from config", rows))

    choice = Prompt.ask(
        "[accent]Select episode number or[/accent] [highlight]A[/highlight] [accent]for all[/accent]",
        default="A",
        console=console,
    ).upper()

    if choice == "A":
        print_success(f"Selected all {len(episodes)} episode(s)")
        return episodes, None

    try:
        selected_index = int(choice)
    except ValueError as error:
        raise ValueError(f"Invalid selection: {choice}") from error

    if selected_index < 1 or selected_index > len(episodes):
        raise ValueError(f"Selection out of range: {selected_index}")

    selected = episodes[selected_index - 1]
    print_success(f"Selected {selected['id']}")
    return [selected], selected["id"]


def _select_episodes_from_folder(project_root: Path) -> list[dict]:
    search_dirs = [project_root / "input", project_root / "episodes"]
    videos = _discover_videos(search_dirs)

    if not videos:
        searched = ", ".join(str(path) for path in search_dirs)
        raise FileNotFoundError(
            f"No video files found in {searched}. "
            "Place source videos there or use episodes.json config."
        )

    print_section("Select Video")
    rows = [(str(index), video.stem, video.name) for index, video in enumerate(videos, start=1)]
    console.print(create_episode_table("Available videos", rows))

    choice = Prompt.ask(
        "[accent]Select video number or[/accent] [highlight]A[/highlight] [accent]for all[/accent]",
        default="A",
        console=console,
    ).upper()

    if choice == "A":
        print_success(f"Selected all {len(videos)} video(s)")
        return [_build_episode_from_video(video, project_root) for video in videos]

    try:
        selected_index = int(choice)
    except ValueError as error:
        raise ValueError(f"Invalid selection: {choice}") from error

    if selected_index < 1 or selected_index > len(videos):
        raise ValueError(f"Selection out of range: {selected_index}")

    selected = videos[selected_index - 1]
    print_success(f"Selected {selected.name}")
    return [_build_episode_from_video(selected, project_root)]


def _prompt_audio_enhancement() -> AudioEnhancementOptions:
    print_section("Audio Enhancement")

    options = [
        ("Remove background noise", "remove_noise", False),
        ("Boost voice clarity", "voice_booster", False),
        ("Normalize audio levels", "normalize", False),
        ("Boost bass", "bass_boost", False),
    ]

    selected: dict[str, bool] = {}
    for label, key, default in options:
        selected[key] = Confirm.ask(f"[white]{label}[/white]", default=default, console=console)

    enabled = [label for label, key, _ in options if selected[key]]
    if enabled:
        print_success("Enabled: " + ", ".join(enabled))
    else:
        print_info("No audio enhancement selected")

    return AudioEnhancementOptions(
        remove_noise=selected["remove_noise"],
        voice_booster=selected["voice_booster"],
        normalize=selected["normalize"],
        bass_boost=selected["bass_boost"],
    )


def run_interactive_cli(project_root: Path, config_path: Path) -> int:
    print_header()

    print_section("Configuration")
    use_config = Confirm.ask(
        "[white]Use[/white] [highlight]episodes.json[/highlight] [white]config?[/white]",
        default=True,
        console=console,
    )

    config: dict | None = None
    settings = DEFAULT_SETTINGS

    if use_config:
        if not config_path.exists():
            print_error(f"Config file not found: {config_path}")
            return 1
        config = load_config(config_path)
        settings = config["settings"]
        episodes, episode_id = _select_episodes_from_config(config)
    else:
        episodes = _select_episodes_from_folder(project_root)
        episode_id = episodes[0]["id"] if len(episodes) == 1 else None
        if config_path.exists():
            config = load_config(config_path)
            settings = config["settings"]
            print_info("Using settings from episodes.json (episode list ignored).")

    audio_enhancement = _prompt_audio_enhancement()

    enabled_audio = []
    if audio_enhancement.remove_noise:
        enabled_audio.append("noise removal")
    if audio_enhancement.voice_booster:
        enabled_audio.append("voice booster")
    if audio_enhancement.normalize:
        enabled_audio.append("normalize")
    if audio_enhancement.bass_boost:
        enabled_audio.append("bass boost")

    print_section("Confirm")
    print_summary_table(
        use_config=use_config,
        episode_count=len(episodes),
        audio_labels=enabled_audio,
    )

    if not Confirm.ask("[accent]Start processing?[/accent]", default=True, console=console):
        print_warning("Cancelled by user.")
        return 0

    console.print()
    print_section("Processing")

    try:
        with create_progress() as progress:
            outputs = process_episodes(
                config_path if config_path.exists() else None,
                project_root=project_root,
                episode_id=episode_id if use_config and episode_id else None,
                episodes=episodes,
                settings=settings,
                audio_enhancement=audio_enhancement,
                progress_manager=progress,
            )
    except (FileNotFoundError, ValueError, RuntimeError) as error:
        console.print()
        print_error(str(error))
        return 1

    console.print()
    print_success(f"Done! Generated {len(outputs)} video(s).")
    for output in outputs:
        console.print(f"  [muted]→[/muted] [green]{output}[/green]")

    return 0
