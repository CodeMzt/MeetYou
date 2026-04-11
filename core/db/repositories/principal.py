from __future__ import annotations

from core.db.models.principal import Principal
from core.db.repositories.base import RepositoryBase


class PrincipalRepository(RepositoryBase):
    def create(self, *, principal_key: str, display_name: str, status: str = "active") -> Principal:
        principal = Principal(principal_key=principal_key, display_name=display_name, status=status)
        self.session.add(principal)
        self.session.flush()
        return principal

    def get_by_principal_key(self, principal_key: str) -> Principal | None:
        return self.session.query(Principal).filter_by(principal_key=principal_key).one_or_none()
