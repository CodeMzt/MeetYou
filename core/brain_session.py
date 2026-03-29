"""
大脑单会话状态。
"""

from dataclasses import dataclass, field
import time


@dataclass
class BrainSession:
    session_id: str
    chat_history: list[dict]
    active_stream_id: str = ""
    metadata: dict = field(default_factory=dict)
    last_active_at: float = field(default_factory=time.time)

    def touch(self):
        self.last_active_at = time.time()
