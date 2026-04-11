from __future__ import annotations

from core.db.models.procedure import Procedure
from core.db.repositories.base import RepositoryBase


class ProcedureRepository(RepositoryBase):
    def create(
        self,
        *,
        procedure_id: str,
        principal_id,
        title: str = "",
        description: str = "",
        prompt_overlay: str = "",
        default_execution_target: str = "",
        risk_profile: str = "standard",
        status: str = "active",
        applicable_modes: list[str] | None = None,
        recommended_capabilities: list[str] | None = None,
        recommended_source_profiles: list[str] | None = None,
        meta: dict | None = None,
    ) -> Procedure:
        row = Procedure(
            procedure_id=procedure_id,
            principal_id=principal_id,
            title=title,
            description=description,
            prompt_overlay=prompt_overlay,
            default_execution_target=default_execution_target,
            risk_profile=risk_profile,
            status=status,
            applicable_modes=list(applicable_modes or []),
            recommended_capabilities=list(recommended_capabilities or []),
            recommended_source_profiles=list(recommended_source_profiles or []),
            meta=dict(meta or {}),
        )
        self.session.add(row)
        self.session.flush()
        return row

    def get_by_procedure_id(self, procedure_id: str) -> Procedure | None:
        return self.session.query(Procedure).filter_by(procedure_id=procedure_id).one_or_none()

    def list_active(self, principal_id) -> list[Procedure]:
        return list(
            self.session.query(Procedure)
            .filter_by(principal_id=principal_id, status="active")
            .order_by(Procedure.procedure_id.asc())
            .all()
        )
