import json

import pytest

from backend.services.workflows.ltx23_director_adapter import (
    LTXDirectorConfig,
    LTXWorkflowError,
    REQUIRED_NODE_SCHEMAS,
    available_lora_choices,
    build_ltx23_workflow,
    capability_report,
    find_role,
)


def config(**patch):
    raw = {
        "mode": "i2v",
        "prompt": "A woman turns toward the light.",
        "source_image": "/tmp/first.png",
    }
    raw.update(patch)
    return LTXDirectorConfig.from_dict(raw)


def test_mode_input_contracts_are_explicit():
    with pytest.raises(LTXWorkflowError, match="source image"):
        config(source_image=None).validate()
    with pytest.raises(LTXWorkflowError, match="last-frame"):
        config(mode="flf2v", last_frame=None).validate()
    with pytest.raises(LTXWorkflowError, match="source video"):
        config(mode="v2v", source_image=None, source_video=None).validate()
    with pytest.raises(LTXWorkflowError, match="only available in V2V"):
        config(audio_source="source").validate()


def test_director_prompt_timeline_and_source_round_trip():
    cfg = config(
        mode="flf2v",
        last_frame="/tmp/last.png",
        timeline_segments=[{"start": 0, "end": 4, "prompt": "turns"}],
        motion_segments=[{"start": 1, "end": 2, "strength": 0.6}],
    )
    workflow = build_ltx23_workflow(cfg)
    director = workflow[find_role(workflow, "DIRECTOR")]
    assert director["inputs"]["global_prompt"] == cfg.prompt
    data = json.loads(director["inputs"]["timeline_data"])
    assert data["mode"] == "flf2v"
    assert data["sources"]["image"] == "/tmp/first.png"
    assert data["sources"]["last_frame"] == "/tmp/last.png"
    assert data["segments"][0]["prompt"] == "turns"
    assert data["motionSegments"][0]["strength"] == 0.6


def test_uploaded_i2v_image_is_wired_into_latent_guidance():
    workflow = build_ltx23_workflow(config(source_image="input/first.png"))
    source = workflow[find_role(workflow, "SOURCE_IMAGE")]
    guide = workflow[find_role(workflow, "SOURCE_GUIDE")]
    pass1 = workflow[find_role(workflow, "GUIDE_PASS1")]
    assert source["class_type"] == "LoadImage"
    assert source["inputs"]["image"] == "input\\first.png"
    assert guide["class_type"] == "LTXVAddGuide"
    assert guide["inputs"]["image"] == ["source_image", 0]
    assert guide["inputs"]["frame_idx"] == 0
    assert pass1["inputs"]["latent"] == ["source_guide", 2]


def test_flf2v_wires_last_frame_at_final_aligned_frame():
    workflow = build_ltx23_workflow(config(mode="flf2v", last_frame="input/last.png", duration_seconds=2, fps=24))
    guide = workflow[find_role(workflow, "LAST_GUIDE")]
    pass1 = workflow[find_role(workflow, "GUIDE_PASS1")]
    assert guide["inputs"]["image"] == ["last_frame", 0]
    assert guide["inputs"]["frame_idx"] == 47
    assert pass1["inputs"]["latent"] == ["last_guide", 2]


def test_pass_specific_sampling_values_reach_unique_roles():
    cfg = config(
        pass1={"enabled": True, "cfg": 1.25, "steps": 11, "scheduler": "simple", "denoise": 0.95},
        pass2={"enabled": True, "cfg": 1.5, "steps": 5, "scheduler": "karras", "denoise": 0.35},
        pass3={"enabled": True, "cfg": 1.75, "steps": 3, "scheduler": "normal", "denoise": 0.2},
    )
    workflow = build_ltx23_workflow(cfg)
    for suffix, expected in (("PASS1", cfg.pass1), ("PASS2", cfg.pass2), ("PASS3", cfg.pass3)):
        assert workflow[find_role(workflow, f"CFG_{suffix}")]["inputs"]["cfg"] == expected["cfg"]
        scheduler = workflow[find_role(workflow, f"SCHEDULER_{suffix}")]["inputs"]
        assert scheduler["steps"] == expected["steps"]
        assert scheduler["scheduler"] == expected["scheduler"]
        assert scheduler["denoise"] == expected["denoise"]


