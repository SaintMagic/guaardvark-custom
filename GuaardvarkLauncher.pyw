#!/usr/bin/env python3
"""Guaardvark Launcher — Hypermodern UI."""

import ctypes
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

from PyQt6.QtCore import (
    QEasingCurve,
    QPointF,
    QPropertyAnimation,
    QRectF,
    QSettings,
    QThread,
    QTimer,
    Qt,
    QUrl,
    pyqtSignal,
)
from PyQt6.QtGui import (
    QAction,
    QBrush,
    QCloseEvent,
    QColor,
    QDesktopServices,
    QFont,
    QIcon,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QStatusBar,
    QSystemTrayIcon,
    QToolBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)
# ─── Constants ────────────────────────────────────────────────────────────────

APP_ID = "Martin.Guaardvark.Launcher"
BACKEND_PORT = 5000
FRONTEND_PORT = 5173
COMFY_PORT = 8191
REPO_ROOT = Path(__file__).resolve().parent
ICON_PATH = REPO_ROOT / "frontend" / "public" / "icon-512.png"
VERSION_PATH = REPO_ROOT / "VERSION"
LOGS_DIR = REPO_ROOT / "logs"
SETUP_LOG = LOGS_DIR / "setup.log"
LAUNCH_LOG = LOGS_DIR / "launch.log"
BACKEND_LOG = LOGS_DIR / "backend_startup.log"
FRONTEND_LOG = LOGS_DIR / "frontend.log"
COMFY_ERR_LOG = LOGS_DIR / "comfyui-windows.err.log"
LAUNCHER_MUTEX = "Local\\GuaardvarkLauncherSingleton"
EDGE_WRAPPER_PROFILE = Path(os.environ.get("LOCALAPPDATA", REPO_ROOT)) / "Guaardvark" / "EdgeWrapper"
LOG_FILES = {
    "Setup": SETUP_LOG,
    "Launch": LAUNCH_LOG,
    "Backend": BACKEND_LOG,
    "Frontend": FRONTEND_LOG,
    "Comfy Errors": COMFY_ERR_LOG,
    "Video Generation": LOGS_DIR / "video_generation.log",
    "Audio Foundry": LOGS_DIR / "audio_foundry.log",
}
COMMON_COMFY_FLAGS = [
    ("lowvram", "--lowvram", "Use lower VRAM mode"),
    ("novram", "--novram", "Use the most aggressive VRAM-saving mode"),
    ("highvram", "--highvram", "Keep more models resident in VRAM"),
    ("gpu_only", "--gpu-only", "Prefer GPU-only execution where possible"),
    ("cpu_vae", "--cpu-vae", "Offload VAE work to CPU"),
    ("force_fp16", "--force-fp16", "Force fp16 where supported"),
    ("fp32_vae", "--fp32-vae", "Run the VAE in fp32"),
    ("disable_async_offload", "--disable-async-offload", "Disable async offload"),
]

_WSL_IP_CACHE: str | None = None


# ─── Utility Functions ────────────────────────────────────────────────────────

def set_windows_app_id() -> None:
    if os.name != "nt":
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except Exception:
        pass


def acquire_single_instance() -> object | None:
    if os.name != "nt":
        return object()
    # ``ctypes.windll`` does not reliably preserve the Win32 last-error value
    # across the call.  That made duplicate launchers possible, which in turn
    # could start competing service/restart flows and blank the display while
    # the GPU driver was being reset.  Use a DLL with ``use_last_error`` and
    # read the error immediately after CreateMutexW.
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    mutex = kernel32.CreateMutexW(None, False, LAUNCHER_MUTEX)
    if not mutex:
        return None
    already_exists = ctypes.get_last_error() == 183  # ERROR_ALREADY_EXISTS
    if already_exists:
        kernel32.CloseHandle(mutex)
        return None
    return mutex


def is_port_open(port: int, host: str | None = None, timeout: float = 0.15) -> bool:
    hosts = [host] if host else ["127.0.0.1", "::1", get_wsl_ip()]
    for candidate in hosts:
        if not candidate:
            continue
        try:
            with socket.create_connection((candidate, port), timeout=timeout):
                return True
        except OSError:
            continue
    return False


def tail_text(path: Path, lines: int = 80) -> str:
    if not path.exists():
        return f"{path.name}: log file not found"
    try:
        with path.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            file_size = handle.tell()
            chunk_size = 4096
            buffer = bytearray()
            line_count = 0

            while file_size > 0 and line_count <= lines:
                read_size = min(chunk_size, file_size)
                file_size -= read_size
                handle.seek(file_size)
                chunk = handle.read(read_size)
                buffer[:0] = chunk
                line_count = buffer.count(b"\n")

            content = buffer.decode("utf-8", errors="replace").splitlines()
    except OSError as exc:
        return f"{path.name}: could not read log: {exc}"
    if not content:
        return f"{path.name}: log is empty"
    return "\n".join(content[-lines:])


def get_wsl_ip(refresh: bool = False) -> str | None:
    global _WSL_IP_CACHE
    if _WSL_IP_CACHE and not refresh:
        return _WSL_IP_CACHE
    try:
        result = subprocess.run(
            ["wsl.exe", "-d", "Ubuntu", "bash", "-lc", "hostname -I | awk '{print $1}'"],
            text=True,
            capture_output=True,
            timeout=10,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except Exception:
        return _WSL_IP_CACHE
    ip = (result.stdout or "").strip().split()
    _WSL_IP_CACHE = ip[0] if result.returncode == 0 and ip else None
    return _WSL_IP_CACHE


def resolve_service_url(port: int, path: str = "") -> str:
    suffix = path if not path or path.startswith("/") else f"/{path}"
    if is_port_open(port, host="127.0.0.1"):
        return f"http://127.0.0.1:{port}{suffix}"
    wsl_ip = get_wsl_ip(refresh=True)
    if wsl_ip and is_port_open(port, host=wsl_ip):
        return f"http://{wsl_ip}:{port}{suffix}"
    return f"http://localhost:{port}{suffix}"


def find_listening_pid(port: int) -> int | None:
    command = (
        "Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue | "
        f"Where-Object {{ $_.LocalPort -eq {port} }} | "
        "Select-Object -First 1 -ExpandProperty OwningProcess"
    )
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", command],
        text=True,
        capture_output=True,
        timeout=10,
    )
    if result.returncode != 0:
        return None
    raw = (result.stdout or "").strip()
    if not raw.isdigit():
        return None
    return int(raw)


def read_version() -> str:
    """Read the version string from the VERSION file at repo root."""
    try:
        return VERSION_PATH.read_text(encoding="utf-8").strip()
    except OSError:
        return "dev"


# ─── Startup Worker ───────────────────────────────────────────────────────────

class StartupWorker(QThread):
    status = pyqtSignal(str)
    phase = pyqtSignal(str, int)
    failed = pyqtSignal(str, str)
    ready = pyqtSignal()

    def __init__(self, repo_root: Path, startup_options: dict[str, object]) -> None:
        super().__init__()
        self.repo_root = repo_root
        self.startup_options = startup_options

    def run(self) -> None:
        try:
            if self.startup_options.get("start_comfy", True):
                self.phase.emit("Checking ComfyUI", 10)
                self._ensure_comfy()
            else:
                self.status.emit("Skipping native ComfyUI startup by request.")

            if self.startup_options.get("start_wsl", True):
                self.phase.emit("Starting WSL services", 30)
                self._start_wsl_services()
            else:
                self.status.emit("Skipping WSL services startup by request.")

            self.phase.emit("Waiting for backend", 60)
            self._wait_for_port(BACKEND_PORT, 1800, "backend")
            self.phase.emit("Waiting for frontend", 85)
            self._wait_for_port(FRONTEND_PORT, 1800, "frontend")
            if self.startup_options.get("open_wrapper", True):
                self.phase.emit("Opening UI", 100)
            else:
                self.phase.emit("Frontend ready", 100)
            self.ready.emit()
        except Exception as exc:
            self.failed.emit(str(exc), self._collect_logs())

    def _ensure_comfy(self) -> None:
        if is_port_open(COMFY_PORT):
            self.status.emit("Native ComfyUI is already running on port 8191.")
            return

        self.status.emit("Starting native Windows ComfyUI...")
        script = self.repo_root / "Run-ComfyUI-Native.ps1"
        env = os.environ.copy()
        env["GUAARDVARK_COMFYUI_FLAGS"] = str(self.startup_options.get("comfy_flags", "")).strip()
        
        with open(LAUNCH_LOG, "a", encoding="utf-8") as f_out:
            f_out.write(f"\n--- Native ComfyUI Bootstrap: {time.asctime()} ---\n")
            result = subprocess.run(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(script),
                ],
                cwd=self.repo_root,
                stdout=f_out,
                stderr=subprocess.STDOUT,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                timeout=1800,
                env=env,
            )
            
        if result.returncode != 0:
            raise RuntimeError(f"Native ComfyUI bootstrap failed (exit code {result.returncode}). Check Launch log.")

        self._wait_for_port(COMFY_PORT, 180, "ComfyUI")

    def _run_wsl(self, command: str, capture_output: bool = True) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["wsl.exe", "-d", "Ubuntu", "bash", "-lc", command],
            cwd=self.repo_root,
            text=True,
            capture_output=capture_output,
            timeout=120,
        )

    def _resolve_wsl_python(self) -> str:
        probe = r"""
if command -v python3.12 >/dev/null 2>&1; then
    printf '%s\n' "python3.12"
elif [ -x "$HOME/.local/bin/uv" ]; then
    "$HOME/.local/bin/uv" python find 3.12 2>/dev/null
fi
"""
        result = self._run_wsl(probe)
        python_cmd = (result.stdout or "").strip().splitlines()
        if result.returncode != 0 or not python_cmd:
            raise RuntimeError(
                "WSL Python 3.12 is missing. Install it inside Ubuntu with "
                "'~/.local/bin/uv python install 3.12' or system package python3.12."
            )
        return python_cmd[0].strip()

    def _start_wsl_services(self) -> None:
        python_cmd = self._resolve_wsl_python()
        if is_port_open(BACKEND_PORT) and is_port_open(FRONTEND_PORT):
            self.status.emit(f"Guaardvark services are already running in WSL with {python_cmd}.")
            return

        self.status.emit(f"Starting backend and frontend in WSL with {python_cmd}...")
        wsl_repo_root = self._wsl_repo_root()
        linux_command = (
            f"cd '{wsl_repo_root}' && "
            f"export PYTHON_CMD='{python_cmd}' && "
            "bash ./scripts/wsl_start_launcher_services.sh core"
        )
        subprocess.Popen(
            ["wsl.exe", "-d", "Ubuntu", "bash", "-lc", linux_command],
            cwd=self.repo_root,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )

    def _wsl_repo_root(self) -> str:
        return f"/mnt/{self.repo_root.drive[0].lower()}{self.repo_root.as_posix()[2:]}"

    def _wait_for_port(self, port: int, timeout_seconds: int, label: str) -> None:
        self.status.emit(f"Waiting for {label} on port {port}...")
        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            if is_port_open(port):
                self.status.emit(f"{label.capitalize()} is ready on port {port}.")
                return
            time.sleep(1)
        raise RuntimeError(f"Timed out waiting for {label} on port {port}.")

    def _collect_logs(self) -> str:
        log_files = [
            LOGS_DIR / "launch.log",
            LOGS_DIR / "backend_startup.log",
            LOGS_DIR / "frontend.log",
            LOGS_DIR / "comfyui-windows.err.log",
        ]
        parts = []
        for path in log_files:
            parts.append(f"===== {path.name} =====")
            parts.append(tail_text(path))
            parts.append("")
        return "\n".join(parts).strip()


