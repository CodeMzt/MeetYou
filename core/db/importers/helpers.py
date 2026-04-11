from __future__ import annotations


def infer_workspace_key(scope_user_id: str) -> str | None:
    candidate = str(scope_user_id or "").strip().lower()
    if not candidate or candidate == "global":
        return None
    if "study" in candidate:
        return "study"
    if any(token in candidate for token in ("lab", "raspi", "k230", "edge")):
        return "home-lab"
    if any(token in candidate for token in ("desktop", "pc", "windows")):
        return "desktop-main"
    return "personal"