def test_disabled_passes_are_really_absent():
    workflow = build_ltx23_workflow(config(pass2={"enabled": False, "cfg": 1, "steps": 4, "scheduler": "linear_quadratic", "denoise": 0.3}))
    assert not any((node.get("_meta") or {}).get("title") == "GUAARDVARK_LTX_SAMPLE_PASS2" for node in workflow.values())
    assert not any((node.get("_meta") or {}).get("title") == "GUAARDVARK_LTX_SAMPLE_PASS3" for node in workflow.values())


def test_tiled_decode_and_post_process_roles_are_wired():
    cfg = config(
        tiled_vae=True,
        simple_upscale=True,
        rtx={"enabled": True, "scale": 2.5, "quality": "High"},
        watermark={"enabled": True, "path": "mark.png", "position": "top-left", "scale": 0.12, "opacity": 0.35},
    )
    workflow = build_ltx23_workflow(cfg)
    tiled = workflow[find_role(workflow, "DECODE_TILED")]
    assert tiled["class_type"] == "LTXVSpatioTemporalTiledVAEDecode"
    assert tiled["inputs"]["spatial_tiles"] == 4
    assert tiled["inputs"]["spatial_overlap"] == 4
    assert tiled["inputs"]["temporal_tile_length"] == 32
    assert tiled["inputs"]["temporal_overlap"] == 8
    assert "tile_size" not in tiled["inputs"]
    assert workflow[find_role(workflow, "SIMPLE_UPSCALE")]["inputs"]["scale_by"] == 2
    assert workflow[find_role(workflow, "RTX_UPSCALE")]["inputs"]["scale"] == 2.5
    assert workflow[find_role(workflow, "WATERMARK")]["inputs"]["watermark_path"] == "mark.png"
    assert workflow[find_role(workflow, "OUTPUT")]["inputs"]["images"] == ["watermark", 0]


def test_audio_modes_serialize_without_silent_fallback():
    cfg = config(audio_source="uploaded", uploaded_audio="/tmp/voice.wav")
    data = json.loads(build_ltx23_workflow(cfg)["director"]["inputs"]["timeline_data"])
    assert data["audioTrackEnabled"] is True
    assert data["overrideAudio"] is True
    assert data["sources"]["audio"] == "/tmp/voice.wav"
    assert data["inpaint_audio"] is False


def test_duration_fps_frame_alignment():
    assert config(duration_seconds=10, fps=24).total_frames == 240
    assert config(duration_seconds=1, fps=25).total_frames == 32


def test_capability_report_names_missing_and_schema_drift():
    info = {
        name: {"input": {"required": {key: ["ANY", {}] for key in fields}}}
        for name, fields in REQUIRED_NODE_SCHEMAS.items()
    }
    assert capability_report(info)["ready"] is True
    info.pop("LTXDirectorGuide")
    report = capability_report(info)
    assert report["ready"] is False
    assert "LTXDirectorGuide" in report["missing_nodes"]
    info["LTXDirectorGuide"] = {"input": {"required": {"positive": ["CONDITIONING", {}]}}}
    report = capability_report(info)
    assert report["incompatible_nodes"][0]["class_type"] == "LTXDirectorGuide"


def test_semantic_role_lookup_fails_on_ambiguity():
    workflow = build_ltx23_workflow(config())
    workflow["duplicate"] = dict(workflow["director"])
    with pytest.raises(LTXWorkflowError, match="found 2"):
        find_role(workflow, "DIRECTOR")


def test_dragonleap_is_the_backend_default():
    cfg = config()
    assert cfg.model_id == "ltx23-dasiwa-dragonleap-v4"
    assert cfg.model_name == "LTX2/DasiwaLTX23_dragonleapV4.safetensors"


