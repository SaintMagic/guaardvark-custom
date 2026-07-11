"""Phase-one hard-cut stitching for completed LTX shot outputs."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, Iterable, Mapping


def stitch_hard_cuts(paths: Iterable[str | Path], output_path: str | Path, *, audio_policy: str = "preserve_shot_audio") -> Path:
    inputs = [Path(path) for path in paths]
    if not inputs or any(not path.is_file() for path in inputs):
        raise ValueError("All selected shot outputs must exist before stitching")
    if audio_policy not in {"preserve_shot_audio", "mute_all", "external_sequence_audio"}:
        raise ValueError("Unsupported sequence audio policy")
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    manifest = target.with_suffix(".manifest.json")
    concat_file = target.with_suffix(".concat.txt")
    concat_file.write_text("\n".join(f"file '{path.resolve().as_posix().replace(chr(39), chr(39) + chr(92) + chr(39) + chr(39))}'" for path in inputs) + "\n", encoding="utf-8")
    command = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_file), "-c:v", "libx264", "-pix_fmt", "yuv420p"]
    if audio_policy == "mute_all":
        command.append("-an")
    else:
        command.extend(["-c:a", "aac", "-ar", "48000", "-ac", "2"])
    command.append(str(target))
    try:
        subprocess.run(command, check=True, capture_output=True, text=True, timeout=3600)
    finally:
        concat_file.unlink(missing_ok=True)
    manifest.write_text(json.dumps({"inputs": [str(path) for path in inputs], "output": str(target), "audio_policy": audio_policy}, indent=2) + "\n", encoding="utf-8")
    return target
