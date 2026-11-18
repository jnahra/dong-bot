"""Posting to X (API v2, OAuth 1.0a user context), plus a dry-run stand-in."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Protocol

log = logging.getLogger(__name__)

API = "https://api.x.com/2"


class Poster(Protocol):
    def post(self, text: str, image: Path | None, alt_text: str = "") -> str: ...


class DryRunPoster:
    """Writes each would-be post next to its image instead of sending it."""

    def __init__(self, out_dir: str | Path = "out"):
        self.out_dir = Path(out_dir)
        self.posts: list[str] = []

    def post(self, text: str, image: Path | None, alt_text: str = "") -> str:
        self.posts.append(text)
        if image is not None:
            image.with_suffix(".txt").write_text(text + "\n", encoding="utf-8")
        log.info("[dry run] would post (%s):\n%s", image.name if image else "no image", text)
        return f"dry-run-{len(self.posts)}"


class XError(RuntimeError):
    pass


class XPoster:
    """Three calls per post: upload image, set alt text (best effort), create post."""

    def __init__(self, api_key: str, api_secret: str, access_token: str, access_secret: str,
                 session=None, timeout: float = 30.0):
        if session is None:
            from requests_oauthlib import OAuth1Session
            session = OAuth1Session(api_key, client_secret=api_secret,
                                    resource_owner_key=access_token,
                                    resource_owner_secret=access_secret)
        self.session = session
        self.timeout = timeout

    def _check(self, resp, what: str) -> dict:
        if resp.status_code >= 300:
            raise XError(f"{what} failed: HTTP {resp.status_code} {resp.text[:300]}")
        return resp.json()

    def upload_image(self, image: Path) -> str:
        with open(image, "rb") as fh:
            resp = self.session.post(
                f"{API}/media/upload",
                files={"media": (image.name, fh, "image/png")},
                data={"media_category": "tweet_image"},
                timeout=self.timeout,
            )
        return str(self._check(resp, "media upload")["data"]["id"])

    def set_alt_text(self, media_id: str, alt_text: str) -> None:
        resp = self.session.post(
            f"{API}/media/metadata",
            json={"id": media_id, "metadata": {"alt_text": {"text": alt_text[:1000]}}},
            timeout=self.timeout,
        )
        self._check(resp, "alt text")

    def post(self, text: str, image: Path | None, alt_text: str = "") -> str:
        body: dict = {"text": text}
        if image is not None:
            media_id = self.upload_image(image)
            if alt_text:
                try:
                    self.set_alt_text(media_id, alt_text)
                except Exception as exc:  # alt text is nice-to-have; never block the post
                    log.warning("could not set alt text: %s", exc)
            body["media"] = {"media_ids": [media_id]}
        resp = self.session.post(f"{API}/tweets", json=body, timeout=self.timeout)
        return str(self._check(resp, "create post")["data"]["id"])
