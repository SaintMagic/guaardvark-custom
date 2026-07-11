import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  Alert, Box, Button, Card, CardActions, CardContent, Chip, CircularProgress,
  Divider, FormControl, FormControlLabel, Grid, InputLabel, LinearProgress,
  MenuItem, Select, Stack, Switch, TextField, Tooltip, Typography,
} from "@mui/material";
import AutoAwesomeMotionIcon from "@mui/icons-material/AutoAwesomeMotion";
import CloudDownloadIcon from "@mui/icons-material/CloudDownload";
import RefreshIcon from "@mui/icons-material/Refresh";
import ReplayIcon from "@mui/icons-material/Replay";
import StopIcon from "@mui/icons-material/Stop";

import PageLayout from "../components/layout/PageLayout";
import GpuGateBanner from "../components/common/GpuGateBanner";
import LTXFileField from "../components/ltx-director/LTXFileField";
import LTXLoraStackEditor from "../components/ltx-director/LTXLoraStackEditor";
import LTXSection from "../components/ltx-director/LTXSection";
import LTXShotList from "../components/ltx-director/LTXShotList";
import useBatchVideo from "../hooks/useBatchVideo";
import useJobsGate from "../hooks/useJobsGate";
import {
  DEFAULT_LTX_CONFIG, LTX_MODEL_OPTIONS, LTX_STORAGE_KEY, LTX_WORKFLOW_PRESETS, MODE_HELP, QUALITY_PRESETS, mergeLtxConfig,
} from "../constants/ltxDirectorPresets";

const API_BASE = import.meta.env.VITE_API_BASE_URL || "/api";

const pathFromUrl = (value) => String(value || "").replaceAll("\\", "/").split("/").filter(Boolean).pop() || "output.mp4";
const encodePathSegments = (value) => String(value || "").split("/").filter(Boolean).map(encodeURIComponent).join("/");
const resultVideoUrl = (batchId, result) => result?.video_path
  ? `${API_BASE}/batch-video/video/${batchId}/${encodePathSegments(pathFromUrl(result.video_path))}`
  : "";

const apiErrorText = (payload, fallback) => {
  const error = payload?.error;
  if (typeof error === "string" && error.trim()) return error;
  if (error && typeof error === "object") {
    if (typeof error.message === "string" && error.message.trim()) return error.message;
    if (typeof error.detail === "string" && error.detail.trim()) return error.detail;
    if (typeof error.details === "string" && error.details.trim()) return error.details;
    try { return JSON.stringify(error); } catch { return fallback; }
  }
  if (typeof payload?.message === "string" && payload.message.trim()) return payload.message;
  return fallback;
};

const normalizeLoraName = (value) => String(value || "").trim().replaceAll("\\", "/").toLowerCase();
const loraLabel = (value) => String(value || "").split(/[\\/]/).pop() || value;
const canonicalLoraValue = (value, choices) => choices.find((item) => normalizeLoraName(item) === normalizeLoraName(value)) || value || "";
const choicesWithCurrent = (choices, current) => {
  const selected = canonicalLoraValue(current, choices);
  return choices.some((item) => normalizeLoraName(item) === normalizeLoraName(selected))
    ? choices
    : selected ? [selected, ...choices] : choices;
};

const readSaved = () => {
  try {
    const parsed = JSON.parse(localStorage.getItem(LTX_STORAGE_KEY) || "null");
    const merged = parsed && typeof parsed === "object" ? mergeLtxConfig(DEFAULT_LTX_CONFIG, parsed) : DEFAULT_LTX_CONFIG;
    // Migrate stale saved configs until the native Windows Sage runtime is
    // explicitly validated; never restore the crashing experimental mode.
    return { ...merged, sage_attention: "off" };
  } catch {
    return DEFAULT_LTX_CONFIG;
  }
};

const NumberField = ({ label, value, onChange, min, max, step = 1, disabled = false, helperText }) => (
  <TextField
    fullWidth size="small" type="number" label={label} value={value}
    inputProps={{ min, max, step }} disabled={disabled} helperText={helperText}
    onChange={(event) => onChange(Number(event.target.value))}
  />
);

const SelectField = ({ label, value, onChange, children, disabled = false, helperText }) => (
  <FormControl fullWidth size="small" disabled={disabled}>
    <InputLabel>{label}</InputLabel>
    <Select label={label} value={value} onChange={(event) => onChange(event.target.value)}>{children}</Select>
    {helperText ? <Typography variant="caption" color="text.secondary" sx={{ mt: 0.5 }}>{helperText}</Typography> : null}
  </FormControl>
);

