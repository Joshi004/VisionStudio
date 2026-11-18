"""`draw`: a debug picture with the rectangles drawn over the screenshot, to see by eye that they
sit on the quote. Written under the system temporary folder, never in the round.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from PIL import Image, ImageDraw

from .rounds import Refused, Round
from .validate import capture_file

DEBUG_FOLDER = "visio-evidence-debug"


def draw_debug(rnd: Round, claim_id: str, evidence_id: str) -> list[Path]:
    """Write `<round>-<claim>-<evidence>.png` (the rectangles on the image) and, when there is a
    context image, `...-context.png` (the image's place in it). Returns the paths.
    """
    result = rnd.load_result(claim_id)
    item = next(
        (e for e in (result["evidence"] if result else []) if e.get("id") == evidence_id), None
    )
    if item is None:
        raise Refused(f"Claim {claim_id} has no evidence {evidence_id}.")
    capture = item.get("capture") or {}
    folder = rnd.claim_dir(claim_id, create=False)
    try:
        image_path = capture_file(folder, capture.get("image"), root=rnd.root)
    except ValueError as error:
        raise Refused(f"The image cannot be drawn: {error}.") from error

    out_dir = Path(tempfile.gettempdir()) / DEBUG_FOLDER
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{rnd.round_id}-{claim_id}-{evidence_id}"
    written: list[Path] = []

    with Image.open(image_path) as source:
        image = source.convert("RGBA")
    width, height = image.size
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    painter = ImageDraw.Draw(overlay)
    line = max(2, round(min(width, height) / 300))
    for x, y, w, h in capture.get("rects") or []:
        box = (x * width, y * height, (x + w) * width, (y + h) * height)
        painter.rectangle(box, fill=(255, 220, 0, 70), outline=(255, 0, 0, 255), width=line)
    path = out_dir / f"{stem}.png"
    Image.alpha_composite(image, overlay).convert("RGB").save(path)
    written.append(path)

    context_name = capture.get("context_image")
    box = capture.get("context_box")
    if context_name and box:
        try:
            context_path = capture_file(folder, context_name, root=rnd.root)
        except ValueError as error:
            raise Refused(f"The context image cannot be drawn: {error}.") from error
        with Image.open(context_path) as source:
            context = source.convert("RGB")
        cw, ch = context.size
        painter = ImageDraw.Draw(context)
        painter.rectangle(
            (box[0] * cw, box[1] * ch, (box[0] + box[2]) * cw, (box[1] + box[3]) * ch),
            outline=(255, 0, 0),
            width=max(3, round(min(cw, ch) / 200)),
        )
        context_out = out_dir / f"{stem}-context.png"
        context.save(context_out)
        written.append(context_out)
    return written
