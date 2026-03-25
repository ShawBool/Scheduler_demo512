"""静态基线规划的领域模型定义。"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class VisibilityWindow:
    """可见窗口：任务若绑定该窗口，则执行必须落在该时间段内。"""

    window_id: str
    start: int
    end: int


@dataclass(slots=True)
class Task:
    """任务实体：与 data/latest_small_tasks_pool.json 一一对齐。"""

    task_id: str
    duration: int
    value: int
    cpu: int
    gpu: int
    memory: int
    power: int
    thermal_load: int
    payload_type_requirements: list[str] = field(default_factory=list)
    predecessors: list[str] = field(default_factory=list)
    attitude_angle_deg: float | None = None
    is_key_task: bool = False
    visibility_window: VisibilityWindow | None = None


@dataclass(slots=True)
class ScheduleItem:
    """单条排程记录：用于输出最终计划与调试信息。"""

    task_id: str
    start: int
    end: int
    value: int
    is_key_task: bool
    visibility_window_id: str | None


@dataclass(slots=True)
class UnscheduledItem:
    """未排程任务记录：用于解释任务为什么被放弃。"""

    task_id: str
    reason_code: str
    reason_detail: str


@dataclass(slots=True)
class ScheduleResult:
    """规划结果：统一承载已排、未排、指标与求解摘要。"""

    schedule: list[ScheduleItem]
    unscheduled: list[UnscheduledItem]
    metrics: dict[str, float | int]
    solver_summary: dict[str, str | int | float | bool]


@dataclass(slots=True)
class ResourceSnapshot:
    """资源快照：保留用于后续扩展在线监控/重规划。"""

    timestamp: int
    cpu: int
    gpu: int
    memory: int
    attitude_angle_deg: float
    power: int
    thermal: int


