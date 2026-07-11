# Local Anima Integration Update Notes

Date: 2026-07-08
Scope: local-only integration for Anima / REanimaTE models inside Guaardvark's private ComfyUI stack

This file exists so a future upstream update does not silently wipe or break the Anima integration that was added locally on this machine.

## What was added

### Selectable image models

The following models were exposed in Guaardvark's image model catalog:

- `reanimate-v20` -> `REanimaTE 2.0`
- `reanimate-v30` -> `REanimaTE 3.0`
- `dasiwa-anima` -> `DaSiWa Anima Obsidian`

### Required model assets

These files must exist inside Guaardvark's private ComfyUI model tree:

- `plugins/comfyui/ComfyUI/models/diffusion_models/reanimate_v20.safetensors`
- `plugins/comfyui/ComfyUI/models/diffusion_models/reanimate_v30.safetensors`
- `plugins/comfyui/ComfyUI/models/diffusion_models/dasiwaAnima_obsidianArchivesV2.safetensors`
- `plugins/comfyui/ComfyUI/models/text_encoders/qwen_3_06b_base.safetensors`
- `plugins/comfyui/ComfyUI/models/vae/qwen_image_vae.safetensors`
- `plugins/comfyui/ComfyUI/models/loras/ZodaPlus.safetensors`
- `plugins/comfyui/ComfyUI/models/loras/anima-highres-aesthetic-boost.safetensors`

### Required custom nodes

These custom node folders must exist in Guaardvark's private ComfyUI:

- `plugins/comfyui/ComfyUI/custom_nodes/rgthree-comfy`
- `plugins/comfyui/ComfyUI/custom_nodes/ComfyUI-DaSiWa-Nodes`

The following nodes were explicitly verified as present in `/object_info`:

- `Power Lora Loader (rgthree)`
- `DaSiWa_MetadataImageSaver`
- `TextEncodeQwenImageEditPlus`
- `ModelSamplingAuraFlow`
- `UNETLoader`
- `CLIPLoader`
- `VAELoader`
- `LoraLoaderModelOnly`
- `EmptySD3LatentImage`

## Local code changes

These files were patched locally and are update-sensitive:

- `backend/services/comfyui_image_generator.py`
- `backend/services/offline_image_generator.py`
- `backend/api/batch_image_generation_api.py`
- `backend/services/gpu_resource_policy.py`
- `plugins/comfyui/ComfyUI/custom_nodes/ComfyUI-DaSiWa-Nodes/__init__.py`

### 1. `backend/services/comfyui_image_generator.py`

Purpose:

- add Anima model catalog
- add Qwen clip + VAE stack for Anima
- build Anima workflow with:
  - `UNETLoader`
  - `CLIPLoader`
  - `VAELoader`
  - `LoraLoaderModelOnly`
  - `ModelSamplingAuraFlow`
  - `CLIPTextEncode`
  - `EmptySD3LatentImage`
  - `KSampler`
  - `VAEDecode`
- auto-apply default LoRAs for Anima models

Current default LoRAs:

- `anima-highres-aesthetic-boost.safetensors` at `0.40`
- `ZodaPlus.safetensors` at `1.50`

Sampler settings currently used for Anima:

- sampler: `er_sde`
- scheduler: `beta`
- steps: `30`
- cfg: `5.0`
- shift: `5.0`

### 2. `backend/services/offline_image_generator.py`

Purpose:

- treat the new model ids as family `anima`
- expose them in `get_available_models()`
- route generation requests for those ids through `ComfyUIImageGenerator(...)`
- use an Anima VRAM estimate that matches real observed usage on this host

Current local estimate:

- `_FAMILY_VRAM_MB["anima"] = 9000`
- `_FAMILY_RAM_GB["anima"] = 10.0`

Reason:

- `10000` MB was too conservative and blocked valid runs on the RTX 4070 even though the model completed successfully in practice.

### 3. `backend/api/batch_image_generation_api.py`

Purpose:

- allow the new local Anima model ids through API validation
- expose approximate model sizes

Current local sizes:

- `reanimate-v20`: `3.9`
- `reanimate-v30`: `3.9`
- `dasiwa-anima`: `3.9`

### 4. `backend/services/gpu_resource_policy.py`

Purpose:

- stop assuming ComfyUI is Krita's server on `127.0.0.1:8188`
- use Guaardvark's private ComfyUI URL instead

Important:

- local reclaim/free logic must target private ComfyUI on `127.0.0.1:8191`
- if this drifts back to `8188`, the policy can try to free the wrong Comfy instance

### 5. `plugins/comfyui/ComfyUI/custom_nodes/ComfyUI-DaSiWa-Nodes/__init__.py`

Purpose:

- change imports from "all or nothing" to tolerant per-module registration

Reason:

