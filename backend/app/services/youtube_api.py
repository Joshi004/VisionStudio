"""The Google calls of an upload: send the video, read its processing state (YT-004).

Like `youtube_auth`, this module is a recorded exception to the `core/outbound.py` rule (Y-4): the
Google library makes the HTTP calls, they are synchronous, so the caller runs every function
here in a worker thread (`anyio.to_thread.run_sync`), and nothing but Google's fixed endpoints is
called.

Nothing here logs. A caller may log the `ApiFailure`'s kind, status and reason code, never the
title, the description, the file or a token.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Literal

import httplib2
from google.auth.exceptions import RefreshError
from google.oauth2.credentials import Credentials
from google_auth_httplib2 import AuthorizedHttp
from googleapiclient.discovery import Resource, build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

from app.services.youtube_auth import NETWORK_ERRORS

# A multiple of 256 KiB, as the resumable upload requires.
CHUNK_BYTES: Final = 32 * 256 * 1024
# Times the library repeats a chunk (with backoff) after a 5xx answer or a dropped connection.
SEND_RETRIES: Final = 3
# httplib2 has no timeout of its own. This is per request, so a chunk may take this long.
HTTP_TIMEOUT_S: Final = 120

VIDEO_MIME: Final = "video/mp4"

# What `videos.list` says about `status.uploadStatus`.
UPLOAD_UPLOADED: Final = "uploaded"
UPLOAD_PROCESSED: Final = "processed"
UPLOAD_FAILED: Final = "failed"
UPLOAD_REJECTED: Final = "rejected"
UPLOAD_DELETED: Final = "deleted"

FailureKind = Literal[
    "needs_reconnect", "quota", "upload_limit", "refused", "unreachable", "server_error"
]

_QUOTA_REASONS: Final = ("quotaExceeded", "dailyLimitExceeded")
_UPLOAD_LIMIT_REASONS: Final = ("uploadLimitExceeded",)


class ApiFailure(Exception):
    """A Google call failed. `kind` says what the caller should do about it.

    `status` is the HTTP status when there was an answer, and `reason` Google's reason code (for
    example `quotaExceeded`). The message is a fixed sentence: it never holds Google's text.
    """

    def __init__(self, kind: FailureKind, *, status: int | None = None, reason: str | None = None):
        super().__init__(kind)
        self.kind = kind
        self.status = status
        self.reason = reason


def _reason_code(exc: HttpError) -> str | None:
    """Google's reason code of an error answer (`error.errors[0].reason`), or None."""
    try:
        data = json.loads(exc.content.decode("utf-8"))
    except (ValueError, AttributeError):
        return None
    error = data.get("error") if isinstance(data, dict) else None
    errors = error.get("errors") if isinstance(error, dict) else None
    if isinstance(errors, list) and errors and isinstance(errors[0], dict):
        reason = errors[0].get("reason")
        if isinstance(reason, str):
            return reason
    return None


def classify(exc: BaseException) -> ApiFailure | None:
    """Sorts an error of a Google call. None means it is not one this module knows, and the
    caller lets it go on as an unexpected error.
    """
    if isinstance(exc, ApiFailure):
        return exc
    if isinstance(exc, RefreshError):
        return ApiFailure("needs_reconnect")
    if isinstance(exc, HttpError):
        status = int(exc.resp.status)
        reason = _reason_code(exc)
        if status == 401:
            return ApiFailure("needs_reconnect", status=status, reason=reason)
        if status >= 500:
            return ApiFailure("server_error", status=status, reason=reason)
        if reason in _QUOTA_REASONS:
            return ApiFailure("quota", status=status, reason=reason)
        if reason in _UPLOAD_LIMIT_REASONS:
            return ApiFailure("upload_limit", status=status, reason=reason)
        return ApiFailure("refused", status=status, reason=reason)
    if isinstance(exc, NETWORK_ERRORS):
        return ApiFailure("unreachable")
    return None


def build_service(credentials: Credentials) -> Resource:
    """The YouTube client. Every request has a timeout, and the access token is renewed by the
    library when a call needs one.
    """
    http = AuthorizedHttp(credentials, http=httplib2.Http(timeout=HTTP_TIMEOUT_S))
    return build("youtube", "v3", http=http, static_discovery=True)


def insert_body(sent: dict[str, Any]) -> dict[str, Any]:
    """The `videos.insert` body, from the upload's snapshot (Y-5). No tags, no category."""
    return {
        "snippet": {
            "title": sent["title"],
            "description": sent["description"],
            "defaultLanguage": sent["default_language"],
            "defaultAudioLanguage": sent["default_audio_language"],
        },
        "status": {
            "privacyStatus": sent["privacy"],
            "selfDeclaredMadeForKids": sent["made_for_kids"],
            "containsSyntheticMedia": sent["synthetic_media"],
        },
    }


class ResumableUpload:
    """One resumable `videos.insert`, sent a chunk at a time so the caller can report progress."""

    def __init__(self, service: Resource, sent: dict[str, Any], path: Path) -> None:
        self.total_bytes = path.stat().st_size
        self._media = MediaFileUpload(
            str(path), mimetype=VIDEO_MIME, resumable=True, chunksize=CHUNK_BYTES
        )
        self._request = service.videos().insert(
            part="snippet,status",
            body=insert_body(sent),
            media_body=self._media,
            notifySubscribers=bool(sent["notify_subscribers"]),
        )

    def send_next(self) -> tuple[int, str | None]:
        """Sends the next chunk. Returns the bytes sent so far, and the video's id once YouTube
        has the whole file (None before that). Raises what the library raises.
        """
        progress, answer = self._request.next_chunk(num_retries=SEND_RETRIES)
        if answer is None:
            return int(progress.resumable_progress), None
        video_id = answer.get("id") if isinstance(answer, dict) else None
        if not isinstance(video_id, str) or not video_id:
            raise ApiFailure("server_error")
        return self.total_bytes, video_id


@dataclass(frozen=True)
class VideoStatus:
    """What YouTube says about a video it has been sent."""

    upload_status: str | None
    # YouTube's own words for why it failed or was rejected (a code such as `codec`), or None.
    problem: str | None
    privacy_status: str | None


def read_status(service: Resource, video_id: str) -> VideoStatus | None:
    """`videos.list(part="status,processingDetails")`, 1 quota unit. None when YouTube no longer
    lists the video.
    """
    answer = service.videos().list(part="status,processingDetails", id=video_id).execute()
    items = answer.get("items") or []
    if not items:
        return None
    status = items[0].get("status") or {}
    return VideoStatus(
        upload_status=status.get("uploadStatus"),
        problem=status.get("failureReason") or status.get("rejectionReason"),
        privacy_status=status.get("privacyStatus"),
    )


def failure_message(failure: ApiFailure, channel_title: str, *, sending: bool) -> str:
    """The sentence the owner reads for a failed call. `sending` is true while the video is being
    sent: a connection that fails then asks for Try again, which sends it again.
    """
    if failure.kind == "needs_reconnect":
        return f"Reconnect {channel_title} in Settings, then press Try again."
    if failure.kind == "quota":
        return "YouTube's daily limit for this app is used up. It resets at midnight Pacific time."
    if failure.kind == "upload_limit":
        return "This channel has reached YouTube's upload limit for now. Try again later."
    if failure.kind == "refused":
        detail = f"HTTP {failure.status}" if failure.status is not None else "no status"
        if failure.reason:
            detail = f"{detail}: {failure.reason}"
        return f"YouTube refused the request ({detail})."
    if sending:
        return "The video could not be sent to YouTube. Press Try again to send it again."
    return "YouTube could not be reached. Press Try again."
