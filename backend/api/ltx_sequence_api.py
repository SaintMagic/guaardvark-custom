"""Versioned LTX Director sequence API; single-shot routes remain separate."""

from __future__ import annotations

import copy
import uuid

from flask import Blueprint, request

from backend.services.ltx_sequence_service import get_ltx_sequence_service, new_sequence
from backend.services.workflows.ltx_shot_compiler import compile_timeline
from backend.utils.response_utils import error_response, success_response


ltx_sequence_bp = Blueprint("ltx_sequence", __name__, url_prefix="/api/ltx-director/sequences")


def _body() -> dict:
    value = request.get_json(silent=True)
    return value if isinstance(value, dict) else {}


@ltx_sequence_bp.route("", methods=["POST"])
def create_sequence():
    service = get_ltx_sequence_service()
    document = new_sequence(_body())
    try:
        # Creation may start as an empty editor document; strict shot/project
        # validation applies when rendering or saving an edited project.
        return success_response(service.repository.create(document))
    except (TypeError, ValueError) as exc:
        return error_response(str(exc), 400)


@ltx_sequence_bp.route("", methods=["GET"])
def list_sequences():
    return success_response(list(get_ltx_sequence_service().repository.list()))


@ltx_sequence_bp.route("/<sequence_id>", methods=["GET"])
def get_sequence(sequence_id: str):
    document = get_ltx_sequence_service().repository.get(sequence_id)
    return success_response(document) if document else error_response("Sequence not found", 404)


@ltx_sequence_bp.route("/<sequence_id>", methods=["PATCH"])
def update_sequence(sequence_id: str):
    service = get_ltx_sequence_service()
    current = service.repository.get(sequence_id)
    if not current:
        return error_response("Sequence not found", 404)
    updated = copy.deepcopy(current)
    updated.update(_body())
    updated["project_id"] = sequence_id
    try:
        return success_response(service.save(updated))
    except (TypeError, ValueError) as exc:
        return error_response(str(exc), 400)


@ltx_sequence_bp.route("/<sequence_id>", methods=["DELETE"])
def delete_sequence(sequence_id: str):
    return success_response({"deleted": get_ltx_sequence_service().repository.delete(sequence_id)})


@ltx_sequence_bp.route("/<sequence_id>/render", methods=["POST"])
def render_sequence(sequence_id: str):
    try:
        return success_response(get_ltx_sequence_service().render_all(sequence_id))
    except (KeyError, RuntimeError, ValueError) as exc:
        return error_response(str(exc), 400)


@ltx_sequence_bp.route("/<sequence_id>/cancel", methods=["POST"])
def cancel_sequence(sequence_id: str):
    return success_response({"cancelled": get_ltx_sequence_service().cancel(sequence_id)})


@ltx_sequence_bp.route("/<sequence_id>/stitch", methods=["POST"])
def stitch_sequence(sequence_id: str):
    try:
        return success_response(get_ltx_sequence_service().stitch(sequence_id))
    except (KeyError, ValueError, RuntimeError) as exc:
        return error_response(str(exc), 400)


@ltx_sequence_bp.route("/<sequence_id>/shots/<shot_id>/render", methods=["POST"])
def render_shot(sequence_id: str, shot_id: str):
    try:
        return success_response(get_ltx_sequence_service().render_shot(sequence_id, shot_id))
    except (KeyError, ValueError, RuntimeError) as exc:
        return error_response(str(exc), 400)


@ltx_sequence_bp.route("/<sequence_id>/shots/<shot_id>/retry", methods=["POST"])
def retry_shot(sequence_id: str, shot_id: str):
    try:
        return success_response(get_ltx_sequence_service().render_shot(sequence_id, shot_id, retry=True))
    except (KeyError, ValueError, RuntimeError) as exc:
        return error_response(str(exc), 400)


@ltx_sequence_bp.route("/<sequence_id>/shots/<shot_id>/keyframe/approve", methods=["POST"])
def approve_keyframe(sequence_id: str, shot_id: str):
    asset_path = (_body().get("asset_path") or "").strip()
    if not asset_path:
        return error_response("asset_path is required", 400)
    try:
        return success_response(get_ltx_sequence_service().approve_keyframe(sequence_id, shot_id, asset_path))
    except (KeyError, ValueError) as exc:
        return error_response(str(exc), 400)


@ltx_sequence_bp.route("/<sequence_id>/shots/<shot_id>/keyframe/generate", methods=["POST"])
def generate_keyframe(sequence_id: str, shot_id: str):
    try:
        return success_response(get_ltx_sequence_service().generate_keyframe(sequence_id, shot_id, regenerate=bool(_body().get("regenerate"))))
    except (KeyError, ValueError, RuntimeError) as exc:
        return error_response(str(exc), 400)


@ltx_sequence_bp.route("/<sequence_id>/shots/<shot_id>/cancel", methods=["POST"])
def cancel_shot(sequence_id: str, shot_id: str):
    return success_response({"cancelled": get_ltx_sequence_service().cancel(sequence_id), "shot_id": shot_id})


@ltx_sequence_bp.route("/<sequence_id>/manifest", methods=["GET"])
def manifest(sequence_id: str):
    document = get_ltx_sequence_service().repository.get(sequence_id)
    return success_response(document) if document else error_response("Sequence not found", 404)


@ltx_sequence_bp.route("/<sequence_id>/timeline-preview", methods=["POST"])
def timeline_preview(sequence_id: str):
    document = get_ltx_sequence_service().repository.get(sequence_id)
    if not document:
        return error_response("Sequence not found", 404)
    try:
        return success_response(compile_timeline(document))
    except (TypeError, ValueError) as exc:
        return error_response(str(exc), 400)
