import { BASE_URL, handleResponse } from "./apiClient";

export const getBackendHealth = async () => {
  const response = await fetch(`${BASE_URL}/health`);
  return handleResponse(response, { quiet: true });
};

export const getDbHealth = async () => {
  const response = await fetch(`${BASE_URL}/health/db`);
  return handleResponse(response, { quiet: true });
};

export const getCeleryHealth = async () => {
  const response = await fetch(`${BASE_URL}/health/celery`);
  return handleResponse(response, { quiet: true });
};

export const getRedisHealth = async () => {
  const response = await fetch(`${BASE_URL}/health/redis`);
  return handleResponse(response, { quiet: true });
};

export const getComfyUIHealth = async () => {
  const response = await fetch(`${BASE_URL}/gpu/comfyui/status`);
  const payload = await handleResponse(response, { quiet: true });
  const data = payload?.data || payload || {};
  return {
    running: data.comfyui_running === true,
    status: data.comfyui_running === true ? "up" : "down",
    url: data.comfyui_url || null,
    nodeCount: data.custom_nodes_count ?? null,
  };
};

export const getCeleryTasks = async () => {
  const response = await fetch(`${BASE_URL}/celery/tasks`);
  return handleResponse(response);
};
