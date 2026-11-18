"""The command line of the capture tool.

Exit codes: 0 done, 1 refused or checks failed (the message says what to change), 2 wrong usage.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from . import RELATIONS, STATUSES, TIERS, TOOL_NAME, TOOL_VERSION
from .rounds import Described, Refused, Round, check_described


def _add_round(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--round",
        default=".",
        metavar="FOLDER",
        help="the round folder (default: the current folder)",
    )


def _add_claim(parser: argparse.ArgumentParser, *, evidence: bool = False) -> None:
    parser.add_argument("--claim", required=True, help="the claim id, for example c1")
    if evidence:
        parser.add_argument("--evidence", required=True, help="the evidence id, for example e1")


def _add_described(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--quote", required=True, help="the exact words of the source")
    parser.add_argument("--relation", required=True, choices=RELATIONS)
    parser.add_argument("--tier", required=True, choices=TIERS, help="source_tier")
    parser.add_argument("--publisher", required=True)
    parser.add_argument(
        "--what-it-says",
        required=True,
        dest="what_it_says",
        help="a plain sentence, including any difference from the claim",
    )
    parser.add_argument("--title", help="default: the page's own title")
    parser.add_argument("--author")
    parser.add_argument("--published", metavar="YYYY-MM-DD")
    parser.add_argument("--archive-url", dest="archive_url")
    parser.add_argument("--notes", default="", help="agent_notes")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=TOOL_NAME,
        description=(
            "Captures verified screenshots of web pages and PDFs for a research round. It is "
            "the only thing that writes coordinates and screenshots, and it writes the whole "
            "result.json. Run it inside the round folder."
        ),
    )
    parser.add_argument("--version", action="version", version=f"{TOOL_NAME} {TOOL_VERSION}")
    commands = parser.add_subparsers(dest="command", required=True)

    web = commands.add_parser("web", help="capture a quote on a web page")
    _add_round(web)
    _add_claim(web, evidence=True)
    web.add_argument("--url", required=True)
    _add_described(web)

    pdf = commands.add_parser("pdf", help="capture a quote in a PDF")
    _add_round(pdf)
    _add_claim(pdf, evidence=True)
    pdf.add_argument("--url", help="the address of the PDF")
    pdf.add_argument("--file", help="a PDF on this computer (needs --source-url)")
    pdf.add_argument("--source-url", dest="source_url", help="where the --file came from")
    pdf.add_argument("--page", type=int, help="the page (from 1), to search only there")
    _add_described(pdf)

    report = commands.add_parser(
        "report", help="set a claim's status and summary, and add attempts"
    )
    _add_round(report)
    _add_claim(report)
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

    remove = commands.add_parser("remove", help="remove one piece of evidence and its files")
    _add_round(remove)
    _add_claim(remove, evidence=True)

    validate = commands.add_parser("validate", help="check every result of the round")
    _add_round(validate)

    draw = commands.add_parser("draw", help="write a debug picture of a capture's rectangles")
    _add_round(draw)
    _add_claim(draw, evidence=True)
    return parser


def _described(args: argparse.Namespace) -> Described:
    return check_described(
        Described(
            relation=args.relation,
            tier=args.tier,
            publisher=args.publisher,
            what_it_says=args.what_it_says,
            title=args.title,
            author=args.author,
            published=args.published,
            archive_url=args.archive_url,
            notes=args.notes,
        )
    )


def _saved(rnd: Round, claim_id: str, evidence_id: str, notes: list[str]) -> None:
    print(f"OK: saved evidence {evidence_id} of claim {claim_id}.")
    for note in notes:
        print(f"  {note}")
    print(
        f"  Next: run `report --claim {claim_id}` to set the claim's status and summary, and "
        "`validate` before you finish."
    )


def _run_web(args: argparse.Namespace) -> int:
    from .web import capture_web

    rnd = Round(Path(args.round))
    described = _described(args)
    captured = capture_web(
        rnd,
        claim_id=args.claim,
        evidence_id=args.evidence,
        url=args.url,
        quote=args.quote,
        described=described,
    )
    rnd.store_evidence(args.claim, captured.entry, captured.files)
    _saved(rnd, args.claim, args.evidence, captured.notes)
    return 0


def _run_pdf(args: argparse.Namespace) -> int:
    from .pdf import capture_pdf

    rnd = Round(Path(args.round))
    described = _described(args)
    captured = capture_pdf(
        rnd,
        claim_id=args.claim,
        evidence_id=args.evidence,
        url=args.url,
        file=args.file,
        source_url=args.source_url,
        quote=args.quote,
        page=args.page,
        described=described,
    )
    rnd.store_evidence(args.claim, captured.entry, captured.files)
    _saved(rnd, args.claim, args.evidence, captured.notes)
    return 0


def _run_report(args: argparse.Namespace) -> int:
    rnd = Round(Path(args.round))
    rnd.claim(args.claim)
    result = rnd.report(
        args.claim,
        status=args.status,
        summary=args.summary,
        attempts=[(what, outcome) for what, outcome in args.attempt],
    )
    print(
        f"OK: claim {args.claim} is {result['status']} with {len(result['evidence'])} piece(s) "
        f"of evidence and {len(result['attempts'])} attempt(s)."
    )
    return 0


def _run_remove(args: argparse.Namespace) -> int:
    rnd = Round(Path(args.round))
    result = rnd.remove_evidence(args.claim, args.evidence)
    print(f"OK: removed {args.evidence} of claim {args.claim}.")
    if result["status"] is None:
        print("  The claim's status is now unset: run `report` again.")
    return 0


def _run_validate(args: argparse.Namespace) -> int:
    from .validate import validate_round

    rnd = Round(Path(args.round))
    report = validate_round(rnd)
    print(f"Round {rnd.round_id}: {len(rnd.claim_ids)} claim(s)")
    width = max((len(row[0]) for row in report.rows), default=2)
    for claim_id, status, sources in report.rows:
        print(f"  {claim_id.ljust(width)}  {status.ljust(12)}  {sources}")
    for text in report.warnings:
        print(f"WARNING: {text}")
    for text in report.problems:
        print(f"PROBLEM: {text}")
    if report.ok:
        print("Checks passed: shape, files, quotes and rectangles.")
        return 0
    print(f"{len(report.problems)} problem(s) found. Fix them and run validate again.")
    return 1


def _run_draw(args: argparse.Namespace) -> int:
    from .draw import draw_debug

    rnd = Round(Path(args.round))
    for path in draw_debug(rnd, args.claim, args.evidence):
        print(path)
    return 0


_COMMANDS = {
    "web": _run_web,
    "pdf": _run_pdf,
    "report": _run_report,
    "remove": _run_remove,
    "validate": _run_validate,
    "draw": _run_draw,
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
