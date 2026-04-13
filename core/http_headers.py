from __future__ import annotations

import unicodedata
from urllib.parse import quote


def build_attachment_content_disposition(file_name: str, *, fallback_name: str = "download") -> str:
    original = str(file_name or "").strip() or fallback_name
    normalized = unicodedata.normalize("NFKD", original)
    ascii_fallback = normalized.encode("ascii", "ignore").decode("ascii")
    ascii_fallback = ascii_fallback.replace('"', "_").replace("\\", "_").replace(";", "_")
    ascii_fallback = "".join(ch for ch in ascii_fallback if 32 <= ord(ch) < 127).strip(" .")
    if not ascii_fallback:
        ascii_fallback = fallback_name
    encoded_name = quote(original, safe="")
    return f"attachment; filename=\"{ascii_fallback}\"; filename*=UTF-8''{encoded_name}"
