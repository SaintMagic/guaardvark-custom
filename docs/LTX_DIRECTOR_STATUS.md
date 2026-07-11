# LTX Director status

This is the maintained implementation and verification note for the LTX Director work. Older audit and diff artifacts are retained locally under `obsolete diffs/` and are not part of the public source checkout.

## Implemented

- Dedicated LTX Director page and navigation entry, isolated from WAN/CogVideo UI logic.
- Versioned sequence documents with atomic JSON persistence, local autosave, stable shot IDs, ordered shot-batch rendering, continuity final-frame extraction, hard-cut stitching, and retry metadata.
- Shared GPU-session ownership for direct sequence shots and generated keyframes.
- Asynchronous individual shot and keyframe child jobs with persisted child state and cancellation events.
- Save-before-render plus optimistic sequence revisions for API updates.
- Restart reconciliation for persisted running sequences.
- Persistent keyframe assets and metadata; Cast subject LoRA and trigger-word resolution reuse the existing Subject model.
- Lightspeed and Quality profiles with safe 576×896 defaults and Bodyphysics disabled by default.
- Normalized global progress states and frame-weighted sequence progress.
- Frontend production build and focused Python tests pass.

## Intentionally gated

- FLF2V remains unavailable in the selectable UI until a native ComfyUI `/prompt` capture proves the actual first/last-frame LTX Director payload. The current adapter structure is not treated as proof.
- Timeline mode remains experimental and blocked for rendering until the real Director timeline payload is captured and compared with the compiler output.
- Temporal upscale, model upscale, color transfer, soundmark, NAG, and optional Sage variants remain capability/schema gated.

## Verification standard

Passing unit tests and `/object_info` checks are not equivalent to a successful render. Before unattended use, capture one known-good native ComfyUI I2V and FLF2V submission, compare the complete `/prompt` payload and ComfyUI history, then run a short fixed-seed 576×896 test with audio, upscale, NAG, and Bodyphysics disabled.

## Remaining engineering work

- Add live FLF2V payload capture/contract test and re-enable the mode only after it passes.
- Add ffprobe-driven stitch normalization, duration validation, and detailed post-processing progress.
- Add frontend refresh/conflict UX for revision conflicts and child-job polling/history.
- Add race, cancellation, restart-recovery, Cast-resolution, frame-weighting, and incomplete-stitch tests.
- Implement native WebView2 taskbar progress only after the browser progress contract remains stable.
