import React, { useEffect, useMemo, useState } from "react";
import { Alert, Box, Button, Card, CardContent, Chip, Grid, IconButton, Stack, TextField, Tooltip, Typography } from "@mui/material";
import AddIcon from "@mui/icons-material/Add";
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutline";
import ContentCopyIcon from "@mui/icons-material/ContentCopy";
import ArrowUpwardIcon from "@mui/icons-material/ArrowUpward";
import ArrowDownwardIcon from "@mui/icons-material/ArrowDownward";
import PlayArrowIcon from "@mui/icons-material/PlayArrow";
import ReplayIcon from "@mui/icons-material/Replay";
import CallSplitIcon from "@mui/icons-material/CallSplit";
import AutoAwesomeIcon from "@mui/icons-material/AutoAwesome";
import { createSequence, updateSequence, renderSequence, renderShot, stitchSequence, approveKeyframe, generateKeyframe } from "../../services/ltxSequenceService";

const newShot = (index, global) => ({
  id: crypto.randomUUID(), order: index, name: `Shot ${index + 1}`, enabled: true,
  prompt: global.prompt || "", negative_prompt_override: "", duration_seconds: 4,
  guide_strength: global.guide_strength ?? 1, motion_strength: global.motion_guide_strength ?? 1,
  source_image: global.source_image || null, last_frame: null, source_video: null,
  keyframe_source: global.source_image ? "uploaded" : "generated", keyframe_asset_path: null,
  keyframe_status: "unapproved", keyframe_model: null, cast_subject_id: null,
  image_loras: [], keyframe_seed: null,
  continuity_mode: "independent", previous_shot_id: null, transition_type: "hard_cut",
  seed_mode: "random", seed_value: null, sampling_override: {}, status: "pending", attempt_number: 0,
});

