"""Atomic, versioned persistence for LTX Director sequence documents."""

from __future__ import annotations

import copy
import json
import os
import tempfile
import uuid
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

try:
    from backend.config import DATA_DIR
except Exception:
    DATA_DIR = Path("data")


SCHEMA_VERSION = 1


class LTXSequenceRepository:
    def __init__(self, root: Optional[Path] = None):
        self.root = Path(root or DATA_DIR / "ltx_sequences")
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, sequence_id: str) -> Path:
        return self.root / f"{sequence_id}.json"

    def create(self, document: Dict[str, Any]) -> Dict[str, Any]:
        sequence = copy.deepcopy(document)
        sequence.setdefault("project_id", str(uuid.uuid4()))
        sequence["revision"] = 1
        self.save(sequence)
        return sequence

    def save(self, document: Dict[str, Any]) -> Dict[str, Any]:
        sequence = copy.deepcopy(document)
        sequence["schema_version"] = SCHEMA_VERSION
        sequence_id = str(sequence["project_id"])
        target = self._path(sequence_id)
        if target.exists():
            try:
                with target.open("r", encoding="utf-8") as handle:
                    previous = json.load(handle)
                sequence["revision"] = max(int(previous.get("revision", 0)) + 1, int(sequence.get("revision", 0) or 0))
            except (OSError, ValueError, TypeError):
                sequence["revision"] = int(sequence.get("revision", 0) or 0) + 1
        fd, tmp_name = tempfile.mkstemp(prefix=f".{sequence_id}.", suffix=".tmp", dir=str(self.root))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(sequence, handle, indent=2, ensure_ascii=False)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_name, target)
        finally:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)
        return sequence

    def get(self, sequence_id: str) -> Optional[Dict[str, Any]]:
        path = self._path(sequence_id)
        if not path.is_file():
            return None
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    def delete(self, sequence_id: str) -> bool:
        path = self._path(sequence_id)
        if not path.exists():
            return False
        path.unlink()
        return True

    def list(self) -> Iterable[Dict[str, Any]]:
        for path in sorted(self.root.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True):
            try:
                with path.open("r", encoding="utf-8") as handle:
                    yield json.load(handle)
            except (OSError, ValueError):
                continue
