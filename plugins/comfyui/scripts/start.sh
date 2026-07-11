#!/bin/bash
# Start ComfyUI server

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLUGIN_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PROJECT_ROOT="$(cd "$PLUGIN_ROOT/../.." && pwd)"
COMFYUI_DIR="$PLUGIN_ROOT/ComfyUI"
VENV_PYTHON="$PROJECT_ROOT/backend/venv/bin/python"
if [ -f "$PROJECT_ROOT/.env" ]; then
    set -a
    . "$PROJECT_ROOT/.env"
    set +a
fi
COMFYUI_URL="${GUAARDVARK_COMFYUI_URL:-http://127.0.0.1:8188}"
PORT="${GUAARDVARK_COMFYUI_PORT:-${COMFYUI_URL##*:}}"

# Windows desktop mode owns ComfyUI outside WSL.  Do not create a second
# Linux process: its localhost, port, and SQLite database would conflict with
# the native server.  The backend only needs to verify the external service.
if [ "${GUAARDVARK_EXTERNAL_COMFYUI:-0}" = "1" ]; then
    if curl -fsS --max-time 5 "$COMFYUI_URL/system_stats" >/dev/null; then
        echo "Using external ComfyUI at $COMFYUI_URL"
        exit 0
    fi
    echo "Error: external ComfyUI is not reachable at $COMFYUI_URL" >&2
    exit 1
fi
# Allow ComfyUI to use its normal dynamic/CPU-offload path by default. The old
# `--highvram --disable-async-offload` combination aggressively pinned weights
# on the GPU, which fights the repo's newer "spill into RAM/swap instead of
# hard-blocking on VRAM budget" policy for large Wan/I2V jobs.
if [ -n "${GUAARDVARK_COMFYUI_FLAGS:-}" ]; then
    # shellcheck disable=SC2206
    COMFYUI_FLAGS=(${GUAARDVARK_COMFYUI_FLAGS})
else
    COMFYUI_FLAGS=(--reserve-vram 0.3)
fi

# Check ComfyUI exists
if [ ! -f "$COMFYUI_DIR/main.py" ]; then
    echo "Error: ComfyUI not found at $COMFYUI_DIR/main.py"
    exit 1
fi

# Check if already running
if lsof -Pi :$PORT -sTCP:LISTEN -t >/dev/null 2>&1; then
    echo "ComfyUI is already running on port $PORT"
    exit 0
fi

# Check venv python exists
if [ ! -f "$VENV_PYTHON" ]; then
    echo "Error: Python venv not found at $VENV_PYTHON"
    exit 1
fi

# Install ComfyUI + custom-node deps into backend/venv (shared — no plugin venv)
# shellcheck source=install_deps.sh
source "$SCRIPT_DIR/install_deps.sh"
install_comfyui_python_deps

# Log file
LOG_DIR="$PROJECT_ROOT/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/comfyui.log"

echo "Starting ComfyUI..."
echo "Dir: $COMFYUI_DIR"
echo "Port: $PORT"
echo "Python: $VENV_PYTHON"
echo "Log: $LOG_FILE"
echo "PYTORCH_CUDA_ALLOC_CONF: expandable_segments:True"
echo "ComfyUI flags: ${COMFYUI_FLAGS[*]}"

# Start ComfyUI detached so it survives the shell that launched this script.
cd "$COMFYUI_DIR"
export PYTORCH_CUDA_ALLOC_CONF="expandable_segments:True"
setsid -f "$VENV_PYTHON" main.py --listen --port "$PORT" "${COMFYUI_FLAGS[@]}" >> "$LOG_FILE" 2>&1 < /dev/null

# Save the actual listener PID. Detached launchers can otherwise leave a stale
# parent PID, making later health checks think ComfyUI is running when it exited.
PID_DIR="$PROJECT_ROOT/pids"
mkdir -p "$PID_DIR"
for _ in {1..30}; do
    RUNNING_PID=$(lsof -Pi :$PORT -sTCP:LISTEN -t 2>/dev/null | head -n 1 || true)
    if [ -n "$RUNNING_PID" ]; then
        echo "$RUNNING_PID" > "$PID_DIR/comfyui.pid"
        break
    fi
    sleep 1
done

if [ ! -s "$PID_DIR/comfyui.pid" ]; then
    echo "Error: ComfyUI did not start listening on port $PORT"
    exit 1
fi

echo "ComfyUI started (PID: $(cat $PID_DIR/comfyui.pid))"
