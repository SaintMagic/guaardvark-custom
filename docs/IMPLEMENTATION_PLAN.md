# Guaardvark Implementation Plan

Status: active audit and maintenance plan
Updated: 2026-07-10
Baseline: `AUDIT_DIFF_SCOPED.md`, generated against upstream commit `94b0d5c3774123ae2239363f91b6896f1899cb23`

## Implemented; Awaiting Live Verification

### Add `Cinema+` Output Quality Preset

Status: implemented; pending one live render verification

Use one RTX preset only; do not add a separate anime RTX variant.

- `Cinema+` should combine 2x frame interpolation with the native
  `DaSiWa_RTX_UpscalerRefiner` VSR path.
- The backend advertises `capabilities.cinema_plus` per model only when the
  selected model is Wan and ComfyUI exposes `DaSiWa_RTX_UpscalerRefiner`.
- The frontend hides the preset for unsupported models/workflows and resets a
  stale restored selection to Standard.
- Generated API workflows use a serial `frames -> RIFE -> RTX VSR -> VHS`
  chain with scale `2.0`, VSR Ultra, denoise/deblur disabled, divisible-by-8,
  and Letterbox (Fit) semantics. Legacy Real-ESRGAN is not stacked on Cinema+.
- Keep anime model upscaling as a separate future option, not part of `Cinema+`.

### Make Explicit UI Guidance Scale Override Model Presets

Status: implemented; verified by focused workflow tests

Before this implementation, the DaSiWa WAN 2.2 Lightspeed workflow replaced the UI-selected Guidance Scale and inference steps with the model registry defaults. The explicit override path now preserves the model defaults only when the control remains untouched.

Planned behavior:

1. Preserve model defaults as initial values and recommendations.
2. Allow an explicit UI value to override the preset value when the user changes it.
3. Carry explicitness through API, batch request, retry metadata, and restored UI state.
4. Apply the same precedence rule to both Wan sampling passes.
5. Add tests proving that an explicit Guidance Scale reaches both KSampler nodes and that an untouched control still receives the model default.

Likely touchpoints:

- `backend/services/comfyui_video_generator.py`
- `backend/services/batch_video_generator.py`
- `backend/api/batch_video_generation_api.py`
- `frontend/src/pages/VideoGeneratorPage.jsx`
- `frontend/src/constants/videoGeneratorPresets.js`
- `backend/tests/` workflow and batch tests

Acceptance criteria:

- A DaSiWa request with no explicit override uses CFG `1.0` and 4 steps.
- A request with an explicit Guidance Scale uses that value in both sampling passes.
- The generated workflow and persisted retry metadata agree.
- A validation test confirms the value sent to ComfyUI.

Implementation notes:

- `guidanceScaleOverridden` is persisted separately from the numeric control.
- Model changes update the numeric default only while the control remains untouched.
- Direct API callers that include `guidance_scale` without the new flag are
  treated as explicit for backwards-compatible API behavior.

### Launcher and Startup Reconciliation

Status: implemented; verified by a clean WSL restart

- The WSL launcher now verifies/starts Redis and PostgreSQL before migrations,
  waits for backend health, reconciles Celery workers/beat, and waits for Vite.
- Native Windows ComfyUI and Windows Ollama remain external services; the
  launcher does not start a second WSL ComfyUI instance.
- `GUAARDVARK_SKIP_REDIS`, `GUAARDVARK_SKIP_POSTGRES`, and
  `GUAARDVARK_SKIP_CELERY` provide explicit external-service escape hatches.

### WebSocket Handshake Diagnosis

Status: implemented; polling and websocket upgrade verified

- Browser diagnostics record origin, API/socket URLs, configured transports,
  upgrade failures, disconnect reasons, and reconnect errors.
- Server diagnostics record handshake origin, transport, remote address,
  auth-key presence, accept/reject outcome, and disconnect information.
- Socket.IO polling returned HTTP 200 with the expected CORS origin, and the
  backend log confirmed websocket upgrades.

### Absolute System Metrics

Status: implemented; endpoint verified after restart

- Metrics expose dedicated VRAM used/total, Windows shared GPU memory
  used/total/percent when the WDDM counter is available, GPU utilization,
  system memory used/total, and swap used/total.
- Shared memory uses the Windows host physical-memory budget under WSL rather
  than the WSL memory cap. Native Linux/macOS remains fail-safe.
- The frontend refreshes metrics every two seconds and renders unavailable
  absolute values as `—`, not `0/0`.

### Theme, Form, and ComfyUI Status Persistence

Status: implemented and verified by code inspection/runtime wiring

- Existing Zustand theme/sidebar persistence and video form localStorage
  persistence are retained.
