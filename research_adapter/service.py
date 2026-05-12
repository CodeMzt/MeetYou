from __future__ import annotations

import asyncio
import os
import time
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from fastapi import BackgroundTasks, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field


app = FastAPI(title="MeetYou Research Adapter", version="v1")
RUNS: dict[str, dict[str, Any]] = {}


class ResearchRunRequest(BaseModel):
    schema_name: str = Field(default="meetyou.research.adapter.run.v1", alias="schema")
    provider: str = "gpt_researcher"
    research_task_id: str
    topic: str
    source_policy: dict[str, Any] = Field(default_factory=dict)
    output_format: str = "markdown"
    project: dict[str, Any] | None = None
    thread: dict[str, Any] | None = None
    project_sources: list[dict[str, Any]] = Field(default_factory=list)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _token() -> str:
    return str(os.environ.get("MEETYOU_RESEARCH_ADAPTER_TOKEN", "") or "").strip()


def _require_auth(authorization: str = Header(default="")) -> None:
    expected = _token()
    if not expected:
        return
    if authorization != f"Bearer {expected}":
        raise HTTPException(status_code=401, detail={"code": "unauthorized", "message": "Invalid research adapter token."})


def _gpt_researcher_available() -> bool:
    try:
        __import__("gpt_researcher")
        return True
    except Exception:
        return False


def _fake_enabled() -> bool:
    return str(os.environ.get("MEETYOU_RESEARCH_ADAPTER_FAKE", "") or "").strip().lower() in {"1", "true", "yes", "on"}


def _bridge_provider_env() -> None:
    """Expose Core-owned provider credentials under names used by external SDKs."""
    if not str(os.environ.get("OPENAI_API_KEY") or "").strip():
        core_key = str(os.environ.get("MEETYOU_API_KEY") or "").strip()
        if core_key:
            os.environ["OPENAI_API_KEY"] = core_key


def _public_run(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "run_id": row["run_id"],
        "status": row["status"],
        "provider": row["provider"],
        "progress": row.get("progress", {}),
        "summary": row.get("summary", ""),
        "report_markdown": row.get("report_markdown", ""),
        "sources": row.get("sources", []),
        "usage": row.get("usage", {}),
        "metadata": row.get("metadata", {}),
        "error": row.get("error", ""),
        "created_at": row.get("created_at", ""),
        "updated_at": row.get("updated_at", ""),
    }


def _set_progress(row: dict[str, Any], stage: str, message: str, *, status: str | None = None, **metadata: Any) -> None:
    progress = {
        "stage": stage,
        "message": message,
        "at": _now_iso(),
    }
    if status:
        progress["status"] = status
    if metadata:
        progress.update(metadata)
    row["progress"] = progress
    row["updated_at"] = _now_iso()


@app.get("/health")
async def health() -> dict[str, Any]:
    provider = str(os.environ.get("MEETYOU_RESEARCH_PROVIDER", "gpt_researcher") or "gpt_researcher")
    available = _gpt_researcher_available()
    fake = _fake_enabled()
    ready = fake or available
    return {
        "status": "ready" if ready else "degraded",
        "ready": ready,
        "provider": provider,
        "gpt_researcher_available": available,
        "fake_enabled": fake,
        "active_run_count": sum(1 for row in RUNS.values() if row.get("status") == "running"),
        "updated_at": _now_iso(),
    }


@app.post("/v1/research/runs")
async def create_run(payload: ResearchRunRequest, background_tasks: BackgroundTasks, authorization: str = Header(default="")) -> dict[str, Any]:
    _require_auth(authorization)
    run_id = f"rad_{uuid4().hex}"
    row = {
        "run_id": run_id,
        "provider": payload.provider or "gpt_researcher",
        "status": "running",
        "progress": {"stage": "queued", "status": "running", "message": "研究任务已进入外部服务队列。", "at": _now_iso()},
        "request": payload.model_dump(by_alias=True),
        "sources": [],
        "report_markdown": "",
        "summary": "",
        "usage": {},
        "metadata": {},
        "error": "",
        "cancel_requested": False,
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
    }
    RUNS[run_id] = row
    background_tasks.add_task(_execute_run, run_id)
    return _public_run(row)


@app.get("/v1/research/runs/{run_id}")
async def get_run(run_id: str, authorization: str = Header(default="")) -> dict[str, Any]:
    _require_auth(authorization)
    row = RUNS.get(run_id)
    if row is None:
        raise HTTPException(status_code=404, detail={"code": "research_run_not_found", "message": f"Unknown run: {run_id}"})
    return _public_run(row)


