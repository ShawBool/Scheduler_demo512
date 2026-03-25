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
    power: int  # 功率占用
    payload_type_requirements: list[str] = field(default_factory=list)  # 载荷类型约束
    # payload_id_requirements: list[str] = field(default_factory=list)  # 指定载荷ID约束，保留字段，默认不参与规划约束
    predecessors: list[str] = field(default_factory=list)  # 前置依赖任务ID列表
    attitude_angle_deg: float  =None# 姿态角（度，0-360），缺省则不要求
    is_key_task: bool = False  # 是否关键任务（必须规划）
    visibility_window: VisibilityWindow | None = None  # 绑定的可见窗口（可选）


@dataclass(slots=True)
class ResourceSnapshot:
    """资源快照模型：记录某时刻的资源使用情况。"""

    timestamp: int
    cpu: int
    gpu: int
    memory: int
    attitude_angle_deg: float
    power: int
    thermal: int


