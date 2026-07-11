"""Isolated LTX Director generation service.

Queue ownership, persistence, progress events, cancellation, and result history
remain in the existing batch-video infrastructure.  This service owns only LTX
schema/readiness checks, media upload, semantic workflow construction, and the
ComfyUI request lifecycle.
"""

from __future__ import annotations

import logging
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

import requests

from backend.services.comfyui_progress_bridge import ComfyUIProgressBridge
from backend.services.comfyui_video_generator import (
    ComfyUIVideoGenerator,
    VideoGenerationResult,
)
from backend.services.video_model_registry import is_model_installed
from backend.services.workflows.ltx23_director_adapter import (
    LTXDirectorConfig,
    LTXWorkflowError,
    OPTIONAL_NODE_SCHEMAS,
    build_ltx23_workflow,
    available_lora_choices,
    canonicalize_config_loras,
    capability_report,
    enabled_optional_classes,
    normalize_lora_name,
    selected_lora_names,
)

logger = logging.getLogger(__name__)

_cache_lock = threading.Lock()
_object_info_cache: Dict[str, Dict[str, Any]] = {}
_OBJECT_INFO_TTL = 15.0


def invalidate_ltx_capability_cache(comfy_url: Optional[str] = None) -> None:
    """Invalidate one native ComfyUI identity or the complete cache."""
    with _cache_lock:
        if comfy_url:
            _object_info_cache.pop(comfy_url.rstrip("/"), None)
        else:
            _object_info_cache.clear()


