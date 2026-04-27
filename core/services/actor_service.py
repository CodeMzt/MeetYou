from __future__ import annotations

from core.db.repositories import ActorRepository
from core.services.base import ServiceBase


class ActorService(ServiceBase):
    def ensure_actor(
        self,
        *,
        actor_id: str,
        actor_type: str,
        owner_user_id: str | None = None,
        display_name: str = "",
        permission_profile_id: str = "",
        metadata: dict | None = None,
    ):
        with self.session_scope() as session:
            return ActorRepository(session).upsert(
                actor_id=actor_id,
                actor_type=actor_type,
                owner_user_id=owner_user_id,
                display_name=display_name,
                permission_profile_id=permission_profile_id,
                metadata=metadata,
            )

    def get_by_actor_id(self, actor_id: str):
        with self.session_scope() as session:
            return ActorRepository(session).get_by_actor_id(actor_id)

    def get_by_id(self, row_id):
        with self.session_scope() as session:
            return ActorRepository(session).get_by_id(row_id)
