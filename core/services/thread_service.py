from __future__ import annotations

from uuid import uuid4

from core.db.repositories import ThreadRepository
from core.services.base import ServiceBase


class ThreadService(ServiceBase):
    def create_thread(
        self,
        *,
        principal_id,
        home_workspace_id=None,
        workspace_id=None,
        title: str = "",
        pinned_procedure_id: str | None = None,
    ):
        resolved_home_workspace_id = home_workspace_id if home_workspace_id is not None else workspace_id
        with self.session_scope() as session:
            return ThreadRepository(session).create(
                thread_id=f"thr_{uuid4().hex}",
                principal_id=principal_id,
                home_workspace_id=resolved_home_workspace_id,
                title=title,
                pinned_procedure_id=pinned_procedure_id,
            )

    def get_by_thread_id(self, thread_id: str):
        with self.session_scope() as session:
            return ThreadRepository(session).get_by_thread_id(thread_id)

    def get_by_id(self, row_id):
        with self.session_scope() as session:
            return ThreadRepository(session).get_by_id(row_id)

    def set_pinned_procedure(self, *, thread_id, pinned_procedure_id: str | None):
        with self.session_scope() as session:
            return ThreadRepository(session).update_pinned_procedure(
                thread_id=thread_id,
                pinned_procedure_id=pinned_procedure_id,
            )

    def set_latest_inferred_procedure(
        self,
        *,
        thread_id,
        procedure_id: str,
        score: int = 0,
        reason: str = "",
        inferred_at: str = "",
    ):
        with self.session_scope() as session:
            thread = ThreadRepository(session).get_by_id(thread_id)
            if thread is None:
                return None
            merged = dict(thread.meta or {})
            if procedure_id:
                merged["latest_inferred_procedure"] = {
                    "procedure_id": str(procedure_id or "").strip(),
                    "score": max(int(score or 0), 0),
                    "reason": str(reason or "").strip(),
                    "inferred_at": str(inferred_at or "").strip(),
                }
            else:
                merged.pop("latest_inferred_procedure", None)
            thread.meta = merged
            session.flush()
            return thread

    def clear_pinned_procedure_for_procedure(self, *, procedure_id: str) -> int:
        with self.session_scope() as session:
            return ThreadRepository(session).clear_pinned_procedure_for_procedure(procedure_id=procedure_id)

    @staticmethod
    def get_latest_inferred_state(thread) -> dict:
        meta = dict(getattr(thread, "meta", {}) or {})
        inferred = dict(meta.get("latest_inferred_procedure") or {})
        return {
            "procedure_id": str(inferred.get("procedure_id") or "").strip(),
            "score": max(int(inferred.get("score", 0) or 0), 0),
            "reason": str(inferred.get("reason") or "").strip(),
            "inferred_at": str(inferred.get("inferred_at") or "").strip(),
        }
