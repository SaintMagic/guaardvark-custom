"""Shot-batch orchestration for versioned LTX Director sequences."""

from __future__ import annotations

import copy
import json
import logging
import subprocess
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from backend.services.ltx_director_service import get_ltx_director_service
from backend.services.ltx_sequence_repository import LTXSequenceRepository
from backend.services.ltx_stitch_service import stitch_hard_cuts
from backend.services.workflows.ltx_shot_compiler import compile_timeline, resolve_shot_config

logger = logging.getLogger(__name__)


def _emit_progress(sequence_id: str, *, state: str, percent: float, label: str, completed_units: int, total_units: int) -> None:
    """Publish the normalized shape consumed by the existing global progress UI."""
    payload = {
        "job_id": f"ltx-sequence:{sequence_id}", "job_type": "ltx_sequence",
        "process_type": "ltx_sequence", "state": state, "status": state,
        "progress": max(0.0, min(100.0, percent)), "percent": max(0.0, min(100.0, percent)),
        "message": label, "label": label, "completed_units": completed_units,
        "total_units": total_units, "queued_count": max(0, total_units - completed_units),
        "can_cancel": state in {"queued", "running", "postprocessing"},
    }
    try:
        from backend.socketio_instance import socketio
        socketio.emit("job_progress", payload, to="global_progress", namespace="/")
        socketio.emit("job:event", {"id": payload["job_id"], **payload}, to="jobs:all", namespace="/")
    except Exception as exc:
        logger.debug("Sequence progress emission unavailable: %s", exc)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_sequence(payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    payload = copy.deepcopy(payload or {})
    project_id = payload.get("project_id") or str(uuid.uuid4())
    global_config = {
        "model_id": "ltx23-dasiwa-dragonleap-v4", "width": 576, "height": 896,
        "fps": 24, "negative_prompt": "", "sampler": "euler_cfg_pp",
        "seed_policy": "random_per_shot", "audio_source": "generated",
        "keyframe_model": "flux-schnell", "cast_subject_id": None,
        "image_loras": [], "keyframe_seed_policy": "random_per_shot",
        "keyframe_defaults": {"width": 576, "height": 896, "steps": 8},
        "pass1": {"enabled": True, "cfg": 1.0, "steps": 10, "scheduler": "linear_quadratic", "denoise": 1.0},
        "pass2": {"enabled": True, "cfg": 1.0, "steps": 4, "scheduler": "linear_quadratic", "denoise": 0.3},
        "pass3": {"enabled": False, "cfg": 1.0, "steps": 2, "scheduler": "linear_quadratic", "denoise": 0.2},
        "tiled_vae": True, "chunking": True,
    }
    sequence = {
        "schema_version": 1, "project_id": project_id,
        "title": payload.get("title") or "Untitled LTX Sequence",
        "render_mode": payload.get("render_mode") or "shot_batch",
        "global": {**global_config, **(payload.get("global") or {})},
        "shots": payload.get("shots") or [],
        "stitch": {"enabled": True, "output_format": "video/h264-mp4", "transition_default": "hard_cut", "dissolve_seconds": 0.35, "audio_policy": "preserve_shot_audio", **(payload.get("stitch") or {})},
        "updated_at": _now(), "jobs": payload.get("jobs") or {},
    }
    return sequence


class LTXSequenceService:
    def __init__(self, repository: Optional[LTXSequenceRepository] = None):
        self.repository = repository or LTXSequenceRepository()
        self._threads: Dict[str, threading.Thread] = {}
        self._cancel: Dict[str, threading.Event] = {}
        self._lock = threading.Lock()

    def validate(self, sequence: Dict[str, Any]) -> Dict[str, Any]:
        if sequence.get("schema_version") != 1:
            raise ValueError("Unsupported LTX sequence schema_version")
        if sequence.get("render_mode") not in {"shot_batch", "timeline"}:
            raise ValueError("render_mode must be shot_batch or timeline")
        shots = sequence.get("shots") or []
        if not shots or not any(shot.get("enabled", True) for shot in shots):
            raise ValueError("Sequence must contain at least one enabled shot")
        ids = [shot.get("id") for shot in shots]
        if any(not item for item in ids) or len(ids) != len(set(ids)):
            raise ValueError("Every shot must have a unique id")
        for index, shot in enumerate(shots):
            if not str(shot.get("prompt", "")).strip():
                raise ValueError(f"Shot {index + 1} requires a prompt")
            if float(shot.get("duration_seconds", 0)) <= 0:
                raise ValueError(f"Shot {index + 1} requires a positive duration")
            dependency = shot.get("previous_shot_id") if shot.get("continuity_mode") == "previous" else None
            if dependency and dependency not in ids[:index]:
                raise ValueError(f"Shot {index + 1} must depend on an earlier shot")
        return sequence

    def save(self, sequence: Dict[str, Any]) -> Dict[str, Any]:
        self.validate(sequence)
        sequence = copy.deepcopy(sequence)
        sequence["updated_at"] = _now()
        return self.repository.save(sequence)

    def render_shot(self, sequence_id: str, shot_id: str, *, retry: bool = False) -> Dict[str, Any]:
        sequence = self.repository.get(sequence_id)
        if not sequence:
            raise KeyError("Sequence not found")
        self.validate(sequence)
        shot = next((item for item in sequence["shots"] if item.get("id") == shot_id), None)
        if not shot:
            raise KeyError("Shot not found")
        if shot.get("keyframe_source") == "generated" and shot.get("keyframe_asset_path") and shot.get("keyframe_status") != "approved":
            raise ValueError("Generated keyframe must be approved before LTX animation")
        if shot.get("status") == "completed" and not retry:
            return sequence
        if shot.get("continuity_mode") == "previous":
            previous = next((item for item in sequence["shots"] if item.get("id") == shot.get("previous_shot_id")), None)
            if not previous or previous.get("status") != "completed" or not previous.get("final_frame_path"):
                shot["status"] = "blocked"
                shot["error"] = "Previous shot must complete before this shot can render"
                return self.save(sequence)
            shot["source_image"] = previous["final_frame_path"]
        config = resolve_shot_config(sequence, shot)
        attempt = int(shot.get("attempt_number", 0)) + 1
        shot.update({"status": "running", "attempt_number": attempt, "error": None, "resolved_config": copy.deepcopy(config.__dict__), "started_at": _now()})
        self.save(sequence)
        output_root = Path("data") / "ltx_sequences" / sequence_id / "shots"
        result = get_ltx_director_service().generate(config.__dict__, output_dir=output_root, batch_id=f"ltx-sequence-{sequence_id}-{shot_id}-{attempt}")
        if result.success:
            shot.update({"status": "completed", "output_path": result.video_path, "finished_at": _now(), "metadata": result.metadata})
            if result.video_path:
                final_frame = output_root / f"{shot_id}-attempt-{attempt}-final.png"
                subprocess.run(["ffmpeg", "-y", "-sseof", "-0.05", "-i", str(result.video_path), "-frames:v", "1", str(final_frame)], capture_output=True, timeout=120)
                shot["final_frame_path"] = str(final_frame) if final_frame.exists() else None
        else:
            shot.update({"status": "error", "error": result.error, "finished_at": _now()})
        sequence = self.save(sequence)
        logger.info("LTX shot %s/%s finished with status %s", sequence_id, shot_id, shot["status"])
        return sequence

    def approve_keyframe(self, sequence_id: str, shot_id: str, asset_path: str) -> Dict[str, Any]:
        sequence = self.repository.get(sequence_id)
        if not sequence:
            raise KeyError("Sequence not found")
        shot = next((item for item in sequence.get("shots", []) if item.get("id") == shot_id), None)
        if not shot:
            raise KeyError("Shot not found")
        path = Path(asset_path)
        if not path.exists() or path.stat().st_size == 0:
            raise ValueError("Keyframe asset does not exist or is empty")
        shot.update({"keyframe_asset_path": str(path), "keyframe_status": "approved", "source_image": str(path), "keyframe_approved_at": _now()})
        return self.save(sequence)

    def generate_keyframe(self, sequence_id: str, shot_id: str, *, regenerate: bool = False) -> Dict[str, Any]:
        """Generate a persistent FLUX/ComfyUI keyframe using the shared image service."""
        sequence = self.repository.get(sequence_id)
        if not sequence:
            raise KeyError("Sequence not found")
        shot = next((item for item in sequence.get("shots", []) if item.get("id") == shot_id), None)
        if not shot:
            raise KeyError("Shot not found")
        if shot.get("keyframe_status") == "approved" and not regenerate:
            raise ValueError("Keyframe is approved; use regenerate explicitly")
        from backend.services.comfyui_image_generator import ComfyUIImageGenerator
        keyframe_dir = Path("data") / "ltx_sequences" / sequence_id / "keyframes"
        keyframe_dir.mkdir(parents=True, exist_ok=True)
        attempt = int(shot.get("keyframe_attempt", 0)) + 1
        path = keyframe_dir / f"{shot_id}-keyframe-{attempt}.png"
        global_config = sequence.get("global") or {}
        defaults = global_config.get("keyframe_defaults") or {}
        seed = int(shot.get("keyframe_seed") or shot.get("seed_value") or 42)
        model = shot.get("keyframe_model") or global_config.get("keyframe_model") or "flux-schnell"
        raw_loras = shot.get("image_loras") or global_config.get("image_loras") or []
        loras = [item if isinstance(item, str) else (item.get("path") or item.get("name")) for item in raw_loras]
        loras = [item for item in loras if item]
        generator = ComfyUIImageGenerator()
        generator.generate_image(prompt=shot.get("prompt", ""), negative_prompt=shot.get("negative_prompt_override") or global_config.get("negative_prompt", ""), output_path=str(path), width=int(defaults.get("width", 576)), height=int(defaults.get("height", 896)), seed=seed, steps=int(defaults.get("steps", 8)), model=model, loras=loras)
        metadata = {"sequence_id": sequence_id, "shot_id": shot_id, "image_model": model, "cast_subject_id": shot.get("cast_subject_id") or global_config.get("cast_subject_id"), "image_loras": loras, "seed": seed, "prompt": shot.get("prompt", ""), "source_references": {"source_image": shot.get("source_image")}, "generated_at": _now()}
        path.with_suffix(".json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        shot.update({"keyframe_source": "generated", "keyframe_asset_path": str(path), "keyframe_status": "unapproved", "keyframe_attempt": attempt, "keyframe_metadata": metadata})
        return self.save(sequence)

    def render_all(self, sequence_id: str) -> Dict[str, Any]:
        sequence = self.repository.get(sequence_id)
        if not sequence:
            raise KeyError("Sequence not found")
        with self._lock:
            if sequence_id in self._threads and self._threads[sequence_id].is_alive():
                raise RuntimeError("Sequence is already rendering")
            cancel = threading.Event()
            self._cancel[sequence_id] = cancel
            thread = threading.Thread(target=self._render_all_worker, args=(sequence_id, cancel), daemon=True)
            self._threads[sequence_id] = thread
            thread.start()
        sequence["jobs"]["active"] = {"state": "queued", "started_at": _now()}
        _emit_progress(sequence_id, state="queued", percent=0, label="Queued LTX sequence", completed_units=0, total_units=len(sequence.get("shots", [])))
        return self.save(sequence)

    def _render_all_worker(self, sequence_id: str, cancel: threading.Event) -> None:
        sequence = None
        try:
            sequence = self.repository.get(sequence_id) or {}
            shots = [shot for shot in sequence.get("shots", []) if shot.get("enabled", True)]
            total_units = len(shots)
            completed_units = 0
            if sequence.get("render_mode") == "timeline":
                self._render_timeline(sequence, sequence_id, cancel)
                return
            for shot in shots:
                if cancel.is_set():
                    break
                if not shot.get("enabled", True) or shot.get("status") == "completed":
                    completed_units += 1
                    continue
                _emit_progress(sequence_id, state="running", percent=(completed_units / max(1, total_units)) * 95, label=f"Rendering LTX shot {completed_units + 1} of {total_units}", completed_units=completed_units, total_units=total_units)
                sequence = self.render_shot(sequence_id, shot["id"])
                completed_units += 1
                _emit_progress(sequence_id, state="running", percent=(completed_units / max(1, total_units)) * 95, label=f"Completed LTX shot {completed_units} of {total_units}", completed_units=completed_units, total_units=total_units)
            sequence = self.repository.get(sequence_id) or sequence
            _emit_progress(sequence_id, state="completed" if not cancel.is_set() else "cancelled", percent=100 if not cancel.is_set() else (completed_units / max(1, total_units)) * 95, label="LTX sequence complete" if not cancel.is_set() else "LTX sequence cancelled", completed_units=completed_units, total_units=total_units)
            sequence.setdefault("jobs", {})["active"] = {"state": "cancelled" if cancel.is_set() else "completed", "finished_at": _now()}
            self.save(sequence)
        except Exception as exc:
            logger.exception("LTX sequence %s failed", sequence_id)
            sequence = self.repository.get(sequence_id)
            if sequence:
                sequence.setdefault("jobs", {})["active"] = {"state": "failed", "finished_at": _now(), "error": str(exc)}
                try:
                    self.save(sequence)
                except Exception:
                    logger.exception("Could not persist failed LTX sequence %s", sequence_id)
            _emit_progress(sequence_id, state="failed", percent=0, label=f"LTX sequence failed: {exc}", completed_units=0, total_units=len((sequence or {}).get("shots", [])))

    def _render_timeline(self, sequence: Dict[str, Any], sequence_id: str, cancel: threading.Event) -> None:
        """Submit one compiled LTX timeline while keeping the editable shot list intact."""
        from backend.services.workflows.ltx23_director_adapter import LTXDirectorConfig

        compiled = compile_timeline(sequence)
        shots = [shot for shot in sequence.get("shots", []) if shot.get("enabled", True)]
        if cancel.is_set():
            return
        first = shots[0]
        global_config = copy.deepcopy(sequence.get("global") or {})
        merged = {
            **global_config,
            "mode": "t2v" if not first.get("source_image") else global_config.get("mode", "i2v"),
            "prompt": first.get("prompt", ""),
            "source_image": first.get("source_image"),
            "last_frame": first.get("last_frame"),
            "source_video": first.get("source_video"),
            "duration_seconds": compiled["total_frames"] / max(1, compiled["fps"]),
            "fps": compiled["fps"],
            "timeline_segments": compiled["timeline_segments"],
            "motion_segments": compiled["motion_segments"],
            "audio_segments": compiled["audio_segments"],
        }
        config = LTXDirectorConfig.from_dict(merged)
        config.validate()
        jobs = sequence.setdefault("jobs", {})
        jobs["active"] = {"state": "running", "mode": "timeline", "started_at": _now(), "total_frames": compiled["total_frames"]}
        self.save(sequence)
        _emit_progress(sequence_id, state="running", percent=5, label="Compiling LTX timeline", completed_units=0, total_units=len(shots))
        output_root = Path("data") / "ltx_sequences" / sequence_id / "sequence"
        result = get_ltx_director_service().generate(config.__dict__, output_dir=output_root, batch_id=f"ltx-timeline-{sequence_id}")
        sequence = self.repository.get(sequence_id) or sequence
        jobs = sequence.setdefault("jobs", {})
        if result.success:
            jobs["active"] = {"state": "completed", "mode": "timeline", "finished_at": _now(), "output_path": result.video_path, "total_frames": compiled["total_frames"]}
            sequence.setdefault("timeline", {})["compiled"] = compiled
            sequence["timeline"]["output_path"] = result.video_path
            _emit_progress(sequence_id, state="completed", percent=100, label="LTX timeline complete", completed_units=len(shots), total_units=len(shots))
        else:
            jobs["active"] = {"state": "failed", "mode": "timeline", "finished_at": _now(), "error": result.error}
            _emit_progress(sequence_id, state="failed", percent=5, label=f"LTX timeline failed: {result.error}", completed_units=0, total_units=len(shots))
        self.save(sequence)

    def cancel(self, sequence_id: str) -> bool:
        event = self._cancel.get(sequence_id)
        if not event:
            return False
        event.set()
        return True

    def stitch(self, sequence_id: str) -> Dict[str, Any]:
        sequence = self.repository.get(sequence_id)
        if not sequence:
            raise KeyError("Sequence not found")
        if sequence.get("render_mode") == "timeline":
            timeline_path = (sequence.get("timeline") or {}).get("output_path")
            if timeline_path:
                sequence.setdefault("stitch", {})["output_path"] = timeline_path
                return self.save(sequence)
        paths = [shot.get("output_path") for shot in sequence.get("shots", []) if shot.get("enabled", True) and shot.get("status") == "completed" and shot.get("output_path")]
        if not paths:
            raise ValueError("No completed shots are available to stitch")
        output = Path("data") / "ltx_sequences" / sequence_id / "sequence" / "final.mp4"
        stitch_hard_cuts(paths, output, audio_policy=(sequence.get("stitch") or {}).get("audio_policy", "preserve_shot_audio"))
        sequence.setdefault("stitch", {})["output_path"] = str(output)
        return self.save(sequence)


_service: Optional[LTXSequenceService] = None


def get_ltx_sequence_service() -> LTXSequenceService:
    global _service
    if _service is None:
        _service = LTXSequenceService()
    return _service
