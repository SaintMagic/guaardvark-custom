const API_BASE = import.meta.env.VITE_API_BASE_URL || "/api";

async function request(path, options = {}) {
  const response = await fetch(`${API_BASE}/ltx-director/sequences${path}`, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(payload?.error?.message || payload?.error || payload?.message || `Request failed (${response.status})`);
    error.status = response.status;
    error.payload = payload;
    throw error;
  }
  return payload.data ?? payload;
}

export const createSequence = (document) => request("", { method: "POST", body: JSON.stringify(document) });
export const getSequence = (id) => request(`/${encodeURIComponent(id)}`);
export const updateSequence = (id, document) => request(`/${encodeURIComponent(id)}`, { method: "PATCH", body: JSON.stringify(document) });
export const renderSequence = (id) => request(`/${encodeURIComponent(id)}/render`, { method: "POST", body: "{}" });
export const renderShot = (id, shotId, retry = false) => request(`/${encodeURIComponent(id)}/shots/${encodeURIComponent(shotId)}/${retry ? "retry" : "render"}`, { method: "POST", body: "{}" });
export const approveKeyframe = (id, shotId, assetPath) => request(`/${encodeURIComponent(id)}/shots/${encodeURIComponent(shotId)}/keyframe/approve`, { method: "POST", body: JSON.stringify({ asset_path: assetPath }) });
export const generateKeyframe = (id, shotId, regenerate = false) => request(`/${encodeURIComponent(id)}/shots/${encodeURIComponent(shotId)}/keyframe/generate`, { method: "POST", body: JSON.stringify({ regenerate }) });
export const stitchSequence = (id) => request(`/${encodeURIComponent(id)}/stitch`, { method: "POST", body: "{}" });
export const cancelSequence = (id) => request(`/${encodeURIComponent(id)}/cancel`, { method: "POST", body: "{}" });