class LTXDirectorService:
    def __init__(self, comfy_url: Optional[str] = None):
        try:
            from backend.config import COMFYUI_URL
        except Exception:
            COMFYUI_URL = os.environ.get("GUAARDVARK_COMFYUI_URL", "http://127.0.0.1:8188")
        self.comfy_url = (comfy_url or COMFYUI_URL).rstrip("/")
        self.transport = ComfyUIVideoGenerator()

    def object_info(self, *, force: bool = False) -> Dict[str, Any]:
        key = self.comfy_url
        now = time.monotonic()
        with _cache_lock:
            cached = _object_info_cache.get(key)
            if cached and not force and now - cached["time"] < _OBJECT_INFO_TTL:
                return cached["value"]
        try:
            response = requests.get(f"{key}/object_info", timeout=10)
            response.raise_for_status()
            value = response.json()
        except Exception as exc:
            logger.warning("LTX object_info probe failed for %s: %s", key, exc)
            value = {}
        with _cache_lock:
            _object_info_cache[key] = {"time": now, "value": value}
        return value

    @staticmethod
    def _required_models(model_id: str, config: Optional[LTXDirectorConfig] = None) -> list[str]:
        required = [
            model_id,
            "ltx23-video-vae",
            "ltx23-audio-vae",
            "ltx23-text-encoder",
            "ltx23-text-projection",
        ]
        if config is None or config.pass2.get("enabled", True):
            required.append("ltx23-spatial-upscaler")
        if config and config.distilled_lora:
            required.append("ltx23-distilled-lora")
        if config and config.bodyphysics_lora:
            required.append("ltx23-bodyphysics-lora")
        if config and config.temporal_upscale:
            required.append("ltx23-temporal-upscaler")
        # Preserve order while removing duplicates.
        return list(dict.fromkeys(required))

    def readiness(
        self,
        model_id: str = "ltx23-dasiwa-dragonleap-v4",
        *,
        force: bool = False,
        config: Optional[LTXDirectorConfig] = None,
    ) -> Dict[str, Any]:
        object_info = self.object_info(force=force)
        nodes = capability_report(object_info)
        lora_choices = available_lora_choices(object_info)
        required_models = self._required_models(model_id, config)
        missing_models = [item for item in required_models if not is_model_installed(item)]
        return {
            **nodes,
            "ready": nodes["ready"] and not missing_models,
            "model_id": model_id,
            "required_models": required_models,
            "missing_models": missing_models,
            "available_loras": lora_choices,
            "lora_limit": 12,
            "restart_required": False,
            "custom_node_setup": [
                {"name": "WhatDreamsCost ComfyUI", "url": "https://github.com/WhatDreamsCost/WhatDreamsCost-ComfyUI", "provides": ["LTXDirector", "LTXDirectorGuide", "LTXDirectorCropGuides"]},
                {"name": "ComfyUI-LTXVideo", "url": "https://github.com/Lightricks/ComfyUI-LTXVideo", "provides": ["LTXVConditioning", "LTXVLatentUpsampler", "LTXVAudioVAEDecode"]},
                {"name": "ComfyUI-KJNodes", "url": "https://github.com/kijai/ComfyUI-KJNodes", "provides": ["VAELoaderKJ", "LTX2SamplingPreviewOverride"]},
                {"name": "ComfyUI-VideoHelperSuite", "url": "https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite", "provides": ["VHS_VideoCombine"]},
                {"name": "ComfyUI-DaSiWa-Nodes", "url": "https://github.com/darksidewalker/ComfyUI-DaSiWa-Nodes", "provides": ["DaSiWa_LTX2LoraLoader", "DaSiWa_RTX_UpscalerRefiner"]},
            ],
        }

    def _upload(self, path: Optional[str]) -> Optional[str]:
        if not path:
            return None
        candidate = Path(path)
        if not candidate.exists() or not candidate.is_file():
            raise LTXWorkflowError(f"Source file does not exist: {path}")
        with candidate.open("rb") as handle:
            response = requests.post(
                f"{self.comfy_url}/upload/image",
                files={"image": (candidate.name, handle)},
                data={"type": "input", "overwrite": "true"},
                timeout=120,
            )
        response.raise_for_status()
        uploaded = response.json()
        name = uploaded.get("name")
        subfolder = uploaded.get("subfolder") or ""
        return f"{subfolder}/{name}".strip("/")

    def validate_config(self, raw_config: Mapping[str, Any]) -> tuple[LTXDirectorConfig, Dict[str, Any]]:
        config = LTXDirectorConfig.from_dict(raw_config)
        config.validate()
        report = self.readiness(config.model_id, config=config)
        if not report["ready"]:
            parts = []
            if report["missing_models"]:
                parts.append("missing models: " + ", ".join(report["missing_models"]))
            if report["missing_nodes"]:
                parts.append("missing ComfyUI nodes: " + ", ".join(report["missing_nodes"]))
            if report["incompatible_nodes"]:
                parts.append("incompatible node schemas: " + ", ".join(item["class_type"] for item in report["incompatible_nodes"]))
            raise LTXWorkflowError("LTX Director is not ready; " + "; ".join(parts))
        object_info = self.object_info()
        missing_optional = [class_type for class_type in enabled_optional_classes(config) if class_type not in object_info]
        if missing_optional:
            raise LTXWorkflowError("Enabled options require unavailable ComfyUI nodes: " + ", ".join(missing_optional))

        # The DaSiWa node publishes its installed LoRA list through object_info.
        # Canonicalize separator spelling and reject stale/missing selections
        # before a long render reaches the node. Older node builds that do not
        # expose the list remain usable, but the selector will say unavailable.
        lora_choices = available_lora_choices(object_info)
        canonicalize_config_loras(config, lora_choices)
        if lora_choices:
            allowed = {normalize_lora_name(item) for item in lora_choices}
            unavailable = [
                name for name in selected_lora_names(config)
                if normalize_lora_name(name) not in allowed
            ]
            if unavailable:
                raise LTXWorkflowError(
                    "Selected LoRA files are not reported by ComfyUI: " + ", ".join(unavailable)
                )
        return config, report

    def generate(self, raw_config: Mapping[str, Any], *, output_dir: Path, batch_id: str, cancel_event=None) -> VideoGenerationResult:
        try:
            config, _ = self.validate_config(raw_config)
            config.source_image = self._upload(config.source_image)
            config.last_frame = self._upload(config.last_frame)
            config.source_video = self._upload(config.source_video)
            config.uploaded_audio = self._upload(config.uploaded_audio)
            workflow = build_ltx23_workflow(config)
            client_id = str(uuid.uuid4())
            bridge = ComfyUIProgressBridge()
            bridge.start(client_id, batch_id, self.comfy_url, workflow, extra={"batch_id": batch_id, "engine": "ltx-director"})
            try:
                prompt_id = self.transport._queue_prompt(workflow, client_id=client_id)
                if not prompt_id:
                    return VideoGenerationResult(False, prompt_used=config.prompt, error="ComfyUI rejected the LTX Director workflow")
                outputs = self.transport._wait_for_completion(prompt_id, timeout=7200, cancel_event=cancel_event)
            finally:
                bridge.stop()
            if outputs and outputs.get("_cancelled_by_event"):
                self.transport.interrupt()
                return VideoGenerationResult(False, prompt_used=config.prompt, error="cancelled")
            if not outputs:
                return VideoGenerationResult(False, prompt_used=config.prompt, error="LTX Director timed out or returned no history")
            output_dir.mkdir(parents=True, exist_ok=True)
            paths = self.transport._download_result(outputs, output_dir)
            videos = [path for path in paths if Path(path).suffix.lower() in {".mp4", ".webm", ".mov", ".mkv"}]
            if not videos:
                return VideoGenerationResult(False, prompt_used=config.prompt, error="LTX Director completed without a video output")
            return VideoGenerationResult(
                True,
                prompt_used=config.prompt,
                video_path=videos[0],
                metadata={
                    "engine": "ltx-director", "mode": config.mode,
                    "prompt_id": prompt_id, "total_frames": str(config.total_frames),
                },
            )
        except Exception as exc:
            logger.error("LTX Director generation failed: %s", exc, exc_info=True)
            return VideoGenerationResult(False, prompt_used=str(raw_config.get("prompt", "")), error=str(exc))


_service: Optional[LTXDirectorService] = None


def get_ltx_director_service() -> LTXDirectorService:
    global _service
    if _service is None:
        _service = LTXDirectorService()
    return _service