def test_sage_chunking_and_nag_are_real_model_chain_nodes():
    cfg = config(
        chunking=True,
        chunk_count=3,
        chunk_dim_threshold=4096,
        sage_attention="memory_efficient",
        sage_triton_kernels=True,
        nag={"enabled": True, "scale": 9.0, "alpha": 0.2, "tau": 2.0, "inplace": True},
        bodyphysics_lora=False,
    )
    workflow = build_ltx23_workflow(cfg)
    chunk = workflow[find_role(workflow, "CHUNK_FEED_FORWARD")]
    sage = workflow[find_role(workflow, "SAGE_ATTENTION")]
    nag = workflow[find_role(workflow, "NAG")]
    assert chunk["inputs"]["model"] == ["model", 0]
    assert chunk["inputs"]["chunks"] == 3
    assert sage["class_type"] == "LTX2MemoryEfficientSageAttentionPatch"
    assert sage["inputs"]["model"] == ["chunk_ff", 0]
    assert sage["inputs"]["triton_kernels"] is True
    assert nag["inputs"]["model"] == ["sage_memory", 0]
    assert workflow[find_role(workflow, "DIRECTOR")]["inputs"]["model"] == ["nag", 0]


def test_kj_sage_patch_inputs_match_live_schema():
    workflow = build_ltx23_workflow(config(
        sage_attention="patch",
        sage_kernel="sageattn_qk_int8_pv_fp16_triton",
        sage_allow_compile=False,
        bodyphysics_lora=False,
    ))
    sage = workflow[find_role(workflow, "SAGE_ATTENTION")]
    assert sage["class_type"] == "PathchSageAttentionKJ"
    assert sage["inputs"]["sage_attention"] == "sageattn_qk_int8_pv_fp16_triton"
    assert sage["inputs"]["allow_compile"] is False


def test_distilled_bodyphysics_and_general_loras_share_the_real_dasiwa_stack():
    workflow = build_ltx23_workflow(config(
        bodyphysics_lora=True,
        bodyphysics_lora_strength=0.65,
        distilled_lora=True,
        distilled_lora_strength=0.4,
        loras=[{
            "name": "LTX/custom-style.safetensors",
            "enabled": True,
            "strength": 0.8,
            "video_strength": 0.9,
            "audio_strength": 0.2,
        }],
    ))
    stack = workflow[find_role(workflow, "LORA_STACK")]
    assert stack["class_type"] == "DaSiWa_LTX2LoraLoader"
    stack_data = json.loads(stack["inputs"]["stack_data"])
    assert "distilled-lora" in stack_data[0]["lora"]
    assert stack_data[0]["str"] == 0.4
    assert stack_data[1]["lora"].endswith("Bodyphysics_Fluid_Motion_Enhancer_v01.safetensors")
    assert stack_data[1]["str"] == 0.65
    assert stack_data[2] == {
        "on": True,
        "lora": "LTX/custom-style.safetensors",
        "str": 0.8,
        "vs": 0.9,
        "as": 0.2,
    }
    assert len(stack_data) == 12
    assert all(item["lora"] == "None" for item in stack_data[3:])
    assert not any(node["class_type"] == "LoraLoaderModelOnly" for node in workflow.values())


def test_lora_stack_deduplicates_separator_variants():
    cfg = config(
        distilled_lora=False,
        bodyphysics_lora=True,
        loras=[{
            "name": "LTX\\DaSiWa_LTX23_NSFW_Bodyphysics_Fluid_Motion_Enhancer_v01.safetensors",
            "enabled": True,
            "strength": 1.0,
            "video_strength": 1.0,
            "audio_strength": 1.0,
        }],
    )
    workflow = build_ltx23_workflow(cfg)
    stack = json.loads(workflow[find_role(workflow, "LORA_STACK")]["inputs"]["stack_data"])
    assert len([item for item in stack if item["lora"] != "None"]) == 1
    assert len(stack) == 12


def test_lora_stack_enforces_twelve_total_slots():
    cfg = config(
        bodyphysics_lora=True,
        distilled_lora=True,
        loras=[{
            "name": f"LTX/style-{index}.safetensors",
            "enabled": True,
            "strength": 1.0,
            "video_strength": 1.0,
            "audio_strength": 1.0,
        } for index in range(11)],
    )
    with pytest.raises(LTXWorkflowError, match="at most 12"):
        cfg.validate()


def test_available_loras_are_read_from_live_hidden_picker_schema():
    info = {
        "DaSiWa_LTX2LoraLoader": {
            "input": {
                "hidden": {
                    "available_loras": [[
                        "None",
                        "LTX\\body.safetensors",
                        "LTX/style.safetensors",
                        "LTX/body.safetensors",
                    ], {"description": "picker"}],
                },
            },
        },
    }
    assert available_lora_choices(info) == [
        "LTX\\body.safetensors",
        "LTX/style.safetensors",
    ]
