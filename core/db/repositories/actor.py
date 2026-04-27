from __future__ import annotations

from core.db.models.actor import Actor
from core.db.repositories.base import RepositoryBase


class ActorRepository(RepositoryBase):
    def upsert(
        self,
        *,
        actor_id: str,
        actor_type: str,
        owner_user_id: str | None = None,
        display_name: str = "",
        permission_profile_id: str = "",
        metadata: dict | None = None,
    ) -> Actor:
        row = self.get_by_actor_id(actor_id)
        if row is None:
            row = Actor(
                actor_id=actor_id,
                actor_type=actor_type,
                owner_user_id=owner_user_id,
                display_name=display_name,
                permission_profile_id=permission_profile_id,
                meta=dict(metadata or {}),
            )
            self.session.add(row)
        else:
            row.actor_type = actor_type
            row.owner_user_id = owner_user_id
            row.display_name = display_name
            row.permission_profile_id = permission_profile_id
            row.meta = dict(metadata or row.meta or {})
        self.session.flush()
        return row

    def get_by_actor_id(self, actor_id: str) -> Actor | None:
        return self.session.query(Actor).filter_by(actor_id=actor_id).one_or_none()

    def get_by_id(self, row_id) -> Actor | None:
        return self.session.query(Actor).filter_by(id=row_id).one_or_none()
