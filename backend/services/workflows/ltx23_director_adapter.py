"""Semantic-role adapter for the DaSiWa LTX 2.3 OmniForge workflow.

The uploaded source is a ComfyUI UI workflow with nested subgraphs.  Runtime
code never edits its numeric node ids.  This adapter emits a plain API prompt
whose nodes carry stable ``GUAARDVARK_LTX_*`` titles and validates the installed
node schemas before submission.  Optional features are either wired here or
reported as unavailable by :func:`capability_report`; they are never ignored.
"""

from __future__ import annotations

import copy
import json
import math
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional


REQUIRED_NODE_SCHEMAS: Dict[str, set[str]] = {
    # ``timeline_data`` is the serialized UI-track payload.  Older versions of
    # WhatDreamsCost exposed the timeline only as an opaque widget; those builds
    # are intentionally rejected because API submissions would drop sources.
    "LTXDirector": {"model", "clip", "audio_vae", "global_prompt", "timeline_data"},
    "LTXDirectorGuide": {
        "positive", "negative", "vae", "latent", "guide_data",
        "motion_guide_data", "model",
    },
    "LTXDirectorCropGuides": {"positive", "negative", "latent"},
    "LTXVConditioning": {"positive", "negative", "frame_rate"},
    "LTXVAddGuide": {"positive", "negative", "vae", "latent", "image", "frame_idx", "strength"},
    "LoadImage": {"image"},
    "LTXVLatentUpsampler": {"samples", "upscale_model", "vae"},
    "LTXVConcatAVLatent": {"video_latent", "audio_latent"},
    "LTXVSeparateAVLatent": {"av_latent"},
    "LTXVAudioVAEDecode": {"samples", "audio_vae"},
    "VHS_VideoCombine": {"images", "frame_rate", "filename_prefix", "format"},
}

OPTIONAL_NODE_SCHEMAS: Dict[str, set[str]] = {
    "LTXVSpatioTemporalTiledVAEDecode": {
        "vae", "latents", "spatial_tiles", "spatial_overlap",
        "temporal_tile_length", "temporal_overlap", "last_frame_fix",
        "working_device", "working_dtype",
    },
    "LTXVChunkFeedForward": {"model", "chunks", "dim_threshold"},
    "ModelPatchTorchSettings": {"model"},
    "LTX2_NAG": {"model", "nag_scale", "nag_alpha", "nag_tau"},
    "PathchSageAttentionKJ": {"model", "sage_attention"},
    "LTX2MemoryEfficientSageAttentionPatch": {"model", "triton_kernels"},
    "ColorTransfer": {"image_target", "image_ref"},
    "ImageScaleBy": {"image", "upscale_method", "scale_by"},
    "UpscaleWithModelAdvanced": {"image", "upscale_model"},
    "DaSiWa_RTX_UpscalerRefiner": {"images"},
    "DaSiWa_Watermark": {"images", "watermark_path"},
    "DaSiWa_LTX2LoraLoader": {"model", "clip", "stack_data"},
}

SUPPORTED_MODES = {"t2v", "i2v", "flf2v", "v2v"}
SUPPORTED_AUDIO = {"generated", "uploaded", "source", "none"}
SUPPORTED_FORMATS = {"video/h264-mp4", "video/h265-mp4", "video/webm", "video/av1-webm"}


class LTXWorkflowError(ValueError):
    """A user-actionable LTX workflow validation error."""


