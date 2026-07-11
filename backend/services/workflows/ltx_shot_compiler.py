"""Compile editable LTX sequence shots into existing LTX config payloads."""

from __future__ import annotations

import copy
from typing import Any, Dict, Mapping

from backend.services.workflows.ltx23_director_adapter import LTXDirectorConfig, LTXWorkflowError


def resolve_shot_config(sequence: Mapping[str, Any], shot: Mapping[str, Any]) -> LTXDirectorConfig:
    global_config = copy.deepcopy(sequence.get("global") or {})
    shot_config = copy.deepcopy(shot.get("sampling_override") or {})
    merged: Dict[str, Any] = {**global_config, **shot_config}
    merged["prompt"] = shot.get("prompt", "")
    merged["negative_prompt"] = shot.get("negative_prompt_override") or global_config.get("negative_prompt", "")
    merged["duration_seconds"] = float(shot.get("duration_seconds", 1.0))
    merged["source_image"] = shot.get("source_image")
    merged["last_frame"] = shot.get("last_frame")
    merged["source_video"] = shot.get("source_video")
    merged["seed"] = int(shot["seed_value"]) if shot.get("seed_mode") == "fixed" and shot.get("seed_value") is not None else int(merged.get("seed", 42))
    merged["guide_strength"] = float(shot.get("guide_strength", merged.get("guide_strength", 1.0)))
    merged["motion_guide_strength"] = float(shot.get("motion_strength", merged.get("motion_guide_strength", 1.0)))
    merged["audio_source"] = shot.get("audio_source_override") or merged.get("audio_source", "generated")
    config = LTXDirectorConfig.from_dict(merged)
    config.validate()
    return config


def compile_timeline(sequence: Mapping[str, Any]) -> Dict[str, Any]:
    fps = int((sequence.get("global") or {}).get("fps", 24))
    shots = [shot for shot in sequence.get("shots", []) if shot.get("enabled", True)]
    if not shots:
        raise LTXWorkflowError("Sequence must contain at least one enabled shot")
    cursor = 0
    timeline_segments = []
    motion_segments = []
    audio_segments = []
    for shot in shots:
        frames = max(8, ((round(float(shot.get("duration_seconds", 1.0)) * fps) + 7) // 8) * 8)
        end = cursor + frames
        timeline_segments.append({"start": cursor, "end": end, "prompt": shot.get("prompt", "")})
        motion_segments.append({"start": cursor, "end": end, "strength": float(shot.get("motion_strength", 1.0))})
        audio_segments.append({"start": cursor, "end": end, "source": shot.get("audio_source_override") or "generated"})
        cursor = end
    return {
        "timeline_segments": timeline_segments,
        "motion_segments": motion_segments,
        "audio_segments": audio_segments,
        "total_frames": cursor,
        "fps": fps,
    }
