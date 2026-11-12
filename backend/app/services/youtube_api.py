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
from googleapiclient.http import MediaFileUpload, MediaInMemoryUpload

from app.services.youtube_auth import NETWORK_ERRORS

# A multiple of 256 KiB, as the resumable upload requires.
CHUNK_BYTES: Final = 32 * 256 * 1024
# Times the library repeats a chunk (with backoff) after a 5xx answer or a dropped connection.
SEND_RETRIES: Final = 3
# httplib2 has no timeout of its own. This is per request, so a chunk may take this long.
HTTP_TIMEOUT_S: Final = 120

VIDEO_MIME: Final = "video/mp4"
THUMBNAIL_MIME: Final = "image/png"
# YouTube accepts an SRT file as a generic binary upload.
CAPTIONS_MIME: Final = "application/octet-stream"
CAPTIONS_LANGUAGE: Final = "en"
CAPTIONS_NAME: Final = "English"

# What `videos.list` says about `status.uploadStatus`.
UPLOAD_UPLOADED: Final = "uploaded"
UPLOAD_PROCESSED: Final = "processed"
UPLOAD_FAILED: Final = "failed"
UPLOAD_REJECTED: Final = "rejected"
UPLOAD_DELETED: Final = "deleted"

# What `videos.list` says about `processingDetails.processingStatus` (YTF-001). A Short's
# thumbnail is only applied once this is `succeeded`.
PROCESSING_SUCCEEDED: Final = "succeeded"
PROCESSING_FAILED_STATUSES: Final = ("failed", "terminated")

# `captions.insert` answers 409 with this reason when a track with the same language and name
# is already on the video. `thumbnails.set` answers 429 with the other when a channel changed
# thumbnails too often.
CAPTION_EXISTS_REASON: Final = "captionExists"
THUMBNAIL_RATE_REASON: Final = "uploadRateLimitExceeded"
CAPTION_EXISTS_MESSAGE: Final = "The video already has an English caption track named English."
THUMBNAIL_RATE_MESSAGE: Final = (
    "YouTube says this channel changed thumbnails too often. Try again later."
)

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
    raw = httplib2.Http(timeout=HTTP_TIMEOUT_S)
    # A resumable upload answers each chunk with 308 "Resume Incomplete", which is not a redirect.
    raw.redirect_codes = raw.redirect_codes - {308}
    http = AuthorizedHttp(credentials, http=raw)
    return build("youtube", "v3", http=http, static_discovery=True)


def insert_body(sent: dict[str, Any]) -> dict[str, Any]:
    """The `videos.insert` body, from the upload's snapshot (Y-5, F-4). No category. The tags
    are sent only when there are some: a snapshot made before tags existed has none.
    """
    snippet: dict[str, Any] = {
        "title": sent["title"],
        "description": sent["description"],
        "defaultLanguage": sent["default_language"],
        "defaultAudioLanguage": sent["default_audio_language"],
    }
    if sent.get("tags"):
        snippet["tags"] = list(sent["tags"])
    return {
        "snippet": snippet,
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
    # `processingDetails.processingStatus` (`processing`, `succeeded`, `failed`, `terminated`),
    # or None when the answer has no `processingDetails`.
    processing_status: str | None = None
    # `processingDetails.processingFailureReason` (a code such as `streamingFailure`), or None.
    processing_problem: str | None = None


def read_status(service: Resource, video_id: str) -> VideoStatus | None:
    """`videos.list(part="status,processingDetails")`, 1 quota unit. None when YouTube no longer
    lists the video.
    """
    answer = service.videos().list(part="status,processingDetails", id=video_id).execute()
    items = answer.get("items") or []
    if not items:
        return None
    status = items[0].get("status") or {}
    details = items[0].get("processingDetails")
    if not isinstance(details, dict):
        details = {}
    processing_status = details.get("processingStatus")
    processing_problem = details.get("processingFailureReason")
    return VideoStatus(
        upload_status=status.get("uploadStatus"),
        problem=status.get("failureReason") or status.get("rejectionReason"),
        privacy_status=status.get("privacyStatus"),
        processing_status=processing_status if isinstance(processing_status, str) else None,
        processing_problem=processing_problem if isinstance(processing_problem, str) else None,
    )


def set_thumbnail(service: Resource, video_id: str, path: Path) -> None:
    """`thumbnails.set`, 50 quota units. A 5xx or a dropped connection is repeated by the library
    with backoff; a 4xx is not.
    """
    service.thumbnails().set(
        videoId=video_id,
        media_body=MediaFileUpload(str(path), mimetype=THUMBNAIL_MIME, resumable=False),
    ).execute(num_retries=SEND_RETRIES)


def insert_captions(service: Resource, video_id: str, srt: bytes) -> None:
    """`captions.insert` with an SRT track named "English", language `en`, not a draft, 400 quota
    units. The bytes are sent from memory, so no file is made.
    """
    service.captions().insert(
        part="snippet",
        body={
            "snippet": {
                "videoId": video_id,
                "language": CAPTIONS_LANGUAGE,
                "name": CAPTIONS_NAME,
                "isDraft": False,
            }
        },
        media_body=MediaInMemoryUpload(srt, mimetype=CAPTIONS_MIME, resumable=False),
    ).execute(num_retries=SEND_RETRIES)


def step_failure_message(failure: ApiFailure, channel_title: str, what: str) -> str:
    """The sentence the owner reads for a failed thumbnail or captions step. `what` is
    "thumbnail" or "captions".
    """
    if failure.kind == "needs_reconnect":
        return f"Reconnect {channel_title} in Settings, then press Try again on the {what}."
    if failure.kind == "quota":
        return "YouTube's daily limit for this app is used up. It resets at midnight Pacific time."
    if what == "thumbnail" and (failure.reason == THUMBNAIL_RATE_REASON or failure.status == 429):
        return THUMBNAIL_RATE_MESSAGE
    if failure.kind in ("refused", "upload_limit"):
        detail = f"HTTP {failure.status}" if failure.status is not None else "no status"
        if failure.reason:
            detail = f"{detail}: {failure.reason}"
        return f"YouTube refused the {what} ({detail})."
    return f"YouTube could not be reached for the {what}. Press Try again on it."


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
