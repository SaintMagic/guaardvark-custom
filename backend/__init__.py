"""Backend package helpers with minimal import side effects."""

from __future__ import annotations

__all__ = ["socketio"]


def __getattr__(name: str):
    if name == "socketio":
        from .socketio_instance import socketio

        return socketio
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