- some optional heavy dependencies can fail, but `DaSiWa_MetadataImageSaver` still needs to load
- without this patch, the whole DaSiWa node pack can disappear from Comfy startup

## Source-backed LoRA notes

### ZodaPlus

Source status:

- verified from Civitai metadata/examples

Recommended local default:

- `1.5`

### anima-highres-aesthetic-boost

Source status:

- the page description was available, but no clear machine-readable recommended strength was exposed

Current local default:

- `0.40`

This value is a local conservative choice, not a source-verified official strength.

## End-to-end verification that passed

### Catalog verification

Successful:

- `GET /api/batch-image/models`
- returned:
  - `reanimate-v20`
  - `reanimate-v30`
  - `dasiwa-anima`

### Comfy node verification

Successful:

- `GET http://127.0.0.1:8191/object_info`
- returned the required rgthree + DaSiWa + Anima workflow nodes

### Direct Comfy generation verification

Successful test output:

- `data/outputs/anima_test_reanimate_v30.png`

### UI-facing generator verification

Successful:

- `OfflineImageGenerator.generate_image(...)`
- with `model='reanimate-v20'`

Note:

- the generator may print:
  - `Post-evict still short ... admitting anyway`

This is acceptable here because the model was empirically shown to complete on this GPU.

## What to re-check after any upstream update

Run these checks in this order.

### 1. Check that the private model files still exist

Verify these directories:

- `plugins/comfyui/ComfyUI/models/diffusion_models`
- `plugins/comfyui/ComfyUI/models/text_encoders`
- `plugins/comfyui/ComfyUI/models/vae`
- `plugins/comfyui/ComfyUI/models/loras`

### 2. Check that the custom nodes still load

Run:

```bash
curl -sS http://127.0.0.1:8191/object_info | jq 'keys[]' | rg 'Power Lora Loader \(rgthree\)|DaSiWa_MetadataImageSaver|TextEncodeQwenImageEditPlus|ModelSamplingAuraFlow'
```

If missing:

- re-check `rgthree-comfy`
- re-check `ComfyUI-DaSiWa-Nodes`
- re-check the patched `__init__.py`

### 3. Check that the models are still visible in the app catalog

Run:

```bash
curl -sS http://127.0.0.1:5000/api/batch-image/models | jq '.models // .data // .'
```

Confirm these ids exist:

- `reanimate-v20`
- `reanimate-v30`
- `dasiwa-anima`

### 4. Check that private Comfy is still the target

Re-check:

- `backend/services/gpu_resource_policy.py`
- `backend/services/comfyui_image_generator.py`

The private Comfy URL must stay aligned with:

- `http://127.0.0.1:8191`

### 5. Re-run one real generation

Minimum direct smoke test:

```bash
./backend/venv/bin/python - <<'PY'
from pathlib import Path
from backend.services.comfyui_image_generator import ComfyUIImageGenerator
out = Path('data/outputs/anima_update_smoketest.png')
out.parent.mkdir(parents=True, exist_ok=True)
print(
    ComfyUIImageGenerator(comfy_url='http://127.0.0.1:8191', model='reanimate-v30').generate_image(
        prompt='anime-style portrait of a red-haired woman, white studio background, clean lineart, detailed eyes',
        output_path=str(out),
        width=512,
        height=768,
        seed=123456,
        steps=30,
        cfg=5.0,
        model='reanimate-v30',
    )
)
PY
```

### 6. Re-run one UI-path generation

Minimum higher-level smoke test:

```bash
./backend/venv/bin/python - <<'PY'
from backend.services.offline_image_generator import OfflineImageGenerator, ImageGenerationRequest
req = ImageGenerationRequest(
    prompt='anime-style portrait of a woman with short dark hair, white background, clean lineart',
    width=384,
    height=512,
    num_inference_steps=30,
    guidance_scale=5.0,
    model='reanimate-v20',
    style='artistic',
    auto_enhance=False,
)
print(OfflineImageGenerator().generate_image(req))
PY
```

## If the update breaks this integration

Most likely break points:

1. upstream rewrites `offline_image_generator.py` model catalog or routing
2. upstream rewrites `comfyui_image_generator.py` workflow builder
3. upstream resets `gpu_resource_policy.py` back to port `8188`
4. upstream changes Comfy custom node loading behavior
5. node package updates invalidate the tolerant `ComfyUI-DaSiWa-Nodes/__init__.py` import patch

If that happens, re-implement the logic described in this file rather than blindly copying old files.

## Current local operational state

At the time this note was written, the intended runtime was:

- backend: `127.0.0.1:5000`
- frontend: `127.0.0.1:5173`
- private ComfyUI: `127.0.0.1:8191`

Use `launch_guaardvark.sh` for the detached local startup path when validating the full stack.
