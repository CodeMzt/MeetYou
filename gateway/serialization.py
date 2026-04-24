from __future__ import annotations

import json
from typing import Any


def make_json_safe(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))