function PassControls({ name, value, onChange, canDisable = true }) {
  const set = (key, next) => onChange({ ...value, [key]: next });
  return (
    <Grid container spacing={1.5} alignItems="center">
      <Grid item xs={12} sm={2}>
        <FormControlLabel control={<Switch checked={value.enabled} disabled={!canDisable} onChange={(event) => set("enabled", event.target.checked)} />} label={name} />
      </Grid>
      <Grid item xs={6} sm={2}><NumberField label="CFG" value={value.cfg} min={0} max={20} step={0.1} disabled={!value.enabled} onChange={(next) => set("cfg", next)} /></Grid>
      <Grid item xs={6} sm={2}><NumberField label="Steps" value={value.steps} min={1} max={100} disabled={!value.enabled} onChange={(next) => set("steps", next)} /></Grid>
      <Grid item xs={6} sm={3}>
        <SelectField label="Scheduler" value={value.scheduler} disabled={!value.enabled} onChange={(next) => set("scheduler", next)}>
          {["linear_quadratic", "simple", "normal", "sgm_uniform", "karras"].map((item) => <MenuItem key={item} value={item}>{item}</MenuItem>)}
        </SelectField>
      </Grid>
      <Grid item xs={6} sm={3}><NumberField label="Denoise" value={value.denoise} min={0.01} max={1} step={0.01} disabled={!value.enabled} onChange={(next) => set("denoise", next)} /></Grid>
    </Grid>
  );
}

