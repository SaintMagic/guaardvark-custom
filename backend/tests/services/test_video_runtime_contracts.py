import json
import threading
from pathlib import Path
from unittest.mock import Mock


def _wan_generator():
    from backend.services.comfyui_video_generator import ComfyUIVideoGenerator

    generator = object.__new__(ComfyUIVideoGenerator)
    generator._comfy_model_separator = "/"
    generator.WAN22_MODELS = {
        "test-wan": {
            "unet_high": "high.gguf",
            "unet_low": "low.gguf",
            "clip": "clip.safetensors",
            "vae": "vae.safetensors",
            "type": "i2v",
            "workflow_defaults": {
                "num_inference_steps": 4,
                "guidance_scale": 1.0,
                "sampler_name": "euler",
                "scheduler": "simple",
            },
        }
    }
    return generator


def test_dasiwa_cfg_default_and_explicit_override_reach_both_samplers():
    generator = _wan_generator()

    default = generator._create_wan22_i2v_workflow(
        image_filename="start.png", prompt="test", model_key="test-wan",
        num_inference_steps=20, guidance_scale=7.5,
        guidance_scale_overridden=False, interpolation_multiplier=1,
    )
    assert default["10"]["inputs"]["cfg"] == 1.0
    assert default["11"]["inputs"]["cfg"] == 1.0
    assert default["10"]["inputs"]["steps"] == 4

    overridden = generator._create_wan22_i2v_workflow(
        image_filename="start.png", prompt="test", model_key="test-wan",
        num_inference_steps=12, guidance_scale=7.5,
        guidance_scale_overridden=True, interpolation_multiplier=1,
    )
    assert overridden["10"]["inputs"]["cfg"] == 7.5
    assert overridden["11"]["inputs"]["cfg"] == 7.5
    assert overridden["10"]["inputs"]["steps"] == 12


def test_cancellation_breaks_wait_loop_before_network_poll(monkeypatch):
    from backend.services.comfyui_video_generator import ComfyUIVideoGenerator

    generator = object.__new__(ComfyUIVideoGenerator)
    generator._comfyui_alive = Mock(side_effect=AssertionError("network poll should not run"))
    event = threading.Event()
    event.set()

    assert generator._wait_for_completion("prompt", timeout=10, cancel_event=event) == {
        "_cancelled_by_event": True
    }


def test_wait_loop_does_not_orphan_prompt_on_liveness_probe_failure(monkeypatch):
    from backend.services import comfyui_video_generator as module
    from backend.services.comfyui_video_generator import ComfyUIVideoGenerator

    generator = object.__new__(ComfyUIVideoGenerator)
    generator.comfy_url = "http://comfy"
    generator._comfy_model_separator = "/"
    generator._comfyui_alive = Mock(return_value=False)

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"prompt": {"outputs": {"13": {"gifs": [{"filename": "video.mp4"}]}}}}

    monkeypatch.setattr(module.requests, "get", lambda *_args, **_kwargs: Response())

    assert generator._wait_for_completion("prompt", timeout=10) == {
        "13": {"gifs": [{"filename": "video.mp4"}]}
    }


def test_pending_batch_restore_preserves_explicit_cfg_flag(tmp_path: Path):
    from backend.services.batch_video_generator import BatchVideoGenerator

    generator = object.__new__(BatchVideoGenerator)
    generator.base_output_dir = tmp_path
    generator.active_batches = {}
    generator.batch_lock = threading.Lock()
    generator.start_batch_from_prompts = Mock()

    batch_dir = tmp_path / "VideoBatch_restore"
    batch_dir.mkdir()
    (batch_dir / "batch_metadata.json").write_text(json.dumps({
        "batch_id": "VideoBatch_restore",
        "status": "queued",
        "retry_data": {
            "mode": "text",
            "prompts": ["restore me"],
            "params": {
                "model": "wan22-snatchkiss-i2v-fp8-full",
                "guidance_scale": 7.5,
                "guidance_scale_overridden": True,
            },
        },
    }))

    generator._restore_pending_batches()
    kwargs = generator.start_batch_from_prompts.call_args.kwargs
    assert kwargs["guidance_scale"] == 7.5
    assert kwargs["guidance_scale_overridden"] is True


def test_progress_bridge_emits_step_and_stage_payload(monkeypatch):
    import backend.services.comfyui_progress_bridge as bridge_module

    emitted = []

    class FakeSocket:
        def settimeout(self, _timeout):
            return None

        def recv(self):
            if not hasattr(self, "sent"):
                self.sent = True
                return '{"type":"progress","data":{"value":2,"max":4,"node":"7"}}'
            return '{"type":"executing","data":{"node":null}}'

        def close(self):
            return None

    monkeypatch.setattr(bridge_module.websocket, "create_connection", lambda *_args, **_kwargs: FakeSocket())
    monkeypatch.setattr(bridge_module, "emit_progress_event", lambda **payload: emitted.append(payload))

    bridge = bridge_module.ComfyUIProgressBridge()
    bridge._run("ws://comfy/ws", "job-1", {"7": "denoising"}, 10, {"batch_id": "batch-1"})

    progress = next(item for item in emitted if item["progress"] == 50)
    extra = progress["additional_data"]
    assert extra["stage"] == "denoising"
    assert extra["current"] == 2
    assert extra["total"] == 4
    assert extra["batch_id"] == "batch-1"


def test_cinema_plus_chain_is_rife_then_rtx_before_vhs():
    generator = _wan_generator()
    workflow = {
        "1": {"class_type": "VAEDecode", "inputs": {}},
        "2": {"class_type": "VHS_VideoCombine", "inputs": {"images": ["1", 0], "frame_rate": 16}},
    }
    generator._add_rife_interpolation(workflow, "1", "2", base_fps=16, multiplier=2)
    rife_id = workflow["2"]["inputs"]["images"][0]
    generator._add_rtx_upscale_node(workflow, rife_id, "2")
    rtx_id = workflow["2"]["inputs"]["images"][0]

    assert workflow[rife_id]["class_type"] == "RIFE VFI"
    assert workflow[rtx_id]["class_type"] == "DaSiWa_RTX_UpscalerRefiner"
    assert workflow[rtx_id]["inputs"]["images"] == [rife_id, 0]
