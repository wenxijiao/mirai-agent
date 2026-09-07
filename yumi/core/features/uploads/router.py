"""File upload routes."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import FileResponse
from yumi.core.features.uploads.service import decode_upload_payload, owned_image_path, save_uploaded_file
from yumi.core.platform.http.dependencies import CurrentIdentity
from yumi.core.platform.http.schemas import FileUploadRequest
from yumi.core.platform.plugins import get_session_scope

router = APIRouter()


@router.post("/uploads")
async def uploads_endpoint(identity: CurrentIdentity, request: FileUploadRequest):
    raw = decode_upload_payload(request.content_base64)
    sid = get_session_scope().qualify_session_http(identity, request.session_id)
    return save_uploaded_file(
        sid,
        request.filename,
        raw,
        owner_user_id=identity.user_id if identity.user_id != "_local" else None,
    )


@router.get("/uploads/content")
async def uploaded_image_endpoint(identity: CurrentIdentity, path: str):
    image = owned_image_path(path, identity.user_id)
    return FileResponse(image, headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"})
