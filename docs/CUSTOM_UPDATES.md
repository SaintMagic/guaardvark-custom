# Custom updates

This is the maintained, repository-level summary of the downstream Guaardvark changes in this fork. It consolidates the recent implementation and hardening work rather than describing only LTX. Runtime state, model weights, credentials, audit dumps, and generated diffs remain local-only.

## Recent implementation history

- `018375c` organized implementation notes under `docs/` and moved audit artifacts out of the tracked source tree.
- `d220e95` routed LTX sequence work through the shared GPU session/lease and added repository revisions.
- `16a55d8` replaced the LTX-only status note with this general custom-updates document.

The feature work summarized here originated in the preceding LTX/runtime commits and is intentionally kept isolated from the existing WAN behavior.

## LTX Director

- Added a dedicated LTX Director page, route, navigation entry, API namespace, registry entries, and isolated workflow adapter.
- Added LTX 2.3 DragonLeap, Civitai FP8, and Unsloth GGUF model selection without changing WAN behavior.
- Added shared LTX assets/readiness checks for video/audio/preview VAE, text encoder/projection, spatial upscaler, LoRAs, and required ComfyUI node classes.
- Added versioned sequence projects with atomic persistence, autosave, stable shot IDs, ordered shot-batch rendering, continuity final-frame extraction, retries, hard-cut stitching, and restart reconciliation.
- Sequence shots and keyframe jobs now use the shared GPU session/lease, remain serial, and expose asynchronous child-job state.
- Added optimistic sequence revisions and save-before-render behavior to reduce stale browser overwrites.
- Added frame-weighted sequence progress and normalized global progress states.
- Added persistent keyframe assets and metadata, Generate/Regenerate/Approve-and-lock actions, and a no-silent-regeneration guard.
- Cast keyframe generation resolves the selected trained Subject LoRA and trigger phrase through the existing Subject model.
- Lightspeed and Quality profiles are explicit and use safe 576×896 defaults. Bodyphysics is off by default and warns when explicitly enabled.
- FLF2V and Timeline rendering are intentionally gated until native ComfyUI payload schemas are captured and contract-tested.

## ComfyUI and runtime integration

- Preserved the Windows-native ComfyUI plus WSL backend split.
- Added capability/readiness checks based on `/object_info`, with stale capability-cache invalidation support.
- Added native model-path handling for LTX safetensors and GGUF loaders.
- Added protection against false orphan cancellation when slow CPU-offloaded LTX renders temporarily time out.
- Avoided sending a late global ComfyUI interrupt after a connection-loss classification.
- Added safer launcher/service scripts and retained the current Edge WebView2 host path.
- SageAttention/Triton options remain capability-gated; unsafe combinations default to the safe PyTorch path.

## Launcher, platform, and service changes

- Preserved the Windows-native launcher and native ComfyUI process while keeping the backend/frontend services in WSL.
- Added/updated the native and GUI launch scripts, service health checks, startup reconciliation, stop handling, and external-ComfyUI URL/path normalization.
- Kept the current Edge WebView2-based host path; the obsolete Qt/QWebEngine wrapper is not the active integration target.
- Added safer dependency reconciliation and frontend build handling for the WSL-mounted workspace.
- Kept GPU rendering serial through the shared resource policy/session rather than allowing independent LTX workers to compete with normal image/video work.

## Image, video, and model-system changes

- Extended the existing video generation path with capability-aware LTX routing while leaving WAN/CogVideo request behavior intact.
- Preserved shared upload, gallery, history, retry, batch, and progress infrastructure instead of creating parallel systems for LTX.
- Added LTX-specific frontend sections/components, presets, LoRA stack handling, file fields, sequence services, and API routing so the normal Video Generator page does not become an LTX conditional block.
- Reused Cast/Subject metadata for generated keyframes, including the selected trained Subject LoRA and trigger phrase, with persistent keyframe asset metadata.
- Kept the canonical model registry/downloader as the source of truth for model names, exact destinations, dependency readiness, and optional capability reporting.
- GoldenLace is no longer an active LTX choice; the selected FP8 and GGUF LTX alternatives are represented instead. Existing local model files are not replaced or redownloaded automatically.

## Model and downloader changes

- Extended the canonical video model registry with exact LTX destinations and shared dependencies.
- Replaced GoldenLace as an active model option with the selected Civitai LTX 2.3 FP8/GGUF alternatives.
- Kept model weights, partial downloads, ComfyUI installations, virtual environments, caches, and runtime state outside Git.
- Added ignore rules for secrets, local audit snapshots, generated diffs, model/workflow directories, runtime state, and duplicate local copies.

## Global UI and progress

- Reused the unified progress context/footer for LTX sequence jobs.
- Normalized `queued`, `loading`, `running`, `postprocessing`, `complete`, `cancelled`, and `error` states.
- Added generated/target unit counts and frame-weighted sequence percentages.
- Preserved existing WAN, batch-video, retry, and gallery paths.

## Documentation and repository hygiene

- Maintained project notes are under `docs/`, including the implementation plan, local model notes, work log, and improvement backlog.
- Historical audit reports and generated review diffs are kept in the local `obsolete diffs` archive and are not part of the public source history.
- Ignore rules exclude secrets, local credentials, model weights, partial downloads, ComfyUI runtime/workflow state, caches, virtual environments, generated diffs, and other machine-specific artifacts.
- The public fork does not contain `.env` values or the local `GUAARDVARK.md` handoff file.

## Current verification and remaining work

The focused LTX Python tests and frontend production build pass. These checks do not substitute for a live ComfyUI render. Before unattended use, capture and compare native ComfyUI `/prompt` and history payloads for FLF2V, then test a short fixed-seed 576×896 render with audio, upscale, NAG, and Bodyphysics disabled.

Remaining work is tracked here rather than in separate LTX-only documents:

- capture and contract-test the native FLF2V payload before re-enabling FLF2V;
- validate the native timeline/director payload before allowing timeline rendering;
- add ffprobe-driven stitch normalization, duration, pixel-format, and audio validation;
- expand child-job polling/history and revision-conflict UX in the frontend; the editor now refreshes saved projects, polls backend state, preserves dirty drafts, and handles 409 conflicts safely;
- add focused tests for cancellation propagation, restart recovery, frame-weighted progress, failed-sequence state, save-before-render, Cast resolution, thread races, and incomplete stitching;
- decide whether WebView2 taskbar progress can be integrated without destabilizing the current launcher, otherwise leave it explicitly deferred;
- complete live ComfyUI contract validation; no full live FLF2V render is claimed by this document.
