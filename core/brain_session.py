"""
Per-session brain state.
"""

from dataclasses import dataclass, field
import time

from core.status import RuntimeStateSnapshot, UsageSnapshot


@dataclass
class BrainSession:
    session_id: str
    chat_history: list[dict]
    active_stream_id: str = ""
    metadata: dict = field(default_factory=dict)
    last_active_at: float = field(default_factory=time.time)
    runtime_state: RuntimeStateSnapshot = field(default_factory=RuntimeStateSnapshot)
    usage_snapshot: UsageSnapshot = field(default_factory=UsageSnapshot)

    def __post_init__(self):
        self.runtime_state.session_id = self.session_id
        self.usage_snapshot.session_id = self.session_id

    def touch(self):
        self.last_active_at = time.time()
