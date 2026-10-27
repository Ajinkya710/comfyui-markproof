"""
Markproof nodes for ComfyUI.

Mark & Save writes the exact file the API returns, because ComfyUI's own
Save Image re-encodes images and would strip the C2PA manifest (the
watermark survives either way; it's in the pixels).
"""

import io
import os

import numpy as np
import torch
from PIL import Image

from .markproof_client import MarkproofError, mark_png, verify_png

try:  # Present inside ComfyUI; absent when the module is imported for tests.
    import folder_paths
except ImportError:  # pragma: no cover - only outside ComfyUI
    folder_paths = None


def tensor_to_png(image: torch.Tensor) -> bytes:
    """One ComfyUI IMAGE ([H, W, C] float 0-1) -> PNG bytes, with no metadata."""
    arr = np.clip(255.0 * image.cpu().numpy(), 0, 255).astype(np.uint8)
    buf = io.BytesIO()
    Image.fromarray(arr).save(buf, format="PNG", compress_level=4)
    return buf.getvalue()


def png_to_tensor(data: bytes) -> torch.Tensor:
    arr = np.asarray(Image.open(io.BytesIO(data)).convert("RGB")).astype(np.float32) / 255.0
    return torch.from_numpy(arr)


class MarkproofMarkAndSave:
    """Watermarks and C2PA-signs each image, then saves the marked files."""

    CATEGORY = "Markproof"
    FUNCTION = "mark_and_save"
    OUTPUT_NODE = True
    RETURN_TYPES = ("IMAGE", "STRING", "STRING")
    RETURN_NAMES = ("images", "watermark_codes", "verify_urls")
    DESCRIPTION = (
        "Adds an invisible watermark and signed Content Credentials (C2PA) to each image for EU AI Act Article 50, "
        "and saves the marked PNGs to the output folder. Use this instead of Save Image: re-encoding would strip "
        "the C2PA manifest. Needs MARKPROOF_API_KEY; one API call per image."
    )

    def __init__(self, output_dir=None):
        self.output_dir = output_dir

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "images": ("IMAGE",),
                "filename_prefix": ("STRING", {"default": "markproof"}),
            },
            "optional": {
                "generator_name": ("STRING", {"default": "ComfyUI", "tooltip": "Recorded in the C2PA manifest."}),
                "model_name": ("STRING", {"default": "", "tooltip": "e.g. the checkpoint you used. Recorded in the C2PA manifest."}),
            },
        }

    def _destination(self, prefix, width, height):
        if self.output_dir is None and folder_paths is not None:
            folder, name, counter, subfolder, _ = folder_paths.get_save_image_path(
                prefix, folder_paths.get_output_directory(), width, height
            )
            return folder, name, counter, subfolder
        folder = self.output_dir or os.getcwd()
        os.makedirs(folder, exist_ok=True)
        existing = [f for f in os.listdir(folder) if f.startswith(prefix + "_")]
        return folder, prefix, len(existing) + 1, ""

    def mark_and_save(self, images, filename_prefix="markproof", generator_name="ComfyUI", model_name=""):
        height, width = int(images.shape[1]), int(images.shape[2])
        folder, name, counter, subfolder = self._destination(filename_prefix, width, height)

        marked_tensors, codes, urls, previews, weak = [], [], [], [], []
        for image in images:
            result = mark_png(tensor_to_png(image), generator_name, model_name)
            filename = f"{name}_{counter:05}_.png"
            with open(os.path.join(folder, filename), "wb") as f:
                f.write(result.data)  # exact bytes: keeps the C2PA manifest intact
            counter += 1
            marked_tensors.append(png_to_tensor(result.data))
            codes.append(result.watermark_code)
            urls.append(result.verify_url)
            previews.append({"filename": filename, "subfolder": subfolder, "type": "output"})
            if result.watermark_robust is False:
                weak.append(result.watermark_code)

        if weak:
            print(
                "[Markproof] The watermark may not survive heavy editing for very smooth images "
                f"{', '.join(weak)}; their C2PA manifests are intact."
            )
        return {
            "ui": {"images": previews},
            "result": (torch.stack(marked_tensors), "\n".join(codes), "\n".join(urls)),
        }


class MarkproofVerifyImage:
    """Checks images for a Markproof watermark."""

    CATEGORY = "Markproof"
    FUNCTION = "verify"
    RETURN_TYPES = ("BOOLEAN", "STRING", "STRING")
    RETURN_NAMES = ("all_marked", "watermark_codes", "summary")
    DESCRIPTION = (
        "Checks each image for a Markproof watermark. ComfyUI images carry pixels only, so C2PA metadata can't be "
        "checked here; use markproof.co/check on the saved file for that. One API call per image."
    )

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"images": ("IMAGE",)}}

    def verify(self, images):
        codes, lines, all_marked = [], [], True
        for i, image in enumerate(images):
            r = verify_png(tensor_to_png(image))
            wm = r.get("watermark", {})
            detected = bool(wm.get("detected"))
            all_marked = all_marked and detected
            code = wm.get("watermark_code") or ""
            codes.append(code)
            matched = " (matches your record)" if r.get("matched_asset") else ""
            lines.append(f"Image {i + 1}: " + (f"watermark found, code {code}{matched}" if detected else "no Markproof watermark"))
        return (all_marked, "\n".join(codes), "\n".join(lines))


NODE_CLASS_MAPPINGS = {
    "MarkproofMarkAndSave": MarkproofMarkAndSave,
    "MarkproofVerifyImage": MarkproofVerifyImage,
}
NODE_DISPLAY_NAME_MAPPINGS = {
    "MarkproofMarkAndSave": "Markproof: Mark & Save",
    "MarkproofVerifyImage": "Markproof: Verify Image",
}

__all__ = ["MarkproofError", "NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]
