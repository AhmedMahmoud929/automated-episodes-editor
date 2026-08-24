"""Episode video production pipeline."""

from __future__ import annotations

import json
import shutil
from collections.abc import Callable
from pathlib import Path

from ffmpeg_utils import (
    AudioEnhancementOptions,
    CutSegment,
    FFmpegNotFoundError,
    apply_video_cuts,
    build_episode_video,
    find_ffmpeg,
    prepare_watermark_png,
)
from intro import generate_intro_image, lesson_subtitle


def load_config(config_path: Path) -> dict:
    with config_path.open(encoding="utf-8") as handle:
        return json.load(handle)


def resolve_project_paths(project_root: Path) -> Path:
    temp_dir = project_root / "temp"
    temp_dir.mkdir(parents=True, exist_ok=True)
    return temp_dir


def _resolve_path(project_root: Path, relative_path: str) -> Path:
    path = Path(relative_path)
    if path.is_absolute():
        return path
    return project_root / path


def _parse_cuts(episode: dict) -> list[CutSegment]:
    raw_cuts = episode.get("cuts", [])
    if not raw_cuts:
        return []
    return [CutSegment.from_dict(item) for item in raw_cuts]


def process_episode(
    episode: dict,
    settings: dict,
    project_root: Path,
    temp_dir: Path,
    *,
    audio_enhancement: AudioEnhancementOptions | None = None,
    step_callback: Callable[[str, float | None], None] | None = None,
) -> Path:
    def report(step: str, percent: float | None = None) -> None:
        if step_callback:
            step_callback(step, percent)

    episode_id = episode["id"]
    input_path = _resolve_path(project_root, episode["input"])
    output_path = _resolve_path(project_root, episode["output"])
    title = episode["title"]
    cuts = _parse_cuts(episode)

    if not input_path.exists():
        raise FileNotFoundError(f"Input video not found: {input_path}")

    episode_temp = temp_dir / episode_id
    episode_temp.mkdir(parents=True, exist_ok=True)

    main_video = input_path
    if cuts:
        trimmed_video = episode_temp / "trimmed.mp4"
        report(f"Applying {len(cuts)} cut(s)", 0)

        def on_cut_progress(percent: float) -> None:
            report("Trimming video", percent)

        apply_video_cuts(
            input_path,
            cuts,
            trimmed_video,
            fps=int(settings["fps"]),
            progress_callback=on_cut_progress,
        )
        main_video = trimmed_video
        report("Trimming video", 100)

    report("Generating intro slide", None)
    intro_image = episode_temp / "intro.png"
    watermark_png: Path | None = None
    episode_number = episode.get("number")
    generate_intro_image(
        title,
        settings,
        intro_image,
        project_root,
        episode_number=episode_number,
        episode_subtitle=episode.get("subtitle")
        or (lesson_subtitle(episode_number) if episode_number is not None else None),
    )
    report("Generating intro slide", 100)

    watermark_settings = settings["watermark"]
    if watermark_settings.get("enabled", False):
        report("Preparing watermark", None)
        logo_path = _resolve_path(project_root, watermark_settings["logo"])
        watermark_png = prepare_watermark_png(
            logo_path,
            episode_temp / "watermark.png",
            scale=float(watermark_settings["scale"]),
            opacity=float(watermark_settings["opacity"]),
            frame_width=int(settings["resolution"][0]),
        )
        report("Preparing watermark", 100)

    report("Rendering final video", 0)

    def on_render_progress(percent: float) -> None:
        report("Rendering final video", percent)

    build_episode_video(
        intro_image=intro_image,
        main_video=main_video,
        watermark_png=watermark_png,
        output_path=output_path,
        settings=settings,
        audio_enhancement=audio_enhancement,
        progress_callback=on_render_progress,
    )
    report("Rendering final video", 100)

    shutil.rmtree(episode_temp, ignore_errors=True)
    return output_path


def process_episodes(
    config_path: Path | None,
    *,
    project_root: Path,
    episode_id: str | None = None,
    episodes: list[dict] | None = None,
    settings: dict | None = None,
    audio_enhancement: AudioEnhancementOptions | None = None,
    progress_manager=None,
) -> list[Path]:
    find_ffmpeg()

    if settings is None or episodes is None:
        if config_path is None or not config_path.exists():
            raise FileNotFoundError("Config file is required when episodes or settings are not provided.")
        config = load_config(config_path)
        resolved_settings = settings or config["settings"]
        resolved_episodes = episodes if episodes is not None else config["episodes"]
    else:
        resolved_settings = settings
        resolved_episodes = episodes

    temp_dir = resolve_project_paths(project_root)

    if episode_id:
        available_episodes = resolved_episodes
        resolved_episodes = [episode for episode in resolved_episodes if episode["id"] == episode_id]
        if not resolved_episodes:
            available = ", ".join(item["id"] for item in available_episodes)
            raise ValueError(f"Episode '{episode_id}' not found. Available: {available}")

    outputs: list[Path] = []
    use_progress = progress_manager is not None

    if use_progress:
        overall_task = progress_manager.add_task(
            "[bold bright_cyan]Overall progress[/bold bright_cyan]",
            total=len(resolved_episodes),
        )
        step_task = progress_manager.add_task("[cyan]Starting...[/cyan]", total=100)

    for episode in resolved_episodes:
        episode_label = episode["id"]

        def step_callback(step: str, percent: float | None = None) -> None:
            if not use_progress:
                return
            description = f"[bright_yellow]{episode_label}[/bright_yellow] · [white]{step}[/white]"
            if percent is None:
                progress_manager.update(step_task, description=description, completed=0, total=100)
            else:
                progress_manager.update(
                    step_task,
                    description=description,
                    completed=max(0, min(100, int(percent))),
                    total=100,
                )

        if not use_progress:
            print(f"Processing {episode_label}...")

        output = process_episode(
            episode,
            resolved_settings,
            project_root,
            temp_dir,
            audio_enhancement=audio_enhancement,
            step_callback=step_callback,
        )
        outputs.append(output)

        if use_progress:
            progress_manager.update(overall_task, advance=1)
            progress_manager.update(
                step_task,
                description=f"[green]{episode_label}[/green] · [bold green]Done[/bold green]",
                completed=100,
            )

    return outputs
