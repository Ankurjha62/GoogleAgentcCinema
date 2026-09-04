"""Gmail trigger: polls the inbox for release emails.

Uses IMAP + the Gmail App Password (GMAIL_USER / GMAIL_APP_PASSWORD from .env)
so the pipeline can run fully headless - no interactive OAuth consent needed.

Matches emails whose subject hints at a release/feature/PR (configurable) and
returns their raw subject+body text for the intake agent.
"""
from __future__ import annotations

import imaplib
import email
from email.header import decode_header, make_header
from email.message import Message
from typing import List, Optional

from orchestrator.config import Config

RELEASE_KEYWORDS = ("release", "deploy", "feature", "pr:", "[testmind]")
SENDER_PREFIXES = ()  # optional: ("ops@", "ci@", "dev@")

MARK_SEEN = True


def _decode(value: Optional[str]) -> str:
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value)))
    except Exception:
        return value


def _get_body(msg: Message, max_len: int = 40000) -> str:
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() in ("text/plain", "text/html"):
                try:
                    payload = part.get_payload(decode=True)
                    if payload:
                        charset = part.get_content_charset() or "utf-8"
                        return payload.decode(charset, errors="replace")[:max_len]
                except Exception:
                    continue
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            charset = msg.get_content_charset() or "utf-8"
            return payload.decode(charset, errors="replace")[:max_len]
    return ""


def fetch_release_emails(cfg: Config, limit: int = 5) -> List[dict]:
    """Connect to Gmail IMAP and return matching unseen release emails.

    Each dict: {"id":..., "subject":..., "sender":..., "body":..., "raw":...}
    """
    host = "imap.gmail.com"
    mail = imaplib.IMAP4_SSL(host)
    try:
        mail.login(cfg.gmail_user, cfg.gmail_app_password)
    except imaplib.IMAP4.error as exc:
        raise ConnectionError(
            f"Gmail login failed for {cfg.gmail_user}: {exc}. "
            "Check GMAIL_APP_PASSWORD (an app password, not the normal password)."
        ) from exc

    mail.select("INBOX")
    status, data = mail.search(None, "UNSEEN")
    if status != "OK":
        return []

    found: List[dict] = []
    for num in (data[0] or b"").split()[:limit]:
        try:
            status, msg_data = mail.fetch(num, "(RFC822)")
            if status != "OK":
                continue
            raw = msg_data[0][1]
            msg = email.message_from_bytes(raw)
            subject = _decode(msg.get("Subject"))
            sender = _decode(msg.get("From"))
            if not _is_release(subject, sender):
                continue
            body = _get_body(msg)
            found.append(
                {
                    "id": num.decode(),
                    "subject": subject,
                    "sender": sender,
                    "body": body,
                    "raw": raw.decode(errors="replace"),
                }
            )
            if MARK_SEEN:
                mail.store(num, "+FLAGS", "\\Seen")
        except Exception:
            continue
    return found


def _is_release(subject: str, sender: str) -> bool:
    lowered = subject.lower()
    if any(k in lowered for k in RELEASE_KEYWORDS):
        return True
    if SENDER_PREFIXES and sender.lower().startswith(SENDER_PREFIXES):
        return True
    return False


def sample_email() -> str:
    """Return a canned release email for local/demo runs without Gmail."""
    return (
        "Subject: [RELEASE] v2.4.0 - Checkout & Cart improvements\n\n"
        "Hi team,\n\n"
        "Shipping v2.4.0 in this release:\n"
        "- Checkout flow now validates coupon codes (POST /checkout)\n"
        "- Cart endpoint /cart returns item stock badges\n"
        "- New /orders/{id} endpoint for order status\n"
        "- Checkout service is being re-deployed; keep an eye on its error rate\n\n"
        "Release ID: REL-2026-0905\n"
        "Affected services: cart-service, checkout-service\n"
    )