# ─── Custom Widgets ───────────────────────────────────────────────────────────

class CollapsibleSection(QWidget):
    """A panel with a clickable header that smoothly expands/collapses its content."""

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self._expanded = True

        self._toggle_btn = QToolButton()
        self._toggle_btn.setText(f"  {title}")
        self._toggle_btn.setCheckable(True)
        self._toggle_btn.setChecked(True)
        self._toggle_btn.setArrowType(Qt.ArrowType.DownArrow)
        self._toggle_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self._toggle_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._toggle_btn.setObjectName("collapsibleToggle")
        self._toggle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._toggle_btn.toggled.connect(self._on_toggle)

        self._content = QWidget()
        self._inner_layout = QVBoxLayout(self._content)
        self._inner_layout.setContentsMargins(14, 10, 14, 14)
        self._inner_layout.setSpacing(8)

        self._animation = QPropertyAnimation(self._content, b"maximumHeight")
        self._animation.setDuration(280)
        self._animation.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self._animation.finished.connect(self._on_animation_finished)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._toggle_btn)
        layout.addWidget(self._content)

    def content_layout(self) -> QVBoxLayout:
        """Return the inner layout to which child widgets should be added."""
        return self._inner_layout

    def _on_toggle(self, checked: bool) -> None:
        self._animation.stop()
        if checked:
            self._toggle_btn.setArrowType(Qt.ArrowType.DownArrow)
            # Temporarily allow full size to measure the natural height.
            self._content.setMaximumHeight(16777215)
            self._content.show()
            target = self._content.sizeHint().height()
            if target <= 0:
                target = 200
            self._content.setMaximumHeight(0)
            self._animation.setStartValue(0)
            self._animation.setEndValue(target)
            self._animation.start()
        else:
            self._toggle_btn.setArrowType(Qt.ArrowType.RightArrow)
            self._animation.setStartValue(self._content.height())
            self._animation.setEndValue(0)
            self._animation.start()

    def _on_animation_finished(self) -> None:
        if self._toggle_btn.isChecked():
            self._content.setMaximumHeight(16777215)
        else:
            self._content.hide()


class ServiceCard(QFrame):
    """A compact card showing the live status of a single service."""

    def __init__(
        self,
        name: str,
        port: int | str,
        active_label: str = "running",
        inactive_label: str = "stopped",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("serviceCard")
        self._active_label = active_label
        self._inactive_label = inactive_label
        self._is_active = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 12)
        layout.setSpacing(3)

        # Header row: dot + name
        header = QHBoxLayout()
        header.setSpacing(8)
        self.dot_label = QLabel("\u25cf")
        self.dot_label.setFixedWidth(14)
        self.dot_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.dot_label.setStyleSheet("font-size: 12px; color: #475569;")
        self._name_label = QLabel(name)
        self._name_label.setStyleSheet(
            "font-size: 14px; font-weight: 600; color: #e2e8f0;"
        )
        header.addWidget(self.dot_label)
        header.addWidget(self._name_label)
        header.addStretch()

        # Port
        port_text = f":{port}" if isinstance(port, int) else port
        port_label = QLabel(port_text)
        port_label.setStyleSheet(
            "font-size: 11px; color: #64748b; font-family: Consolas, monospace;"
        )

        # Status text
        self.status_text = QLabel(inactive_label)
        self.status_text.setStyleSheet(
            "font-size: 11px; color: #64748b; font-weight: 500;"
        )

        # Separator line
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFixedHeight(1)
        sep.setStyleSheet("background: rgba(148, 163, 184, 0.08);")

        # Action buttons
        btn_row = QHBoxLayout()
        btn_row.setSpacing(5)
        self.start_btn = QPushButton("\u25b6")
        self.stop_btn = QPushButton("\u25a0")
        self.restart_btn = QPushButton("\u21bb")
        for btn in (self.start_btn, self.stop_btn, self.restart_btn):
            btn.setObjectName("cardActionBtn")
            btn.setFixedSize(30, 26)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.start_btn.setToolTip(f"Start {name}")
        self.stop_btn.setToolTip(f"Stop {name}")
        self.restart_btn.setToolTip(f"Restart {name}")
        btn_row.addWidget(self.start_btn)
        btn_row.addWidget(self.stop_btn)
        btn_row.addWidget(self.restart_btn)
        btn_row.addStretch()

        layout.addLayout(header)
        layout.addWidget(port_label)
        layout.addSpacing(2)
        layout.addWidget(self.status_text)
        layout.addSpacing(4)
        layout.addWidget(sep)
        layout.addSpacing(2)
        layout.addLayout(btn_row)

    def set_active(self, active: bool) -> None:
        """Update the visual state of this card."""
        self._is_active = active
        if active:
            self.dot_label.setStyleSheet("font-size: 12px; color: #00d4aa;")
            self.status_text.setText(self._active_label)
            self.status_text.setStyleSheet(
                "font-size: 11px; color: #00d4aa; font-weight: 600;"
            )
            self.setStyleSheet(
                "#serviceCard {"
                "  background: rgba(0, 212, 170, 0.04);"
                "  border: 1px solid rgba(0, 212, 170, 0.18);"
                "  border-radius: 10px;"
                "}"
            )
        else:
            self.dot_label.setStyleSheet("font-size: 12px; color: #475569;")
            self.status_text.setText(self._inactive_label)
            self.status_text.setStyleSheet(
                "font-size: 11px; color: #64748b; font-weight: 500;"
            )
            self.setStyleSheet(
                "#serviceCard {"
                "  background: #111827;"
                "  border: 1px solid rgba(148, 163, 184, 0.08);"
                "  border-radius: 10px;"
                "}"
            )


# ─── Launcher Window ─────────────────────────────────────────────────────────

class LauncherWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.settings = QSettings("Martin", "GuaardvarkLauncher")
        self.current_phase_name = "Idle"
        self.current_activity = "Waiting to start."
        self.current_log_source = "Launcher"
        self.menu_actions: dict[str, list[QAction]] = {}
        self.restart_pending = False
        self.restart_deadline = 0.0
        self.last_log_snapshot = ""
        self.last_log_label = ""
        self.setWindowTitle("Guaardvark Launcher")
        self.resize(1020, 800)
        self.setMinimumSize(860, 640)
        if ICON_PATH.exists():
            self.setWindowIcon(QIcon(str(ICON_PATH)))

        # ── Main Content Container ────────────────────────────────────────
        content = QWidget()
        content.setObjectName("mainContent")
        main_layout = QVBoxLayout(content)
        main_layout.setContentsMargins(28, 22, 28, 22)
        main_layout.setSpacing(14)

        # ── Header: logo + title + version ────────────────────────────────
        header_widget = QWidget()
        header_layout = QHBoxLayout(header_widget)
        header_layout.setContentsMargins(0, 0, 0, 4)
        header_layout.setSpacing(14)

        logo_label = QLabel()
        if ICON_PATH.exists():
            logo_pix = QPixmap(str(ICON_PATH)).scaled(
                40, 40,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            logo_label.setPixmap(logo_pix)
        logo_label.setFixedSize(40, 40)

        title_label = QLabel("GUAARDVARK")
        title_label.setStyleSheet(
            "font-size: 24px; font-weight: 700; color: #f1f5f9;"
            "letter-spacing: 3px;"
        )

        version_label = QLabel(f"v{read_version()}")
        version_label.setStyleSheet(
            "background: rgba(59, 130, 246, 0.12);"
            "color: #60a5fa; border-radius: 5px; padding: 3px 10px;"
            "font-size: 11px; font-weight: 600;"
        )

        header_layout.addWidget(logo_label)
        header_layout.addWidget(title_label)
        header_layout.addWidget(version_label)
        header_layout.addStretch()

        # ── Status label (current activity summary) ───────────────────────
        self.status_label = QLabel("Preparing Guaardvark...")
        self.status_label.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet(
            "font-size: 14px; padding: 2px 0; color: #94a3b8;"
        )

        # ── Service Cards Row ─────────────────────────────────────────────
        cards_widget = QWidget()
        cards_layout = QHBoxLayout(cards_widget)
        cards_layout.setContentsMargins(0, 0, 0, 0)
        cards_layout.setSpacing(10)

        self.backend_card = ServiceCard("Backend", BACKEND_PORT)
        self.frontend_card = ServiceCard("Frontend", FRONTEND_PORT)
        self.comfy_card = ServiceCard("ComfyUI", COMFY_PORT)
        self.wrapper_card = ServiceCard(
            "Wrapper", "\u2014",
            active_label="open", inactive_label="closed",
        )

        # Wire card action buttons to service methods.
        self.backend_card.start_btn.clicked.connect(self._start_backend_only)
        self.backend_card.stop_btn.clicked.connect(self._stop_backend_only)
        self.backend_card.restart_btn.clicked.connect(self._restart_backend_only)
        self.frontend_card.start_btn.clicked.connect(self._start_frontend_only)
        self.frontend_card.stop_btn.clicked.connect(self._stop_frontend_only)
        self.frontend_card.restart_btn.clicked.connect(self._restart_frontend_only)
        self.comfy_card.start_btn.clicked.connect(self._start_comfy_only)
        self.comfy_card.stop_btn.clicked.connect(self._stop_comfy_only)
        self.comfy_card.restart_btn.clicked.connect(self._restart_comfy_only)
        self.wrapper_card.start_btn.clicked.connect(self.show_wrapper)
        self.wrapper_card.stop_btn.clicked.connect(self._stop_wrapper_only)
        self.wrapper_card.restart_btn.clicked.connect(self._restart_wrapper_only)

        cards_layout.addWidget(self.backend_card)
        cards_layout.addWidget(self.frontend_card)
        cards_layout.addWidget(self.comfy_card)
        cards_layout.addWidget(self.wrapper_card)

        # ── Progress Bar ──────────────────────────────────────────────────
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFormat("Idle")
        self.progress_bar.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # ── Phase + Activity Labels ───────────────────────────────────────
        phase_activity = QWidget()
        pa_layout = QHBoxLayout(phase_activity)
        pa_layout.setContentsMargins(0, 0, 0, 0)
        pa_layout.setSpacing(12)

        self.phase_label = QLabel("Idle")
        self.phase_label.setStyleSheet(
            "font-size: 12px; color: #64748b; font-weight: 600;"
        )
        self.activity_label = QLabel("No startup activity yet.")
        self.activity_label.setWordWrap(True)
        self.activity_label.setStyleSheet("font-size: 12px; color: #64748b;")

        pa_layout.addWidget(self.phase_label, 0)
        pa_layout.addWidget(self.activity_label, 1)

        # ── Collapsible: Startup Options ──────────────────────────────────
        self.startup_section = CollapsibleSection("Startup Options")
        startup_inner = self.startup_section.content_layout()

        startup_grid = QGridLayout()
        startup_grid.setHorizontalSpacing(20)
        startup_grid.setVerticalSpacing(10)

        self.start_comfy_checkbox = QCheckBox("Start native ComfyUI")
        self.start_comfy_checkbox.setChecked(True)
        self.start_comfy_checkbox.setToolTip(
            "Launch the Windows ComfyUI server first. Turn this off only if you "
            "already started ComfyUI yourself."
        )
        self.start_wsl_checkbox = QCheckBox("Start WSL backend/frontend")
        self.start_wsl_checkbox.setChecked(True)
        self.start_wsl_checkbox.setToolTip(
            "Launch the Linux-side Guaardvark backend and frontend inside WSL. "
            "Usually you want this on."
        )
        self.open_wrapper_checkbox = QCheckBox("Open wrapper window when ready")
        self.open_wrapper_checkbox.setChecked(True)
        self.open_wrapper_checkbox.setToolTip(
            "Open the main Guaardvark app window automatically after startup finishes."
        )
        self.minimize_to_tray_checkbox = QCheckBox("Minimize launcher to tray")
        self.minimize_to_tray_checkbox.setChecked(True)
        self.minimize_to_tray_checkbox.setToolTip(
            "Hide this launcher after startup and keep it available from the "
            "tray icon near the clock."
        )

        startup_grid.addWidget(self.start_comfy_checkbox, 0, 0)
        startup_grid.addWidget(self.start_wsl_checkbox, 0, 1)
        startup_grid.addWidget(self.open_wrapper_checkbox, 1, 0)
        startup_grid.addWidget(self.minimize_to_tray_checkbox, 1, 1)
        startup_inner.addLayout(startup_grid)

        # ── Collapsible: ComfyUI Flags ────────────────────────────────────
        self.comfy_section = CollapsibleSection("ComfyUI Flags")
        comfy_inner = self.comfy_section.content_layout()

        comfy_grid = QGridLayout()
        comfy_grid.setHorizontalSpacing(20)
        comfy_grid.setVerticalSpacing(10)

        self.comfy_flag_checkboxes: dict[str, QCheckBox] = {}
        for index, (key, flag, description) in enumerate(COMMON_COMFY_FLAGS):
            checkbox = QCheckBox(flag)
            checkbox.setToolTip(self._flag_tooltip(flag, description))
            self.comfy_flag_checkboxes[key] = checkbox
            comfy_grid.addWidget(checkbox, index // 2, index % 2)

        self.reserve_vram_checkbox = QCheckBox("Reserve VRAM")
        self.reserve_vram_checkbox.setChecked(True)
        self.reserve_vram_checkbox.setToolTip(
            "Keep some GPU memory free so Windows and other GPU tasks have "
            "breathing room."
        )
        self.reserve_vram_value = QDoubleSpinBox()
        self.reserve_vram_value.setDecimals(2)
        self.reserve_vram_value.setRange(0.0, 12.0)
        self.reserve_vram_value.setSingleStep(0.05)
        self.reserve_vram_value.setValue(0.30)
        self.reserve_vram_value.setSuffix(" GB")
        self.reserve_vram_value.setToolTip(
            "How much GPU memory ComfyUI should try not to consume. Higher "
            "values are safer, lower values are more aggressive."
        )
        self.reserve_vram_checkbox.toggled.connect(self.reserve_vram_value.setEnabled)

        reserve_row = (len(COMMON_COMFY_FLAGS) + 1) // 2
        reserve_layout = QHBoxLayout()
        reserve_layout.setContentsMargins(0, 0, 0, 0)
        reserve_layout.setSpacing(8)
        reserve_layout.addWidget(self.reserve_vram_checkbox)
        reserve_layout.addWidget(self.reserve_vram_value)
        reserve_layout.addStretch(1)
        comfy_grid.addLayout(reserve_layout, reserve_row, 0, 1, 2)
        comfy_inner.addLayout(comfy_grid)

        # ── Hero Launch Button ────────────────────────────────────────────
        self.retry_button = QPushButton("\u25b6   Launch Guaardvark")
        self.retry_button.setObjectName("heroButton")
        self.retry_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.retry_button.setToolTip(
            "Begin launching ComfyUI, the WSL services, and then the wrapper "
            "using the options above."
        )
        self.retry_button.clicked.connect(self.startup)

        hero_container = QHBoxLayout()
        hero_container.setContentsMargins(0, 4, 0, 4)
        hero_container.addStretch()
        hero_container.addWidget(self.retry_button)
        hero_container.addStretch()

        # ── Log Viewer Header ─────────────────────────────────────────────
        self.log_selector = QComboBox()
        self.log_selector.setMinimumWidth(180)
        for label in LOG_FILES:
            self.log_selector.addItem(label)
        self.log_selector.currentTextChanged.connect(self._refresh_live_logs)

        self.log_hint_label = QLabel("Live log view")
        self.log_hint_label.setStyleSheet("font-size: 11px; color: #64748b;")

        self.copy_logs_btn = QPushButton("Copy")
        self.copy_logs_btn.setObjectName("secondaryBtn")
        self.copy_logs_btn.setFixedHeight(28)
        self.copy_logs_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.copy_logs_btn.setToolTip("Copy the current log view to the clipboard.")
        self.copy_logs_btn.clicked.connect(self._copy_logs_to_clipboard)

        log_header = QHBoxLayout()
        log_header.setContentsMargins(0, 0, 0, 0)
        log_header.setSpacing(10)
        log_title = QLabel("Live Logs")
        log_title.setStyleSheet(
            "font-size: 13px; font-weight: 600; color: #94a3b8;"
        )
        log_header.addWidget(log_title)
        log_header.addWidget(self.log_selector, 0)
        log_header.addWidget(self.log_hint_label, 1)
        log_header.addWidget(self.copy_logs_btn)

        # ── Log Viewer ────────────────────────────────────────────────────
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setPlaceholderText("Selected log output will stream here.")

        # ── Hidden service state label (for backwards compat in status bar) ─
        self.service_state_label = QLabel("")
        self.service_state_label.hide()

        # ── Assemble Main Layout ──────────────────────────────────────────
        main_layout.addWidget(header_widget)
        main_layout.addWidget(self.status_label)
        main_layout.addWidget(cards_widget)
        main_layout.addWidget(self.progress_bar)
        main_layout.addWidget(phase_activity)
        main_layout.addWidget(self.startup_section)
        main_layout.addWidget(self.comfy_section)
        main_layout.addLayout(hero_container)
        main_layout.addLayout(log_header)
        main_layout.addWidget(self.log_view, 1)

        self.setCentralWidget(content)

        # ── Status Bar ────────────────────────────────────────────────────
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)

        # ── Toolbar ───────────────────────────────────────────────────────
        self._build_toolbar()

        # ── Sub-windows and Timers ────────────────────────────────────────
        self.wrapper_process: subprocess.Popen | None = None
        self.worker: StartupWorker | None = None

        self.ready_timer = QTimer(self)
        self.ready_timer.setInterval(1500)
        self.ready_timer.timeout.connect(self._show_wrapper_when_ready)

        self.log_timer = QTimer(self)
        self.log_timer.setInterval(2500)
        self.log_timer.timeout.connect(self._refresh_live_logs)

        self.service_status_timer = QTimer(self)
        self.service_status_timer.setInterval(2000)
        self.service_status_timer.timeout.connect(self._refresh_service_state)

        self.restart_watch_timer = QTimer(self)
        self.restart_watch_timer.setInterval(1000)
        self.restart_watch_timer.timeout.connect(self._continue_restart_all)

        self.tray_anim_timer = QTimer(self)
        self.tray_anim_timer.setInterval(180)
        self.tray_anim_timer.timeout.connect(self._advance_tray_animation)

        self.tray_icon: QSystemTrayIcon | None = None
        self.tray_anim_frame = 0
        self._create_tray_icon()
        self._restore_preferences()
        self._set_idle_state()
        self._refresh_service_state()
        self.service_status_timer.start()

    # ── Toolbar ───────────────────────────────────────────────────────────

    def _build_toolbar(self) -> None:
        toolbar = QToolBar("Actions", self)
        toolbar.setMovable(False)
        self.addToolBar(toolbar)
        toolbar.addWidget(self._make_menu_button("Open", self._build_open_menu()))
        toolbar.addWidget(self._make_menu_button("Start", self._build_start_menu()))
        toolbar.addWidget(
            self._make_menu_button("Restart", self._build_restart_menu())
        )
        toolbar.addWidget(self._make_menu_button("Stop", self._build_stop_menu()))

    def _make_menu_button(self, title: str, menu: QMenu) -> QToolButton:
        button = QToolButton(self)
        button.setText(title)
        button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        button.setMenu(menu)
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        return button

    def _build_open_menu(self) -> QMenu:
        menu = QMenu(self)
        menu.setTitle("Open")
        self._add_menu_action(
            menu, "open_ui", "Guaardvark UI", self.show_wrapper,
            "Open the embedded Guaardvark window.",
        )
        self._add_menu_action(
            menu, "open_frontend", "Frontend in Browser",
            lambda: QDesktopServices.openUrl(
                QUrl(resolve_service_url(FRONTEND_PORT))
            ),
            "Open the frontend directly in your default browser.",
        )
        self._add_menu_action(
            menu, "open_comfy", "ComfyUI",
            lambda: QDesktopServices.openUrl(
                QUrl(f"http://127.0.0.1:{COMFY_PORT}")
            ),
            "Open the native Windows ComfyUI page.",
        )
        self._add_menu_action(
            menu, "open_backend_health", "Backend Health",
            lambda: QDesktopServices.openUrl(
                QUrl(resolve_service_url(BACKEND_PORT, "/api/health"))
            ),
            "Open the backend health endpoint in your browser.",
        )
        self._add_menu_action(
            menu, "open_logs", "Logs Folder",
            lambda: QDesktopServices.openUrl(
                QUrl.fromLocalFile(str(LOGS_DIR))
            ),
            "Open the logs folder in Explorer.",
        )
        return menu

    def _build_start_menu(self) -> QMenu:
        menu = QMenu(self)
        menu.setTitle("Start")
        self._add_menu_action(
            menu, "start_all", "All", self.startup,
            "Run the launcher startup flow using the selected options above.",
        )
        self._add_menu_action(
            menu, "start_comfy", "ComfyUI", self._start_comfy_only,
            "Start native Windows ComfyUI only.",
        )
        self._add_menu_action(
            menu, "start_backend", "Backend", self._start_backend_only,
            "Start the WSL backend process on port 5000.",
        )
        self._add_menu_action(
            menu, "start_frontend", "Frontend", self._start_frontend_only,
            "Start the WSL frontend dev server on port 5173.",
        )
        self._add_menu_action(
            menu, "start_wsl_stack", "WSL Services Stack",
            self._start_wsl_stack_only,
            "Start the main WSL services stack without rerunning the full "
            "launcher flow.",
        )
        return menu

    def _build_restart_menu(self) -> QMenu:
        menu = QMenu(self)
        menu.setTitle("Restart")
        self._add_menu_action(
            menu, "restart_all", "All", self._restart_all_services,
            "Stop ComfyUI, backend, frontend, and wrapper, then start "
            "everything in order.",
        )
        self._add_menu_action(
            menu, "restart_comfy", "ComfyUI", self._restart_comfy_only,
            "Restart native Windows ComfyUI.",
        )
        self._add_menu_action(
            menu, "restart_backend", "Backend", self._restart_backend_only,
            "Restart only the WSL backend.",
        )
        self._add_menu_action(
            menu, "restart_frontend", "Frontend", self._restart_frontend_only,
            "Restart only the WSL frontend.",
        )
        self._add_menu_action(
            menu, "restart_wrapper", "Wrapper", self._restart_wrapper_only,
            "Reopen the embedded Guaardvark window.",
        )
        return menu

    def _build_stop_menu(self) -> QMenu:
        menu = QMenu(self)
        menu.setTitle("Stop")
        self._add_menu_action(
            menu, "stop_all", "All", self._stop_all_services,
            "Stop wrapper, WSL services, and native Windows ComfyUI.",
        )
        self._add_menu_action(
            menu, "stop_comfy", "ComfyUI", self._stop_comfy_only,
            "Stop native Windows ComfyUI.",
        )
        self._add_menu_action(
            menu, "stop_backend", "Backend", self._stop_backend_only,
            "Stop the WSL backend process.",
        )
        self._add_menu_action(
            menu, "stop_frontend", "Frontend", self._stop_frontend_only,
            "Stop the WSL frontend dev server.",
        )
        self._add_menu_action(
            menu, "stop_wrapper", "Wrapper", self._stop_wrapper_only,
            "Close only the embedded Guaardvark window.",
        )
        return menu

    def _add_menu_action(
        self, menu: QMenu, key: str, label: str, callback, tooltip: str,
    ) -> None:
        action = QAction(label, self)
        action.setToolTip(tooltip)
        action.setStatusTip(tooltip)
        action.triggered.connect(callback)
        menu.addAction(action)
        self.menu_actions.setdefault(key, []).append(action)

    # ── Tray Icon ─────────────────────────────────────────────────────────

    def _create_tray_icon(self) -> None:
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return

        self.tray_icon = QSystemTrayIcon(self)
        self._set_tray_state("idle")

        menu = QMenu(self)

        show_launcher = QAction("Show Launcher", self)
        show_launcher.triggered.connect(self.show_launcher)
        menu.addAction(show_launcher)

        show_wrapper = QAction("Show Guaardvark", self)
        show_wrapper.triggered.connect(self.show_wrapper)
        menu.addAction(show_wrapper)

        menu.addSeparator()

        menu.addMenu(self._build_open_menu())
        menu.addMenu(self._build_start_menu())
        menu.addMenu(self._build_restart_menu())
        menu.addMenu(self._build_stop_menu())

        menu.addSeparator()

        quit_action = QAction("Quit", self)
        quit_action.triggered.connect(QApplication.instance().quit)
        menu.addAction(quit_action)

        self.tray_icon.setContextMenu(menu)
        self.tray_icon.activated.connect(self._on_tray_activated)
        self.tray_icon.setToolTip("Guaardvark Launcher")
        self.tray_icon.show()

    def _base_tray_pixmap(self) -> QPixmap:
        pixmap = QPixmap(32, 32)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#1a1f29"))
        painter.drawEllipse(2, 2, 28, 28)

        painter.setPen(QPen(QColor("#56657a"), 1.2))
        painter.setBrush(QColor("#232a36"))
        painter.drawEllipse(3, 3, 26, 26)

        if ICON_PATH.exists():
            logo = QPixmap(str(ICON_PATH)).scaled(
                18, 18,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            painter.drawPixmap(7, 7, logo)

        painter.end()
        return pixmap

    def _icon_from_pixmap(self, pixmap: QPixmap) -> QIcon:
        return QIcon(pixmap)

    def _make_status_icon(self, state: str, frame: int = 0) -> QIcon:
        pixmap = self._base_tray_pixmap()
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        badge_rect = QRectF(18, 18, 12, 12)

        if state == "starting":
            painter.setBrush(QColor("#1f6feb"))
            painter.setPen(QPen(QColor("#9cc3ff"), 1.0))
            painter.drawEllipse(badge_rect)

            painter.translate(24, 24)
            painter.rotate(frame * 45)
            for index in range(8):
                alpha = 40 + int(26 * index)
                color = QColor(255, 255, 255, min(alpha, 255))
                painter.setPen(
                    QPen(color, 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
                )
                painter.drawLine(QPointF(0.0, -4.2), QPointF(0.0, -2.0))
                painter.rotate(45)
            painter.resetTransform()

        elif state == "ready":
            painter.setBrush(QColor("#2ea043"))
            painter.setPen(QPen(QColor("#d8ffe0"), 1.0))
            painter.drawEllipse(badge_rect)
            path = QPainterPath()
            path.moveTo(QPointF(20.8, 24.1))
            path.lineTo(QPointF(23.1, 26.3))
            path.lineTo(QPointF(27.4, 21.2))
            painter.setPen(
                QPen(
                    QColor("#ffffff"), 2.0,
                    Qt.PenStyle.SolidLine,
                    Qt.PenCapStyle.RoundCap,
                    Qt.PenJoinStyle.RoundJoin,
                )
            )
            painter.drawPath(path)

        elif state == "failed":
            painter.setBrush(QColor("#da3633"))
            painter.setPen(QPen(QColor("#ffd7d5"), 1.0))
            painter.drawEllipse(badge_rect)
            painter.setPen(
                QPen(QColor("#ffffff"), 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
            )
            painter.drawLine(QPointF(21.0, 21.0), QPointF(27.0, 27.0))
            painter.drawLine(QPointF(27.0, 21.0), QPointF(21.0, 27.0))

        else:
            painter.setBrush(QColor(120, 130, 145, 180))
            painter.setPen(QPen(QColor("#e6edf3"), 1.0))
            painter.drawEllipse(badge_rect)
            painter.setPen(QPen(QColor("#ffffff"), 1.6))
            painter.drawPoint(QPointF(24, 24))

        painter.end()
        return self._icon_from_pixmap(pixmap)

    def _set_tray_state(self, state: str) -> None:
        if self.tray_icon is None:
            return

        if state == "starting":
            if not self.tray_anim_timer.isActive():
                self.tray_anim_timer.start()
        else:
            self.tray_anim_timer.stop()

        if state == "ready":
            self.tray_icon.setToolTip("Guaardvark ready")
        elif state == "failed":
            self.tray_icon.setToolTip("Guaardvark startup failed")
        elif state == "starting":
            self.tray_icon.setToolTip("Guaardvark starting")
        else:
            self.tray_icon.setToolTip("Guaardvark Launcher")

        icon = self._make_status_icon(state, self.tray_anim_frame)
        self.tray_icon.setIcon(icon)

    def _advance_tray_animation(self) -> None:
        self.tray_anim_frame = (self.tray_anim_frame + 1) % 8
        if self.tray_icon is not None:
            self.tray_icon.setIcon(
                self._make_status_icon("starting", self.tray_anim_frame)
            )

    # ── Startup Flow ──────────────────────────────────────────────────────

    def startup(self) -> None:
        if self.worker and self.worker.isRunning():
            return
        self.restart_pending = False
        self.restart_watch_timer.stop()

        startup_options = self._collect_startup_options()
        self.retry_button.setEnabled(False)
        self.retry_button.setText("\u23f3   Launching\u2026")
        self.status_label.show()
        self.phase_label.show()
        self.activity_label.show()
        self.log_view.show()
        self.progress_bar.show()
        if self._wrapper_is_running():
            self._stop_wrapper_only()
        self._set_tray_state("starting")
        self.progress_bar.setRange(0, 0)
        self.current_phase_name = "Preparing startup"
        self.current_activity = "Applying launcher startup options."
        self.current_log_source = "Launcher"
        self.phase_label.setText("Preparing startup")
        self.activity_label.setText(
            "Startup order: native ComfyUI first, then WSL services, then the "
            "wrapper window. On first launch, dependency installs can take "
            "quite a while."
        )
        self.status_label.setText(
            "Applying launcher startup options and starting services\u2026"
        )
        comfy_flags = startup_options["comfy_flags"] or "(no extra Comfy flags)"
        self.log_hint_label.setText(f"Comfy flags: {comfy_flags}")
        waiting_text = "Waiting for log output...\n"
        self.log_view.setPlainText(waiting_text)
        self.last_log_snapshot = waiting_text
        self.last_log_label = "Launcher"
        self.status_bar.showMessage("Launching Guaardvark...")
        self._update_progress_text()

        self.worker = StartupWorker(REPO_ROOT, startup_options)
        self.worker.status.connect(self._set_status)
        self.worker.phase.connect(self._set_phase)
        self.worker.ready.connect(self._on_ready)
        self.worker.failed.connect(self._on_failed)
        self.worker.start()
        self.log_timer.start()
        self._refresh_service_state()

    def _set_status(self, message: str) -> None:
        self.current_activity = message
        self.status_label.setText(message)
        self.status_bar.showMessage(message)
        self.activity_label.setText(message)
        self._update_progress_text()
        self._refresh_service_state()

    def _set_phase(self, phase_name: str, progress: int) -> None:
        self.current_phase_name = phase_name
        self.current_log_source = self._log_source_for_phase(phase_name)
        self.phase_label.setText(f"Phase: {phase_name}")
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(progress)
        self._update_progress_text()

    def _refresh_live_logs(self) -> None:
        label = self.log_selector.currentText()
        path = LOG_FILES.get(label, SETUP_LOG)
        if path.exists():
            self.log_hint_label.setText(f"{path.name} \u2022 live tail")
            new_text = tail_text(path, lines=120)
        else:
            self.log_hint_label.setText(f"{path.name} not created yet")
            new_text = f"{path.name}: waiting for file to appear..."
        if new_text != self.last_log_snapshot or label != self.last_log_label:
            self.log_view.setPlainText(new_text)
            cursor = self.log_view.textCursor()
            cursor.movePosition(cursor.MoveOperation.End)
            self.log_view.setTextCursor(cursor)
            self.last_log_snapshot = new_text
            self.last_log_label = label
        self.current_log_source = label
        self._update_progress_text()
        self._save_preferences()

    def _on_ready(self) -> None:
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(100)
        self.current_phase_name = "Frontend ready"
        self.current_log_source = "Frontend"
        self.phase_label.setText("Phase: Frontend ready")
        if self.open_wrapper_checkbox.isChecked():
            self.current_activity = "Frontend is ready. Opening Guaardvark window..."
            self.status_label.setText(
                "Frontend is ready. Opening Guaardvark window..."
            )
        else:
            self.current_activity = (
                "Frontend is ready. Wrapper auto-open is disabled."
            )
            self.status_label.setText(
                "Frontend is ready. Wrapper auto-open is disabled."
            )
        self.activity_label.setText(self.current_activity)
        self.status_bar.showMessage("Frontend ready.")
        self._set_tray_state("ready")
        self.retry_button.setEnabled(True)
        self.retry_button.setText("\u21bb   Relaunch")
        self.retry_button.setToolTip(
            "Run the startup sequence again with the current options."
        )
        self._update_progress_text()
        if self.open_wrapper_checkbox.isChecked():
            self._show_wrapper_when_ready()
            if not self._wrapper_is_running():
                self.ready_timer.start()

    def _show_wrapper_when_ready(self) -> None:
        if not is_port_open(FRONTEND_PORT):
            return
        self.ready_timer.stop()
        self.show_wrapper()
        self.current_phase_name = "Wrapper opened"
        self.current_activity = "The embedded Guaardvark UI has been opened."
        self.current_log_source = "Frontend"
        self._update_progress_text()
        if self.minimize_to_tray_checkbox.isChecked():
            self.hide_to_tray()
            self.status_bar.showMessage(
                "Guaardvark is ready. Launcher minimized to tray."
            )
        else:
            self.status_bar.showMessage("Guaardvark is ready.")
        self._refresh_service_state()

    def _on_failed(self, message: str, logs: str) -> None:
        self.ready_timer.stop()
        self.log_timer.stop()
        self.progress_bar.setRange(0, 100)
        self.retry_button.setEnabled(True)
        self.retry_button.setText("\u21bb   Retry Startup")
        self.retry_button.setToolTip(
            "Try the startup sequence again using the current options."
        )
        self.current_phase_name = "Startup failed"
        self.current_activity = message
        self.current_log_source = "Launcher"
        self.status_label.setText(message)
        self.phase_label.setText("Phase: Startup failed")
        self.progress_bar.setValue(100)
        self.activity_label.setText(
            "Startup stopped. The latest collected logs are shown below."
        )
        self.log_view.setPlainText(logs)
        self.status_bar.showMessage("Startup failed.")
        self._set_tray_state("failed")
        self._update_progress_text()
        self._refresh_service_state()
        QMessageBox.critical(
            self, "Guaardvark Startup Failed", f"{message}\n\n{logs}"
        )

    # ── Window Management ─────────────────────────────────────────────────

    def show_launcher(self) -> None:
        self.show()
        self.raise_()
        self.activateWindow()
        self._refresh_service_state()

    @staticmethod
    def _edge_executable() -> Path:
        candidates = (
            Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
            Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
            Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "Edge" / "Application" / "msedge.exe",
        )
        for candidate in candidates:
            if candidate.is_file():
                return candidate
        raise RuntimeError("Microsoft Edge is required for the standalone Guaardvark wrapper.")

    def _wrapper_is_running(self) -> bool:
        return self.wrapper_process is not None and self.wrapper_process.poll() is None

    def show_wrapper(self) -> None:
        EDGE_WRAPPER_PROFILE.mkdir(parents=True, exist_ok=True)
        self.wrapper_process = subprocess.Popen(
            [
                str(self._edge_executable()),
                f"--app={resolve_service_url(FRONTEND_PORT)}",
                f"--user-data-dir={EDGE_WRAPPER_PROFILE}",
                "--no-first-run",
                "--disable-background-mode",
            ],
            cwd=REPO_ROOT,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        self._refresh_service_state()

    def hide_to_tray(self) -> None:
        if self.tray_icon is None:
            self.hide()
            return
        self.hide()
        self.tray_icon.showMessage(
            "Guaardvark",
            "Launcher minimized to tray. Use the tray icon to reopen logs "
            "or the main window.",
            QSystemTrayIcon.MessageIcon.Information,
            4000,
        )

    def _on_tray_activated(
        self, reason: QSystemTrayIcon.ActivationReason,
    ) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            if self._wrapper_is_running():
                self.show_wrapper()
            else:
                self.show_launcher()

    # ── Service Actions (backend logic unchanged) ─────────────────────────

    def _run_powershell_background(
        self, script_path: Path, env: dict[str, str] | None = None,
    ) -> None:
        subprocess.Popen(
            [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(script_path),
            ],
            cwd=self.settings.fileName() and REPO_ROOT or REPO_ROOT,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            env=env or os.environ.copy(),
        )

    def _run_wsl_background(self, command: str) -> None:
        subprocess.Popen(
            ["wsl.exe", "-d", "Ubuntu", "bash", "-lc", command],
            cwd=REPO_ROOT,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )

    def _resolve_wsl_python(self) -> str:
        probe = r"""
if command -v python3.12 >/dev/null 2>&1; then
    printf '%s\n' "python3.12"
elif [ -x "$HOME/.local/bin/uv" ]; then
    "$HOME/.local/bin/uv" python find 3.12 2>/dev/null
fi
"""
        result = subprocess.run(
            ["wsl.exe", "-d", "Ubuntu", "bash", "-lc", probe],
            cwd=REPO_ROOT,
            text=True,
            capture_output=True,
            timeout=120,
        )
        python_cmd = (result.stdout or "").strip().splitlines()
        if result.returncode != 0 or not python_cmd:
            raise RuntimeError("WSL Python 3.12 is missing.")
        return python_cmd[0].strip()

    def _wsl_repo_root(self) -> str:
        return f"/mnt/{REPO_ROOT.drive[0].lower()}{REPO_ROOT.as_posix()[2:]}"

    def _backend_start_command(self, python_cmd: str) -> str:
        return (
            f"cd '{self._wsl_repo_root()}' && "
            f"export PYTHON_CMD='{python_cmd}' && "
            "bash ./scripts/wsl_start_launcher_services.sh backend"
        )

    def _frontend_start_command(self) -> str:
        return (
            f"cd '{self._wsl_repo_root()}' && "
            "bash ./scripts/wsl_start_launcher_services.sh frontend"
        )

    def _wsl_core_stack_command(self, python_cmd: str) -> str:
        return (
            f"cd '{self._wsl_repo_root()}' && "
            f"export PYTHON_CMD='{python_cmd}' && "
            "bash ./scripts/wsl_start_launcher_services.sh core"
        )

    def _run_service_action(self, title: str, action) -> None:
        try:
            action()
        except Exception as exc:
            self.status_bar.showMessage(f"{title} failed.")
            QMessageBox.critical(self, title, str(exc))
            return
        self.status_bar.showMessage(f"{title} requested.")

    def _start_comfy_only(self) -> None:
        def run() -> None:
            if is_port_open(COMFY_PORT):
                self._set_status("ComfyUI is already running on port 8191.")
                return
            env = os.environ.copy()
            env["GUAARDVARK_COMFYUI_FLAGS"] = str(
                self._collect_startup_options().get("comfy_flags", "")
            ).strip()
            self._run_powershell_background(
                REPO_ROOT / "Run-ComfyUI-Native.ps1", env=env
            )
            self.current_phase_name = "Start ComfyUI"
            self.current_activity = "Launching native Windows ComfyUI."
            self.current_log_source = "Comfy Errors"
            self._update_progress_text()
        self._run_service_action("Start ComfyUI", run)

    def _start_wsl_stack_only(self) -> None:
        def run() -> None:
            python_cmd = self._resolve_wsl_python()
            command = self._wsl_core_stack_command(python_cmd)
            self._run_wsl_background(command)
            self.current_phase_name = "Start WSL services"
            self.current_activity = (
                f"Launching backend/frontend stack with {python_cmd}."
            )
            self.current_log_source = "Launch"
            self._update_progress_text()
        self._run_service_action("Start WSL services", run)

    def _start_backend_only(self) -> None:
        def run() -> None:
            if is_port_open(BACKEND_PORT):
                self._set_status("Backend is already running on port 5000.")
                return
            python_cmd = self._resolve_wsl_python()
            command = self._backend_start_command(python_cmd)
            self._run_wsl_background(command)
            self.current_phase_name = "Start backend"
            self.current_activity = "Launching the backend Flask app in WSL."
            self.current_log_source = "Backend"
            self._update_progress_text()
        self._run_service_action("Start backend", run)

    def _start_frontend_only(self) -> None:
        def run() -> None:
            if is_port_open(FRONTEND_PORT):
                self._set_status("Frontend is already running on port 5173.")
                return
            command = self._frontend_start_command()
            self._run_wsl_background(command)
            self.current_phase_name = "Start frontend"
            self.current_activity = "Launching the Vite frontend in WSL."
            self.current_log_source = "Frontend"
            self._update_progress_text()
        self._run_service_action("Start frontend", run)

    def _stop_comfy_only(self) -> None:
        def run() -> None:
            pid = find_listening_pid(COMFY_PORT)
            if pid is None:
                self._set_status(
                    "ComfyUI is not currently listening on port 8191."
                )
                self._refresh_service_state()
                return
            subprocess.run(
                ["taskkill.exe", "/PID", str(pid), "/T", "/F"],
                capture_output=True, text=True, timeout=20,
            )
            self.current_phase_name = "Stop ComfyUI"
            self.current_activity = f"Stopped ComfyUI process {pid}."
            self.current_log_source = "Comfy Errors"
            self._update_progress_text()
            self._refresh_service_state()
        self._run_service_action("Stop ComfyUI", run)

    def _stop_backend_only(self) -> None:
        def run() -> None:
            command = (
                f"cd '{self._wsl_repo_root()}' && "
                "if [ -f ./pids/backend.pid ]; then "
                'pid=$(cat ./pids/backend.pid); kill -TERM "$pid" '
                "2>/dev/null || true; rm -f ./pids/backend.pid; "
                "fi; "
                "fuser -k 5000/tcp 2>/dev/null || true"
            )
            self._run_wsl_background(command)
            self.current_phase_name = "Stop backend"
            self.current_activity = "Stopping the WSL backend process."
            self.current_log_source = "Backend"
            self._update_progress_text()
            self._refresh_service_state()
        self._run_service_action("Stop backend", run)

    def _stop_frontend_only(self) -> None:
        def run() -> None:
            command = (
                f"cd '{self._wsl_repo_root()}' && "
                "if [ -f ./pids/frontend.pid ]; then "
                'pid=$(cat ./pids/frontend.pid); kill -TERM "$pid" '
                "2>/dev/null || true; rm -f ./pids/frontend.pid; "
                "fi; "
                "fuser -k 5173/tcp 2>/dev/null || true"
            )
            self._run_wsl_background(command)
            self.current_phase_name = "Stop frontend"
            self.current_activity = "Stopping the WSL frontend process."
            self.current_log_source = "Frontend"
            self._update_progress_text()
            self._refresh_service_state()
        self._run_service_action("Stop frontend", run)

    def _stop_wrapper_only(self) -> None:
        if self._wrapper_is_running():
            subprocess.run(
                ["taskkill.exe", "/PID", str(self.wrapper_process.pid), "/T", "/F"],
                capture_output=True, text=True, timeout=20,
            )
        self.wrapper_process = None
        self.current_phase_name = "Stop wrapper"
        self.current_activity = "Closed the standalone Guaardvark window."
        self.current_log_source = "Frontend"
        self._update_progress_text()
        self.status_bar.showMessage("Wrapper closed.")
        self._refresh_service_state()

    def _stop_all_services(self) -> None:
        def run() -> None:
            self._stop_wrapper_only()
            stop_command = (
                f"cd '{self._wsl_repo_root()}' && "
                "if [ -f ./pids/backend.pid ]; then "
                'pid=$(cat ./pids/backend.pid); kill -TERM "$pid" '
                "2>/dev/null || true; rm -f ./pids/backend.pid; "
                "fi; "
                "if [ -f ./pids/frontend.pid ]; then "
                'pid=$(cat ./pids/frontend.pid); kill -TERM "$pid" '
                "2>/dev/null || true; rm -f ./pids/frontend.pid; "
                "fi; "
                "fuser -k 5000/tcp 2>/dev/null || true; "
                "fuser -k 5173/tcp 2>/dev/null || true"
            )
            self._run_wsl_background(stop_command)
            pid = find_listening_pid(COMFY_PORT)
            if pid is not None:
                subprocess.run(
                    ["taskkill.exe", "/PID", str(pid), "/T", "/F"],
                    capture_output=True, text=True, timeout=20,
                )
            self.current_phase_name = "Stop all"
            self.current_activity = (
                "Stopping wrapper, WSL services, and ComfyUI."
            )
            self.current_log_source = "Launch"
            self._update_progress_text()
            self._refresh_service_state()
        self._run_service_action("Stop all services", run)

    def _restart_comfy_only(self) -> None:
        self._stop_comfy_only()
        self._start_comfy_only()

    def _restart_backend_only(self) -> None:
        self._stop_backend_only()
        self._start_backend_only()

    def _restart_frontend_only(self) -> None:
        self._stop_frontend_only()
        self._start_frontend_only()

    def _restart_wrapper_only(self) -> None:
        self._stop_wrapper_only()
        self.show_wrapper()

    def _restart_all_services(self) -> None:
        if self.worker and self.worker.isRunning():
            return
        self.restart_pending = True
        self.restart_deadline = time.time() + 60
        self.current_phase_name = "Restart all"
        self.current_activity = (
            "Stopping current services and waiting for a clean shutdown."
        )
        self.current_log_source = "Launch"
        self._update_progress_text()
        self._stop_all_services()
        self.restart_watch_timer.start()

    # ── Close / Preferences ───────────────────────────────────────────────

    def closeEvent(self, event: QCloseEvent) -> None:
        self._save_preferences()
        if self.tray_icon is not None:
            event.ignore()
            self.hide_to_tray()
            return
        super().closeEvent(event)

    def _restore_preferences(self) -> None:
        selected_log = self.settings.value("selected_log", "Backend", type=str)
        index = self.log_selector.findText(selected_log)
        if index >= 0:
            self.log_selector.setCurrentIndex(index)
        self.start_comfy_checkbox.setChecked(
            self.settings.value("start_comfy", True, type=bool)
        )
        self.start_wsl_checkbox.setChecked(
            self.settings.value("start_wsl", True, type=bool)
        )
        self.open_wrapper_checkbox.setChecked(
            self.settings.value("open_wrapper", True, type=bool)
        )
        self.minimize_to_tray_checkbox.setChecked(
            self.settings.value("minimize_to_tray", True, type=bool)
        )
        self.reserve_vram_checkbox.setChecked(
            self.settings.value("reserve_vram_enabled", True, type=bool)
        )
        self.reserve_vram_value.setValue(
            self.settings.value("reserve_vram_value", 0.30, type=float)
        )
        for key, flag, _description in COMMON_COMFY_FLAGS:
            self.comfy_flag_checkboxes[key].setChecked(
                self.settings.value(f"comfy_flag_{key}", False, type=bool)
            )
        self.reserve_vram_value.setEnabled(
            self.reserve_vram_checkbox.isChecked()
        )

    def _save_preferences(self) -> None:
        self.settings.setValue("selected_log", self.log_selector.currentText())
        self.settings.setValue(
            "start_comfy", self.start_comfy_checkbox.isChecked()
        )
        self.settings.setValue(
            "start_wsl", self.start_wsl_checkbox.isChecked()
        )
        self.settings.setValue(
            "open_wrapper", self.open_wrapper_checkbox.isChecked()
        )
        self.settings.setValue(
            "minimize_to_tray", self.minimize_to_tray_checkbox.isChecked()
        )
        self.settings.setValue(
            "reserve_vram_enabled", self.reserve_vram_checkbox.isChecked()
        )
        self.settings.setValue(
            "reserve_vram_value", self.reserve_vram_value.value()
        )
        for key in self.comfy_flag_checkboxes:
            self.settings.setValue(
                f"comfy_flag_{key}",
                self.comfy_flag_checkboxes[key].isChecked(),
            )

    def _collect_startup_options(self) -> dict[str, object]:
        flags: list[str] = []
        for key, flag, _description in COMMON_COMFY_FLAGS:
            if self.comfy_flag_checkboxes[key].isChecked():
                flags.append(flag)
        if self.reserve_vram_checkbox.isChecked():
            flags.extend(
                ["--reserve-vram", f"{self.reserve_vram_value.value():.2f}"]
            )
        self._save_preferences()
        return {
            "start_comfy": self.start_comfy_checkbox.isChecked(),
            "start_wsl": self.start_wsl_checkbox.isChecked(),
            "open_wrapper": self.open_wrapper_checkbox.isChecked(),
            "minimize_to_tray": self.minimize_to_tray_checkbox.isChecked(),
            "comfy_flags": " ".join(flags).strip(),
        }

    # ── State Management ──────────────────────────────────────────────────

    def _set_idle_state(self) -> None:
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.current_phase_name = "Idle"
        self.current_activity = "Nothing has launched yet."
        self.current_log_source = "Launcher"
        self.phase_label.setText("Idle")
        self.status_label.setText(
            "Choose your startup options, then press Launch Guaardvark."
        )
        self.activity_label.setText(
            "Nothing has launched yet. Adjust the options above, hover "
            "anything unclear, and start when you are happy with the setup."
        )
        self.log_hint_label.setText("Waiting for startup...")
        idle_text = (
            "Launcher is idle.\n\n"
            "Pick your startup options above and press Launch Guaardvark "
            "when ready."
        )
        self.log_view.setPlainText(idle_text)
        self.last_log_snapshot = idle_text
        self.last_log_label = "Launcher"
        self.retry_button.setEnabled(True)
        self.retry_button.setText("\u25b6   Launch Guaardvark")
        self.retry_button.setToolTip(
            "Begin launching ComfyUI, the WSL services, and then the wrapper "
            "using the options above."
        )
        self.status_bar.showMessage("Launcher idle.")
        self._set_tray_state("idle")
        self._update_progress_text()
        self._refresh_service_state()

    def _flag_tooltip(self, flag: str, description: str) -> str:
        explainers = {
            "--lowvram": (
                "Uses less GPU memory by moving more work around. Slower, but "
                "often helps on tight VRAM."
            ),
            "--novram": (
                "The most extreme memory-saving mode. Use this only if normal "
                "or low VRAM modes still run out."
            ),
            "--highvram": (
                "Keeps more things loaded on the GPU for speed. Good if you "
                "have room to spare."
            ),
            "--gpu-only": (
                "Pushes more work onto the GPU instead of CPU or RAM. Faster "
                "when it works, but less forgiving on memory."
            ),
            "--cpu-vae": (
                "Moves VAE encode/decode work to the CPU. Slower, but can "
                "reduce GPU memory pressure."
            ),
            "--force-fp16": (
                "Forces half-precision where possible. Usually lowers VRAM "
                "use and can speed things up on supported GPUs."
            ),
            "--fp32-vae": (
                "Runs the VAE in full precision. Uses more memory, but can "
                "help avoid some image artifacts or weirdness."
            ),
            "--disable-async-offload": (
                "Turns off background memory shuffling. Mostly useful if "
                "async offload is causing instability."
            ),
        }
        return f"{description}\n\nNoob version: {explainers.get(flag, description)}"

    def _log_source_for_phase(self, phase_name: str) -> str:
        lowered = phase_name.lower()
        if "comfy" in lowered:
            return "Comfy Errors"
        if "backend" in lowered:
            return "Backend"
        if "frontend" in lowered or "ui" in lowered or "wrapper" in lowered:
            return "Frontend"
        if "wsl" in lowered:
            return "Launch"
        return self.log_selector.currentText() or "Launcher"

    def _update_progress_text(self) -> None:
        source = self.current_log_source or "Launcher"
        phase = self.current_phase_name or "Working"
        detail = (self.current_activity or "").replace("\n", " ").strip()
        if len(detail) > 72:
            detail = detail[:69].rstrip() + "..."
        if detail:
            text = f"{source} \u2022 {phase} \u2022 {detail}"
        else:
            text = f"{source} \u2022 {phase}"
        self.progress_bar.setFormat(text)

    def _refresh_service_state(self) -> None:
        state = self._collect_service_state()
        # Update the visual service cards.
        self.backend_card.set_active(state["backend"])
        self.frontend_card.set_active(state["frontend"])
        self.comfy_card.set_active(state["comfy"])
        self.wrapper_card.set_active(state["wrapper"])
        # Keep the hidden text label in sync (for any future use).
        parts = [
            f"Backend: {'running' if state['backend'] else 'stopped'}",
            f"Frontend: {'running' if state['frontend'] else 'stopped'}",
            f"ComfyUI: {'running' if state['comfy'] else 'stopped'}",
            f"Wrapper: {'open' if state['wrapper'] else 'closed'}",
        ]
        self.service_state_label.setText(" | ".join(parts))
        self._update_action_states(state)

    def _collect_service_state(self) -> dict[str, bool]:
        return {
            "backend": is_port_open(BACKEND_PORT),
            "frontend": is_port_open(FRONTEND_PORT),
            "comfy": is_port_open(COMFY_PORT, host="127.0.0.1"),
            "wrapper": self._wrapper_is_running(),
            "busy": (
                bool(self.worker and self.worker.isRunning())
                or self.restart_pending
            ),
        }

    def _set_actions_enabled(self, key: str, enabled: bool) -> None:
        for action in self.menu_actions.get(key, []):
            action.setEnabled(enabled)

    def _update_action_states(self, state: dict[str, bool]) -> None:
        busy = state["busy"]
        backend = state["backend"]
        frontend = state["frontend"]
        comfy = state["comfy"]
        wrapper = state["wrapper"]

        # Toolbar menu actions.
        self._set_actions_enabled("open_ui", frontend or wrapper)
        self._set_actions_enabled("open_frontend", frontend)
        self._set_actions_enabled("open_comfy", comfy)
        self._set_actions_enabled("open_backend_health", backend)
        self._set_actions_enabled("open_logs", True)

        self._set_actions_enabled("start_all", not busy)
        self._set_actions_enabled("start_comfy", not busy and not comfy)
        self._set_actions_enabled("start_backend", not busy and not backend)
        self._set_actions_enabled("start_frontend", not busy and not frontend)
        self._set_actions_enabled(
            "start_wsl_stack", not busy and not (backend and frontend)
        )

        self._set_actions_enabled(
            "restart_all",
            not busy and (backend or frontend or comfy or wrapper),
        )
        self._set_actions_enabled("restart_comfy", not busy and comfy)
        self._set_actions_enabled("restart_backend", not busy and backend)
        self._set_actions_enabled("restart_frontend", not busy and frontend)
        self._set_actions_enabled(
            "restart_wrapper", not busy and (frontend or wrapper)
        )

        self._set_actions_enabled(
            "stop_all",
            not busy and (backend or frontend or comfy or wrapper),
        )
        self._set_actions_enabled("stop_comfy", not busy and comfy)
        self._set_actions_enabled("stop_backend", not busy and backend)
        self._set_actions_enabled("stop_frontend", not busy and frontend)
        self._set_actions_enabled("stop_wrapper", not busy and wrapper)

        # Service card buttons.
        self.backend_card.start_btn.setEnabled(not busy and not backend)
        self.backend_card.stop_btn.setEnabled(not busy and backend)
        self.backend_card.restart_btn.setEnabled(not busy and backend)

        self.frontend_card.start_btn.setEnabled(not busy and not frontend)
        self.frontend_card.stop_btn.setEnabled(not busy and frontend)
        self.frontend_card.restart_btn.setEnabled(not busy and frontend)

        self.comfy_card.start_btn.setEnabled(not busy and not comfy)
        self.comfy_card.stop_btn.setEnabled(not busy and comfy)
        self.comfy_card.restart_btn.setEnabled(not busy and comfy)

        self.wrapper_card.start_btn.setEnabled(
            not busy and frontend and not wrapper
        )
        self.wrapper_card.stop_btn.setEnabled(not busy and wrapper)
        self.wrapper_card.restart_btn.setEnabled(
            not busy and (frontend or wrapper)
        )

    def _continue_restart_all(self) -> None:
        if not self.restart_pending:
            self.restart_watch_timer.stop()
            return
        state = self._collect_service_state()
        self._refresh_service_state()
        if not any((
            state["backend"], state["frontend"],
            state["comfy"], state["wrapper"],
        )):
            self.restart_pending = False
            self.restart_watch_timer.stop()
            self.current_phase_name = "Restart all"
            self.current_activity = (
                "Shutdown confirmed. Launching fresh startup sequence."
            )
            self.current_log_source = "Launch"
            self._update_progress_text()
            self.startup()
            return
        if time.time() >= self.restart_deadline:
            self.restart_pending = False
            self.restart_watch_timer.stop()
            self.current_phase_name = "Restart all timed out"
            self.current_activity = (
                "Some services did not shut down cleanly within 60 seconds."
            )
            self.current_log_source = "Launch"
            self._update_progress_text()
            self.status_bar.showMessage(
                "Restart timed out waiting for shutdown."
            )

    # ── Clipboard helper ──────────────────────────────────────────────────

    def _copy_logs_to_clipboard(self) -> None:
        text = self.log_view.toPlainText()
        clipboard = QApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(text)
        self.status_bar.showMessage("Logs copied to clipboard.", 3000)


# ─── Global Stylesheet ────────────────────────────────────────────────────────

def build_stylesheet() -> str:
    """Return the complete QSS dark-theme stylesheet for the application."""
    return """

    /* ═══════════════════════════════════════════════════
       BASE
       ═══════════════════════════════════════════════════ */

    QMainWindow, #mainContent {
        background-color: #0a0e17;
    }

    QWidget {
        color: #e2e8f0;
        font-family: 'Segoe UI', 'Inter', system-ui, sans-serif;
        font-size: 13px;
    }

    /* ═══════════════════════════════════════════════════
       TOOLBAR
       ═══════════════════════════════════════════════════ */

    QToolBar {
        background: #0f1520;
        border: none;
        border-bottom: 1px solid rgba(148, 163, 184, 0.06);
        padding: 5px 10px;
        spacing: 5px;
    }

    QToolBar QToolButton {
        background: transparent;
        color: #94a3b8;
        border: 1px solid transparent;
        border-radius: 7px;
        padding: 7px 16px;
        font-weight: 600;
        font-size: 12px;
        letter-spacing: 0.3px;
    }

    QToolBar QToolButton:hover {
        background: rgba(59, 130, 246, 0.08);
        color: #cbd5e1;
        border-color: rgba(59, 130, 246, 0.15);
    }

    QToolBar QToolButton:pressed {
        background: rgba(59, 130, 246, 0.14);
    }

    QToolBar QToolButton::menu-indicator {
        image: none;
        width: 0;
    }

    /* ═══════════════════════════════════════════════════
       MENUS
       ═══════════════════════════════════════════════════ */

    QMenu {
        background: #151d2c;
        border: 1px solid rgba(148, 163, 184, 0.10);
        border-radius: 8px;
        padding: 5px;
    }

    QMenu::item {
        padding: 8px 28px 8px 14px;
        border-radius: 5px;
        color: #cbd5e1;
        font-size: 12px;
    }

    QMenu::item:selected {
        background: rgba(59, 130, 246, 0.12);
        color: #f1f5f9;
    }

    QMenu::item:disabled {
        color: #3e4a5c;
    }

    QMenu::separator {
        height: 1px;
        background: rgba(148, 163, 184, 0.06);
        margin: 5px 10px;
    }

    /* ═══════════════════════════════════════════════════
       PROGRESS BAR
       ═══════════════════════════════════════════════════ */

    QProgressBar {
        border: 1px solid rgba(148, 163, 184, 0.08);
        border-radius: 10px;
        background: #111827;
        color: #94a3b8;
        min-height: 28px;
        max-height: 28px;
        font-size: 11px;
        font-weight: 500;
        text-align: center;
    }

    QProgressBar::chunk {
        border-radius: 9px;
        background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
            stop:0 #3b82f6, stop:0.5 #6366f1, stop:1 #8b5cf6);
    }

    /* ═══════════════════════════════════════════════════
       CHECKBOXES
       ═══════════════════════════════════════════════════ */

    QCheckBox {
        color: #cbd5e1;
        spacing: 8px;
        font-size: 12px;
    }

    QCheckBox::indicator {
        width: 16px;
        height: 16px;
        min-width: 16px;
        min-height: 16px;
        max-width: 16px;
        max-height: 16px;
        border-radius: 4px;
        border: 1.5px solid #3e4a5c;
        background: #1a2332;
    }

    QCheckBox::indicator:checked {
        background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
            stop:0 #3b82f6, stop:1 #6366f1);
        border-color: #3b82f6;
    }

    QCheckBox::indicator:hover {
        border-color: #60a5fa;
    }

    /* ═══════════════════════════════════════════════════
       COMBOBOX
       ═══════════════════════════════════════════════════ */

    QComboBox {
        background: #151d2c;
        border: 1px solid rgba(148, 163, 184, 0.10);
        border-radius: 7px;
        padding: 5px 12px;
        color: #cbd5e1;
        font-size: 12px;
    }

    QComboBox:hover {
        border-color: rgba(59, 130, 246, 0.25);
    }

    QComboBox::drop-down {
        border: none;
        padding-right: 8px;
    }

    QComboBox QAbstractItemView {
        background: #151d2c;
        border: 1px solid rgba(148, 163, 184, 0.10);
        border-radius: 6px;
        color: #cbd5e1;
        selection-background-color: rgba(59, 130, 246, 0.18);
        outline: none;
        padding: 4px;
    }

    /* ═══════════════════════════════════════════════════
       SPINBOX
       ═══════════════════════════════════════════════════ */

    QDoubleSpinBox {
        background: #151d2c;
        border: 1px solid rgba(148, 163, 184, 0.10);
        border-radius: 7px;
        padding: 4px 8px;
        color: #cbd5e1;
        font-size: 12px;
    }

    QDoubleSpinBox:hover {
        border-color: rgba(59, 130, 246, 0.25);
    }

    QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {
        background: transparent;
        border: none;
        width: 16px;
    }

    /* ═══════════════════════════════════════════════════
       LOG VIEWER
       ═══════════════════════════════════════════════════ */

    QPlainTextEdit {
        background: #0b0f18;
        color: #c9d1d9;
        border: 1px solid rgba(148, 163, 184, 0.06);
        border-radius: 10px;
        font-family: Consolas, 'Cascadia Code', 'JetBrains Mono', monospace;
        font-size: 12px;
        padding: 10px;
        selection-background-color: rgba(59, 130, 246, 0.25);
        selection-color: #f1f5f9;
    }

    /* ═══════════════════════════════════════════════════
       STATUS BAR
       ═══════════════════════════════════════════════════ */

    QStatusBar {
        background: #080c14;
        border-top: 1px solid rgba(148, 163, 184, 0.04);
        color: #4a5568;
        font-size: 11px;
        padding: 3px 10px;
    }

    /* ═══════════════════════════════════════════════════
       SCROLLBARS
       ═══════════════════════════════════════════════════ */

    QScrollBar:vertical {
        background: transparent;
        width: 7px;
        margin: 0;
    }

    QScrollBar::handle:vertical {
        background: rgba(148, 163, 184, 0.12);
        border-radius: 3px;
        min-height: 32px;
    }

    QScrollBar::handle:vertical:hover {
        background: rgba(148, 163, 184, 0.22);
    }

    QScrollBar::add-line:vertical,
    QScrollBar::sub-line:vertical,
    QScrollBar::add-page:vertical,
    QScrollBar::sub-page:vertical {
        height: 0;
        background: transparent;
    }

    QScrollBar:horizontal {
        background: transparent;
        height: 7px;
        margin: 0;
    }

    QScrollBar::handle:horizontal {
        background: rgba(148, 163, 184, 0.12);
        border-radius: 3px;
        min-width: 32px;
    }

    QScrollBar::handle:horizontal:hover {
        background: rgba(148, 163, 184, 0.22);
    }

    QScrollBar::add-line:horizontal,
    QScrollBar::sub-line:horizontal,
    QScrollBar::add-page:horizontal,
    QScrollBar::sub-page:horizontal {
        width: 0;
        background: transparent;
    }

    /* ═══════════════════════════════════════════════════
       SERVICE CARDS
       ═══════════════════════════════════════════════════ */

    #serviceCard {
        background: #111827;
        border: 1px solid rgba(148, 163, 184, 0.08);
        border-radius: 10px;
    }

    /* ═══════════════════════════════════════════════════
       HERO BUTTON
       ═══════════════════════════════════════════════════ */

    #heroButton {
        background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
            stop:0 #3b82f6, stop:1 #8b5cf6);
        color: #ffffff;
        border: none;
        border-radius: 12px;
        padding: 14px 48px;
        font-size: 15px;
        font-weight: 700;
        letter-spacing: 0.5px;
        min-width: 260px;
    }

    #heroButton:hover {
        background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
            stop:0 #4f93f7, stop:1 #9b75f8);
    }

    #heroButton:pressed {
        background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
            stop:0 #2563eb, stop:1 #7c3aed);
    }

    #heroButton:disabled {
        background: #1e293b;
        color: #475569;
    }

    /* ═══════════════════════════════════════════════════
       CARD ACTION BUTTONS
       ═══════════════════════════════════════════════════ */

    #cardActionBtn {
        background: rgba(148, 163, 184, 0.06);
        border: 1px solid rgba(148, 163, 184, 0.08);
        border-radius: 6px;
        color: #64748b;
        font-size: 11px;
        padding: 0;
    }

    #cardActionBtn:hover {
        background: rgba(59, 130, 246, 0.12);
        color: #cbd5e1;
        border-color: rgba(59, 130, 246, 0.2);
    }

    #cardActionBtn:pressed {
        background: rgba(59, 130, 246, 0.22);
    }

    #cardActionBtn:disabled {
        color: #1e293b;
        background: transparent;
        border-color: transparent;
    }

    /* ═══════════════════════════════════════════════════
       SECONDARY BUTTON (copy logs, etc.)
       ═══════════════════════════════════════════════════ */

    #secondaryBtn {
        background: rgba(148, 163, 184, 0.06);
        border: 1px solid rgba(148, 163, 184, 0.10);
        border-radius: 6px;
        color: #94a3b8;
        font-size: 11px;
        font-weight: 500;
        padding: 4px 14px;
    }

    #secondaryBtn:hover {
        background: rgba(59, 130, 246, 0.10);
        color: #cbd5e1;
        border-color: rgba(59, 130, 246, 0.2);
    }

    /* ═══════════════════════════════════════════════════
       COLLAPSIBLE SECTION TOGGLE
       ═══════════════════════════════════════════════════ */

    #collapsibleToggle {
        background: #111827;
        border: 1px solid rgba(148, 163, 184, 0.06);
        border-radius: 8px;
        color: #94a3b8;
        font-weight: 600;
        font-size: 12px;
        padding: 10px 14px;
        text-align: left;
    }

    #collapsibleToggle:hover {
        background: #151d2c;
        color: #cbd5e1;
        border-color: rgba(148, 163, 184, 0.10);
    }

    #collapsibleToggle:checked {
        border-bottom-left-radius: 0;
        border-bottom-right-radius: 0;
        border-bottom-color: transparent;
    }

    /* ═══════════════════════════════════════════════════
       TOOLTIPS
       ═══════════════════════════════════════════════════ */

    QToolTip {
        background: #1e293b;
        color: #e2e8f0;
        border: 1px solid rgba(148, 163, 184, 0.12);
        border-radius: 6px;
        padding: 8px 12px;
        font-size: 12px;
    }

    /* ═══════════════════════════════════════════════════
       MESSAGE BOXES
       ═══════════════════════════════════════════════════ */

    QMessageBox {
        background: #151d2c;
    }

    QMessageBox QLabel {
        color: #e2e8f0;
        font-size: 13px;
    }

    QMessageBox QPushButton {
        background: #1e293b;
        border: 1px solid rgba(148, 163, 184, 0.12);
        border-radius: 7px;
        padding: 7px 24px;
        color: #e2e8f0;
        font-weight: 500;
        min-width: 80px;
    }

    QMessageBox QPushButton:hover {
        background: rgba(59, 130, 246, 0.12);
        border-color: rgba(59, 130, 246, 0.25);
    }

    """


# ─── Entry Point ──────────────────────────────────────────────────────────────

def main() -> int:
    instance = acquire_single_instance()
    if instance is None:
        app = QApplication(sys.argv)
        QMessageBox.information(
            None, "Guaardvark", "Guaardvark Launcher is already running."
        )
        return 0

    set_windows_app_id()
    app = QApplication(sys.argv)
    app.setApplicationName("Guaardvark")
    app.setStyleSheet(build_stylesheet())
    if ICON_PATH.exists():
        app.setWindowIcon(QIcon(str(ICON_PATH)))
    window = LauncherWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
