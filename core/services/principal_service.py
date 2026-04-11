from __future__ import annotations

from core.db.repositories import PrincipalRepository
from core.services.base import ServiceBase


class PrincipalService(ServiceBase):
    def ensure_principal(self, *, principal_key: str, display_name: str, status: str = "active"):
        with self.session_scope() as session:
            repo = PrincipalRepository(session)
            existing = repo.get_by_principal_key(principal_key)
            if existing is not None:
                return existing
            return repo.create(principal_key=principal_key, display_name=display_name, status=status)

    def get_by_principal_key(self, principal_key: str):
        with self.session_scope() as session:
            return PrincipalRepository(session).get_by_principal_key(principal_key)
