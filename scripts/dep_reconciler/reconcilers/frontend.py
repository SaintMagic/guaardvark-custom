"""Reconcile frontend node_modules against package-lock.json."""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from scripts.dep_reconciler.base import Reconciler


class Frontend(Reconciler):
    id = "frontend"
    name = "Frontend node_modules"

    def __init__(self, repo_root: Path):
        self.root = repo_root

    def manifests(self) -> list[Path]:
        # Lockfile only — it's the installed truth, same way pip uses requirements.txt.
        return [self.root / "frontend" / "package-lock.json"]

    def is_active(self) -> bool:
        return self.manifests()[0].is_file()

    def compute_hash(self) -> str:
        from scripts.dep_reconciler.util import hash_file
        return hash_file(self.manifests()[0]) or ""

    def install(self, log_path: Path) -> int:
        with log_path.open("a", encoding="utf-8") as log:
            log.write(f"\n=== {self.id} install @ {os.getpid()} ===\n")
            log.flush()
            npm_args = ["npm", "ci"]
            if os.environ.get("WSL_DISTRO_NAME"):
                npm_args.append("--no-bin-links")
            rc = self._run_subprocess(npm_args, log, cwd=self.root / "frontend")
            if rc == 0:
                return 0

            log.write("npm ci failed; clearing node_modules and npm cache before one retry\n")
            self._heal_install_state(log)
            return self._run_subprocess(npm_args, log, cwd=self.root / "frontend")

    def _heal_install_state(self, log) -> None:
        node_modules = self.root / "frontend" / "node_modules"
        npm_cache = Path.home() / ".npm" / "_cacache"
        for path in (node_modules, npm_cache):
            try:
                if path.exists():
                    shutil.rmtree(path)
                    log.write(f"Removed {path}\n")
            except OSError as exc:
                log.write(f"WARN: could not remove {path}: {exc}\n")

    @staticmethod
    def _run_subprocess(args: list[str], log, cwd: Path | None = None) -> int:
        proc = subprocess.run(args, stdout=log, stderr=subprocess.STDOUT, cwd=cwd)
        return proc.returncode
