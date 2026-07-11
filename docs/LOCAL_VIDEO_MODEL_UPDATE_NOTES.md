# Local Video Model Update Notes

Date: 2026-07-08

## What was added

- `wan22-snatchkiss-i2v-gguf-q6`
- `wan22-snatchkiss-i2v-gguf-q8`
- `wan22-snatchkiss-i2v-fp8-pruned`
- `wan22-snatchkiss-i2v-fp8-full`

These are Wan 2.2 I2V Lightspeed presets backed by a HighNoise + LowNoise pair.

## Registry wiring

- The single source of truth is `backend/services/video_model_registry.py`
- Each preset uses `direct_urls` so the downloader can fetch the exact Civitai mirror files
- Each preset must keep both HighNoise and LowNoise files in `ComfyUI/models/unet/`
- The file names are intentionally distinct per quantization / variant to avoid overwrite collisions

## Recommended workflow defaults

- GGUF Q6: `steps=4`, `cfg=1`, `sampler=uni_pc`, `scheduler=simple`
- GGUF Q8: `steps=4`, `cfg=1`, `sampler=uni_pc`, `scheduler=simple`
- FP8 pruned: `steps=4`, `cfg=1`, `sampler=euler`, `scheduler=simple`
- FP8 full: `steps=4`, `cfg=1`, `sampler=euler`, `scheduler=simple`

## Frontend wiring

- `frontend/src/constants/videoGeneratorPresets.js`
  - add the four model ids
  - mark them as I2V-only
  - keep their step/guidance defaults at the recommended lightspeed values
  - bypass the old low-VRAM Wan clamp for these presets
- `frontend/src/pages/MusicVideoPage.jsx`
  - include the new I2V options in the animation model dropdown

## Backend wiring

- `backend/services/comfyui_video_generator.py`
  - use the registry workflow defaults for Wan presets when present
  - the prompt wait loop now extends while ComfyUI still knows about the prompt so long renders do not hit the old wall-clock timeout

## Runtime limiter note

- `backend/services/gpu_resource_policy.py`
  - the GPU session wrapper no longer infers a RAM/load admission budget from `vram_estimate_mb`
  - video jobs may now spill into system RAM/swap and surface the real backend OOM reason instead of getting blocked early
  - RAM admission still exists, but only when a caller explicitly passes `ram_estimate_gb`

## If this needs rework later

1. Re-check the Civitai mirror API for the model version ids if the download URLs change.
2. Keep the HighNoise / LowNoise naming aligned with `wan_comfyui_map()`.
3. If a new precision ships, add a new registry entry instead of mutating an existing one.
4. If the UI needs a separate sampler selector later, move `workflow_defaults` into an explicit preset object and keep the registry as the source of file paths only.
