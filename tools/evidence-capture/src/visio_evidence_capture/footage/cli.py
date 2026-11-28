"""The command line of the footage capture tool.

Exit codes: 0 done, 1 refused or checks failed (the message says what to change), 2 wrong usage.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from ..youtube import parse_time_tenths
from . import (
    CLIP_MAX_S,
    CLIP_MIN_S,
    MAX_FINE_S,
    ON_SCREEN_TEXT,
    SAME_EVENT,
    STATUSES,
    TIERS,
    TOOL_NAME,
    TOOL_VERSION,
)
from .rounds import Described, FootageRound, Refused, check_described


def _add_round(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--round",
        default=".",
        metavar="FOLDER",
        help="the round folder (default: the current folder)",
    )


def _add_piece(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--mark", required=True, help="the mark id, for example f3")
    parser.add_argument("--piece", required=True, help="the piece id, for example p1")


def _add_described(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--tier", required=True, choices=TIERS, help="where the source stands")
    parser.add_argument("--publisher", required=True)
    parser.add_argument(
        "--what-it-shows",
        required=True,
        dest="what_it_shows",
        help="a plain sentence on what the viewer sees",
    )
    parser.add_argument(
        "--same-event",
        required=True,
        dest="same_event",
        choices=SAME_EVENT,
        help="does it show the very event the words describe (no = file footage)",
    )
    parser.add_argument(
        "--on-screen-text",
        required=True,
        dest="on_screen_text",
        choices=ON_SCREEN_TEXT,
        help="text on the picture that is not part of the scene: none, small or large",
    )
    parser.add_argument("--title", help="default: the page's own title")
    parser.add_argument("--published", metavar="YYYY-MM-DD")
    parser.add_argument("--event-date", dest="event_date", metavar="YYYY-MM-DD")
    parser.add_argument("--licence", help="for example: public domain, CC BY 4.0")
    parser.add_argument("--licence-url", dest="licence_url")
    parser.add_argument("--notes", default="", help="agent_notes")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=TOOL_NAME,
        description=(
            "Captures pictures, web pages, PDF pages and YouTube clips for a footage round, and "
            "scans YouTube videos by their pictures. It is the only "
            "thing that writes the pictures and the focus rectangles, and it writes the whole "
            "result.json. Run it inside the round folder."
        ),
    )
    parser.add_argument("--version", action="version", version=f"{TOOL_NAME} {TOOL_VERSION}")
    commands = parser.add_subparsers(dest="command", required=True)

    image = commands.add_parser("image", help="download a photo (JPEG, PNG or WebP)")
    _add_round(image)
    _add_piece(image)
    image.add_argument("--url", required=True, help="the address of the picture itself")
    image.add_argument("--page-url", dest="page_url", help="the page the picture was found on")
    _add_described(image)

    page = commands.add_parser("page", help="capture a web page from its top")
    _add_round(page)
    _add_piece(page)
    page.add_argument("--url", required=True)
    page.add_argument("--focus", help="the words on the page the script talks about")
    _add_described(page)

    pdf = commands.add_parser("pdf", help="capture one page of a PDF")
    _add_round(pdf)
    _add_piece(pdf)
    pdf.add_argument("--url", help="the address of the PDF")
    pdf.add_argument("--file", help="a PDF on this computer (needs --source-url)")
    pdf.add_argument("--source-url", dest="source_url", help="where the --file came from")
    pdf.add_argument("--page", type=int, required=True, help="the page (from 1)")
    pdf.add_argument("--focus", help="the words on the page the script talks about")
    _add_described(pdf)

    scan = commands.add_parser(
        "scan",
        help="look at a YouTube video by its pictures (nothing of the video is kept)",
        description=(
            "Without --fine: the video's facts, its captions and YouTube's preview pictures as "
            "contact sheets, with no download of the video. With --fine: only the range given is "
            "downloaded at low resolution and written as sheets of frames half a second apart, "
            "with the exact cut times. The files are written to results/<mark>/scans/<video_id>/."
        ),
    )
    _add_round(scan)
    scan.add_argument("--mark", required=True, help="the mark id, for example f3")
    scan.add_argument("--url", required=True, help="the video's YouTube address")
    scan.add_argument(
        "--from", dest="from_time", metavar="TIME", help="start of the range, such as 37:58.5"
    )
    scan.add_argument("--to", dest="to_time", metavar="TIME", help="end of the range")
    scan.add_argument(
        "--fine",
        action="store_true",
        help=f"frames half a second apart of a range of at most {MAX_FINE_S:.0f} s",
    )

    clip = commands.add_parser(
        "clip", help="download only the chosen seconds of a YouTube video, without sound"
    )
    _add_round(clip)
    _add_piece(clip)
    clip.add_argument("--url", required=True, help="the video's YouTube address")
    clip.add_argument(
        "--from",
        dest="from_time",
        required=True,
        metavar="TIME",
        help="where the part to use starts, such as 2:21.5",
    )
    clip.add_argument(
        "--to",
        dest="to_time",
        required=True,
        metavar="TIME",
        help=f"where it ends ({CLIP_MIN_S:.0f} to {CLIP_MAX_S:.0f} s after --from)",
    )
    clip.add_argument(
        "--moment",
        metavar="TIME",
        help="the instant that matters, inside the part to use (the clip is centred on it)",
    )
    _add_described(clip)

    report = commands.add_parser("report", help="set a mark's status and summary, add attempts")
    _add_round(report)
    report.add_argument("--mark", required=True)
    report.add_argument("--status", required=True, choices=STATUSES)
    report.add_argument("--summary", required=True, help="one or two plain sentences")
    report.add_argument(
        "--attempt",
        nargs=2,
        action="append",
        default=[],
        metavar=("WHAT", "OUTCOME"),
        help="what was tried and why it was not used (repeat for each attempt)",
    )

    remove = commands.add_parser("remove", help="remove one piece and its files")
    _add_round(remove)
    _add_piece(remove)

    validate = commands.add_parser("validate", help="check every result of the round")
    _add_round(validate)
    return parser


def _described(args: argparse.Namespace) -> Described:
    return check_described(
        Described(
            tier=args.tier,
            publisher=args.publisher,
            what_it_shows=args.what_it_shows,
            same_event=args.same_event,
            on_screen_text=args.on_screen_text,
            title=args.title,
            published=args.published,
            event_date=args.event_date,
            licence=args.licence,
            licence_url=args.licence_url,
            notes=args.notes,
        )
    )


def _saved(mark_id: str, piece_id: str, notes: list[str]) -> None:
    print(f"OK: saved piece {piece_id} of mark {mark_id}.")
    for note in notes:
        print(f"  {note}")
    print(
        f"  Next: run `report --mark {mark_id}` to set the mark's status and summary, and "
        "`validate` before you finish."
    )


def _run_image(args: argparse.Namespace) -> int:
    from .image import capture_image

    rnd = FootageRound(Path(args.round))
    described = _described(args)
    captured = capture_image(
        rnd,
        mark_id=args.mark,
        piece_id=args.piece,
        url=args.url,
        page_url=args.page_url,
        described=described,
    )
    rnd.store_piece(args.mark, captured.entry, captured.files)
    _saved(args.mark, args.piece, captured.notes)
    return 0


def _run_page(args: argparse.Namespace) -> int:
    from .page import capture_page

    rnd = FootageRound(Path(args.round))
    described = _described(args)
    captured = capture_page(
        rnd,
        mark_id=args.mark,
        piece_id=args.piece,
        url=args.url,
        focus=args.focus,
        described=described,
    )
    rnd.store_piece(args.mark, captured.entry, captured.files)
    _saved(args.mark, args.piece, captured.notes)
    return 0


def _run_pdf(args: argparse.Namespace) -> int:
    from .pdf_page import capture_pdf_page

    rnd = FootageRound(Path(args.round))
    described = _described(args)
    captured = capture_pdf_page(
        rnd,
        mark_id=args.mark,
        piece_id=args.piece,
        url=args.url,
        file=args.file,
        source_url=args.source_url,
        page_number=args.page,
        focus=args.focus,
        described=described,
    )
    rnd.store_piece(args.mark, captured.entry, captured.files)
    _saved(args.mark, args.piece, captured.notes)
    return 0


def _time(text: str | None) -> float | None:
    return None if text is None else parse_time_tenths(text)


def _run_scan(args: argparse.Namespace) -> int:
    from .scan import scan_fine, scan_previews

    rnd = FootageRound(Path(args.round))
    run = scan_fine if args.fine else scan_previews
    lines = run(
        rnd,
        mark_id=args.mark,
        url=args.url,
        from_s=_time(args.from_time),
        to_s=_time(args.to_time),
    )
    print("OK: scan done." if lines else "OK.")
    for line in lines:
        print(f"  {line}")
    return 0


def _run_clip(args: argparse.Namespace) -> int:
    from .clip import capture_clip

    rnd = FootageRound(Path(args.round))
    described = _described(args)
    use_from, use_to = _time(args.from_time), _time(args.to_time)
    assert use_from is not None and use_to is not None
    captured = capture_clip(
        rnd,
        mark_id=args.mark,
        piece_id=args.piece,
        url=args.url,
        use_from=use_from,
        use_to=use_to,
        moment=_time(args.moment),
        described=described,
    )
    rnd.store_piece(args.mark, captured.entry, captured.files)
    _saved(args.mark, args.piece, captured.notes)
    return 0


def _run_report(args: argparse.Namespace) -> int:
    rnd = FootageRound(Path(args.round))
    rnd.mark(args.mark)
    result = rnd.report(
        args.mark,
        status=args.status,
        summary=args.summary,
        attempts=[(what, outcome) for what, outcome in args.attempt],
    )
    print(
        f"OK: mark {args.mark} is {result['status']} with {len(result['pieces'])} piece(s) "
        f"and {len(result['attempts'])} attempt(s)."
    )
    return 0


def _run_remove(args: argparse.Namespace) -> int:
    rnd = FootageRound(Path(args.round))
    rnd.mark(args.mark)
    result = rnd.remove_piece(args.mark, args.piece)
    print(f"OK: removed {args.piece} of mark {args.mark}.")
    if result["status"] is None:
        print("  The mark's status is now unset: run `report` again.")
    return 0


def _run_validate(args: argparse.Namespace) -> int:
    from .validate import validate_round

    rnd = FootageRound(Path(args.round))
    report = validate_round(rnd)
    print(f"Round {rnd.round_id}: {len(rnd.mark_ids)} mark(s)")
    width = max((len(row[0]) for row in report.rows), default=2)
    for mark_id, status, pieces in report.rows:
        print(f"  {mark_id.ljust(width)}  {status.ljust(10)}  {pieces}")
    for text in report.warnings:
        print(f"WARNING: {text}")
    for text in report.problems:
        print(f"PROBLEM: {text}")
    if report.ok:
        print("Checks passed: shape, files, places and focus.")
        return 0
    print(f"{len(report.problems)} problem(s) found. Fix them and run validate again.")
    return 1


_COMMANDS = {
    "image": _run_image,
    "page": _run_page,
    "pdf": _run_pdf,
    "scan": _run_scan,
    "clip": _run_clip,
    "report": _run_report,
    "remove": _run_remove,
    "validate": _run_validate,
}


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return _COMMANDS[args.command](args)
    except Refused as error:
        print(f"REFUSED: {error}", file=sys.stderr)
        return 1
    except OSError as error:
        print(f"REFUSED: a file could not be read or written: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
