from __future__ import annotations

from contextlib import contextmanager


class ServiceBase:
    def __init__(self, session_factory):
        self._session_factory = session_factory

    @contextmanager
    def session_scope(self):
        session = self._session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
