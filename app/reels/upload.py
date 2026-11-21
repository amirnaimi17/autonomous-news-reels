"""Authenticated upload of one outbox package.

The Instagram token is never read here. A failed upload stays in the outbox.
"""

from __future__ import annotations

import json
import mimetypes
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.reels.config import ReelConfig
from app.reels.package import file_sha256
from app.reels.store import ReelStore, utc_now


class UploadTransport:
    """HTTP POST used by the uploader. Tests supply a fake."""

    def post(self, url: str, data: bytes, headers: dict[str, str]) -> tuple[int, dict]:
        request = urllib.request.Request(url, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=120) as response:  # noqa: S310
                body = response.read().decode("utf-8")
                return response.status, json.loads(body) if body else {}
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            try:
                payload = json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                payload = {"error": raw[:500]}
            return exc.code, payload


def fresh_enough(facts_checked_at: str, *, now: datetime, freshness_hours: int, recheck) -> tuple[bool, str]:
    """Refuse a package whose facts are older than the window or no longer current."""

    if not facts_checked_at:
        return False, "facts were not checked"
    checked = datetime.fromisoformat(facts_checked_at)
    if checked.tzinfo is None:
        checked = checked.replace(tzinfo=timezone.utc)
    if now.astimezone(timezone.utc) - checked.astimezone(timezone.utc) > timedelta(hours=freshness_hours):
        return False, "facts are outside the freshness window"
    result = recheck()
    if not result.get("ok"):
        return False, result.get("message") or "sources no longer match"
    return True, ""


def upload_package(
    config: ReelConfig,
    store: ReelStore,
    package_dir: Path,
    *,
    now: datetime,
    transport: UploadTransport | None = None,
    recheck=None,
    sleep=time.sleep,
) -> dict:
    """Upload one package. The same Reel id and checksum can be sent again."""

    manifest = json.loads((package_dir / "manifest.json").read_text(encoding="utf-8"))
    reel_id = manifest["reel_id"]
    video = package_dir / "reel.mp4"
    checksum = file_sha256(video)
    if checksum != manifest["checksum_sha256"]:
        store.add_upload(reel_id, url=config.ingest_url, http_status=None, response={}, error="checksum mismatch", success=False, now=now)
        store.set_status(reel_id, "upload_failed", error="checksum mismatch", now=now)
        return {"ok": False, "error": "checksum mismatch"}
    ok, reason = fresh_enough(
        manifest.get("facts_checked_at") or "",
        now=now,
        freshness_hours=config.freshness_hours,
        recheck=recheck or (lambda: {"ok": True}),
    )
    if not ok:
        store.set_status(reel_id, "stale", error=reason, now=now)
        store.add_error(reel_id=reel_id, attempt_id=None, stage="upload", message=reason, retryable=False, now=now)
        return {"ok": False, "error": reason}
    if not config.ingest_url or not config.ingest_token:
        store.set_status(reel_id, "queued", error="ingest is not configured", now=now)
        return {"ok": False, "error": "ingest is not configured"}
    if "instagram" in config.ingest_token.lower() or config.ingest_token.startswith("EAA"):
        return {"ok": False, "error": "refusing to send a token that looks like an Instagram token"}

    client = transport or UploadTransport()
    boundary = uuid.uuid4().hex
    body = _multipart(boundary, package_dir, manifest, checksum)
    headers = {
        "Authorization": f"Bearer {config.ingest_token}",
        "Content-Type": f"multipart/form-data; boundary={boundary}",
        "X-Reel-Id": reel_id,
        "X-Checksum-Sha256": checksum,
    }
    delay = 1.0
    last_error = "upload failed"
    status = None
    payload: dict = {}
    for attempt in range(config.max_attempts):
        try:
            status, payload = client.post(config.ingest_url, body, headers)
        except Exception as exc:
            status, payload = None, {"error": str(exc)}
        success = status in {200, 201}
        last_error = "" if success else str(payload.get("error") or status or "upload failed")
        store.add_upload(
            reel_id,
            url=config.ingest_url,
            http_status=status,
            response=payload,
            error=last_error,
            success=success,
            now=now,
        )
        if success:
            delivery_id = str(payload.get("delivery_id") or "")
            store.set_status(reel_id, "uploaded", delivery_id=delivery_id, now=now)
            return {"ok": True, "delivery_id": delivery_id, "response": payload}
        if status is not None and 400 <= status < 500:
            break
        if attempt + 1 < config.max_attempts:
            sleep(delay)
            delay *= 2
    store.set_status(reel_id, "upload_failed", error=last_error, now=now)
    return {"ok": False, "error": last_error, "http_status": status}


def _part(boundary: str, name: str, filename: str | None, content_type: str, payload: bytes) -> bytes:
    disposition = f'Content-Disposition: form-data; name="{name}"'
    if filename:
        disposition += f'; filename="{filename}"'
    header = f"--{boundary}\r\n{disposition}\r\nContent-Type: {content_type}\r\n\r\n".encode("utf-8")
    return header + payload + b"\r\n"


def _multipart(boundary: str, package_dir: Path, manifest: dict, checksum: str) -> bytes:
    video = (package_dir / "reel.mp4").read_bytes()
    parts = [
        _part(boundary, "reel", "reel.mp4", "video/mp4", video),
        _part(boundary, "caption", "caption.txt", "text/plain; charset=utf-8", (package_dir / "caption.txt").read_bytes()),
        _part(boundary, "manifest", "manifest.json", "application/json", json.dumps(manifest).encode("utf-8")),
        _part(boundary, "sources", "sources.json", "application/json", (package_dir / "sources.json").read_bytes()),
        _part(boundary, "attribution", "attribution.json", "application/json", (package_dir / "attribution.json").read_bytes()),
        _part(boundary, "checksum_sha256", None, "text/plain", checksum.encode("utf-8")),
    ]
    return b"".join(parts) + f"--{boundary}--\r\n".encode("utf-8")


def guess_type(path: Path) -> str:
    return mimetypes.guess_type(path.name)[0] or "application/octet-stream"
