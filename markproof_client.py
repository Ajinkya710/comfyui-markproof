"""
Minimal Markproof API client for the ComfyUI nodes — standard library only,
so the node pack adds no dependencies to a ComfyUI install.
"""

import json
import os
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass

DEFAULT_BASE_URL = "https://markproof.co/v1"
USER_AGENT = "comfyui-markproof/0.1.0"


class MarkproofError(Exception):
    pass


@dataclass
class MarkResult:
    data: bytes
    content_type: str
    asset_id: str
    watermark_code: str
    verify_url: str
    c2pa_manifest_label: str | None
    watermark_robust: bool | None


def api_key() -> str:
    key = os.environ.get("MARKPROOF_API_KEY", "").strip()
    if not key:
        # Deliberately not a node widget: ComfyUI embeds widget values in saved
        # images and shared workflow files, which would leak the key.
        raise MarkproofError(
            "Set the MARKPROOF_API_KEY environment variable before starting ComfyUI "
            "(create a key at https://markproof.co/dashboard)."
        )
    return key


def _multipart(fields: dict, filename: str, data: bytes, content_type: str) -> tuple:
    boundary = uuid.uuid4().hex
    crlf = "\r\n"
    parts = []
    for name, value in fields.items():
        if value:
            parts.append(f'--{boundary}{crlf}Content-Disposition: form-data; name="{name}"{crlf}{crlf}{value}{crlf}'.encode())
    head = (
        f'--{boundary}{crlf}Content-Disposition: form-data; name="file"; filename="{filename}"{crlf}'
        f"Content-Type: {content_type}{crlf}{crlf}"
    )
    parts.append(head.encode() + data + crlf.encode())
    return b"".join(parts) + f"--{boundary}--{crlf}".encode(), f"multipart/form-data; boundary={boundary}"


def _post(path: str, body: bytes, content_type: str, timeout: float = 300):
    base = os.environ.get("MARKPROOF_BASE_URL", DEFAULT_BASE_URL).rstrip("/")
    req = urllib.request.Request(
        f"{base}{path}",
        data=body,
        headers={"Authorization": f"Bearer {api_key()}", "Content-Type": content_type, "User-Agent": USER_AGENT},
    )
    try:
        return urllib.request.urlopen(req, timeout=timeout)
    except urllib.error.HTTPError as e:
        try:
            message = json.loads(e.read().decode()).get("error", "")
        except Exception:
            message = ""
        raise MarkproofError(f"Markproof API error {e.code}: {message or e.reason}") from None
    except urllib.error.URLError as e:
        raise MarkproofError(f"Couldn't reach Markproof: {e.reason}") from None


def mark_png(png: bytes, generator_name: str = "", model_name: str = "") -> MarkResult:
    body, ctype = _multipart({"generator_name": generator_name, "model_name": model_name}, "image.png", png, "image/png")
    with _post("/mark", body, ctype) as r:
        robust = r.headers.get("x-watermark-robust")
        return MarkResult(
            data=r.read(),
            content_type=r.headers.get("content-type", "image/png"),
            asset_id=r.headers.get("x-asset-id", ""),
            watermark_code=r.headers.get("x-watermark-code", ""),
            verify_url=r.headers.get("x-verify-url", ""),
            c2pa_manifest_label=r.headers.get("x-c2pa-manifest-label"),
            watermark_robust={"true": True, "false": False}.get(robust or ""),
        )


def verify_png(png: bytes) -> dict:
    body, ctype = _multipart({}, "image.png", png, "image/png")
    with _post("/verify", body, ctype) as r:
        return json.loads(r.read().decode())
