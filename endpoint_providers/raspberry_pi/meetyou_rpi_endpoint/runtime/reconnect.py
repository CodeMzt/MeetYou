from __future__ import annotations

import random
from dataclasses import dataclass


@dataclass(slots=True)
class ReconnectBackoff:
    initial_delay_seconds: float = 1.0
    max_delay_seconds: float = 30.0
    jitter_seconds: float = 1.0
    attempt: int = 0

    def reset(self) -> None:
        self.attempt = 0

    def next_delay(self) -> float:
        base = min(
            float(self.max_delay_seconds),
            float(self.initial_delay_seconds) * (2 ** max(0, self.attempt)),
        )
        self.attempt += 1
        jitter = random.uniform(0, float(self.jitter_seconds)) if self.jitter_seconds > 0 else 0
        return min(float(self.max_delay_seconds), base + jitter)