- Guidance override state is included in persisted form and retry snapshots.
- Global health polling now includes ComfyUI status alongside backend, DB,
  Redis, and Celery.

### Verification Tests

Status: implemented; focused suite passing

- Added `backend/tests/services/test_video_runtime_contracts.py` covering CFG
  precedence, cancellation, queue restore, and websocket progress payloads.
- Focused result: 5 passed, with only the pre-existing `pynvml` deprecation
  warning.

## Implemented Changes

### Native ComfyUI Progress Bridge Hardening

- **Status:** implemented, pending live-generation verification
- Added an immediate queued state so the launcher does not remain visually idle
  while ComfyUI loads models.
- Progress updates now include node/stage transitions and current/total step
  counts, even when the percentage itself has not changed.
- Per-video requests now retain `batch_id`, allowing the frontend to associate
  live ComfyUI progress with the correct batch instead of using a global fallback.
- Added connection, prompt-id/process, and shutdown logging to distinguish a
  websocket problem from a slow ComfyUI node.
- Kept `/history/{prompt_id}` as the completion source of truth; the websocket
  remains progress-only and failure-tolerant.

### Video Output Review: `wan22_i2v_FP8_FULL_25minutes.mp4`

- **Status:** reviewed; no code change required from the visual inspection
- The sampled beginning, middle, and final frames remain coherent and stable.
- The workflow metadata confirms the DaSiWa Lightspeed-style `4` steps and
  `CFG 1.0` settings, `720x720`, `161` frames at `16 fps`, tiled VAE decode,
  and H.264 output.
- These settings can explain a stylized/soft or less prompt-faithful result,
  but they do not by themselves indicate a broken render. A wrong checkpoint
  pairing or a non-square source being forced into `720x720` remains the more
  likely cause of a genuinely strange result.

### Upscaling Frame Progress Display

- **Status:** implemented, pending browser refresh/live verification
- Corrected `UpscalingPage.jsx` to consume the service's `frames_done` and
  `frames_total` fields, while retaining fallback support for legacy field names.
- The active job can now display real frame counts and determinate percentage
  progress instead of `Frame 0 / ?`.

### Runtime Dependency and Ollama Reconciliation

- **Status:** implemented, runtime verified
- The WSL launcher now refuses to stamp a failed frontend dependency install
  as successful and verifies the Vite entrypoint.
- Audio Foundry's isolated music environment was recreated with Python 3.12,
  then installed with a compatible Torch/ACE-Step core stack. The upstream
  ACE-Step dependency chain still contains obsolete `llvmlite` pins and was
  intentionally not forced into the environment.
- Ollama was installed on Windows, configured to listen on the host interface,
  and the WSL launcher now passes the dynamic Windows gateway URL to the backend.
- Backend health verified on port 5000; Ollama `/api/tags` verified reachable.

This inventory is derived from the scoped local-versus-upstream audit. It includes source and launcher changes that are plausible human/updater edits. Model weights, generated media, logs, virtual environments, caches, vendor payloads, and nested repository snapshots are intentionally not listed as implementation items.

### Native Windows ComfyUI and WSL Integration

- `GuaardvarkLauncher.pyw` - Windows launcher UI, startup ordering, service controls, native ComfyUI lifecycle, progress/status reporting, and log access.
- `Run-ComfyUI-Native.cmd` - Windows entry point for native ComfyUI.
- `Run-ComfyUI-Native.ps1` - Native Windows ComfyUI environment/bootstrap, CUDA PyTorch setup, dependency checks, flags, and process launch.
- `Run-Guaardvark-GUI.cmd` - GUI launcher entry point.
- `Run-Guaardvark-GUI.ps1` - GUI launcher PowerShell implementation.
- `Run-Guaardvark.cmd` - Main Windows launcher entry point.
- `Run-Guaardvark.ps1` - Main PowerShell launcher implementation.
- `ui_wrapper.py` - Desktop wrapper rendering and Linux-only software-rendering compatibility behavior.
- `scripts/wsl_start_launcher_services.sh` - WSL backend/frontend startup, dynamic Windows host-gateway ComfyUI URL, and external-ComfyUI environment propagation.
- `scripts/wsl_prepare_backend_venv.sh` - WSL backend environment preparation and dependency reconciliation.
- `plugins/comfyui/scripts/start.sh` - External Windows ComfyUI detection in desktop mode; Linux launch path remains available outside desktop mode.
- `plugins/comfyui/scripts/stop.sh` - Prevents WSL from killing the Windows-owned ComfyUI instance in desktop mode.

### ComfyUI and Video Generation

