from __future__ import annotations

import re
from html import unescape


CODE_RE = re.compile(r"(?<!\d)(\d{6})(?!\d)")


def strip_html(value: str) -> str:
    text = re.sub(r"<[^>]+>", " ", value or "")
    text = unescape(text).replace("\xa0", " ")
    return re.sub(r"\s+", " ", text).strip()


def parse_verification_code(subject: str = "", body: str = "", sender: str = "") -> str | None:
    haystack = " ".join([sender or "", subject or "", strip_html(body or "")]).lower()
    if sender and "openai" not in sender.lower():
        return None
    if subject and not any(keyword in subject.lower() for keyword in ["openai", "verification", "verify", "code"]):
        return None
    match = CODE_RE.search(haystack)
    return match.group(1) if match else None
