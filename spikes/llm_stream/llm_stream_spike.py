"""Spike: how a streamed chat answer from GLM-5.3 looks through Bitdeer.

Throwaway script. Each test is one paid call (cents). Run one test at a time, inside the
backend image, with the key from .env:

    docker run --rm --env-file .env -v "$PWD/spikes/llm_stream:/x" \
        visio-studio-backend:latest python /x/llm_stream_spike.py t1

Tests:
    t1  a tiny JSON-mode question with the settings the app uses: stream, include_usage,
        response_format json_object, reasoning_effort high.
    t2  the same question with max_tokens far too small, to see how a cut-off answer looks
        in a stream (finish_reason "length", and whether usage still arrives).

What it answers (the numbers that set the stall limit and the parser):
    - the content type and the time to the first byte
    - the longest silence between two lines of the stream
    - whether reasoning is streamed (`reasoning_content`), or Bitdeer is silent while the
      model thinks
    - whether a final `usage` chunk arrives, and where `reasoning_tokens` is in it
    - the `finish_reason` of the answer, and any `:` comment (keep-alive) or error lines

Output goes to output/stream_log.jsonl (ignored by git). The key is sent only to
api-inference.bitdeer.ai and is never printed. Of the model's text only the lengths,
whether the answer is valid JSON, and short samples of the raw lines are stored.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path

URL = "https://api-inference.bitdeer.ai/v1/chat/completions"
MODEL = "zai-org/GLM-5.3"
HERE = Path(__file__).parent
OUT = HERE / "output"

SYSTEM = "You split sentences. Answer with a JSON object only."
USER = (
    "Split this sentence into two parts at the comma. Answer in exactly this form: "
    '{"parts": ["first part", "second part"]}\n\n'
    "Sentence: The last robot woke at dawn, and the whole city was silent."
)

# Seconds to wait for any single read. Long on purpose: this spike is here to find out how
# long Bitdeer can be silent, so it must not give up first.
READ_TIMEOUT_S = 600
SAMPLE_LINES = 4
SAMPLE_CHARS = 200


def body_for(name: str) -> dict:
    body = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": USER},
        ],
        "max_tokens": 4000,
        "stream": True,
        "stream_options": {"include_usage": True},
        "response_format": {"type": "json_object"},
        "reasoning_effort": "high",
    }
    if name == "t2":
        body["max_tokens"] = 60
    return body


def main(name: str) -> None:
    OUT.mkdir(exist_ok=True)
    key = os.environ["BITDEEP_API_KEY"].strip().strip("\"'")
    body = body_for(name)
    request = urllib.request.Request(
        URL,
        data=json.dumps(body).encode(),
        # Cloudflare in front of Bitdeer refuses Python's default User-Agent (error 1010).
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key}",
            "User-Agent": "visio-studio-spike/1",
        },
    )

    started = time.monotonic()
    record: dict = {"test": name, "params": {k: v for k, v in body.items() if k != "messages"}}
    raw_lines: list[str] = []  # every line, kept in memory only for the samples below
    stamps: list[float] = []  # seconds since start, one per line

    try:
        with urllib.request.urlopen(request, timeout=READ_TIMEOUT_S) as response:
            record["status"] = response.status
            record["content_type"] = response.headers.get("content-type")
            record["transfer_encoding"] = response.headers.get("transfer-encoding")
            record["seconds_to_headers"] = round(time.monotonic() - started, 2)
            for raw in response:
                stamps.append(time.monotonic() - started)
                raw_lines.append(raw.decode("utf-8", errors="replace").rstrip("\r\n"))
    except urllib.error.HTTPError as error:
        record["status"] = error.code
        record["error_body"] = error.read().decode(errors="replace")[:1500]
    except OSError as error:  # a timeout or a dropped connection, with what arrived so far
        record["transport_error"] = f"{type(error).__name__}: {error}"

    record["seconds_total"] = round(time.monotonic() - started, 2)
    if raw_lines:
        record.update(analyse(raw_lines, stamps, record.get("seconds_to_headers", 0.0)))

    with (OUT / "stream_log.jsonl").open("a") as log:
        log.write(json.dumps(record) + "\n")
    print(json.dumps(record, indent=1))


def analyse(lines: list[str], stamps: list[float], headers_at: float) -> dict:
    """Facts about the stream. The model's text is measured, not stored."""
    kinds: Counter[str] = Counter()
    delta_keys: Counter[str] = Counter()
    finish_reasons: list[str] = []
    errors: list[str] = []
    content = ""
    reasoning_chars = 0
    usage = None
    usage_chunk: dict | None = None
    response_ids: set[str] = set()
    done_seen = False
    unparsed = 0
    first_data_at: float | None = None
    first_content_at: float | None = None
    first_reasoning_at: float | None = None

    for line, stamp in zip(lines, stamps, strict=True):
        if line == "":
            kinds["blank"] += 1
        elif line.startswith(":"):
            kinds["comment"] += 1
        elif line.startswith("data:"):
            kinds["data"] += 1
            payload = line[5:].strip()
            if first_data_at is None:
                first_data_at = stamp
            if payload == "[DONE]":
                done_seen = True
                continue
            try:
                chunk = json.loads(payload)
            except ValueError:
                unparsed += 1
                continue
            if not isinstance(chunk, dict):
                unparsed += 1
                continue
            if isinstance(chunk.get("id"), str):
                response_ids.add(chunk["id"])
            if "error" in chunk:
                errors.append(json.dumps(chunk["error"])[:300])
            if chunk.get("usage"):
                usage = chunk["usage"]
                usage_chunk = {
                    "choices": chunk.get("choices"),
                    "top_level_keys": sorted(chunk),
                    "usage_keys": sorted(usage) if isinstance(usage, dict) else None,
                }
            for choice in chunk.get("choices") or []:
                delta = choice.get("delta") or {}
                for key, value in delta.items():
                    if value not in (None, ""):
                        delta_keys[key] += 1
                text = delta.get("content")
                if isinstance(text, str) and text:
                    content += text
                    if first_content_at is None:
                        first_content_at = stamp
                thought = delta.get("reasoning_content") or delta.get("reasoning")
                if isinstance(thought, str) and thought:
                    reasoning_chars += len(thought)
                    if first_reasoning_at is None:
                        first_reasoning_at = stamp
                if choice.get("finish_reason"):
                    finish_reasons.append(choice["finish_reason"])
        else:
            kinds["other"] += 1

    # The first gap is the wait for the first line, counted from the start of the call.
    gaps = [stamps[0]] + [b - a for a, b in zip(stamps, stamps[1:], strict=False)]
    longest = max(gaps)
    try:
        json.loads(content)
        content_is_json = True
    except ValueError:
        content_is_json = False

    def rounded(value: float | None) -> float | None:
        return None if value is None else round(value, 2)

    return {
        "line_kinds": dict(kinds),
        "lines_total": len(lines),
        "done_seen": done_seen,
        "unparsed_data_lines": unparsed,
        "response_ids": sorted(response_ids),
        "seconds_to_first_line": rounded(stamps[0]),
        "seconds_to_first_data": rounded(first_data_at),
        "seconds_to_first_reasoning": rounded(first_reasoning_at),
        "seconds_to_first_content": rounded(first_content_at),
        "longest_silence_s": round(longest, 2),
        "silences_over_5s": sum(1 for gap in gaps if gap > 5),
        "delta_keys_seen": dict(delta_keys),
        "reasoning_streamed": reasoning_chars > 0,
        "reasoning_chars": reasoning_chars,
        "content_chars": len(content),
        "content_is_json": content_is_json,
        "content_start": content[:SAMPLE_CHARS],
        "finish_reasons": finish_reasons,
        "usage": usage,
        "usage_chunk": usage_chunk,
        "errors": errors,
        "first_lines": [line[:SAMPLE_CHARS] for line in lines[:SAMPLE_LINES]],
        "last_lines": [line[:SAMPLE_CHARS] for line in lines[-SAMPLE_LINES:]],
    }


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in ("t1", "t2"):
        sys.exit("usage: llm_stream_spike.py t1|t2")
    main(sys.argv[1])
