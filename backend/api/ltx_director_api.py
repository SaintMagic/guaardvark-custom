"""Dedicated API surface for the LTX 2.3 Director page."""

from __future__ import annotations

import copy
import json
from pathlib import Path

from flask import Blueprint, request
from werkzeug.utils import secure_filename

from backend.services.batch_video_generator import get_batch_video_generator
from backend.services.ltx_director_service import (
    get_ltx_director_service,
    invalidate_ltx_capability_cache,
)
from backend.services.workflows.ltx23_director_adapter import LTXDirectorConfig, LTXWorkflowError
from backend.utils.response_utils import error_response, success_response

try:
    from backend.config import UPLOAD_DIR
except ImportError:
    UPLOAD_DIR = "/tmp/guaardvark_uploads"


ltx_director_bp = Blueprint("ltx_director", __name__, url_prefix="/api/ltx-director")
_UPLOADS = Path(UPLOAD_DIR) / "LTXDirector"
_UPLOADS.mkdir(parents=True, exist_ok=True)
_ALLOWED = {
    "image": {".png", ".jpg", ".jpeg", ".webp", ".bmp"},
    "video": {".mp4", ".mov", ".mkv", ".webm", ".avi"},
    "audio": {".wav", ".mp3", ".flac", ".m4a", ".ogg", ".aac"},
}


def _json_body() -> dict:
    body = request.get_json(silent=True)
    return body if isinstance(body, dict) else {}


@ltx_director_bp.route("/capabilities", methods=["GET"])
def capabilities():
    model_id = request.args.get("model", "ltx23-dasiwa-dragonleap-v4")
    force = request.args.get("refresh", "false").lower() == "true"
    return success_response(get_ltx_director_service().readiness(model_id, force=force))


@ltx_director_bp.route("/capabilities/invalidate", methods=["POST"])
def invalidate_capabilities():
    invalidate_ltx_capability_cache()
    report = get_ltx_director_service().readiness(
        _json_body().get("model_id", "ltx23-dasiwa-dragonleap-v4"), force=True
    )
    return success_response(report)


@ltx_director_bp.route("/validate", methods=["POST"])
def validate():
    body = _json_body()
    config_raw = body.get("config", body)
    try:
        config, report = get_ltx_director_service().validate_config(config_raw)
        return success_response({
            "valid": True,
            "total_frames": config.total_frames,
            "capabilities": report,
        })
    except (LTXWorkflowError, TypeError, ValueError) as exc:
        return error_response(str(exc), 400)


@ltx_director_bp.route("/upload/<kind>", methods=["POST"])
def upload(kind: str):
    if kind not in _ALLOWED:
        return error_response("Upload kind must be image, video, or audio", 400)
    uploaded = request.files.get("file")
    if not uploaded or not uploaded.filename:
        return error_response("No file supplied", 400)
    name = secure_filename(uploaded.filename)
    suffix = Path(name).suffix.lower()
    if suffix not in _ALLOWED[kind]:
        return error_response(f"Unsupported {kind} extension: {suffix or '(none)'}", 400)
    target = _UPLOADS / name
    stem, counter = target.stem, 1
    while target.exists():
        target = _UPLOADS / f"{stem}_{counter}{suffix}"
        counter += 1
    uploaded.save(target)
    return success_response({"path": str(target), "name": target.name, "kind": kind})


@ltx_director_bp.route("/generate", methods=["POST"])
def generate():
    body = _json_body()
    config_raw = body.get("config")
    if not isinstance(config_raw, dict):
        return error_response("config must be an object", 400)
    try:
        config, _ = get_ltx_director_service().validate_config(config_raw)
    except (LTXWorkflowError, TypeError, ValueError) as exc:
        return error_response(str(exc), 400)

    generator = get_batch_video_generator()
    params = {
        "model": config.model_id,
        "duration_frames": config.total_frames,
        "fps": config.fps,
        "width": config.width,
        "height": config.height,
        "num_inference_steps": int(config.pass1.get("steps", 10)),
        "guidance_scale": float(config.pass1.get("cfg", 1.0)),
        "guidance_scale_overridden": True,
        "seed": config.seed,
        "negative_prompt": config.negative_prompt,
        "prompt_style": body.get("prompt_style", "cinematic"),
        "enhance_prompt": bool(body.get("enhance_prompt", False)),
        "fidelity_mode": bool(body.get("fidelity_mode", False)),
        "director_mode": bool(body.get("cinematic_prompt_rewrite", False)),
        "director_guidance": body.get("cinematic_prompt_guidance") or None,
        "ltx_config": copy.deepcopy(config_raw),
        "ui_config": copy.deepcopy(body.get("ui_config") or config_raw),
        "metadata": {
            "engine": "ltx-director", "mode": config.mode,
            "display_name": body.get("display_name") or f"LTX {config.mode.upper()}: {config.prompt[:32]}",
        },
    }
    if config.mode in {"i2v", "flf2v"}:
        status = generator.start_batch_from_images(
            image_paths=[config.source_image], prompt=config.prompt, **params
        )
    else:
        status = generator.start_batch_from_prompts(prompts=[config.prompt], **params)
    return success_response({"batch_id": status.batch_id, "status": status.status})


@ltx_director_bp.route("/defaults", methods=["GET"])
def defaults():
    return success_response({"config": LTXDirectorConfig().__dict__})
