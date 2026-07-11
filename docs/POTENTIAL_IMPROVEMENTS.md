# Potential Improvements

## Windows Python Launcher UX

- The startup launcher can stay visually simple, but the log presentation could be improved.
- Potential enhancement: render each startup log source in its own collapsible container.
- Each container should expose a full scrollable log view rather than only a short rolling excerpt.
- Candidate log panes:
  - `setup.log`
  - `launch.log`
  - `backend_startup.log`
  - `frontend.log`
  - `comfyui-windows.err.log`
- Nice-to-have behavior:
  - remember collapsed/expanded state during the session
  - highlight the currently active log pane
  - auto-scroll only when the user is already at the bottom

## Performance & Quality Optimization (ComfyUI Generator)

- **DaSiWa RTX Upscaler & Refiner (Video Generation)**
  - Missed opportunity for hardware-accelerated RTX upscaling and deblurring for high-quality DasiWa models.
  - Automatically inject the `DaSiWa_RTX_UpscalerRefiner` node into workflows targeting "dasiwa" models. Injecting it *before* the RIFE interpolation multiplier will upscale fewer base frames, drastically improving VRAM usage and processing speed while achieving superior 1080p+ visual fidelity.
  - Ensure these nodes and specific DaSiWa workflows (FastFidelity, OmniForge) are properly provisioned via Civitai Red using the implemented token.
- **Hardcoded DaSiWa Parameters (Video Generation)**
  - DaSiWa video models (Lightspeed, TastySin, SynthSeduction) are highly distilled for exactly 4 steps. The current generic defaults degrade quality and speed.
  - Override generic `wan22` workflows when hitting `dasiwa` models to strictly use: 4 Steps, CFG 1.0, Euler/Simple, and Sigma-Shift 5. Crucially, do not use external speed-up tricks (LoRAs/FreeU) on these models.
- **DaSiWa Metadata Saver Integration (Image Generation)**
  - Advanced ComfyUI metadata (seeds, CFG, samplers, exact step counts) are currently lost in Anima image workflows due to the use of a standard `SaveImage` node.
  - Replace `SaveImage` with `DaSiWa_MetadataImageSaverFull` for all `ANIMA_MODEL_CATALOG` workflows to inject these generation parameters properly.
- **Unused Quality Nodes (`comfyui_video_generator.py`) (Non-DaSiWa)**
  - The backend defines helper methods for `FreeU_V2` (`_add_freeu_node`) and CodeFormer Face Restoration (`_add_face_detailer_node`), but these are never injected into standard `Wan22` or `CogVideoX` graphs.
  - Actively inject `FreeU_V2` (with model-specific tuned parameters) into all standard video graphs, and expose a UI toggle to optionally inject the Face Restoration node. (Note: Exclude DaSiWa models from FreeU injection).
