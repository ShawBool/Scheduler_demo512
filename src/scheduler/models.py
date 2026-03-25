"""任务规划领域模型。"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class VisibilityWindow:
    """可见窗口模型：描述可见窗口的时间范围。"""
    window_id: str
    start: int
    end: int


@dataclass(slots=True)
class Task:
    """任务模型：描述待规划任务的时间窗、收益、资源与约束。"""

    task_id: str  # 任务唯一标识
    duration: int  # 预计执行时长
    value: int  # 任务收益
    cpu: int  # CPU个数
    gpu: int  # GPU个数
    memory: int  # 内存占用
    # storage: int  # 存储占用，保留字段，暂不参与规划约束
    # bus: int  # 总线占用，保留字段，暂不参与规划约束
    # concurrency_cores: int  # 废弃字段，暂不参与规划约束
    power: int  # 功率占用
    # thermal_load: int  # 热负载,保留字段，暂不参与规划约束，产热暂定与power计算得出
    payload_type_requirements: list[str] = field(default_factory=list)  # 载荷类型约束
    # payload_id_requirements: list[str] = field(default_factory=list)  # 指定载荷ID约束，保留字段，暂不参与规划约束
    predecessors: list[str] = field(default_factory=list)  # 前置依赖任务ID列表
    attitude_angle_deg: float = 0.0  # 姿态角（度，0-360）
    is_key_task: bool = False  # 是否关键任务（必须规划）
    visibility_window: VisibilityWindow | None = None  # 绑定的可见窗口（可选）


@dataclass(slots=True)
class ResourceSnapshot:
    """资源快照模型：记录某时刻的资源使用情况。"""

    timestamp: int
    cpu: int
    gpu: int
    memory: int
    # storage: int 存储占用，保留字段，暂不参与规划约束
    # bus: int# 总线占用，保留字段，暂不参与规划约束
    # concurrency_cores: int# 废弃字段，暂不参与规划约束
    attitude_angle_deg: float
    power: int
    thermal: int


@dataclass(slots=True)
class ScheduleItem:
    """计划项模型：描述单个任务的排程结果。"""

    task_id: str
    start: int
    end: int
    attitude_angle_deg: float
    value: int


@dataclass(slots=True)
class ScheduleResult:
    """计划结果模型：包含已规划任务、未规划任务及统计信息。"""

    scheduled_items: list[ScheduleItem]
    unscheduled_tasks: list[Task]
    objective_value: float
    constraint_stats: dict[str, int | float | str]
    rolling_segments: list[dict[str, int]] = field(default_factory=list)  # 可拆分滚动区间（start/end）
