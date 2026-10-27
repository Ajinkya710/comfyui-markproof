"""
Runs the nodes against a local fake of the Markproof API, so the real HTTP
and multipart code paths are exercised without network access or ComfyUI.
"""

import http.server
import importlib.util
import io
import json
import sys
import threading
from pathlib import Path

import numpy as np
import pytest
import torch
from PIL import Image

PKG_DIR = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("comfyui_markproof", PKG_DIR / "__init__.py", submodule_search_locations=[str(PKG_DIR)])
pkg = importlib.util.module_from_spec(spec)
sys.modules["comfyui_markproof"] = pkg
spec.loader.exec_module(pkg)
nodes = sys.modules["comfyui_markproof.nodes"]
client = sys.modules["comfyui_markproof.markproof_client"]

# Stands in for "the exact file Markproof returned", including a fake C2PA-ish
# chunk, so tests can prove the node saves these bytes rather than re-encoding.
MARKER = b"caBXfake-c2pa-manifest"


def marked_png_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (8, 6), (200, 100, 50)).save(buf, format="PNG")
    return buf.getvalue() + MARKER


class FakeAPI(http.server.BaseHTTPRequestHandler):
    requests: list = []
    fail_with: tuple | None = None

    def log_message(self, *args):
        pass

    def do_POST(self):
        body = self.rfile.read(int(self.headers["Content-Length"]))
        FakeAPI.requests.append({"path": self.path, "auth": self.headers.get("Authorization"), "body": body})
        if FakeAPI.fail_with:
            code, msg = FakeAPI.fail_with
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": msg}).encode())
            return
        n = len(FakeAPI.requests)
        if self.path.endswith("/mark"):
            data = marked_png_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("x-asset-id", f"asset-{n}")
            self.send_header("x-watermark-code", f"CODE{n:04}")
            self.send_header("x-verify-url", f"https://markproof.co/v/CODE{n:04}")
            self.send_header("x-watermark-robust", "true")
            self.end_headers()
            self.wfile.write(data)
        else:
            payload = {"watermark": {"detected": n % 2 == 1, "watermark_code": "CODE0001" if n % 2 == 1 else None}, "matched_asset": {"id": "a"} if n % 2 == 1 else None}
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(payload).encode())


@pytest.fixture
def api(monkeypatch):
    FakeAPI.requests = []
    FakeAPI.fail_with = None
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), FakeAPI)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setenv("MARKPROOF_BASE_URL", f"http://127.0.0.1:{server.server_port}/v1")
    monkeypatch.setenv("MARKPROOF_API_KEY", "lt_live_test")
    yield FakeAPI
    server.shutdown()


def batch(n=2, h=6, w=8):
    return torch.rand(n, h, w, 3)


def test_mark_and_save_saves_exact_bytes_and_returns_proofs(api, tmp_path):
    node = nodes.MarkproofMarkAndSave(output_dir=str(tmp_path))
    out = node.mark_and_save(batch(2), filename_prefix="shot", generator_name="ComfyUI", model_name="sdxl")

    files = sorted(tmp_path.iterdir())
    assert [f.name for f in files] == ["shot_00001_.png", "shot_00002_.png"]
    # Saved verbatim — the C2PA stand-in survives, which a re-encode would have stripped.
    assert all(f.read_bytes().endswith(MARKER) for f in files)

    images, codes, urls = out["result"]
    assert tuple(images.shape) == (2, 6, 8, 3) and images.dtype == torch.float32
    assert codes.split("\n") == ["CODE0001", "CODE0002"]
    assert urls.split("\n")[0] == "https://markproof.co/v/CODE0001"
    assert out["ui"]["images"][0] == {"filename": "shot_00001_.png", "subfolder": "", "type": "output"}

    first = api.requests[0]
    assert first["path"] == "/v1/mark" and first["auth"] == "Bearer lt_live_test"
    assert b'name="model_name"\r\n\r\nsdxl' in first["body"] and b"\x89PNG" in first["body"]


def test_tensor_png_roundtrip_is_lossless():
    img = torch.from_numpy(np.random.randint(0, 256, (5, 7, 3)).astype(np.float32) / 255.0)
    back = nodes.png_to_tensor(nodes.tensor_to_png(img))
    assert torch.allclose(back, img, atol=1 / 255 + 1e-6)


def test_missing_api_key_explains_how_to_set_it(api, monkeypatch, tmp_path):
    monkeypatch.delenv("MARKPROOF_API_KEY")
    with pytest.raises(client.MarkproofError, match="MARKPROOF_API_KEY"):
        nodes.MarkproofMarkAndSave(output_dir=str(tmp_path)).mark_and_save(batch(1))


def test_api_errors_surface_the_server_message(api, tmp_path):
    api.fail_with = (429, "Monthly quota exceeded (250/250).")
    with pytest.raises(client.MarkproofError, match=r"429: Monthly quota exceeded"):
        nodes.MarkproofMarkAndSave(output_dir=str(tmp_path)).mark_and_save(batch(1))
    assert list(tmp_path.iterdir()) == []  # nothing half-written


def test_verify_reports_per_image_and_overall(api):
    all_marked, codes, summary = nodes.MarkproofVerifyImage().verify(batch(2))
    assert all_marked is False
    assert summary.split("\n") == ["Image 1: watermark found, code CODE0001 (matches your record)", "Image 2: no Markproof watermark"]


def test_no_api_key_widget_so_keys_never_land_in_workflows():
    for cls in nodes.NODE_CLASS_MAPPINGS.values():
        spec = cls.INPUT_TYPES()
        names = {*spec.get("required", {}), *spec.get("optional", {})}
        assert not any("key" in n.lower() for n in names)