@app.post("/v1/research/runs/{run_id}/cancel")
async def cancel_run(run_id: str, authorization: str = Header(default="")) -> dict[str, Any]:
    _require_auth(authorization)
    row = RUNS.get(run_id)
    if row is None:
        raise HTTPException(status_code=404, detail={"code": "research_run_not_found", "message": f"Unknown run: {run_id}"})
    row["cancel_requested"] = True
    if row.get("status") == "running":
        row["status"] = "cancelled"
        row["progress"] = {"stage": "cancelled", "message": "Research adapter run cancelled.", "at": _now_iso()}
        row["updated_at"] = _now_iso()
    return _public_run(row)


async def _execute_run(run_id: str) -> None:
    row = RUNS.get(run_id)
    if row is None:
        return
    try:
        if row.get("cancel_requested"):
            row["status"] = "cancelled"
            _set_progress(row, "cancelled", "研究任务已取消。", status="cancelled")
            return
        request = dict(row.get("request") or {})
        _set_progress(row, "starting", "正在启动外部深度研究服务。", status="running")
        if _fake_enabled():
            _set_progress(row, "research", "正在使用测试研究服务生成报告。", status="running")
            await asyncio.sleep(0.2)
            result = _fake_result(request)
        elif _project_source_only_requested(request):
            _set_progress(row, "project_sources", "正在整理项目源并生成引用报告。", status="running", source_count=len(request.get("project_sources") or []))
            result = _project_source_result(request)
        else:
            _set_progress(row, "research", "正在调用 GPT Researcher 收集和综合资料。", status="running")
            result = await _run_gpt_researcher(request, row=row)
        if row.get("cancel_requested"):
            row["status"] = "cancelled"
            _set_progress(row, "cancelled", "研究任务已取消。", status="cancelled")
            return
        _set_progress(row, "sources", "正在整理来源和引用。", status="running", source_count=len(result.get("sources") or []))
        row.update(result)
        row["status"] = "completed"
        _set_progress(row, "completed", "外部研究报告已完成。", status="completed", source_count=len(row.get("sources") or []))
    except Exception as exc:  # noqa: BLE001 - service boundary returns structured failures.
        row["status"] = "failed"
        row["error"] = str(exc)
        row["metadata"] = {"error_type": type(exc).__name__}
        _set_progress(row, "failed", str(exc), status="failed")


async def _run_gpt_researcher(request: dict[str, Any], *, row: dict[str, Any] | None = None) -> dict[str, Any]:
    _bridge_provider_env()
    try:
        from gpt_researcher import GPTResearcher  # type: ignore
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError("gpt-researcher is not installed in the research adapter environment.") from exc
    topic = str(request.get("topic") or "").strip()
    if not topic:
        raise ValueError("topic is required")
    policy = dict(request.get("source_policy") or {})
    query = _query_with_project_sources(topic, request.get("project_sources") or [])
    source_urls = _string_list(policy.get("web_urls") or policy.get("seed_urls") or policy.get("source_urls"))
    report_type = str(policy.get("report_type") or "research_report")
    researcher = GPTResearcher(query=query, report_type=report_type, source_urls=source_urls or None)
    started = time.monotonic()
    if row is not None:
        _set_progress(row, "gather", "GPT Researcher 正在搜索和阅读资料。", status="running", source_url_count=len(source_urls))
    await researcher.conduct_research()
    if row is not None:
        _set_progress(row, "write", "GPT Researcher 正在撰写研究报告。", status="running")
    report = await researcher.write_report()
    if row is not None:
        _set_progress(row, "sources", "正在提取 GPT Researcher 来源列表。", status="running")
    sources = _extract_gpt_researcher_sources(researcher)
    return {
        "summary": f"GPT Researcher completed a report for {topic}.",
        "report_markdown": str(report or "").strip(),
        "sources": sources,
        "usage": {"duration_seconds": round(time.monotonic() - started, 2)},
        "metadata": {"provider": "gpt_researcher", "source_url_count": len(source_urls)},
    }