export default function LTXDirectorPage() {
  const [config, setConfig] = useState(readSaved);
  const [capabilities, setCapabilities] = useState(null);
  const [models, setModels] = useState([]);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [cinematicRewrite, setCinematicRewrite] = useState(false);
  const [enhancePrompt, setEnhancePrompt] = useState(false);
  const [exactText, setExactText] = useState(false);
  const [rewriteGuidance, setRewriteGuidance] = useState("");
  const { gpuBlocked, blockReason } = useJobsGate();
  const batch = useBatchVideo({ setError, setSuccess, computedParams: { fps: config.fps } });

  const set = useCallback((key, value) => setConfig((current) => ({
    ...current,
    [key]: value,
    ...(key !== "performance_profile" && key !== "profile_id" ? { performance_profile: "custom" } : {}),
  })), []);
  const setNested = useCallback((key, patch) => setConfig((current) => ({
    ...current,
    [key]: { ...current[key], ...patch },
    performance_profile: "custom",
  })), []);

  useEffect(() => {
    try { localStorage.setItem(LTX_STORAGE_KEY, JSON.stringify(config)); } catch { /* storage can be unavailable */ }
  }, [config]);

  const refreshReadiness = useCallback(async (force = false) => {
    setLoading(true);
    try {
      const [capResponse, modelResponse] = await Promise.all([
        fetch(`${API_BASE}/ltx-director/capabilities?model=${encodeURIComponent(config.model_id)}&refresh=${force}`),
        fetch(`${API_BASE}/batch-video/models`),
      ]);
      const capPayload = await capResponse.json();
      const modelPayload = await modelResponse.json();
      setCapabilities(capPayload.data || null);
      setModels(modelPayload.data?.models || []);
    } catch (fetchError) {
      setError(fetchError.message);
    } finally {
      setLoading(false);
    }
  }, [config.model_id]);

  useEffect(() => { refreshReadiness(); }, [refreshReadiness]);

  const totalFrames = useMemo(() => Math.max(8, Math.ceil((config.duration_seconds * config.fps) / 8) * 8), [config.duration_seconds, config.fps]);
  const optional = capabilities?.optional_features || {};
  const availableLoras = useMemo(() => capabilities?.available_loras || [], [capabilities]);
  const loraLimit = capabilities?.lora_limit || 12;
  const reservedLoraSlots = Number(Boolean(config.distilled_lora)) + Number(Boolean(config.bodyphysics_lora));
  const bodyphysicsValue = canonicalLoraValue(config.bodyphysics_lora_name, availableLoras);
  const distilledValue = canonicalLoraValue(config.distilled_lora_name, availableLoras);
  const ltxBatches = useMemo(() => batch.batches.filter((item) => item.metadata?.engine === "ltx-director"), [batch.batches]);
  const active = batch.batchStatus;

  const applyPreset = (preset) => setConfig((current) => ({ ...mergeLtxConfig(current, QUALITY_PRESETS[preset].patch), performance_profile: "custom" }));
  const applyWorkflowPreset = (preset) => setConfig((current) => mergeLtxConfig(current, LTX_WORKFLOW_PRESETS[preset].patch));

  const installModel = async () => {
    setError("");
    const response = await fetch(`${API_BASE}/batch-video/models/download`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ model_id: config.model_id }),
    });
    const payload = await response.json();
    if (!response.ok || !payload.success) setError(apiErrorText(payload, "Could not start model install"));
    else setSuccess("LTX model bundle download started. Custom nodes still require explicit setup and a ComfyUI restart.");
  };

  const submit = async () => {
    setError("");
    setSuccess("");
    setSubmitting(true);
    try {
      const body = {
        config,
        ui_config: config,
        enhance_prompt: enhancePrompt,
        fidelity_mode: exactText,
        cinematic_prompt_rewrite: cinematicRewrite,
        cinematic_prompt_guidance: rewriteGuidance,
      };
      const response = await fetch(`${API_BASE}/ltx-director/generate`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
      });
      const payload = await response.json();
      if (!response.ok || !payload.success) throw new Error(apiErrorText(payload, `Generation failed: HTTP ${response.status}`));
      batch.setActiveBatchId(payload.data.batch_id);
      batch.setBatchStatus(null);
      batch.startPollingStatus(payload.data.batch_id);
      await batch.fetchBatches();
      await batch.fetchQueue();
      setSuccess(`LTX Director queued as ${payload.data.batch_id}.`);
    } catch (submitError) {
      setError(submitError.message);
    } finally {
      setSubmitting(false);
    }
  };

  const adjustRetry = async (batchId) => {
    try {
      const response = await fetch(`${API_BASE}/batch-video/status/${batchId}`);
      const payload = await response.json();
      const snapshot = payload.data?.retry_data?.params?.ui_config;
      if (!snapshot) throw new Error("This batch has no complete LTX UI snapshot.");
      setConfig({ ...mergeLtxConfig(DEFAULT_LTX_CONFIG, snapshot), sage_attention: "off" });
      window.scrollTo({ top: 0, behavior: "smooth" });
      setSuccess("Restored the complete LTX Director settings. Adjust them and submit when ready.");
    } catch (restoreError) {
      setError(restoreError.message);
    }
  };

  const sourceReady = config.mode === "t2v" || (config.mode === "i2v" && config.source_image) || (config.mode === "flf2v" && config.source_image && config.last_frame) || (config.mode === "v2v" && config.source_video);
  const submitDisabled = submitting || gpuBlocked || !capabilities?.ready || !config.prompt.trim() || !sourceReady;

  return (
    <PageLayout title="LTX Director" subtitle="Full LTX 2.3 OmniForge generation, isolated from the Wan/CogVideo page.">
      <Stack spacing={2}>
        <GpuGateBanner gpuBlocked={gpuBlocked} blockReason={blockReason} />
        {error ? <Alert severity="error" onClose={() => setError("")}>{error}</Alert> : null}
        {success ? <Alert severity="success" onClose={() => setSuccess("")}>{success}</Alert> : null}
        <Alert severity={capabilities?.ready ? "success" : "warning"} action={<Button color="inherit" size="small" startIcon={<RefreshIcon />} onClick={() => refreshReadiness(true)}>Recheck</Button>}>
          {loading ? "Checking native ComfyUI and LTX assets…" : capabilities?.ready
            ? "LTX Director runtime is ready."
            : `Setup required. Missing models: ${(capabilities?.missing_models || []).join(", ") || "none"}. Missing nodes: ${(capabilities?.missing_nodes || []).join(", ") || "none"}.`}
          <Typography variant="caption" display="block">{capabilities?.nodes_2_beta_warning}</Typography>
        </Alert>

        <LTXShotList globalConfig={config} onGlobalConfigChange={setConfig} />

        <LTXSection title="Mode and source inputs" description="Each mode has an explicit source contract." badge={config.mode.toUpperCase()} defaultExpanded>
          <Grid container spacing={2}>
            <Grid item xs={12} sm={4}>
              <SelectField label="Generation mode" value={config.mode} onChange={(value) => set("mode", value)}>
                {Object.entries(MODE_HELP).map(([value, label]) => <MenuItem key={value} value={value}>{value.toUpperCase()} — {label}</MenuItem>)}
              </SelectField>
            </Grid>
            <Grid item xs={12} sm={8}><Typography variant="body2" color="text.secondary">{MODE_HELP[config.mode]}</Typography></Grid>
            {config.mode === "i2v" || config.mode === "flf2v" ? <Grid item xs={12} sm={6}><LTXFileField label="Upload first/source image" kind="image" accept="image/*" value={config.source_image} onChange={(value) => set("source_image", value)} /></Grid> : null}
            {config.mode === "flf2v" ? <Grid item xs={12} sm={6}><LTXFileField label="Upload last frame" kind="image" accept="image/*" value={config.last_frame} onChange={(value) => set("last_frame", value)} /></Grid> : null}
            {config.mode === "v2v" ? <Grid item xs={12}><LTXFileField label="Upload source video" kind="video" accept="video/*" value={config.source_video} onChange={(value) => set("source_video", value)} /></Grid> : null}
          </Grid>
        </LTXSection>

        <LTXSection title="Prompt and LTX timeline" description="LTX timeline conditioning is distinct from Guaardvark's optional prompt rewrite." defaultExpanded>
          <Stack spacing={2}>
            <TextField multiline minRows={4} label="Global prompt" value={config.prompt} onChange={(event) => set("prompt", event.target.value)} />
            <TextField multiline minRows={2} label="Negative prompt" value={config.negative_prompt} onChange={(event) => set("negative_prompt", event.target.value)} />
            <Grid container spacing={2}>
              <Grid item xs={12} sm={4}><NumberField label="Visual guide strength" value={config.guide_strength} min={0} max={2} step={0.05} onChange={(value) => set("guide_strength", value)} /></Grid>
              <Grid item xs={12} sm={4}><NumberField label="Motion guide strength" value={config.motion_guide_strength} min={0} max={2} step={0.05} onChange={(value) => set("motion_guide_strength", value)} /></Grid>
              <Grid item xs={12} sm={4}><NumberField label="Timeline segments" value={config.timeline_segments.length} disabled helperText="Serialized in the complete UI snapshot; visual segment editor is the next safe extension." /></Grid>
            </Grid>
            <Divider />
            <Typography variant="subtitle2">Guaardvark prompt preprocessing</Typography>
            <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
              <FormControlLabel control={<Switch checked={cinematicRewrite} onChange={(event) => setCinematicRewrite(event.target.checked)} />} label="Cinematic prompt rewrite" />
              <FormControlLabel control={<Switch checked={enhancePrompt} onChange={(event) => setEnhancePrompt(event.target.checked)} />} label="Enhance prompt" />
              <FormControlLabel control={<Switch checked={exactText} onChange={(event) => setExactText(event.target.checked)} />} label="Exact text / light enhance" />
            </Stack>
            <TextField label="Prompt rewrite guidance" value={rewriteGuidance} onChange={(event) => setRewriteGuidance(event.target.value)} disabled={!cinematicRewrite} helperText="Steers Guaardvark's text rewrite; it does not replace LTX timeline conditioning." />
          </Stack>
        </LTXSection>

        <Box>
          <Typography variant="subtitle1" sx={{ mb: 0.5 }}>Workflow presets</Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>Apply the intended LTX sampling path without changing your prompt or source inputs.</Typography>
          <Stack direction={{ xs: "column", sm: "row" }} spacing={1} sx={{ mb: 2 }}>
            {Object.entries(LTX_WORKFLOW_PRESETS).map(([key, preset]) => <Tooltip key={key} title={preset.description}>
              <Button variant={config.performance_profile === key ? "contained" : "outlined"} onClick={() => applyWorkflowPreset(key)}>{preset.label}</Button>
            </Tooltip>)}
          </Stack>
        </Box>

        <LTXSection title="Audio source and settings" badge={config.audio_source}>
          <Grid container spacing={2}>
            <Grid item xs={12} sm={5}>
              <SelectField label="Audio source" value={config.audio_source} onChange={(value) => set("audio_source", value)}>
                <MenuItem value="generated">Model-generated audio</MenuItem>
                <MenuItem value="uploaded">Uploaded audio</MenuItem>
                <MenuItem value="source" disabled={config.mode !== "v2v"}>Source-video audio</MenuItem>
                <MenuItem value="none">No audio</MenuItem>
              </SelectField>
            </Grid>
            {config.audio_source === "uploaded" ? <Grid item xs={12} sm={7}><LTXFileField label="Upload audio" kind="audio" accept="audio/*" value={config.uploaded_audio} onChange={(value) => set("uploaded_audio", value)} /></Grid> : null}
            <Grid item xs={12}><FormControlLabel disabled control={<Switch checked={config.soundmark.enabled} />} label="Soundmark — represented but disabled until the installed node exposes a stable API schema" /></Grid>
          </Grid>
        </LTXSection>

        <LTXSection title="Model and runtime selection" badge={config.model_format.toUpperCase()}>
          <Grid container spacing={2}>
            <Grid item xs={12} sm={6}>
              <SelectField label="LTX model" value={config.model_id} onChange={(value) => {
                const selected = LTX_MODEL_OPTIONS[value];
                if (!selected) return;
                setConfig((current) => ({
                  ...current,
                  model_id: value,
                  model_format: selected.model_format,
                  model_name: selected.model_name,
                }));
              }}>
                {Object.entries(LTX_MODEL_OPTIONS).map(([value, item]) => (
                  <MenuItem key={value} value={value}>{item.label}</MenuItem>
                ))}
              </SelectField>
            </Grid>
            <Grid item xs={12} sm={6}><Button fullWidth variant="outlined" startIcon={<CloudDownloadIcon />} onClick={installModel}>Install model bundle</Button></Grid>
            {["text_encoder", "text_projection", "video_vae", "audio_vae", "preview_vae"].map((key) => <Grid item xs={12} sm={6} key={key}><TextField fullWidth size="small" label={key.replaceAll("_", " ")} value={config[key]} onChange={(event) => set(key, event.target.value)} /></Grid>)}
            <Grid item xs={12}><Typography variant="caption">Custom nodes are never installed during generation. Install the listed packs explicitly, restart native ComfyUI, then use Recheck.</Typography></Grid>
          </Grid>
        </LTXSection>

        <LTXSection title="Resolution, FPS and duration" badge={`${config.width}×${config.height} · ${totalFrames} frames`}>
          <Stack direction="row" spacing={1} sx={{ mb: 2 }}>{Object.entries(QUALITY_PRESETS).map(([key, preset]) => <Button key={key} size="small" variant="outlined" onClick={() => applyPreset(key)}>{preset.label}</Button>)}</Stack>
          <Grid container spacing={2}>
            <Grid item xs={6} sm={2}><NumberField label="Width" value={config.width} min={256} max={4096} step={8} onChange={(value) => set("width", value)} /></Grid>
            <Grid item xs={6} sm={2}><NumberField label="Height" value={config.height} min={256} max={4096} step={8} onChange={(value) => set("height", value)} /></Grid>
            <Grid item xs={6} sm={2}><NumberField label="FPS" value={config.fps} min={1} max={60} onChange={(value) => set("fps", value)} /></Grid>
            <Grid item xs={6} sm={3}><NumberField label="Duration (seconds)" value={config.duration_seconds} min={0.5} max={120} step={0.5} onChange={(value) => set("duration_seconds", value)} /></Grid>
            <Grid item xs={12} sm={3}><NumberField label="Seed" value={config.seed} min={0} max={2147483647} onChange={(value) => set("seed", value)} /></Grid>
          </Grid>
        </LTXSection>

        <LTXSection title="Passes and sampling" badge={`${config.pass2.enabled ? 2 : 1}${config.pass3.enabled ? "+1" : ""} pass`} defaultExpanded>
          <Stack spacing={2} divider={<Divider flexItem />}>
            <PassControls name="Pass 1" value={config.pass1} canDisable={false} onChange={(value) => set("pass1", value)} />
            <PassControls name="Pass 2 + spatial 2×" value={config.pass2} onChange={(value) => set("pass2", value)} />
            <PassControls name="Pass 3" value={config.pass3} onChange={(value) => set("pass3", value)} />
            <SelectField label="Sampler" value={config.sampler} onChange={(value) => set("sampler", value)}>
              {["euler_cfg_pp", "euler", "dpmpp_2m", "uni_pc"].map((item) => <MenuItem key={item} value={item}>{item}</MenuItem>)}
            </SelectField>
          </Stack>
        </LTXSection>

        <LTXSection title="Chunking and VRAM headroom" badge={`${config.vram_headroom}× headroom`}>
          <Grid container spacing={2}>
            <Grid item xs={12} sm={4}><FormControlLabel control={<Switch checked={config.chunking} disabled={!optional.LTXVChunkFeedForward} onChange={(event) => set("chunking", event.target.checked)} />} label="Chunk feed-forward" /></Grid>
            <Grid item xs={6} sm={2}><NumberField label="Chunks" value={config.chunk_count} min={1} max={100} disabled={!config.chunking} onChange={(value) => set("chunk_count", value)} /></Grid>
            <Grid item xs={6} sm={3}><NumberField label="Dimension threshold" value={config.chunk_dim_threshold} min={0} max={16384} step={256} disabled={!config.chunking} onChange={(value) => set("chunk_dim_threshold", value)} /></Grid>
            <Grid item xs={12} sm={3}><NumberField label="VRAM headroom" value={config.vram_headroom} min={1} max={4} step={0.5} onChange={(value) => set("vram_headroom", value)} helperText="1=24GB, 2=16GB, 3=12GB, 4=8GB" /></Grid>
            <Grid item xs={12}><FormControlLabel control={<Switch checked={false} disabled />} label="FP16 accumulation — unavailable because ModelPatchTorchSettings is not exposed by this runtime" /></Grid>
          </Grid>
        </LTXSection>

        <LTXSection title="VAE decode options" badge={config.tiled_vae ? "Tiled" : "Full"}>
          <Grid container spacing={2} alignItems="center">
            <Grid item xs={12} sm={4}><FormControlLabel control={<Switch checked={config.tiled_vae} disabled={!optional.LTXVSpatioTemporalTiledVAEDecode} onChange={(event) => set("tiled_vae", event.target.checked)} />} label="Tiled VAE decode" /></Grid>
            <Grid item xs={6} sm={2}><NumberField label="Spatial tiles" value={config.tiled_spatial_tiles} min={1} max={8} disabled={!config.tiled_vae} onChange={(value) => set("tiled_spatial_tiles", value)} /></Grid>
            <Grid item xs={6} sm={2}><NumberField label="Spatial overlap" value={config.tiled_spatial_overlap} min={0} max={8} disabled={!config.tiled_vae} onChange={(value) => set("tiled_spatial_overlap", value)} /></Grid>
            <Grid item xs={6} sm={2}><NumberField label="Temporal length" value={config.tiled_temporal_tile_length} min={2} max={1000} disabled={!config.tiled_vae} onChange={(value) => set("tiled_temporal_tile_length", value)} /></Grid>
            <Grid item xs={6} sm={2}><NumberField label="Temporal overlap" value={config.tiled_temporal_overlap} min={0} max={8} disabled={!config.tiled_vae} onChange={(value) => set("tiled_temporal_overlap", value)} /></Grid>
            <Grid item xs={12} sm={4}><SelectField label="Working device" value={config.tiled_working_device} disabled={!config.tiled_vae} onChange={(value) => set("tiled_working_device", value)}><MenuItem value="auto">auto</MenuItem><MenuItem value="cpu">cpu</MenuItem></SelectField></Grid>
            <Grid item xs={12} sm={4}><SelectField label="Working dtype" value={config.tiled_working_dtype} disabled={!config.tiled_vae} onChange={(value) => set("tiled_working_dtype", value)}><MenuItem value="auto">auto</MenuItem><MenuItem value="float16">float16</MenuItem><MenuItem value="float32">float32</MenuItem></SelectField></Grid>
            <Grid item xs={12} sm={4}><FormControlLabel control={<Switch checked={config.tiled_last_frame_fix} disabled={!config.tiled_vae} onChange={(event) => set("tiled_last_frame_fix", event.target.checked)} />} label="Last-frame fix" /></Grid>
            <Grid item xs={12}><Typography variant="caption">These controls match the live LTX tiled-decoder schema. Tiled decode reduces peak VRAM but is slower.</Typography></Grid>
          </Grid>
        </LTXSection>

        <LTXSection title="Upscaling and post-processing">
          <Grid container spacing={2}>
            <Grid item xs={12} sm={4}><FormControlLabel control={<Switch checked={config.simple_upscale} disabled={!optional.ImageScaleBy} onChange={(event) => set("simple_upscale", event.target.checked)} />} label="Simple 2× upscale" /></Grid>
            <Grid item xs={12} sm={4}><FormControlLabel control={<Switch checked={config.rtx.enabled} disabled={!optional.DaSiWa_RTX_UpscalerRefiner} onChange={(event) => setNested("rtx", { enabled: event.target.checked })} />} label="RTX upscaler/refiner" /></Grid>
            <Grid item xs={12} sm={4}><NumberField label="RTX scale" value={config.rtx.scale} min={1} max={4} step={0.25} disabled={!config.rtx.enabled} onChange={(value) => setNested("rtx", { scale: value })} /></Grid>
            <Grid item xs={12}><FormControlLabel disabled control={<Switch checked={config.temporal_upscale} />} label="Temporal latent 2× — model is managed, but disabled until the installed temporal node schema is validated" /></Grid>
            <Grid item xs={12}><FormControlLabel disabled control={<Switch checked={config.model_upscale} />} label="Model-based upscale — disabled until UpscaleWithModelAdvanced is available" /></Grid>
            <Grid item xs={12}><FormControlLabel disabled control={<Switch checked={config.color_transfer.enabled} />} label="Color transfer — disabled because the source reference routing is not API-safe on this runtime" /></Grid>
          </Grid>
        </LTXSection>

        <LTXSection title="LoRAs" badge={`${reservedLoraSlots + config.loras.length}/${loraLimit} slots`}>
          <Stack spacing={2}>
            {!optional.DaSiWa_LTX2LoraLoader ? (
              <Alert severity="warning">The installed ComfyUI runtime does not expose the DaSiWa LTX-2 LoRA Loader. LoRA controls are disabled.</Alert>
            ) : null}
            <Grid container spacing={2} alignItems="center">
              <Grid item xs={12} md={3}>
                <FormControlLabel
                  control={<Switch checked={config.bodyphysics_lora} disabled={!optional.DaSiWa_LTX2LoraLoader} onChange={(event) => set("bodyphysics_lora", event.target.checked)} />}
                  label="DaSiWa Bodyphysics enhancer"
                />
              </Grid>
              <Grid item xs={12} md={6}>
                <SelectField
                  label="Bodyphysics LoRA file"
                  value={bodyphysicsValue}
                  disabled={!config.bodyphysics_lora || !optional.DaSiWa_LTX2LoraLoader}
                  onChange={(value) => set("bodyphysics_lora_name", value)}
                >
                  {choicesWithCurrent(availableLoras, bodyphysicsValue).map((item) => <MenuItem key={item} value={item}>{loraLabel(item)}</MenuItem>)}
                </SelectField>
              </Grid>
              <Grid item xs={12} md={3}>
                <NumberField label="Bodyphysics strength" value={config.bodyphysics_lora_strength} min={-2} max={2} step={0.05} disabled={!config.bodyphysics_lora} onChange={(value) => set("bodyphysics_lora_strength", value)} />
              </Grid>

              <Grid item xs={12} md={3}>
                <FormControlLabel
                  control={<Switch checked={config.distilled_lora} disabled={!optional.DaSiWa_LTX2LoraLoader} onChange={(event) => set("distilled_lora", event.target.checked)} />}
                  label="Distilled / lightspeed LoRA"
                />
              </Grid>
              <Grid item xs={12} md={6}>
                <SelectField
                  label="Distilled LoRA file"
                  value={distilledValue}
                  disabled={!config.distilled_lora || !optional.DaSiWa_LTX2LoraLoader}
                  onChange={(value) => set("distilled_lora_name", value)}
                >
                  {choicesWithCurrent(availableLoras, distilledValue).map((item) => <MenuItem key={item} value={item}>{loraLabel(item)}</MenuItem>)}
                </SelectField>
              </Grid>
              <Grid item xs={12} md={3}>
                <NumberField label="Distilled strength" value={config.distilled_lora_strength} min={-2} max={2} step={0.05} disabled={!config.distilled_lora} onChange={(value) => set("distilled_lora_strength", value)} />
              </Grid>
            </Grid>

            <Divider />
            <Typography variant="subtitle2">Additional installed LTX LoRAs</Typography>
            <LTXLoraStackEditor
              value={config.loras}
              onChange={(value) => set("loras", value)}
              availableLoras={availableLoras}
              disabled={!optional.DaSiWa_LTX2LoraLoader}
              reservedSlots={reservedLoraSlots}
              reservedNames={[
                ...(config.bodyphysics_lora ? [bodyphysicsValue] : []),
                ...(config.distilled_lora ? [distilledValue] : []),
              ]}
              limit={loraLimit}
            />
            <Typography variant="caption" color="text.secondary">
              The list comes directly from the live DaSiWa node. Master strength is multiplied by the separate video and audio multipliers. Duplicate files are blocked and the backend revalidates every selection before queueing.
            </Typography>
          </Stack>
        </LTXSection>

        <LTXSection title="Advanced and experimental">
          <Grid container spacing={2}>
            <Grid item xs={12} sm={4}><SelectField label="SageAttention" value={config.sage_attention} onChange={(value) => set("sage_attention", value)} helperText="Memory-efficient mode uses the installed Triton kernels; KJ patch exposes its own kernel selector."><MenuItem value="off">Off</MenuItem><MenuItem value="memory_efficient" disabled={!optional.LTX2MemoryEfficientSageAttentionPatch}>Memory-efficient + Triton</MenuItem><MenuItem value="patch" disabled={!optional.PathchSageAttentionKJ}>KJ Sage patch</MenuItem></SelectField></Grid>
            <Grid item xs={12} sm={4}><FormControlLabel control={<Switch checked={config.sage_triton_kernels} disabled={config.sage_attention !== "memory_efficient"} onChange={(event) => set("sage_triton_kernels", event.target.checked)} />} label="Use Triton fused kernels" /></Grid>
            <Grid item xs={12} sm={4}><SelectField label="KJ Sage kernel" value={config.sage_kernel} disabled={config.sage_attention !== "patch"} onChange={(value) => set("sage_kernel", value)}><MenuItem value="auto">auto</MenuItem><MenuItem value="sageattn_qk_int8_pv_fp16_triton">INT8 QK / FP16 PV Triton</MenuItem><MenuItem value="sageattn_qk_int8_pv_fp16_cuda">INT8 QK / FP16 PV CUDA</MenuItem><MenuItem value="sageattn_qk_int8_pv_fp8_cuda">INT8 QK / FP8 PV CUDA</MenuItem><MenuItem value="sageattn3">SageAttention 3</MenuItem></SelectField></Grid>
            <Grid item xs={12} sm={3}><FormControlLabel control={<Switch checked={config.nag.enabled} disabled={!optional.LTX2_NAG} onChange={(event) => setNested("nag", { enabled: event.target.checked })} />} label="NAG" /></Grid>
            <Grid item xs={6} sm={2}><NumberField label="NAG scale" value={config.nag.scale} min={0} max={100} step={0.25} disabled={!config.nag.enabled} onChange={(value) => setNested("nag", { scale: value })} /></Grid>
            <Grid item xs={6} sm={2}><NumberField label="NAG alpha" value={config.nag.alpha} min={0} max={1} step={0.05} disabled={!config.nag.enabled} onChange={(value) => setNested("nag", { alpha: value })} /></Grid>
            <Grid item xs={6} sm={2}><NumberField label="NAG tau" value={config.nag.tau} min={0} max={10} step={0.1} disabled={!config.nag.enabled} onChange={(value) => setNested("nag", { tau: value })} /></Grid>
            <Grid item xs={6} sm={3}><FormControlLabel control={<Switch checked={config.nag.inplace !== false} disabled={!config.nag.enabled} onChange={(event) => setNested("nag", { inplace: event.target.checked })} />} label="NAG in-place" /></Grid>
            <Grid item xs={12}><FormControlLabel control={<Switch checked={config.watermark.enabled} disabled={!optional.DaSiWa_Watermark} onChange={(event) => setNested("watermark", { enabled: event.target.checked })} />} label="Watermark" /></Grid>
          </Grid>
        </LTXSection>

        <LTXSection title="Output encoding" badge={config.output_format.replace("video/", "")}>
          <Grid container spacing={2}>
            <Grid item xs={12} sm={5}><SelectField label="VHS output format" value={config.output_format} onChange={(value) => set("output_format", value)}><MenuItem value="video/h264-mp4">H.264 MP4 (safe default)</MenuItem><MenuItem value="video/h265-mp4">H.265 MP4</MenuItem><MenuItem value="video/webm">VP9 WebM</MenuItem><MenuItem value="video/av1-webm">AV1 WebM</MenuItem></SelectField></Grid>
            <Grid item xs={6} sm={2}><NumberField label="CRF" value={config.crf} min={0} max={51} onChange={(value) => set("crf", value)} /></Grid>
            <Grid item xs={6} sm={2}><SelectField label="Pixel format" value={config.pix_fmt} onChange={(value) => set("pix_fmt", value)}><MenuItem value="yuv420p">yuv420p</MenuItem><MenuItem value="yuv420p10le">yuv420p10le</MenuItem></SelectField></Grid>
            <Grid item xs={12} sm={3}><FormControlLabel control={<Switch checked={config.save_metadata} onChange={(event) => set("save_metadata", event.target.checked)} />} label="Embed metadata" /></Grid>
          </Grid>
        </LTXSection>

        <Card variant="outlined">
          <CardContent>
            <Typography variant="h6">Computed settings</Typography>
            <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap" sx={{ mt: 1 }}>
              <Chip label={`${config.mode.toUpperCase()} · ${config.duration_seconds}s`} />
              <Chip label={`${config.width}×${config.height}`} />
              <Chip label={`${config.fps} fps · ${totalFrames} aligned frames`} />
              <Chip label={`${config.pass1.steps}/${config.pass2.enabled ? config.pass2.steps : "off"}/${config.pass3.enabled ? config.pass3.steps : "off"} steps`} />
              <Chip label={`${config.audio_source} audio`} />
              <Chip label={config.tiled_vae ? "tiled VAE" : "full VAE"} />
              <Chip label={`CFG ${config.pass1.cfg}${config.pass2.enabled ? `/${config.pass2.cfg}` : ""}${config.pass3.enabled ? `/${config.pass3.cfg}` : ""}`} />
              <Chip label={`${config.sampler} · ${config.pass1.scheduler}`} />
              <Chip label={`Sage ${config.sage_attention === "off" ? "off" : config.sage_attention}${config.sage_attention !== "off" && config.sage_triton_kernels ? " + Triton" : ""}`} />
              <Chip label={`${config.distilled_lora || config.bodyphysics_lora || (config.loras || []).some((item) => item?.enabled) ? "LoRA on" : "LoRA off"}`} />
              <Chip label={config.chunking ? `chunking ${config.chunk_count}` : "no chunking"} />
              <Chip label={config.nag?.enabled ? "NAG on" : "NAG off"} />
              <Chip label={config.temporal_upscale || config.simple_upscale || config.model_upscale || config.rtx?.enabled ? "post-upscale on" : "no post-upscale"} />
              <Chip label={config.output_format.replace("video/", "").toUpperCase()} />
            </Stack>
          </CardContent>
          <CardActions>
            <Tooltip title={!capabilities?.ready ? "Install missing models/nodes and recheck first." : ""}>
              <span><Button variant="contained" size="large" startIcon={submitting ? <CircularProgress size={18} /> : <AutoAwesomeMotionIcon />} disabled={submitDisabled} onClick={submit}>Generate with LTX Director</Button></span>
            </Tooltip>
            {active && ["queued", "running", "processing"].includes(active.status) ? <Button color="error" startIcon={<StopIcon />} onClick={() => batch.handleCancelBatch(active.batch_id)}>Cancel</Button> : null}
          </CardActions>
          {active ? (() => {
            const total = Math.max(1, Number(active.total_videos || 1));
            const completed = Number(active.completed_videos || 0);
            const computedProgress = active.status === "completed"
              ? 100
              : (active.progress != null ? Number(active.progress) : (completed / total) * 100);
            const results = (active.results || []).filter((result) => result?.video_path);
            return <Box sx={{ px: 2, pb: 2 }}>
              <Typography variant="body2">{active.status} · {completed}/{total} · {Math.round(Math.max(0, Math.min(100, computedProgress)))}%</Typography>
              <LinearProgress variant="determinate" value={Math.max(0, Math.min(100, computedProgress))} />
              {results.map((result, index) => {
                const url = resultVideoUrl(active.batch_id, result);
                return <Box key={`${result.video_path}-${index}`} sx={{ mt: 1 }}>
                  <Button size="small" component="a" href={url} target="_blank" rel="noreferrer">Open video {index + 1}</Button>
                  <Box component="video" controls preload="metadata" src={url} sx={{ display: "block", width: "100%", maxHeight: 360, mt: 1, borderRadius: 1 }} />
                </Box>;
              })}
            </Box>;
          })() : null}
        </Card>

        <Typography variant="h5">LTX Director history</Typography>
        <Grid container spacing={2}>
          {ltxBatches.length === 0 ? <Grid item xs={12}><Alert severity="info">No LTX Director batches yet.</Alert></Grid> : ltxBatches.map((item) => (
            <Grid item xs={12} md={6} key={item.batch_id}>
              <Card variant="outlined">
                <CardContent><Typography fontWeight={700}>{item.metadata?.display_name || item.batch_id}</Typography><Typography variant="body2">{item.status} · {item.completed_videos || 0}/{item.total_videos || 1}</Typography>{item.error ? <Typography color="error" variant="caption">{item.error}</Typography> : null}</CardContent>
                <CardActions><Button size="small" onClick={() => { batch.setActiveBatchId(item.batch_id); batch.startPollingStatus(item.batch_id); }}>Open</Button><Button size="small" startIcon={<ReplayIcon />} onClick={() => adjustRetry(item.batch_id)}>Adjust & Retry</Button>{item.can_retry ? <Button size="small" onClick={() => batch.handleRetryBatch(item.batch_id)}>Retry exact</Button> : null}</CardActions>
              </Card>
            </Grid>
          ))}
        </Grid>
      </Stack>
    </PageLayout>
  );
}
