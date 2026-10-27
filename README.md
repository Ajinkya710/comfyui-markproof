# Markproof for ComfyUI

Mark the images your workflows generate for the EU AI Act's Article 50, using [Markproof](https://markproof.co): an invisible watermark plus signed C2PA Content Credentials, saved straight from ComfyUI.

## Nodes

**Markproof: Mark & Save** (category *Markproof*)

Use it in place of **Save Image**. It marks each image and saves the marked PNG to your output folder, and outputs:

- `images`: the marked images, for previews or further nodes;
- `watermark_codes` and `verify_urls`: one per line, for example `https://markproof.co/v/57CR5KMW`.

Set `generator_name` (default `ComfyUI`) and `model_name` (for example your checkpoint) to record them in the C2PA manifest.

> **Why not Save Image?** ComfyUI's Save Image re-encodes images, which strips the C2PA manifest. The watermark survives (it's in the pixels), but the signed Content Credentials don't. Mark & Save writes the exact file Markproof returns, so both layers stay intact.

**Markproof: Verify Image**

Checks images for a Markproof watermark and outputs `all_marked` (true or false), the codes, and a per-image summary. ComfyUI images carry pixels only, so it can't check C2PA metadata; drop the saved file into [markproof.co/check](https://markproof.co/check) for the full check.

## Install

1. Install the node pack, either way:
   - **ComfyUI-Manager:** search for *Markproof* and click Install.
   - **comfy-cli:** `comfy node install comfyui-markproof`
   - **Manually:** `cd ComfyUI/custom_nodes && git clone https://github.com/Ajinkya710/comfyui-markproof`

   No extra Python packages are needed.
2. Create an API key on your [Markproof dashboard](https://markproof.co/dashboard) (250 free calls a month).
3. Start ComfyUI with the key in the environment:
   ```sh
   MARKPROOF_API_KEY=lt_live_... python main.py
   ```
   On Windows (PowerShell): `$env:MARKPROOF_API_KEY = "lt_live_..."; python main.py`

The key is read from the environment on purpose. ComfyUI saves node settings into images and workflow files, so a key typed into a node would leak whenever you shared one.

## Good to know

- Each image is one API call against your plan. Marking takes a few seconds per image.
- Images are processed in the EU and not stored by Markproof.
- If the console reports that a watermark may not survive heavy editing, the image was very smooth or featureless. It's still marked and signed; rely on the C2PA manifest for it.

## Development

```sh
cd tests && python -m pytest   # runs against a local fake of the API
```
