from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import quote_plus


@dataclass(frozen=True, slots=True)
class AcademicAdapterQuery:
    adapter: str
    query_url: str
    source_type: str = "academic_index"

    def to_dict(self) -> dict[str, str]:
        return {
            "adapter": self.adapter,
            "query_url": self.query_url,
            "source_type": self.source_type,
        }


class AcademicSourceRegistry:
    """Read-only academic source adapter registry for V5 research planning."""

    DEFAULT_ADAPTERS = ("arxiv", "openalex", "crossref", "semantic_scholar")

    @staticmethod
    def build_queries(query: str, *, adapters: list[str] | tuple[str, ...] | None = None, limit: int = 10) -> list[AcademicAdapterQuery]:
        normalized = str(query or "").strip()
        if not normalized:
            return []
        safe_query = quote_plus(normalized)
        bounded_limit = max(1, min(int(limit or 10), 50))
        selected = [str(item or "").strip().lower() for item in (adapters or AcademicSourceRegistry.DEFAULT_ADAPTERS)]
        result: list[AcademicAdapterQuery] = []
        for adapter in selected:
            if adapter == "arxiv":
                result.append(
                    AcademicAdapterQuery(
                        adapter="arxiv",
                        query_url=f"https://export.arxiv.org/api/query?search_query=all:{safe_query}&start=0&max_results={bounded_limit}",
                    )
                )
            elif adapter == "openalex":
                result.append(
                    AcademicAdapterQuery(
                        adapter="openalex",
                        query_url=f"https://api.openalex.org/works?search={safe_query}&per-page={bounded_limit}",
                    )
                )
            elif adapter == "crossref":
                result.append(
                    AcademicAdapterQuery(
                        adapter="crossref",
                        query_url=f"https://api.crossref.org/works?query={safe_query}&rows={bounded_limit}",
                    )
                )
            elif adapter in {"semantic_scholar", "semanticscholar"}:
                result.append(
                    AcademicAdapterQuery(
                        adapter="semantic_scholar",
                        query_url=f"https://api.semanticscholar.org/graph/v1/paper/search?query={safe_query}&limit={bounded_limit}&fields=title,authors,year,venue,url,externalIds,abstract",
                    )
                )
        return result

    @classmethod
    def search_payload(cls, query: str, *, adapters: list[str] | None = None, limit: int = 10) -> dict[str, Any]:
        queries = [item.to_dict() for item in cls.build_queries(query, adapters=adapters, limit=limit)]
        return {
            "schema": "meetyou.academic_search.v1",
            "query": str(query or "").strip(),
            "status": "planned_queries",
            "adapters": queries,
            "evidence_ledger": [
                {
                    "source_id": index + 1,
                    "source_type": item["source_type"],
                    "adapter": item["adapter"],
                    "url": item["query_url"],
                    "verification_status": "query_url",
                }
                for index, item in enumerate(queries)
            ],
        }