export default function LTXShotList({ globalConfig, onGlobalConfigChange }) {
  const [sequence, setSequence] = useState(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const totalDuration = useMemo(() => (sequence?.shots || []).filter((shot) => shot.enabled).reduce((sum, shot) => sum + Number(shot.duration_seconds || 0), 0), [sequence]);

  useEffect(() => {
    const saved = localStorage.getItem("guaardvark_ltx_sequence_v1");
    if (saved) { try { setSequence(JSON.parse(saved)); return; } catch { /* migrate by starting fresh */ } }
    setSequence({ schema_version: 1, project_id: null, title: "Untitled LTX Sequence", render_mode: "shot_batch", global: { ...globalConfig, width: 576, height: 896 }, shots: [newShot(0, globalConfig)], stitch: { enabled: true, transition_default: "hard_cut", audio_policy: "preserve_shot_audio" } });
  }, []);

  useEffect(() => { if (sequence) localStorage.setItem("guaardvark_ltx_sequence_v1", JSON.stringify(sequence)); }, [sequence]);
  const patchShot = (id, patch) => setSequence((current) => ({ ...current, shots: current.shots.map((shot) => shot.id === id ? { ...shot, ...patch } : shot) }));
  const move = (index, delta) => setSequence((current) => { const shots = [...current.shots]; const target = index + delta; if (target < 0 || target >= shots.length) return current; [shots[index], shots[target]] = [shots[target], shots[index]]; return { ...current, shots: shots.map((shot, order) => ({ ...shot, order })) }; });
  const add = () => setSequence((current) => ({ ...current, shots: [...current.shots, newShot(current.shots.length, { ...current.global, prompt: "" })] }));
  const duplicate = (shot) => setSequence((current) => ({ ...current, shots: [...current.shots, { ...shot, id: crypto.randomUUID(), order: current.shots.length, name: `${shot.name} copy`, status: "pending", output_path: null, final_frame_path: null, attempt_number: 0 }] }));
  const save = async (value = sequence, announce = true) => { setBusy(true); setError(""); try { const saved = value.project_id ? await updateSequence(value.project_id, value) : await createSequence(value); setSequence(saved); if (announce) setMessage("Sequence saved"); return saved; } catch (err) { setError(err.message); return null; } finally { setBusy(false); } };
  const run = async (action) => { setBusy(true); setError(""); try { const current = await save(sequence, false); if (!current?.project_id) return; const updated = await action(current.project_id); if (updated?.shots) setSequence(updated); setMessage("Request accepted"); } catch (err) { setError(err.message); } finally { setBusy(false); } };
  const approve = async (shot) => {
    if (!sequence.project_id || !shot.keyframe_asset_path) return;
    setBusy(true); setError("");
    try { const updated = await approveKeyframe(sequence.project_id, shot.id, shot.keyframe_asset_path); setSequence(updated); setMessage("Keyframe approved and locked"); }
    catch (err) { setError(err.message); } finally { setBusy(false); }
  };
  const generate = async (shot, regenerate = false) => {
    if (!sequence.project_id) return;
    setBusy(true); setError("");
    try { const updated = await generateKeyframe(sequence.project_id, shot.id, regenerate); setSequence(updated); setMessage(regenerate ? "Keyframe regenerated; approve it before animation" : "Keyframe generated; approve it before animation"); }
    catch (err) { setError(err.message); } finally { setBusy(false); }
  };
  if (!sequence) return null;
  return <Card variant="outlined"><CardContent><Stack spacing={1.5}>
    <Stack direction={{ xs: "column", md: "row" }} justifyContent="space-between" alignItems={{ md: "center" }} spacing={1}>
      <BoxTitle title="LTX Shot Batch Director" subtitle={`${sequence.shots.length} shots · ${totalDuration.toFixed(1)} seconds · ${sequence.render_mode}`} />
      <Stack direction="row" spacing={1} flexWrap="wrap"><Button size="small" variant="outlined" onClick={add} startIcon={<AddIcon />}>Add shot</Button><Button size="small" variant="outlined" disabled={busy} onClick={save}>Save</Button><Button size="small" variant="contained" disabled={busy} onClick={() => run(renderSequence)} startIcon={<PlayArrowIcon />}>Render pending</Button><Button size="small" variant="outlined" disabled={busy} onClick={() => run(stitchSequence)}>Stitch hard cuts</Button></Stack>
    </Stack>
    {error ? <Alert severity="error">{error}</Alert> : null}{message ? <Alert severity="success" onClose={() => setMessage("")}>{message}</Alert> : null}
    {sequence.shots.map((shot, index) => <Card key={shot.id} variant="outlined" sx={{ backgroundColor: "action.hover" }}><CardContent><Stack spacing={1}>
      <Stack direction="row" alignItems="center" spacing={1}><Typography variant="subtitle2" sx={{ flex: 1 }}>{index + 1}. {shot.name}</Typography><Chip size="small" label={shot.status || "pending"} color={shot.status === "completed" ? "success" : shot.status === "error" ? "error" : "default"} /><Tooltip title="Move up"><span><IconButton size="small" onClick={() => move(index, -1)} disabled={index === 0}><ArrowUpwardIcon fontSize="small" /></IconButton></span></Tooltip><Tooltip title="Move down"><span><IconButton size="small" onClick={() => move(index, 1)} disabled={index === sequence.shots.length - 1}><ArrowDownwardIcon fontSize="small" /></IconButton></span></Tooltip><Tooltip title="Duplicate"><IconButton size="small" onClick={() => duplicate(shot)}><ContentCopyIcon fontSize="small" /></IconButton></Tooltip><Tooltip title="Delete"><IconButton size="small" onClick={() => setSequence((current) => ({ ...current, shots: current.shots.filter((item) => item.id !== shot.id) }))}><DeleteOutlineIcon fontSize="small" /></IconButton></Tooltip></Stack>
      <Grid container spacing={1.5}><Grid item xs={12} md={6}><TextField fullWidth size="small" label="Shot name" value={shot.name} onChange={(event) => patchShot(shot.id, { name: event.target.value })} /></Grid><Grid item xs={12} md={3}><TextField fullWidth size="small" type="number" label="Duration (s)" value={shot.duration_seconds} onChange={(event) => patchShot(shot.id, { duration_seconds: Number(event.target.value) })} /></Grid><Grid item xs={12} md={3}><TextField fullWidth size="small" type="number" label="Motion strength" value={shot.motion_strength} onChange={(event) => patchShot(shot.id, { motion_strength: Number(event.target.value) })} /></Grid><Grid item xs={12}><TextField fullWidth multiline minRows={2} label="Prompt" value={shot.prompt} onChange={(event) => patchShot(shot.id, { prompt: event.target.value })} /></Grid><Grid item xs={12} md={8}><TextField fullWidth size="small" label="Approved keyframe asset path" value={shot.keyframe_asset_path || ""} onChange={(event) => patchShot(shot.id, { keyframe_asset_path: event.target.value, keyframe_source: "generated", keyframe_status: "unapproved" })} helperText={shot.keyframe_status === "approved" ? "Locked asset will be used; LTX will not regenerate it." : "Use an existing gallery/upload asset path, then approve it."} /></Grid><Grid item xs={12} md={4} sx={{ display: "flex", alignItems: "center" }}><Button size="small" variant={shot.keyframe_status === "approved" ? "contained" : "outlined"} color={shot.keyframe_status === "approved" ? "success" : "primary"} disabled={busy || !shot.keyframe_asset_path || shot.keyframe_status === "approved"} onClick={() => approve(shot)}>Approve and lock keyframe</Button></Grid></Grid>
      <Stack direction="row" spacing={1} flexWrap="wrap"><Button size="small" onClick={() => run((id) => renderShot(id, shot.id))} disabled={busy} startIcon={<PlayArrowIcon />}>Animate shot</Button><Button size="small" onClick={() => run((id) => renderShot(id, shot.id, true))} disabled={busy} startIcon={<ReplayIcon />}>Retry</Button><Button size="small" onClick={() => generate(shot, false)} disabled={busy} startIcon={<AutoAwesomeIcon />}>Generate keyframe</Button><Button size="small" onClick={() => generate(shot, true)} disabled={busy || !shot.keyframe_asset_path} startIcon={<ReplayIcon />}>Regenerate keyframe</Button><Button size="small" onClick={() => patchShot(shot.id, { continuity_mode: shot.continuity_mode === "previous" ? "independent" : "previous", previous_shot_id: shot.continuity_mode === "previous" ? null : sequence.shots[index - 1]?.id || null })} disabled={index === 0} startIcon={<CallSplitIcon />}>{shot.continuity_mode === "previous" ? "Continue from previous" : "Independent source"}</Button></Stack>
    </Stack></CardContent></Card>)}
  </Stack></CardContent></Card>;
}

function BoxTitle({ title, subtitle }) { return <Box><Typography variant="h6">{title}</Typography><Typography variant="body2" color="text.secondary">{subtitle}</Typography></Box>; }
