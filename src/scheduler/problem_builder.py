"""问题构建器：把原始任务转换为可供启发式与CP-SAT共同使用的问题对象。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .models import Task, VisibilityWindow


@dataclass(slots=True)
class ProblemInstance:
    """求解统一输入结构。"""

    tasks: list[Task]
    task_map: dict[str, Task]
    windows: dict[str, VisibilityWindow]
    topological_tasks: list[str]
    attitude_transition_cost: dict[tuple[str, str], int]
    attitude_time_per_degree: float
    horizon: int
    capacities: dict[str, int]
    thermal_config: dict[str, Any]


def _topological_sort(tasks: list[Task]) -> list[str]:
    """Kahn 算法拓扑排序。

    若出现环依赖，会抛出异常并阻断后续求解。
    """
    incoming: dict[str, int] = {t.task_id: 0 for t in tasks}
    outgoing: dict[str, list[str]] = {t.task_id: [] for t in tasks}

    for task in tasks:
        for pred in task.predecessors:
            incoming[task.task_id] += 1
            outgoing[pred].append(task.task_id)

    queue = sorted([tid for tid, deg in incoming.items() if deg == 0])
    result: list[str] = []

    while queue:
        current = queue.pop(0)
        result.append(current)
        for nxt in outgoing[current]:
            incoming[nxt] -= 1
            if incoming[nxt] == 0:
                queue.append(nxt)
                queue.sort()

    if len(result) != len(tasks):
        raise ValueError("dependency graph contains cycle")
    return result


def _compute_attitude_transition_cost(tasks: list[Task], attitude_time_per_degree: float) -> dict[tuple[str, str], int]:
    """计算任意任务对之间姿态切换时间开销（离散到整数时间单位）。"""
    result: dict[tuple[str, str], int] = {}
    for left in tasks:
        for right in tasks:
            if left.task_id == right.task_id:
                result[(left.task_id, right.task_id)] = 0
                continue

            a1 = left.attitude_angle_deg
            a2 = right.attitude_angle_deg
            if a1 is None or a2 is None:
                result[(left.task_id, right.task_id)] = 0
                continue

            delta = abs(a1 - a2)
            delta = min(delta, 360.0 - delta)
            result[(left.task_id, right.task_id)] = int(round(delta * attitude_time_per_degree))
    return result


def build_problem(
    tasks: list[Task],
    windows: dict[str, VisibilityWindow],
    horizon: int,
    capacities: dict[str, int],
    attitude_time_per_degree: float,
    thermal_config: dict[str, Any] | None = None,
) -> ProblemInstance:
    """将输入任务构建为统一问题对象。"""
    topological_tasks = _topological_sort(tasks)
    transition = _compute_attitude_transition_cost(tasks, attitude_time_per_degree)
    task_map = {task.task_id: task for task in tasks}
    return ProblemInstance(
        tasks=tasks,
        task_map=task_map,
        windows=windows,
        topological_tasks=topological_tasks,
        attitude_transition_cost=transition,
        attitude_time_per_degree=attitude_time_per_degree,
        horizon=horizon,
        capacities=capacities,
        thermal_config=thermal_config or {},
    )
