"""重规划预留接口（一期仅定义契约，不实现算法）。"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class ReplanRequest:
    """重规划请求契约。"""

    reason: str
    current_schedule: list[dict] = field(default_factory=list)
    new_tasks: list[dict] = field(default_factory=list)


@dataclass(slots=True)
class ReplanResponse:
    """重规划响应契约。"""

    accepted: bool
    message: str
    updated_schedule: list[dict] = field(default_factory=list)