- `backend/services/comfyui_video_generator.py` - Wan/CogVideo workflow generation, cancellation propagation, runtime Windows/Linux model-path normalization, FreeU/face-restore handling, VRAM behavior, and generation polling.
- `backend/services/video_model_registry.py` - Shared video model metadata, downloader destinations, model defaults, and requirements.
- `backend/services/video_generation_router.py` - Video backend selection and ComfyUI lifecycle routing.
- `backend/services/batch_video_generator.py` - Batch queueing, retry/restore metadata, cancellation propagation, warm-model behavior, and batch cleanup.
- `backend/api/batch_video_generation_api.py` - Batch video API parameters, model downloads, and request serialization.
- `backend/services/comfyui_image_generator.py` - Image workflow construction and ComfyUI integration.
- `backend/services/gpu_resource_policy.py` - GPU session policy, resource release, and ComfyUI VRAM coordination.
- `backend/services/offline_image_generator.py` - Offline image-generation fallback behavior.
- `backend/services/settings_validator.py` - Generation/settings validation.
- `backend/tests/services/test_i2v_adapter_paths.py` - I2V path and workflow-loader regression coverage.
- `frontend/src/constants/videoGeneratorPresets.js` - Video presets, quality tiers, model defaults, dimensions, and step defaults.
- `frontend/src/pages/VideoGeneratorPage.jsx` - Video-generation controls, advanced toggles, model availability, retry settings, and UI serialization.
- `frontend/src/pages/MusicVideoPage.jsx` - Music-video I2V model and generation settings.
- `frontend/src/pages/BatchImageGeneratorPage.jsx` - Batch image generation UI changes.

### Backend and API Infrastructure

- `backend/__init__.py` - Backend package initialization and exported integrations.
- `backend/api/agent_control_api.py` - Agent control API changes.
- `backend/api/batch_image_generation_api.py` - Batch image generation API changes.
- `backend/api/voice_api.py` - Voice API changes.
- `backend/services/batch_image_generator.py` - Batch image orchestration changes.
- `backend/services/gpu_resource_policy.py` - GPU ownership and cleanup policy changes.
- `backend/services/settings_validator.py` - Shared settings validation changes.

### Frontend and State Management

- `frontend/package-lock.json` - Frontend dependency lockfile updates.
- `frontend/src/components/common/ErrorBoundary.jsx` - Render-safe error handling, including object-shaped error messages.
- `frontend/src/components/dashboard/DashboardCardWrapper.jsx` - Dashboard card behavior/layout changes.
- `frontend/src/components/modals/ImageModelsModal.jsx` - Image model management UI changes.
- `frontend/src/stores/useAppStore.js` - Application state and persistence changes.
- `frontend/vite.config.js` - Frontend development/build configuration.

### Dependency and Startup Reconciliation

- `scripts/dep_reconciler/reconcilers/backend_venv.py` - Backend dependency drift/reconciliation behavior.
- `scripts/dep_reconciler/reconcilers/frontend.py` - Frontend dependency installation and lockfile freshness behavior.
- `start.sh` - Main WSL/Linux startup, health checks, migrations, service ordering, and ComfyUI detection.

### Local-Only Documentation, Launch, and Audit Tooling

These files do not exist in the upstream baseline used for the scoped audit and are tracked here as local implementation/support additions:

- `.env` - Machine-specific runtime configuration. Contains secrets/tokens and is intentionally not reproduced here.
- `docs/LOCAL_ANIMA_UPDATE_NOTES.md` - Local model/update notes.
- `docs/LOCAL_VIDEO_MODEL_UPDATE_NOTES.md` - Local video-model notes.
- `docs/POTENTIAL_IMPROVEMENTS.md` - Deferred launcher/UI improvement notes.
- `launch_guaardvark.sh` - Local launch helper.
- `scripts/generate_scoped_audit_diff.py` - Targeted local-versus-upstream diff generator and exclusion policy.
- `scripts/install_all_models.py` - Local model installation helper.
- `frontend/.npm_stamp` - Local dependency-install marker.
- `GuaardvarkLauncher.pyw` - Local Windows launcher implementation.
- `Run-ComfyUI-Native.cmd` - Local native ComfyUI command wrapper.
- `Run-ComfyUI-Native.ps1` - Local native ComfyUI PowerShell launcher.
- `Run-Guaardvark-GUI.cmd` - Local GUI command wrapper.
- `Run-Guaardvark-GUI.ps1` - Local GUI PowerShell launcher.
- `Run-Guaardvark.cmd` - Local main command wrapper.
- `Run-Guaardvark.ps1` - Local main PowerShell launcher.
- `scripts/wsl_prepare_backend_venv.sh` - Local WSL backend preparation helper.
- `scripts/wsl_start_launcher_services.sh` - Local WSL launcher service coordinator.
- `ui_wrapper.py` - Local desktop wrapper implementation.

