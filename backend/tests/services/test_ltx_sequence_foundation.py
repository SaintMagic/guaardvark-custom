import tempfile
import unittest
from pathlib import Path

from backend.services.ltx_sequence_repository import LTXSequenceRepository
from backend.services.workflows.ltx_shot_compiler import compile_timeline
from backend.services.workflows.ltx23_director_adapter import LTXDirectorConfig


def sequence(payload=None):
    payload = payload or {}
    return {"schema_version": 1, "project_id": "test", "title": "Test", "render_mode": "shot_batch", "global": {"width": 576, "height": 896, "fps": 24, **payload.get("global", {})}, "shots": payload.get("shots", [])}


class LTXSequenceFoundationTests(unittest.TestCase):
    def test_default_dimensions_use_valid_ltx_alignment(self):
        document = sequence()
        self.assertEqual(document["global"]["width"], 576)
        self.assertEqual(document["global"]["height"], 896)

    def test_repository_round_trip_is_versioned(self):
        with tempfile.TemporaryDirectory() as directory:
            repository = LTXSequenceRepository(Path(directory))
            saved = repository.create(sequence())
            self.assertEqual(repository.get(saved["project_id"])["schema_version"], 1)

    def test_timeline_preserves_order_and_frame_alignment(self):
        document = sequence({"global": {"fps": 24}, "shots": [
            {"id": "one", "prompt": "one", "duration_seconds": 5, "enabled": True},
            {"id": "two", "prompt": "two", "duration_seconds": 5, "enabled": True},
        ]})
        preview = compile_timeline(document)
        self.assertEqual(preview["timeline_segments"], [
            {"start": 0, "end": 120, "prompt": "one"},
            {"start": 120, "end": 240, "prompt": "two"},
        ])
        self.assertEqual(preview["total_frames"], 240)

    def test_fp8_model_uses_native_safetensors_config(self):
        config = LTXDirectorConfig.from_dict({
            "mode": "t2v",
            "prompt": "test",
            "model_id": "ltx23-fp8-civitai-2752717",
            "model_name": "LTX2/ltx23_fp8.safetensors",
            "model_format": "safetensors",
        })
        self.assertEqual(config.model_format, "safetensors")
        self.assertTrue(config.model_name.endswith("ltx23_fp8.safetensors"))

    def test_timeline_compiler_emits_motion_and_audio_segments(self):
        document = sequence({"global": {"fps": 24}, "shots": [
            {"id": "one", "prompt": "one", "duration_seconds": 1, "motion_strength": 0.5, "enabled": True},
            {"id": "two", "prompt": "two", "duration_seconds": 1, "audio_source_override": "none", "enabled": True},
        ]})
        preview = compile_timeline(document)
        self.assertEqual(len(preview["motion_segments"]), 2)
        self.assertEqual(len(preview["audio_segments"]), 2)
        self.assertEqual(preview["motion_segments"][0]["strength"], 0.5)
        self.assertEqual(preview["audio_segments"][1]["source"], "none")

if __name__ == "__main__":
    unittest.main()
