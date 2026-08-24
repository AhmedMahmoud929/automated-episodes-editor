#!/usr/bin/env python3
"""CLI entry point for automated episode video generation."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
SRC_DIR = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_DIR))

from cli import run_interactive_cli  # noqa: E402
from console import create_progress, print_error, print_success  # noqa: E402
from ffmpeg_utils import (  # noqa: E402
    AudioEnhancementOptions,
    FFmpegNotFoundError,
)
from pipeline import process_episodes  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate branded episode videos with intro, fade, watermark, and outro."
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=PROJECT_ROOT / "config" / "episodes.json",
        help="Path to episodes JSON config (default: config/episodes.json)",
    )
    parser.add_argument(
        "--episode",
        type=str,
        default=None,
        help="Process a single episode by id (e.g. ep_01)",
    )
    parser.add_argument(
        "--no-interactive",
        action="store_true",
        help="Skip interactive prompts (use with --episode or process all from config)",
    )
    parser.add_argument(
        "--remove-noise",
        action="store_true",
        help="Apply noise removal to main audio",
    )
    parser.add_argument(
        "--voice-booster",
        action="store_true",
        help="Boost voice clarity in main audio",
    )
    parser.add_argument(
        "--normalize-audio",
        action="store_true",
        help="Normalize main audio levels",
    )
    parser.add_argument(
        "--bass-boost",
        action="store_true",
        help="Boost bass in main audio",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config_path = args.config.resolve()

    if not args.no_interactive and len(sys.argv) == 1:
        try:
            return run_interactive_cli(PROJECT_ROOT, config_path)
        except FFmpegNotFoundError as error:
            print_error(str(error))
            return 1
        except KeyboardInterrupt:
            print_error("Cancelled.")
            return 130

    if not config_path.exists():
        print_error(f"Config file not found: {config_path}")
        return 1

    audio_enhancement = AudioEnhancementOptions(
        remove_noise=args.remove_noise,
        voice_booster=args.voice_booster,
        normalize=args.normalize_audio,
        bass_boost=args.bass_boost,
    )

    try:
        with create_progress() as progress:
            outputs = process_episodes(
                config_path,
                project_root=PROJECT_ROOT,
                episode_id=args.episode,
                audio_enhancement=audio_enhancement,
                progress_manager=progress,
            )
    except FFmpegNotFoundError as error:
        print_error(str(error))
        return 1
    except (FileNotFoundError, ValueError, RuntimeError) as error:
        print_error(str(error))
        return 1

    print_success(f"Done! Generated {len(outputs)} video(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
