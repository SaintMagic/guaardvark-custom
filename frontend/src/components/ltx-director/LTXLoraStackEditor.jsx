import React, { useMemo } from "react";
import {
  Alert,
  Button,
  FormControl,
  FormControlLabel,
  Grid,
  IconButton,
  InputLabel,
  MenuItem,
  Paper,
  Select,
  Stack,
  Switch,
  TextField,
  Tooltip,
  Typography,
} from "@mui/material";
import AddIcon from "@mui/icons-material/Add";
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutline";

const normalize = (value) => String(value || "").trim().replaceAll("\\", "/").toLowerCase();
const displayName = (value) => String(value || "").split(/[\\/]/).pop() || value;

const canonicalValue = (value, choices) => {
  const key = normalize(value);
  return choices.find((item) => normalize(item) === key) || value || "";
};

const StrengthField = ({ label, value, disabled, onChange }) => (
  <TextField
    fullWidth
    size="small"
    type="number"
    label={label}
    value={value}
    disabled={disabled}
    inputProps={{ min: -2, max: 2, step: 0.05 }}
    onChange={(event) => onChange(Number(event.target.value))}
  />
);

export default function LTXLoraStackEditor({
  value,
  onChange,
  availableLoras,
  disabled = false,
  reservedSlots = 0,
  reservedNames = [],
  limit = 12,
}) {
  const rows = Array.isArray(value) ? value : [];
  const choices = useMemo(
    () => (availableLoras || []).filter((item) => normalize(item) && normalize(item) !== "none"),
    [availableLoras],
  );
  const capacity = Math.max(0, limit - reservedSlots);
  const canAdd = !disabled && rows.length < capacity && choices.length > 0;

  const updateRow = (index, patch) => {
    onChange(rows.map((row, rowIndex) => (rowIndex === index ? { ...row, ...patch } : row)));
  };

  const removeRow = (index) => onChange(rows.filter((_, rowIndex) => rowIndex !== index));

  const addRow = () => {
    const used = new Set([
      ...reservedNames.map(normalize),
      ...rows.map((row) => normalize(row.name || row.lora)),
    ]);
    const nextName = choices.find((item) => !used.has(normalize(item))) || choices[0];
    if (!nextName) return;
    onChange([
      ...rows,
      {
        name: nextName,
        enabled: true,
        strength: 1,
        video_strength: 1,
        audio_strength: 1,
      },
    ]);
  };

  return (
    <Stack spacing={1.5}>
      {choices.length === 0 ? (
        <Alert severity="warning">
          ComfyUI did not report any LoRA files through DaSiWa_LTX2LoraLoader. Refresh capabilities after adding a LoRA or restarting ComfyUI.
        </Alert>
      ) : null}

      {rows.map((row, index) => {
        const selected = canonicalValue(row.name || row.lora, choices);
        const selectedKnown = choices.some((item) => normalize(item) === normalize(selected));
        const usedByOtherRows = new Set([
          ...reservedNames.map(normalize),
          ...rows
            .filter((_, rowIndex) => rowIndex !== index)
            .map((item) => normalize(item.name || item.lora)),
        ]);
        return (
          <Paper key={`${selected}-${index}`} variant="outlined" sx={{ p: 1.5 }}>
            <Grid container spacing={1.5} alignItems="center">
              <Grid item xs={12} md={1.5}>
                <FormControlLabel
                  control={(
                    <Switch
                      checked={row.enabled !== false}
                      disabled={disabled}
                      onChange={(event) => updateRow(index, { enabled: event.target.checked })}
                    />
                  )}
                  label={`#${index + 1}`}
                />
              </Grid>
              <Grid item xs={12} md={4.5}>
                <FormControl fullWidth size="small" disabled={disabled} error={!selectedKnown}>
                  <InputLabel>Installed LTX LoRA</InputLabel>
                  <Select
                    label="Installed LTX LoRA"
                    value={selected}
                    onChange={(event) => updateRow(index, { name: event.target.value })}
                  >
                    {!selectedKnown && selected ? (
                      <MenuItem value={selected}>Missing: {displayName(selected)}</MenuItem>
                    ) : null}
                    {choices.map((item) => (
                      <MenuItem
                        key={item}
                        value={item}
                        disabled={usedByOtherRows.has(normalize(item))}
                      >
                        {displayName(item)}
                      </MenuItem>
                    ))}
                  </Select>
                </FormControl>
              </Grid>
              <Grid item xs={6} sm={4} md={1.7}>
                <StrengthField
                  label="Master"
                  value={row.strength ?? 1}
                  disabled={disabled || row.enabled === false}
                  onChange={(next) => updateRow(index, { strength: next })}
                />
              </Grid>
              <Grid item xs={6} sm={4} md={1.7}>
                <StrengthField
                  label="Video"
                  value={row.video_strength ?? 1}
                  disabled={disabled || row.enabled === false}
                  onChange={(next) => updateRow(index, { video_strength: next })}
                />
              </Grid>
              <Grid item xs={6} sm={4} md={1.7}>
                <StrengthField
                  label="Audio"
                  value={row.audio_strength ?? 1}
                  disabled={disabled || row.enabled === false}
                  onChange={(next) => updateRow(index, { audio_strength: next })}
                />
              </Grid>
              <Grid item xs={6} md={0.9} sx={{ textAlign: "right" }}>
                <Tooltip title="Remove LoRA">
                  <span>
                    <IconButton
                      color="error"
                      disabled={disabled}
                      onClick={() => removeRow(index)}
                    >
                      <DeleteOutlineIcon />
                    </IconButton>
                  </span>
                </Tooltip>
              </Grid>
            </Grid>
          </Paper>
        );
      })}

      <Stack direction="row" spacing={1} alignItems="center">
        <Button startIcon={<AddIcon />} variant="outlined" disabled={!canAdd} onClick={addRow}>
          Add installed LoRA
        </Button>
        <Typography variant="caption" color="text.secondary">
          {rows.length}/{capacity} general slots, {reservedSlots} reserved quick slot{reservedSlots === 1 ? "" : "s"}, {limit} total.
        </Typography>
      </Stack>
    </Stack>
  );
}