def _fake_result(request: dict[str, Any]) -> dict[str, Any]:
    topic = str(request.get("topic") or "Research").strip()
    project_sources = [item for item in request.get("project_sources") or [] if isinstance(item, dict)]
    sources = []
    for index, source in enumerate(project_sources[:3], start=1):
        sources.append(
            {
                "source_id": str(index),
                "source_type": "project_source",
                "title": str(source.get("title") or f"Project source {index}"),
                "snippet": str(source.get("content") or "")[:700],
                "verification_status": "project_source_snapshot",
            }
        )
    if not sources:
        sources.append(
            {
                "source_id": "1",
                "source_type": "adapter_fixture",
                "title": "Adapter fixture source",
                "snippet": f"Fixture evidence for {topic}.",
                "verification_status": "adapter_fixture",
            }
        )
    lines = [f"# {topic}", "", "## 摘要", ""]
    lines.append(f"外部研究适配器已根据 {len(sources)} 个来源生成报告。[1]")
    lines.extend(["", "## Sources", ""])
    for source in sources:
        lines.append(f"- [{source['source_id']}] {source['title']}")
    return {
        "summary": f"Fake research adapter completed a report for {topic}.",
        "report_markdown": "\n".join(lines) + "\n",
        "sources": sources,
        "usage": {"duration_seconds": 0.2},
        "metadata": {"provider": "fake"},
    }


def _project_source_only_requested(request: dict[str, Any]) -> bool:
    project_sources = [item for item in request.get("project_sources") or [] if isinstance(item, dict)]
    if not project_sources:
        return False
    policy = dict(request.get("source_policy") or {})
    if not policy.get("include_project_sources"):
        return False
    source_adapters = policy.get("source_adapters")
    if isinstance(source_adapters, str):
        source_adapters = [source_adapters]
    if source_adapters:
        return False
    web_keys = ("web_search", "web_queries", "web_urls", "seed_urls", "source_urls")
    return not any(policy.get(key) for key in web_keys)


def _project_source_result(request: dict[str, Any]) -> dict[str, Any]:
    topic = str(request.get("topic") or "Project source research").strip()
    project_sources = [item for item in request.get("project_sources") or [] if isinstance(item, dict)]
    sources = []
    lines = [f"# {topic}", "", "## 摘要", ""]
    lines.append(f"本报告基于 {len(project_sources)} 条 MeetYou 项目源生成，所有结论仅引用已记录的项目源证据。")
    lines.extend(["", "## 关键发现", ""])
    for index, source in enumerate(project_sources, start=1):
        title = str(source.get("title") or f"项目源 {index}").strip()
        content = " ".join(str(source.get("content") or "").split())
        snippet = content[:700]
        lines.append(f"- {title}: {snippet or '该项目源未提供正文摘要。'} [{index}]")
        sources.append(
            {
                "source_id": str(index),
                "project_source_id": str(source.get("source_id") or ""),
                "source_type": "project_source",
                "title": title,
                "snippet": snippet,
                "content_type": str(source.get("content_type") or "text"),
                "verification_status": "project_source_snapshot",
            }
        )
    lines.extend(["", "## 来源", ""])
    for source in sources:
        lines.append(f"- [{source['source_id']}] {source['title']}")
    return {
        "summary": f"Project-source research adapter completed a report for {topic}.",
        "report_markdown": "\n".join(lines).strip() + "\n",
        "sources": sources,
        "usage": {"duration_seconds": 0.0},
        "metadata": {"provider": "project_sources", "source_count": len(sources)},
    }


def _query_with_project_sources(topic: str, project_sources: list[dict[str, Any]]) -> str:
    if not project_sources:
        return topic
    excerpts = []
    for source in project_sources[:5]:
        title = str(source.get("title") or source.get("source_id") or "Project source")
        content = " ".join(str(source.get("content") or "").split())[:1200]
        if content:
            excerpts.append(f"- {title}: {content}")
    if not excerpts:
        return topic
    return f"{topic}\n\nUse these MeetYou project sources as local research context when relevant:\n" + "\n".join(excerpts)


def _extract_gpt_researcher_sources(researcher: Any) -> list[dict[str, Any]]:
    candidates = []
    for attr in ("visited_urls", "source_urls", "all_urls", "context", "sources"):
        value = getattr(researcher, attr, None)
        if isinstance(value, list):
            candidates.extend(value)
    sources = []
    seen = set()
    for index, item in enumerate(candidates, start=1):
        if isinstance(item, str):
            url = item
            title = item
            snippet = item
        elif isinstance(item, dict):
            url = str(item.get("url") or item.get("href") or item.get("link") or "")
            title = str(item.get("title") or item.get("name") or url or f"Source {index}")
            snippet = str(item.get("summary") or item.get("snippet") or item.get("content") or title)
        else:
            continue
        key = url or title
        if not key or key in seen:
            continue
        seen.add(key)
        sources.append(
            {
                "source_id": str(len(sources) + 1),
                "source_type": "web_page" if url else "external_research_source",
                "title": title,
                "url": url,
                "snippet": snippet[:1000],
                "verification_status": "external_agent_reported",
            }
        )
    return sources


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    result = []
    for item in value:
        text = str(item or "").strip()
        if text:
            result.append(text)
    return result[:12]
