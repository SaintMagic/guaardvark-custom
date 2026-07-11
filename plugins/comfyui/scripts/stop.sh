#!/bin/bash
# Stop ComfyUI server

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLUGIN_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PROJECT_ROOT="$(cd "$PLUGIN_ROOT/../.." && pwd)"
PID_FILE="$PROJECT_ROOT/pids/comfyui.pid"
if [ -f "$PROJECT_ROOT/.env" ]; then
    set -a
    . "$PROJECT_ROOT/.env"
    set +a
fi
COMFYUI_URL="${GUAARDVARK_COMFYUI_URL:-http://127.0.0.1:8188}"
PORT="${GUAARDVARK_COMFYUI_PORT:-${COMFYUI_URL##*:}}"
CURRENT_USER=$(whoami)

# In desktop mode ComfyUI is a Windows-owned external service.  The desktop
# launcher stops it directly; never kill a WSL listener as a side effect.
if [ "${GUAARDVARK_EXTERNAL_COMFYUI:-0}" = "1" ]; then
    echo "External ComfyUI is managed by the Windows launcher."
    exit 0
fi

# Free the configured ComfyUI port of any *current-user* listener still bound to it.
# A crashed ComfyUI (or an orphaned child) can keep the port held with no usable
# PID file; the next start then dies with "OSError: [Errno 98] address already
# in use", which trips the circuit breaker and spams the boot log on every
# restart. Mirrors Ollama stop.sh Step 4. Current-user-only for safety — never
# kill a listener owned by another user (e.g. a system service on the port).
free_comfy_port() {
    command -v lsof >/dev/null 2>&1 || return 0
    local remaining_pids
    remaining_pids=$(lsof -i TCP:$PORT -sTCP:LISTEN -t 2>/dev/null || true)
    [ -n "$remaining_pids" ] || return 0
    for pid in $remaining_pids; do
        local proc_owner
        proc_owner=$(ps -o user= -p "$pid" 2>/dev/null | tr -d ' ')
        if [ "$proc_owner" = "$CURRENT_USER" ]; then
            echo "Freeing port $PORT — killing remaining ComfyUI listener (PID: $pid)..."
            kill -TERM "$pid" 2>/dev/null || true
            sleep 1
            kill -0 "$pid" 2>/dev/null && kill -KILL "$pid" 2>/dev/null || true
        fi
    done
}

if [ ! -f "$PID_FILE" ]; then
    # No PID file — ComfyUI may simply not be started, OR a prior crash left an
    # orphan holding the port. Sweep the port either way, then exit cleanly.
    free_comfy_port
    exit 0
fi

PID=$(cat "$PID_FILE")

if [ -z "$PID" ] || ! kill -0 "$PID" 2>/dev/null; then
    echo "ComfyUI is not running (PID: $PID)"
    rm -f "$PID_FILE"
    free_comfy_port
    exit 0
fi

echo "Stopping ComfyUI (PID: $PID)..."
kill "$PID"

for i in {1..10}; do
    if ! kill -0 "$PID" 2>/dev/null; then
        echo "ComfyUI stopped successfully"
        rm -f "$PID_FILE"
        free_comfy_port
        exit 0
    fi
    sleep 1
done

if kill -0 "$PID" 2>/dev/null; then
    echo "Force killing ComfyUI..."
    kill -9 "$PID"
    rm -f "$PID_FILE"
fi

# Final guard: make sure nothing current-user is still holding the configured port.
free_comfy_port
