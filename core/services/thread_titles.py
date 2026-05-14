from __future__ import annotations

import json
import re
from typing import Any


AUTO_TITLE_FALLBACKS = {
    "",
    "new chat",
    "new conversation",
    "desktop chat",
    "untitled",
    "新会话",
    "新對話",
    "桌面聊天",
    "未命名",
    "未命名会话",
    # Historical mojibake variants kept so old rows can still be upgraded.
    "鏂颁細璇?",
    "妗岄潰鑱婂ぉ",
    "鏈懡鍚?",
    "鏈懡鍚嶄細璇?",
}


def normalize_thread_title(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip()).lower()


def can_auto_title_thread(thread: Any | None) -> bool:
    if thread is None:
        return False
    metadata = dict(getattr(thread, "meta", {}) or {})
    if metadata.get("auto_title_disabled") or metadata.get("manual_title"):
        return False
    return normalize_thread_title(getattr(thread, "title", "")) in AUTO_TITLE_FALLBACKS


def extract_title_from_model_text(value: Any, *, max_chars: int = 24) -> str:
    text = str(value or "").strip()
    if not text:
        return ""

    fenced = re.search(r"```(?:json)?\s*(.+?)\s*```", text, flags=re.S | re.I)
    if fenced:
        text = fenced.group(1).strip()

    try:
        payload = json.loads(text)
    except (TypeError, json.JSONDecodeError):
        payload = None
    if isinstance(payload, dict):
        for key in ("title", "name", "标题"):
            candidate = str(payload.get(key) or "").strip()
            if candidate:
                text = candidate
                break

    text = text.splitlines()[0] if "\n" in text else text
    text = re.sub(r"^(标题|title|name)\s*[:：]\s*", "", text, flags=re.I).strip()
    text = text.strip(" \t\r\n\"'`“”‘’[]()（）【】{}.,，。;；:：!?！？")
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return ""
    if len(text) > max_chars:
        text = text[:max_chars].rstrip(" \t,，。;；:：!?！？")
    return text