## Audit Notes

- `AUDIT_DIFF_SCOPED.md` is the authoritative scoped file inventory for this plan.
- `AUDIT_DIFF_LOCAL_VS_UPSTREAM.md` is broader and includes generated/vendor/runtime material; it should not be used as the implementation scope without filtering.
- The scoped diff generator excludes model/media payloads, logs, caches, virtual environments, binaries, and bundled third-party snapshots.
- Several local-only files overlap conceptually with changed shared files because the local Windows launcher was added alongside upstream WSL/Linux startup paths.
- The audit establishes file differences, not authorship. Items above are marked implemented because the corresponding local changes exist; behavior still requires runtime verification where noted.
- Current runtime verification confirms native Windows ComfyUI is reachable through WSL and reports healthy, with no WSL ComfyUI listener on port `8191`.

## Verification Queue

1. Run a no-override DaSiWa workflow and confirm CFG `1.0` in ComfyUI history.
2. Run an explicit CFG override and inspect the ComfyUI prompt payload.
3. Run a live `Cinema+` render and confirm the RTX node executes after RIFE.
4. Re-run the targeted audit generator and update this inventory if additional plausible source changes appear.

## To Be Implemented

### 1. Make Individual Service Restarts Race-Safe

- **Status:** pending
- Individual backend, frontend, and ComfyUI restart actions currently issue
  stop and start asynchronously. The start step can observe the old listener,
  report the service as already running, and then lose the service when the
  asynchronous stop completes.
- Reuse the full-stack restart state-machine behavior: request stop, wait for
  process/port shutdown, then start and wait for health/readiness. Apply the
  same sequencing to each individual service action.

### 2. Complete the Sampling Steps Override Contract

- **Status:** pending
- The frontend recognizes an explicit `num_inference_steps` edit, but the
  backend currently uses `guidance_scale_overridden` to decide whether both
  CFG and steps may override a model profile.
- Add a separate `num_inference_steps_overridden` flag. CFG changes should
  preserve the existing combined behavior, while steps-only changes must also
  survive model-profile resolution and retry serialization.
- Add focused coverage for steps-only override, in addition to the existing
  CFG-plus-steps case.

### 3. Reduce Windows Shared-Memory Metrics Polling Cost

- **Status:** pending
- The frontend refreshes metrics every two seconds, while the shared-memory
  probe launches `powershell.exe` and invokes `Get-Counter` plus
  `Get-CimInstance`.
- Cache the Windows shared-memory result for approximately 5-10 seconds while
  retaining the two-second refresh cadence for cheap CPU/VRAM metrics. Expose
  the cache age or timestamp for diagnostics if practical.

### 4. Verify and Complete ComfyUI Cancellation Semantics

- **Status:** pending live verification
- Confirm whether cancellation stops GPU work and removes or interrupts the
  associated ComfyUI prompt, rather than only breaking Guaardvark's
  `/history` polling loop.
- Verify all three cases: GPU work stops, the prompt does not remain queued in
  ComfyUI, and no completed output appears after Guaardvark reports
  cancellation. If only the waiting loop is cancelled, document that behavior
  honestly or add ComfyUI interrupt/queue-deletion handling.

### 5. Scope ComfyUI Capability Caching by Server Identity

- **Status:** pending
- `_global_object_info_cache` is process-global and not keyed by ComfyUI URL
  or server identity. A restart with different custom nodes can therefore
  leave Guaardvark advertising stale capabilities.
- Replace it with a URL/server-keyed cache with a TTL, and explicitly
  invalidate the relevant entry after reconnect, restart, or capability-fetch
  failure.

### 6. Validate the Cinema+ Custom-Node Schema

- **Status:** pending
- Checking that `DaSiWa_RTX_UpscalerRefiner` exists is necessary but does not
  prove that its input names, types, or enum values still match the generated
  workflow.
- Either pin and record the supported DaSiWa custom-node revision, or query
  `/object_info` and validate the required input schema before advertising
  Cinema+. Unsupported or changed schemas should hide or disable the preset
  with a clear reason.

## Next Session

- **Vite production build:** implemented. `frontend/scripts/build-wsl.mjs`
  stages source/config on the WSL filesystem, reuses the existing dependency
  tree, builds there, and copies `dist` back to the checkout. The main WSL
  `start.sh` production-build path now uses this wrapper too.
- The build completed successfully in approximately 94 seconds and transformed
  15,235 modules. The remaining optimization opportunity is reducing total
  build time, not resolving a hang.
