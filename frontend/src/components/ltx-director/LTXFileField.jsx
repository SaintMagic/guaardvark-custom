import React, { useRef, useState } from "react";
import UploadFileIcon from "@mui/icons-material/UploadFile";
import { Box, Button, LinearProgress, Typography } from "@mui/material";

const API_BASE = import.meta.env.VITE_API_BASE_URL || "/api";

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

export default function LTXFileField({ label, kind, value, accept, onChange, disabled = false }) {
  const inputRef = useRef(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const upload = async (event) => {
    const file = event.target.files?.[0];
    if (!file) return;
    setBusy(true);
    setError("");
    try {
      const body = new FormData();
      body.append("file", file);
      const response = await fetch(`${API_BASE}/ltx-director/upload/${kind}`, { method: "POST", body });
      const payload = await response.json();
      if (!response.ok || !payload.success) throw new Error(apiErrorText(payload, `Upload failed: HTTP ${response.status}`));
      onChange(payload.data.path);
    } catch (uploadError) {
      setError(uploadError.message);
    } finally {
      setBusy(false);
      event.target.value = "";
    }
  };

  return (
    <Box>
      <input ref={inputRef} hidden type="file" accept={accept} onChange={upload} />
      <Button disabled={disabled || busy} variant="outlined" startIcon={<UploadFileIcon />} onClick={() => inputRef.current?.click()}>
        {label}
      </Button>
      {busy ? <LinearProgress sx={{ mt: 1 }} /> : null}
      {value ? <Typography variant="caption" display="block" sx={{ mt: 0.5, wordBreak: "break-all" }}>{value}</Typography> : null}
      {error ? <Typography variant="caption" color="error" display="block">{error}</Typography> : null}
    </Box>
  );
}