@dataclass
class LTXDirectorConfig:
    mode: str = "i2v"
    prompt: str = ""
    negative_prompt: str = ""
    model_id: str = "ltx23-dasiwa-dragonleap-v4"
    model_name: str = "LTX2/DasiwaLTX23_dragonleapV4.safetensors"
    model_format: str = "safetensors"
    text_encoder: str = "gemma-3-12b-it-heretic-v2_fp8_e4m3fn.safetensors"
    text_projection: str = "ltx-2.3_text_projection_bf16.safetensors"
    video_vae: str = "LTX2/LTX23_video_vae_bf16.safetensors"
    audio_vae: str = "LTX2/LTX23_audio_vae_bf16.safetensors"
    preview_vae: str = "LTX2/taeltx2_3.safetensors"
    spatial_upscaler: str = "ltx-2.3-spatial-upscaler-x2-1.1.safetensors"
    temporal_upscaler: str = "ltx-2.3-temporal-upscaler-x2-1.0.safetensors"
    source_image: Optional[str] = None
    last_frame: Optional[str] = None
    source_video: Optional[str] = None
    audio_source: str = "generated"
    uploaded_audio: Optional[str] = None
    width: int = 576
    height: int = 896
    fps: int = 24
    duration_seconds: float = 8.0
    aspect_ratio: str = "9:16"
    seed: int = 42
    resize_method: str = "maintain aspect ratio"
    guide_strength: float = 1.0
    motion_guide_strength: float = 1.0
    timeline_segments: List[Dict[str, Any]] = field(default_factory=list)
    motion_segments: List[Dict[str, Any]] = field(default_factory=list)
    audio_segments: List[Dict[str, Any]] = field(default_factory=list)
    # Distilled and Bodyphysics are separate LoRAs with different jobs.  The
    # source OmniForge graph applies the distilled LoRA model-only; DaSiWa's
    # Bodyphysics enhancer rides the model+CLIP stack.
    distilled_lora: bool = False
    distilled_lora_name: str = "LTX/ltx-2.3-22b-distilled-lora-1.1_fro90_ceil72_condsafe.safetensors"
    distilled_lora_strength: float = 0.5
    bodyphysics_lora: bool = False
    bodyphysics_lora_name: str = "LTX/DaSiWa_LTX23_NSFW_Bodyphysics_Fluid_Motion_Enhancer_v01.safetensors"
    bodyphysics_lora_strength: float = 0.5
    loras: List[Dict[str, Any]] = field(default_factory=list)
    sampler: str = "euler_cfg_pp"
    pass1: Dict[str, Any] = field(default_factory=lambda: {"enabled": True, "cfg": 1.0, "steps": 10, "scheduler": "linear_quadratic", "denoise": 1.0})
    pass2: Dict[str, Any] = field(default_factory=lambda: {"enabled": True, "cfg": 1.0, "steps": 4, "scheduler": "linear_quadratic", "denoise": 0.3})
    pass3: Dict[str, Any] = field(default_factory=lambda: {"enabled": False, "cfg": 1.0, "steps": 2, "scheduler": "linear_quadratic", "denoise": 0.2})
    chunking: bool = False
    chunk_count: int = 2
    chunk_dim_threshold: int = 4096
    vram_headroom: float = 2.0
    fp16_accumulation: bool = False
    # off | patch | memory_efficient
    # The installed SageAttention build cannot service this RTX 4070/CUDA
    # combination reliably; keep the safe PyTorch attention path as default.
    sage_attention: str = "off"
    sage_kernel: str = "auto"
    sage_allow_compile: bool = False
    sage_triton_kernels: bool = True
    nag: Dict[str, Any] = field(default_factory=lambda: {"enabled": False, "scale": 11.0, "alpha": 0.25, "tau": 2.5, "inplace": True})
    tiled_vae: bool = False
    tiled_spatial_tiles: int = 4
    tiled_spatial_overlap: int = 4
    tiled_temporal_tile_length: int = 32
    tiled_temporal_overlap: int = 8
    tiled_last_frame_fix: bool = False
    tiled_working_device: str = "auto"
    tiled_working_dtype: str = "auto"
    # Kept only so old saved ui_config payloads still deserialize harmlessly.
    tile_size: int = 512
    temporal_upscale: bool = False
    simple_upscale: bool = False
    simple_upscale_factor: float = 2.0
    model_upscale: bool = False
    upscale_model: Optional[str] = None
    rtx: Dict[str, Any] = field(default_factory=lambda: {"enabled": False, "scale": 2.0, "quality": "Ultra"})
    color_transfer: Dict[str, Any] = field(default_factory=lambda: {"enabled": False, "method": "reinhard_lab", "strength": 0.75})
    watermark: Dict[str, Any] = field(default_factory=lambda: {"enabled": False, "path": None, "position": "top-left", "scale": 0.12, "opacity": 0.35})
    soundmark: Dict[str, Any] = field(default_factory=lambda: {"enabled": False, "path": None})
    output_format: str = "video/h264-mp4"
    crf: int = 19
    pix_fmt: str = "yuv420p"
    save_metadata: bool = True

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "LTXDirectorConfig":
        migrated = dict(raw)
        # Backward-compatible migrations for snapshots saved by the first LTX UI.
        if migrated.get("output_format") == "video/vp9-webm":
            migrated["output_format"] = "video/webm"
        allowed = cls.__dataclass_fields__.keys()
        return cls(**{key: copy.deepcopy(value) for key, value in migrated.items() if key in allowed})

    @property
    def total_frames(self) -> int:
        # LTX latents are most reliable at 8n frames.  Keep the requested duration
        # but align the final frame count like the source Director node does.
        requested = max(1, round(self.duration_seconds * self.fps))
        return max(8, ((requested + 7) // 8) * 8)

    def validate(self) -> None:
        errors: List[str] = []
        if self.mode not in SUPPORTED_MODES:
            errors.append(f"mode must be one of {sorted(SUPPORTED_MODES)}")
        if self.audio_source not in SUPPORTED_AUDIO:
            errors.append(f"audio_source must be one of {sorted(SUPPORTED_AUDIO)}")
        if not self.prompt.strip():
            errors.append("prompt is required")
        if self.mode in {"i2v", "flf2v"} and not self.source_image:
            errors.append(f"{self.mode.upper()} requires a source image")
        if self.mode == "flf2v" and not self.last_frame:
            errors.append("FLF2V requires a last-frame image")
        if self.mode == "v2v" and not self.source_video:
            errors.append("V2V requires a source video")
        if self.audio_source == "uploaded" and not self.uploaded_audio:
            errors.append("uploaded audio mode requires an audio file")
        if self.audio_source == "source" and self.mode != "v2v":
            errors.append("source-video audio is only available in V2V mode")
        # OmniForge's resolution calculator uses its custom divisor=8 even
        # though the internal LTX latent stages snap where needed.
        if self.width < 256 or self.height < 256 or self.width % 8 or self.height % 8:
            errors.append("width and height must be at least 256 and divisible by 8")
        if not 1 <= self.fps <= 60:
            errors.append("fps must be between 1 and 60")
        if self.aspect_ratio not in {"16:9", "9:16", "1:1", "4:3", "3:4", "custom"}:
            errors.append("aspect_ratio must be a supported preset or custom")
        if not 0.5 <= self.duration_seconds <= 120:
            errors.append("duration_seconds must be between 0.5 and 120")
        if self.output_format not in SUPPORTED_FORMATS:
            errors.append(f"unsupported output format: {self.output_format}")
        if self.sage_attention not in {"off", "patch", "memory_efficient"}:
            errors.append("sage_attention must be off, patch, or memory_efficient")
        if self.chunking and not 1 <= int(self.chunk_count) <= 100:
            errors.append("chunk_count must be between 1 and 100")
        if self.chunking and not 0 <= int(self.chunk_dim_threshold) <= 16384:
            errors.append("chunk_dim_threshold must be between 0 and 16384")
        if self.tiled_vae:
            if not 1 <= int(self.tiled_spatial_tiles) <= 8:
                errors.append("tiled_spatial_tiles must be between 1 and 8")
            if not 0 <= int(self.tiled_spatial_overlap) <= 8:
                errors.append("tiled_spatial_overlap must be between 0 and 8")
            if not 2 <= int(self.tiled_temporal_tile_length) <= 1000:
                errors.append("tiled_temporal_tile_length must be between 2 and 1000")
            if not 0 <= int(self.tiled_temporal_overlap) <= 8:
                errors.append("tiled_temporal_overlap must be between 0 and 8")
            if self.tiled_working_device not in {"auto", "cpu"}:
                errors.append("tiled_working_device must be auto or cpu")
            if self.tiled_working_dtype not in {"auto", "float16", "float32"}:
                errors.append("tiled_working_dtype must be auto, float16, or float32")
        if not isinstance(self.loras, list):
            errors.append("loras must be a list")
        else:
            reserved = int(bool(self.distilled_lora)) + int(bool(self.bodyphysics_lora))
            if reserved + len(self.loras) > 12:
                errors.append("the DaSiWa LTX LoRA stack supports at most 12 total slots")
            for index, item in enumerate(self.loras):
                if not isinstance(item, Mapping):
                    errors.append(f"loras[{index}] must be an object")
                    continue
                name = item.get("name") or item.get("lora")
                if not name or normalize_lora_name(name) == "none":
                    errors.append(f"loras[{index}] must select a LoRA file")
                for field_name in ("strength", "video_strength", "audio_strength"):
                    try:
                        value = float(item.get(field_name, 1.0))
                        if not math.isfinite(value):
                            raise ValueError
                    except (TypeError, ValueError):
                        errors.append(f"loras[{index}].{field_name} must be a finite number")
        for name, settings in (("pass1", self.pass1), ("pass2", self.pass2), ("pass3", self.pass3)):
            if settings.get("enabled") and int(settings.get("steps", 0)) < 1:
                errors.append(f"{name} steps must be at least 1")
            denoise = float(settings.get("denoise", 0))
            if not 0 < denoise <= 1:
                errors.append(f"{name} denoise must be greater than 0 and at most 1")
        if not self.pass1.get("enabled", True):
            errors.append("the first sampling pass cannot be disabled")
        if self.pass3.get("enabled") and not self.pass2.get("enabled"):
            errors.append("third pass requires the second pass")
        if errors:
            raise LTXWorkflowError("; ".join(errors))


def _schema_input_names(node_info: Mapping[str, Any]) -> set[str]:
    inputs = node_info.get("input") or {}
    names: set[str] = set()
    for group in ("required", "optional", "hidden"):
        values = inputs.get(group) or {}
        if isinstance(values, Mapping):
            names.update(values.keys())
    return names


def capability_report(object_info: Mapping[str, Any]) -> Dict[str, Any]:
    missing: List[str] = []
    incompatible: List[Dict[str, Any]] = []
    for class_type, expected in REQUIRED_NODE_SCHEMAS.items():
        info = object_info.get(class_type)
        if not info:
            missing.append(class_type)
            continue
        actual = _schema_input_names(info)
        absent = sorted(expected - actual)
        if absent:
            incompatible.append({"class_type": class_type, "missing_inputs": absent})
    optional: Dict[str, bool] = {}
    optional_incompatible: List[Dict[str, Any]] = []
    for class_type, expected in OPTIONAL_NODE_SCHEMAS.items():
        info = object_info.get(class_type)
        if not info:
            optional[class_type] = False
            continue
        absent = sorted(expected - _schema_input_names(info))
        optional[class_type] = not absent
        if absent:
            optional_incompatible.append({"class_type": class_type, "missing_inputs": absent})
    return {
        "ready": not missing and not incompatible,
        "missing_nodes": missing,
        "incompatible_nodes": incompatible,
        "optional_features": optional,
        "optional_incompatible_nodes": optional_incompatible,
        "nodes_2_beta_warning": "The source workflow is incompatible with ComfyUI Nodes 2.0 beta.",
    }


def normalize_lora_name(value: Any) -> str:
    """Normalize Windows/Unix separators for comparisons without changing payload spelling."""
    return str(value or "").strip().replace("\\", "/").lower()


def available_lora_choices(object_info: Mapping[str, Any]) -> List[str]:
    """Read the live DaSiWa LoRA picker choices from ComfyUI ``object_info``.

    The node exposes its files as a hidden ``available_loras`` enum.  Returning
    the exact runtime spelling lets the frontend submit values ComfyUI already
    recognizes, while duplicate separator variants are collapsed.
    """
    node = object_info.get("DaSiWa_LTX2LoraLoader") or {}
    hidden = ((node.get("input") or {}).get("hidden") or {})
    spec = hidden.get("available_loras")
    choices: List[Any] = []
    if isinstance(spec, list) and spec:
        if isinstance(spec[0], list):
            choices = spec[0]
        elif all(isinstance(item, str) for item in spec):
            choices = spec
    out: List[str] = []
    seen: set[str] = set()
    for item in choices:
        if not isinstance(item, str):
            continue
        key = normalize_lora_name(item)
        if not key or key == "none" or key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def canonicalize_config_loras(config: "LTXDirectorConfig", choices: Iterable[str]) -> None:
    """Rewrite configured LoRA paths to the exact spelling reported by ComfyUI."""
    canonical = {normalize_lora_name(item): item for item in choices}
    if not canonical:
        return
    config.distilled_lora_name = canonical.get(
        normalize_lora_name(config.distilled_lora_name), config.distilled_lora_name
    )
    config.bodyphysics_lora_name = canonical.get(
        normalize_lora_name(config.bodyphysics_lora_name), config.bodyphysics_lora_name
    )
    for item in config.loras:
        if isinstance(item, dict):
            name = item.get("name") or item.get("lora")
            exact = canonical.get(normalize_lora_name(name))
            if exact:
                item["name"] = exact


def selected_lora_names(config: "LTXDirectorConfig") -> List[str]:
    names: List[str] = []
    if config.distilled_lora:
        names.append(config.distilled_lora_name)
    if config.bodyphysics_lora:
        names.append(config.bodyphysics_lora_name)
    for item in config.loras:
        if isinstance(item, Mapping) and item.get("enabled", True):
            name = item.get("name") or item.get("lora")
            if name and normalize_lora_name(name) != "none":
                names.append(str(name))
    return names


def _node(role: str, class_type: str, inputs: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "class_type": class_type,
        "inputs": dict(inputs),
        "_meta": {"title": f"GUAARDVARK_LTX_{role}"},
    }


def find_role(workflow: Mapping[str, Any], role: str) -> str:
    title = f"GUAARDVARK_LTX_{role}"
    matches = [node_id for node_id, node in workflow.items() if (node.get("_meta") or {}).get("title") == title]
    if len(matches) != 1:
        raise LTXWorkflowError(f"Expected exactly one semantic patch role {title}; found {len(matches)}")
    return matches[0]


def _timeline_payload(config: LTXDirectorConfig) -> str:
    return json.dumps({
        "version": 1,
        "mode": config.mode,
        "mainTrackEnabled": True,
        "audioTrackEnabled": config.audio_source != "none",
        "motionTrackEnabled": True,
        "motionGuideStrength": config.motion_guide_strength,
        "overrideAudio": config.audio_source in {"uploaded", "source"},
        "inpaint_audio": config.audio_source == "generated",
        "global_prompt": config.prompt,
        "normalStartFrame": 0,
        "normalDurationFrames": config.total_frames,
        "segments": config.timeline_segments,
        "motionSegments": config.motion_segments,
        "audioSegments": config.audio_segments,
        "sources": {
            "image": config.source_image,
            "last_frame": config.last_frame,
            "video": config.source_video,
            "audio": config.uploaded_audio,
        },
    }, separators=(",", ":"))


def build_ltx23_workflow(config: LTXDirectorConfig) -> Dict[str, Any]:
    """Build the stable core API prompt using semantic ids and titles.

    Post-processing nodes are appended only when enabled.  Capability validation
    happens before this workflow is submitted, so unsupported switches are
    rejected with a precise node/schema explanation.
    """
    config.validate()
    w: Dict[str, Any] = {}
    model_loader = "UnetLoaderGGUF" if config.model_format == "gguf" else "UNETLoader"
    # Do not allow stale persisted UI state to submit the experimental Sage
    # patch when the installed package lacks KJNodes' required API. This keeps
    # a previously saved "memory_efficient" setting from crashing the render.
    # The workflow is submitted from WSL to native Windows ComfyUI. A Sage
    # import check in WSL is not proof that the Windows ComfyUI environment has
    # the required kernels, so never submit this experimental patch until the
    # native runtime has been explicitly validated.
    config.sage_attention = "off"

    # Registry paths are slash-separated, while ComfyUI's Windows API
    # enumerates model choices with backslashes. Normalize at submission time.
    def _asset_path(value: str) -> str:
        return str(value or "").replace("/", "\\")

    model_input = "unet_name"
    w["model"] = _node("MODEL", model_loader, {model_input: _asset_path(config.model_name), **({"weight_dtype": "default"} if model_loader == "UNETLoader" else {})})
    w["clip"] = _node("TEXT_ENCODERS", "DualCLIPLoader", {
        "clip_name1": config.text_encoder, "clip_name2": config.text_projection,
        "type": "ltxv", "device": "default",
    })
    w["video_vae"] = _node("VIDEO_VAE", "VAELoader", {"vae_name": _asset_path(config.video_vae)})
    w["audio_vae"] = _node("AUDIO_VAE", "VAELoader", {"vae_name": _asset_path(config.audio_vae)})
    w["preview_vae"] = _node("PREVIEW_VAE", "VAELoader", {"vae_name": _asset_path(config.preview_vae)})
    model_ref: List[Any] = ["model", 0]

    # Runtime patches are real graph nodes, not capability-only decorations.
    if config.chunking:
        w["chunk_ff"] = _node("CHUNK_FEED_FORWARD", "LTXVChunkFeedForward", {
            "model": model_ref,
            "chunks": int(config.chunk_count),
            "dim_threshold": int(config.chunk_dim_threshold),
        })
        model_ref = ["chunk_ff", 0]

    if config.sage_attention == "patch":
        w["sage_patch"] = _node("SAGE_ATTENTION", "PathchSageAttentionKJ", {
            "model": model_ref,
            "sage_attention": config.sage_kernel,
            "allow_compile": bool(config.sage_allow_compile),
        })
        model_ref = ["sage_patch", 0]
    elif config.sage_attention == "memory_efficient":
        w["sage_memory"] = _node("SAGE_ATTENTION", "LTX2MemoryEfficientSageAttentionPatch", {
            "model": model_ref,
            "triton_kernels": bool(config.sage_triton_kernels),
        })
        model_ref = ["sage_memory", 0]

    if config.nag.get("enabled"):
        w["nag"] = _node("NAG", "LTX2_NAG", {
            "model": model_ref,
            "nag_scale": float(config.nag.get("scale", 11.0)),
            "nag_alpha": float(config.nag.get("alpha", 0.25)),
            "nag_tau": float(config.nag.get("tau", 2.5)),
            "inplace": bool(config.nag.get("inplace", True)),
        })
        model_ref = ["nag", 0]

    # The uploaded OmniForge graph has one real multi-slot LoRA node.  Feed
    # Distilled, Bodyphysics, and user-selected LoRAs through that same stack
    # rather than inventing a separate model-only loader that may not exist.
    stack: List[Dict[str, Any]] = []
    seen_loras: set[str] = set()

    def append_lora(name: Any, *, enabled: bool, strength: Any, video: Any = 1.0, audio: Any = 1.0) -> None:
        key = normalize_lora_name(name)
        if not key or key == "none" or key in seen_loras or len(stack) >= 12:
            return
        seen_loras.add(key)
        stack.append({
            "on": bool(enabled),
            "lora": str(name),
            "str": float(strength),
            "vs": float(video),
            "as": float(audio),
        })

    if config.distilled_lora:
        append_lora(
            config.distilled_lora_name, enabled=True,
            strength=config.distilled_lora_strength,
        )
    if config.bodyphysics_lora:
        append_lora(
            config.bodyphysics_lora_name, enabled=True,
            strength=config.bodyphysics_lora_strength,
        )
    for item in config.loras:
        append_lora(
            item.get("name") or item.get("lora"),
            enabled=item.get("enabled", True),
            strength=item.get("strength", 1.0),
            video=item.get("video_strength", 1.0),
            audio=item.get("audio_strength", 1.0),
        )

    if stack:
        # Match the source node's fixed 12-slot UI payload. Empty slots are
        # explicit ``None`` entries so the API path and graph path agree.
        while len(stack) < 12:
            stack.append({"on": True, "lora": "None", "str": 1.0, "vs": 1.0, "as": 1.0})
        w["lora_stack"] = _node("LORA_STACK", "DaSiWa_LTX2LoraLoader", {
            "model": model_ref, "clip": ["clip", 0], "stack_data": json.dumps(stack),
        })
        model_ref = ["lora_stack", 0]
        clip_ref: List[Any] = ["lora_stack", 1]
    else:
        clip_ref = ["clip", 0]
    w["director"] = _node("DIRECTOR", "LTXDirector", {
        "model": model_ref, "clip": clip_ref, "audio_vae": ["audio_vae", 0],
        "global_prompt": config.prompt, "frame_rate": config.fps,
        "custom_width": config.width, "custom_height": config.height,
        "resize_method": config.resize_method, "start_second": 0.0,
        "end_second": config.duration_seconds, "duration_seconds": config.duration_seconds,
        "start_frame": 0, "end_frame": config.total_frames,
        "duration_frames": config.total_frames,
        "timeline_data": _timeline_payload(config),
        "local_prompts": config.prompt,
        # LTXDirector parses this hidden STRING as comma-separated numbers;
        # JSON list syntax ("[48]") reaches float() and crashes at runtime.
        "segment_lengths": str(config.total_frames),
        "epsilon": 0.001,
        "guide_strength": str(config.guide_strength),
        "use_custom_audio": config.audio_source in {"uploaded", "source"},
        "use_custom_motion": bool(config.motion_segments),
        "inpaint_audio": config.audio_source == "generated",
        "display_mode": "seconds", "divisible_by": 8,
        "img_compression": 18,
        "override_audio": config.audio_source in {"uploaded", "source"},
    })
    w["negative"] = _node("NEGATIVE", "CLIPTextEncode", {"clip": clip_ref, "text": config.negative_prompt})
    w["conditioning"] = _node("CONDITIONING", "LTXVConditioning", {
        "positive": ["director", 1], "negative": ["negative", 0], "frame_rate": ["director", 6],
    })
    # The timeline JSON records source references for the Director editor, but
    # it is not itself an IMAGE/LATENT input.  Explicit guide nodes are
    # required for API-mode I2V/FLF2V submissions; without them ComfyUI can
    # legally run the empty latent branch and ignore the uploaded image.
    guide_positive: List[Any] = ["conditioning", 0]
    guide_negative: List[Any] = ["conditioning", 1]
    guide_latent: List[Any] = ["director", 2]
    if config.mode in {"i2v", "flf2v"} and config.source_image:
        w["source_image"] = _node("SOURCE_IMAGE", "LoadImage", {"image": _asset_path(config.source_image)})
        w["source_guide"] = _node("SOURCE_GUIDE", "LTXVAddGuide", {
            "positive": guide_positive, "negative": guide_negative,
            "vae": ["video_vae", 0], "latent": guide_latent,
            "image": ["source_image", 0], "frame_idx": 0,
            "strength": float(config.guide_strength),
        })
        guide_positive, guide_negative, guide_latent = ["source_guide", 0], ["source_guide", 1], ["source_guide", 2]
    if config.mode == "flf2v" and config.last_frame:
        w["last_frame"] = _node("LAST_FRAME", "LoadImage", {"image": _asset_path(config.last_frame)})
        w["last_guide"] = _node("LAST_GUIDE", "LTXVAddGuide", {
            "positive": guide_positive, "negative": guide_negative,
            "vae": ["video_vae", 0], "latent": guide_latent,
            "image": ["last_frame", 0], "frame_idx": max(0, config.total_frames - 1),
            "strength": float(config.guide_strength),
        })
        guide_positive, guide_negative, guide_latent = ["last_guide", 0], ["last_guide", 1], ["last_guide", 2]
    w["guide1"] = _node("GUIDE_PASS1", "LTXDirectorGuide", {
        "positive": guide_positive, "negative": guide_negative,
        "vae": ["video_vae", 0], "latent": guide_latent,
        "guide_data": ["director", 4], "motion_guide_data": ["director", 5],
        "model": ["director", 0]
    })
    w["noise"] = _node("NOISE", "RandomNoise", {"noise_seed": config.seed})
    w["sampler"] = _node("SAMPLER", "KSamplerSelect", {"sampler_name": config.sampler})
    w["cfg1"] = _node("CFG_PASS1", "CFGGuider", {"model": ["guide1", 3], "positive": ["guide1", 0], "negative": ["guide1", 1], "cfg": float(config.pass1["cfg"])})
    w["scheduler1"] = _node("SCHEDULER_PASS1", "BasicScheduler", {"model": ["guide1", 3], "scheduler": config.pass1["scheduler"], "steps": int(config.pass1["steps"]), "denoise": float(config.pass1["denoise"])})
    w["av1"] = _node("AV_PASS1", "LTXVConcatAVLatent", {"video_latent": ["guide1", 2], "audio_latent": ["director", 3]})
    w["sample1"] = _node("SAMPLE_PASS1", "SamplerCustomAdvanced", {"noise": ["noise", 0], "guider": ["cfg1", 0], "sampler": ["sampler", 0], "sigmas": ["scheduler1", 0], "latent_image": ["av1", 0]})
    w["split1"] = _node("SPLIT_PASS1", "LTXVSeparateAVLatent", {"av_latent": ["sample1", 0]})
    video_ref: List[Any] = ["split1", 0]
    audio_ref: List[Any] = ["split1", 1]
    if config.pass2.get("enabled"):
        w["spatial_model"] = _node("SPATIAL_UPSCALER", "LatentUpscaleModelLoader", {"model_name": config.spatial_upscaler})
        w["spatial"] = _node("SPATIAL_UPSCALE", "LTXVLatentUpsampler", {"samples": video_ref, "upscale_model": ["spatial_model", 0], "vae": ["video_vae", 0]})
        w["guide2"] = _node("GUIDE_PASS2", "LTXDirectorGuide", {"positive": ["guide1", 0], "negative": ["guide1", 1], "vae": ["video_vae", 0], "latent": ["spatial", 0], "guide_data": ["director", 4], "motion_guide_data": ["director", 5], "model": ["director", 0]})
        w["cfg2"] = _node("CFG_PASS2", "CFGGuider", {"model": ["guide2", 3], "positive": ["guide2", 0], "negative": ["guide2", 1], "cfg": float(config.pass2["cfg"])})
        w["scheduler2"] = _node("SCHEDULER_PASS2", "BasicScheduler", {"model": ["guide2", 3], "scheduler": config.pass2["scheduler"], "steps": int(config.pass2["steps"]), "denoise": float(config.pass2["denoise"])})
        w["av2"] = _node("AV_PASS2", "LTXVConcatAVLatent", {"video_latent": ["guide2", 2], "audio_latent": audio_ref})
        w["sample2"] = _node("SAMPLE_PASS2", "SamplerCustomAdvanced", {"noise": ["noise", 0], "guider": ["cfg2", 0], "sampler": ["sampler", 0], "sigmas": ["scheduler2", 0], "latent_image": ["av2", 0]})
        w["split2"] = _node("SPLIT_PASS2", "LTXVSeparateAVLatent", {"av_latent": ["sample2", 0]})
        video_ref, audio_ref = ["split2", 0], ["split2", 1]
    if config.pass3.get("enabled"):
        w["guide3"] = _node("GUIDE_PASS3", "LTXDirectorGuide", {"positive": ["guide1", 0], "negative": ["guide1", 1], "vae": ["video_vae", 0], "latent": video_ref, "guide_data": ["director", 4], "motion_guide_data": ["director", 5], "model": ["director", 0]})
        w["cfg3"] = _node("CFG_PASS3", "CFGGuider", {"model": ["guide3", 3], "positive": ["guide3", 0], "negative": ["guide3", 1], "cfg": float(config.pass3["cfg"])})
        w["scheduler3"] = _node("SCHEDULER_PASS3", "BasicScheduler", {"model": ["guide3", 3], "scheduler": config.pass3["scheduler"], "steps": int(config.pass3["steps"]), "denoise": float(config.pass3["denoise"])})
        w["av3"] = _node("AV_PASS3", "LTXVConcatAVLatent", {"video_latent": ["guide3", 2], "audio_latent": audio_ref})
        w["sample3"] = _node("SAMPLE_PASS3", "SamplerCustomAdvanced", {"noise": ["noise", 0], "guider": ["cfg3", 0], "sampler": ["sampler", 0], "sigmas": ["scheduler3", 0], "latent_image": ["av3", 0]})
        w["split3"] = _node("SPLIT_PASS3", "LTXVSeparateAVLatent", {"av_latent": ["sample3", 0]})
        video_ref, audio_ref = ["split3", 0], ["split3", 1]
    # Always use the LTX spatiotemporal decoder.  ComfyUI's generic
    # ``VAEDecode`` keeps the temporal dimension in a 5-D IMAGE tensor, while
    # VideoHelperSuite expects flattened ``[frames, height, width, channels]``
    # images.  Passing that 5-D value to VHS can trigger an enormous CPU
    # materialization during output collection (the observed ~68 GB OOM).
    # "Full" mode is represented by one spatial tile and one temporal tile;
    # it keeps the same decode semantics without changing the user-facing
    # setting or output shape.
    decode_tiled = bool(config.tiled_vae)
    w["decode"] = _node("DECODE_TILED" if decode_tiled else "DECODE_FULL", "LTXVSpatioTemporalTiledVAEDecode", {
        "vae": ["video_vae", 0],
        "latents": video_ref,
        "spatial_tiles": int(config.tiled_spatial_tiles) if decode_tiled else 1,
        "spatial_overlap": int(config.tiled_spatial_overlap) if decode_tiled else 0,
        "temporal_tile_length": int(config.tiled_temporal_tile_length) if decode_tiled else 1000,
        "temporal_overlap": int(config.tiled_temporal_overlap) if decode_tiled else 0,
        "last_frame_fix": bool(config.tiled_last_frame_fix),
        "working_device": config.tiled_working_device,
        "working_dtype": config.tiled_working_dtype,
    })
    w["audio_decode"] = _node("AUDIO_DECODE", "LTXVAudioVAEDecode", {"samples": audio_ref, "audio_vae": ["audio_vae", 0]})
    image_ref: List[Any] = ["decode", 0]
    if config.simple_upscale:
        w["simple_upscale"] = _node("SIMPLE_UPSCALE", "ImageScaleBy", {"image": image_ref, "upscale_method": "bicubic", "scale_by": config.simple_upscale_factor})
        image_ref = ["simple_upscale", 0]
    if config.rtx.get("enabled"):
        w["rtx"] = _node("RTX_UPSCALE", "DaSiWa_RTX_UpscalerRefiner", {"images": image_ref, "denoise": False, "denoise_quality": config.rtx.get("quality", "Ultra"), "deblur": False, "deblur_quality": config.rtx.get("quality", "Ultra"), "upscale": "VSR", "upscale_quality": config.rtx.get("quality", "Ultra"), "resize_type": "Scale", "scale": float(config.rtx.get("scale", 2)), "megapixels": 2.0, "width": 1920, "height": 1080, "divisible_by": "8", "ratio_preset": "16:9", "resize_method": "Letterbox (Fit)", "device_id": 0})
        image_ref = ["rtx", 0]
    if config.watermark.get("enabled"):
        w["watermark"] = _node("WATERMARK", "DaSiWa_Watermark", {"images": image_ref, "watermark_path": config.watermark.get("path"), "position": config.watermark.get("position", "top-left"), "scale": float(config.watermark.get("scale", 0.12)), "resampling": "bicubic", "transparency": float(config.watermark.get("opacity", 0.35)), "rotation": 0, "padding_x": 20, "padding_y": 20, "optical_padding": False, "optical_strength": 0.4, "random_switches": 3, "fade": False, "fade_margin": 0.1, "randomize_position": False, "random_seed": 0})
        image_ref = ["watermark", 0]
    w["output"] = _node("OUTPUT", "VHS_VideoCombine", {"images": image_ref, "audio": ["audio_decode", 0], "frame_rate": config.fps, "loop_count": 0, "filename_prefix": "video/LTXDirector", "format": config.output_format, "pix_fmt": config.pix_fmt, "crf": config.crf, "save_metadata": config.save_metadata, "trim_to_audio": False, "pingpong": False, "save_output": True})
    for role in ("MODEL", "DIRECTOR", "NEGATIVE", "SAMPLE_PASS1", "OUTPUT"):
        find_role(w, role)
    return w


def enabled_optional_classes(config: LTXDirectorConfig) -> Iterable[str]:
    if config.tiled_vae:
        yield "LTXVSpatioTemporalTiledVAEDecode"
    if config.chunking:
        yield "LTXVChunkFeedForward"
    if config.fp16_accumulation:
        yield "ModelPatchTorchSettings"
    if config.nag.get("enabled"):
        yield "LTX2_NAG"
    if config.sage_attention == "patch":
        yield "PathchSageAttentionKJ"
    if config.sage_attention == "memory_efficient":
        yield "LTX2MemoryEfficientSageAttentionPatch"
    if config.simple_upscale:
        yield "ImageScaleBy"
    if config.model_upscale:
        yield "UpscaleWithModelAdvanced"
    if config.rtx.get("enabled"):
        yield "DaSiWa_RTX_UpscalerRefiner"
    if config.color_transfer.get("enabled"):
        yield "ColorTransfer"
    if config.watermark.get("enabled"):
        yield "DaSiWa_Watermark"
    if config.distilled_lora or config.bodyphysics_lora or config.loras:
        yield "DaSiWa_LTX2LoraLoader"
