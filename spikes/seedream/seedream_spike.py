"""Spike: how Seedream 5.0 Lite behaves through Bitdeer (before planning AI frames).

Throwaway script. Each test is one paid call (about $0.035 per generated image). Run one
test at a time, inside the backend image so Pillow is there, with the key from .env:

    docker run --rm --env-file .env -v "$PWD/spikes/seedream:/x" \
        visio-studio-backend:latest python /x/seedream_spike.py t1

Inputs come from input/prompts.json; images and a log (output/log.jsonl) go to output/.
Both folders are ignored by git. The key is sent only to api-inference.bitdeer.ai and is
never printed. Reference images are images this spike generated itself.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

from PIL import Image

URL = "https://api-inference.bitdeer.ai/v1/images/generations"
MODEL = "seedream-5.0-lite"
SIZE = "1632x2880"  # 1.5 x the 1088 x 1920 generation size: scales down with no crop
HERE = Path(__file__).parent
OUT = HERE / "output"
PROMPTS = json.loads((HERE / "input" / "prompts.json").read_text())

KEEP = (
    "Image 1 is the first frame of a shot. Keep everything identical to image 1: the same "
    "woman, face, hair, clothes, room, light, camera position, framing and lens. Change only "
    "this: "
)
SAME_WOMAN = (
    "The woman in image 1 is the astronomer. Show exactly the same woman (the same face, "
    "hair and charcoal sweater) in a new shot: "
)


def reference(name: str) -> str:
    """An earlier output as a JPEG data URL (smaller than PNG in the request body)."""
    image = Image.open(OUT / f"{name}.png").convert("RGB")
    buffer = io.BytesIO()
    image.save(buffer, "JPEG", quality=90)
    return "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode()


def base(prompt: str, **extra: object) -> dict:
    return {
        "model": MODEL,
        "prompt": prompt,
        "size": SIZE,
        "response_format": "b64_json",
        "watermark": False,
        **extra,
    }


def tests() -> dict[str, dict]:
    s12, s13 = PROMPTS["scene12"], PROMPTS["scene13"]
    return {
        # Text to image, with a seed.
        "t1": lambda: base(s12["first"], seed=42),
        # The same request again: does the seed reproduce the image?
        "t1b": lambda: base(s12["first"], seed=42),
        # Last frame as an edit of the first (one reference image).
        "t2": lambda: base(KEEP + s12["last"], image=[reference("t1")]),
        # The same woman in another scene (one reference), returned as a link.
        "t3": lambda: {
            **base(SAME_WOMAN + s13["first"], image=[reference("t1")]),
            "response_format": "url",
        },
        # Eleven references: above the documented limit of 10.
        "t4": lambda: base(
            SAME_WOMAN + s12["first"], image=[reference(n) for n in ["t1", "t2", "t3"] * 3 + ["t1", "t2"]]
        ),
        # Ten references: the documented limit.
        "t5": lambda: base(
            SAME_WOMAN + s12["first"], image=[reference(n) for n in ["t1", "t2", "t3"] * 3 + ["t1"]]
        ),
        # Is the reference used at all? One image as a plain string, and a prompt that only
        # makes sense with it.
        "t7": lambda: base(
            "Reproduce image 1 exactly: the same woman, room, monitor, light and framing. "
            "Change nothing.",
            image=reference("t1"),
        ),
        # First and last frame in one call, as a related set of two images.
        # (Bitdeer refuses response_format "url": "response_format must be b64_json".)
        # Also a taller canvas (192 px more than 2880), to see
        # whether cropping the bottom strip removes the watermark Bitdeer adds anyway.
        "t6": lambda: {
            **base(
                "Two images of one shot, in order. Image 1, the first frame: "
                + s12["first"]
                + " Image 2, the last frame, the same shot a few seconds later with everything "
                "identical except: "
                + s12["last"],
                sequential_image_generation="auto",
                sequential_image_generation_options={"max_images": 2},
            ),
            "size": "1632x3072",
        },
    }


EDITS_URL = "https://api-inference.bitdeer.ai/v1/images/edits"


def jpeg_bytes(name: str) -> bytes:
    buffer = io.BytesIO()
    Image.open(OUT / f"{name}.png").convert("RGB").save(buffer, "JPEG", quality=90)
    return buffer.getvalue()


def multipart(fields: dict[str, str], files: list[tuple[str, str, bytes]]) -> tuple[bytes, str]:
    """A multipart/form-data body: text fields, then (field, filename, JPEG bytes) files."""
    boundary = "----visiostudiospike" + hashlib.sha256(os.urandom(8)).hexdigest()[:16]
    parts: list[bytes] = []
    for key, value in fields.items():
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'.encode()
        )
    for field, filename, data in files:
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{field}"; filename="{filename}"\r\n'
            "Content-Type: image/jpeg\r\n\r\n".encode()
            + data
            + b"\r\n"
        )
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


# Tests sent to /v1/images/edits as multipart forms: (fields, [(field, filename, image)]).
EDIT_TESTS = {
    # Is the reference used? The same "reproduce exactly" prompt as t7.
    "t8": lambda: (
        {
            "model": MODEL,
            "prompt": "Reproduce image 1 exactly: the same woman, room, monitor, light and "
            "framing. Change nothing.",
            "size": SIZE,
            "response_format": "b64_json",
            "watermark": "false",
        },
        [("image", "t1.jpg", jpeg_bytes("t1"))],
    ),
    }


def _diptych() -> dict:
    """First and last frame as the two halves of one image (t6 drew this by accident)."""
    s12 = PROMPTS["scene12"]
    return base(
        "One single photograph made of two panels side by side, exactly equal halves, each a "
        "tall portrait frame, with no border, no gutter, no frame lines, no text and no labels. "
        "Both panels show the same moment a few seconds apart, from the same camera position, "
        "with the same woman, clothes, room and light. LEFT PANEL: "
        + s12["first"]
        + " RIGHT PANEL: "
        + s12["last"],
        size="3264x3072",
    )


def save_image(name: str, index: int, item: dict) -> dict:
    if "b64_json" in item:
        data = base64.b64decode(item["b64_json"])
        source = "b64_json"
    else:
        link = item["url"]
        started = time.time()
        download = urllib.request.Request(link, headers={"User-Agent": "visio-studio-spike/1"})
        with urllib.request.urlopen(download, timeout=120) as response:  # no key: not Bitdeer
            data = response.read()
        source = f"url (host {urlparse(link).hostname}, download {time.time() - started:.1f} s)"
    suffix = "" if index == 0 else f"_{index + 1}"
    path = OUT / f"{name}{suffix}.png"
    image = Image.open(io.BytesIO(data))
    image.convert("RGB").save(path, "PNG")
    return {
        "file": path.name,
        "source": source,
        "format": image.format,
        "size": f"{image.width}x{image.height}",
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest()[:16],
        "revised_prompt": item.get("revised_prompt"),
        "other_keys": sorted(k for k in item if k not in ("b64_json", "url", "revised_prompt")),
    }


def main(name: str) -> None:
    OUT.mkdir(exist_ok=True)
    key = os.environ["BITDEEP_API_KEY"].strip().strip("\"'")
    if name in EDIT_TESTS:
        fields, files = EDIT_TESTS[name]()
        data, content_type = multipart(fields, files)
        url, body, sent_refs = EDITS_URL, dict(fields), len(files)
    else:
        body = _diptych() if name == "t9" else tests()[name]()
        data, content_type, url = json.dumps(body).encode(), "application/json", URL
        image = body.get("image")
        sent_refs = len(image) if isinstance(image, list) else (1 if image else 0)
    request = urllib.request.Request(
        url,
        data=data,
        # Cloudflare in front of Bitdeer refuses Python's default User-Agent (error 1010).
        headers={
            "Content-Type": content_type,
            "Authorization": f"Bearer {key}",
            "User-Agent": "visio-studio-spike/1",
        },
    )
    request_mb = len(request.data) / 1e6
    started = time.time()
    try:
        with urllib.request.urlopen(request, timeout=600) as response:
            status, payload = response.status, json.load(response)
    except urllib.error.HTTPError as error:
        status, payload = error.code, {"error_body": error.read().decode(errors="replace")[:1500]}
    elapsed = time.time() - started

    images = []
    for index, item in enumerate(payload.get("data") or []):
        images.append(save_image(name, index, item))
    record = {
        "test": name,
        "endpoint": urlparse(url).path,
        "status": status,
        "seconds": round(elapsed, 1),
        "request_mb": round(request_mb, 2),
        "references_sent": sent_refs,
        "params": {k: v for k, v in body.items() if k not in ("prompt", "image")},
        "response_keys": sorted(payload),
        "usage": payload.get("usage"),
        "model": payload.get("model"),
        "images": images,
        "error": payload.get("error") or payload.get("error_body"),
    }
    with (OUT / "log.jsonl").open("a") as log:
        log.write(json.dumps(record) + "\n")
    print(json.dumps(record, indent=1))


if __name__ == "__main__":
    main(sys.argv[1])
