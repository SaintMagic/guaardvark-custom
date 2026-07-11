# LTX Director implementation work log

## Checklist

- [x] Identify the active root source tree and preserve the existing local fork.
- [x] Read the implementation plan, scoped audit inventory, OmniForge explainer, and workflow graph.
- [x] Export the nested OmniForge graph to API form through the installed ComfyUI frontend.
- [x] Probe native ComfyUI node/model availability without installing anything during generation.
- [x] Add the LTX 2.3 registry bundle and exact shared dependency destinations.
- [x] Add schema-aware capability/readiness reporting.
- [x] Add a semantic-role LTX workflow adapter and validation.
- [x] Add the isolated LTX Director API and reuse the existing video batch queue.
- [x] Add a separate modular frontend page, route, navigation entry, persistence, retry, and progress.
- [x] Add focused backend tests and run them.
- [x] Run the WSL-safe frontend production build.
- [x] Generate `LTX_DIRECTOR_IMPLEMENTATION.diff`.

## Runtime observations

- Native ComfyUI is reachable at `http://127.0.0.1:8191`.
- The uploaded workflow is ComfyUI UI format with four nested subgraphs.
- ComfyUI can expand/export the graph, but currently exports eleven custom nodes without
  `class_type` because their node packs are unavailable to this process.
- Missing packs reported by ComfyUI: `comfyui-kjnodes`, `ComfyUI-LTXVideo`,
  `whatdreamscost-comfyui`, and one unknown pack.
- Missing workflow assets reported by ComfyUI: main LTX model, spatial upscaler,
  distilled LoRA, preview VAE, text encoder, and text projection. Audio/video VAEs are
  also treated as mandatory by Guaardvark readiness even when ComfyUI's UI does not
  list them in the initial missing-model panel.
- The workflow warns that ComfyUI Nodes 2.0 beta is incompatible; readiness surfaces
  that warning and generation never attempts automatic node installation.
