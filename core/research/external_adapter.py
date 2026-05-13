from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


TERMINAL_STATUSES = {"completed", "failed", "cancelled"}


@dataclass(frozen=True)
class ResearchAdapterConfig:
    base_url: str = ""
    token: str = ""
    provider: str = "gpt_researcher"
    timeout_seconds: float = 900.0
    poll_interval_seconds: float = 2.0
    poll_max_errors: int = 60
    poll_error_grace_seconds: float = 300.0
    require_external: bool = False

    @property
    def configured(self) -> bool:
        return bool(self.base_url.strip())

    @classmethod
    def from_env(cls) -> "ResearchAdapterConfig":
        base_url = str(os.environ.get("MEETYOU_RESEARCH_ADAPTER_BASE_URL", "") or "").strip()
        required_raw = str(os.environ.get("MEETYOU_RESEARCH_ADAPTER_REQUIRED", "true") or "true").strip().lower()
        return cls(
            base_url=base_url,
            token=str(os.environ.get("MEETYOU_RESEARCH_ADAPTER_TOKEN", "") or "").strip(),
            provider=str(os.environ.get("MEETYOU_RESEARCH_PROVIDER", "gpt_researcher") or "gpt_researcher").strip() or "gpt_researcher",
            timeout_seconds=_float_env("MEETYOU_RESEARCH_TIMEOUT_SECONDS", 900.0),
            poll_interval_seconds=_float_env("MEETYOU_RESEARCH_POLL_SECONDS", 2.0),
            poll_max_errors=_int_env("MEETYOU_RESEARCH_POLL_MAX_ERRORS", 60),
            poll_error_grace_seconds=_float_env("MEETYOU_RESEARCH_POLL_ERROR_GRACE_SECONDS", 300.0),
            require_external=required_raw not in {"0", "false", "no", "off", "disabled"},
        )


class ResearchAdapterError(RuntimeError):
    def __init__(self, code: str, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.details = dict(details or {})


class ResearchAdapterClient:
    def __init__(self, config: ResearchAdapterConfig) -> None:
        self.config = config

    def create_run(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.config.configured:
            raise ResearchAdapterError(
                "research_adapter_unconfigured",
                "Research adapter service is not configured.",
                details={"provider": self.config.provider},
            )
        created = self._request_json("POST", "/v1/research/runs", payload)
        run_id = str(created.get("run_id") or created.get("id") or "").strip()
        if not run_id:
            raise ResearchAdapterError("research_adapter_run_invalid", "Research adapter did not return a run_id.")
        created["run_id"] = run_id
        created["status"] = _normalize_status(created.get("status"))
        return created

    def get_run(self, run_id: str) -> dict[str, Any]:
        normalized_run_id = str(run_id or "").strip()
        if not normalized_run_id:
            raise ResearchAdapterError("research_adapter_run_invalid", "Research adapter run_id is required.")
        current = self._request_json("GET", f"/v1/research/runs/{normalized_run_id}", None)
        current["run_id"] = str(current.get("run_id") or normalized_run_id)
        current["status"] = _normalize_status(current.get("status"))
        return current

    def run_to_completion(self, payload: dict[str, Any], *, cancel_checker=None) -> dict[str, Any]:
        created = self.create_run(payload)
        run_id = str(created.get("run_id") or "").strip()
        current = dict(created)
        while _normalize_status(current.get("status")) not in TERMINAL_STATUSES:
            if callable(cancel_checker) and cancel_checker():
                self.cancel(run_id)
                current["status"] = "cancelled"
                break
            time.sleep(max(0.25, float(self.config.poll_interval_seconds or 2.0)))
            current = self.get_run(run_id)
        current["run_id"] = run_id
        current["status"] = _normalize_status(current.get("status"))
        return current

    def cancel(self, run_id: str) -> None:
        try:
            self._request_json("POST", f"/v1/research/runs/{run_id}/cancel", {})
        except ResearchAdapterError:
            return

    def _request_json(self, method: str, path: str, payload: dict[str, Any] | None) -> dict[str, Any]:
        base = self.config.base_url.rstrip("/")
        url = f"{base}{path}"
        data = None
        headers = {"Accept": "application/json"}
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if self.config.token:
            headers["Authorization"] = f"Bearer {self.config.token}"
        request = urllib.request.Request(url, data=data, headers=headers, method=method.upper())
        try:
            with urllib.request.urlopen(request, timeout=min(max(float(self.config.timeout_seconds or 900.0), 1.0), 120.0)) as response:
                body = response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            raise ResearchAdapterError(
                "research_adapter_http_error",
                f"Research adapter returned HTTP {exc.code}.",
                details={"status_code": exc.code, "body": error_body[:1200]},
            ) from exc
        except Exception as exc:  # noqa: BLE001 - adapter boundary should return structured failures.
            raise ResearchAdapterError(
                "research_adapter_request_failed",
                str(exc),
                details={"error_type": type(exc).__name__},
            ) from exc
        if not body.strip():
            return {}
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError as exc:
            raise ResearchAdapterError(
                "research_adapter_payload_invalid",
                "Research adapter returned invalid JSON.",
                details={"body": body[:1200]},
            ) from exc
        if not isinstance(parsed, dict):
            raise ResearchAdapterError("research_adapter_payload_invalid", "Research adapter returned a non-object payload.")
        return parsed


def _float_env(key: str, default: float) -> float:
    try:
        return max(0.25, float(os.environ.get(key, default) or default))
    except (TypeError, ValueError):
        return float(default)


def _int_env(key: str, default: int) -> int:
    try:
        return max(1, int(os.environ.get(key, default) or default))
    except (TypeError, ValueError):
        return int(default)


def _normalize_status(value: Any) -> str:
    status = str(value or "").strip().lower()
    if status in {"complete", "completed", "success", "succeeded", "done"}:
        return "completed"
    if status in {"cancel", "cancelled", "canceled"}:
        return "cancelled"
    if status in {"fail", "failed", "error", "errored"}:
        return "failed"
    if status in {"queued", "planned", "pending"}:
        return "running"
    return status or "running"
