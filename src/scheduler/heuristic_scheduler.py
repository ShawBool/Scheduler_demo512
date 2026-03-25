"""启发式初解：快速构造可行解并给出未排原因。"""

from __future__ import annotations

from dataclasses import dataclass

from .models import ScheduleItem, Task, UnscheduledItem
from .problem_builder import ProblemInstance


@dataclass(slots=True)
class HeuristicResult:
    schedule: list[ScheduleItem]
    unscheduled: list[UnscheduledItem]


def _task_priority(task: Task) -> tuple[int, float, int]:
    """排序规则：关键任务优先 -> 单位时长收益高优先 -> 任务ID稳定排序。"""
    density = task.value / max(task.duration, 1)
    return (0 if task.is_key_task else 1, -density, hash(task.task_id))


def _fits_time_window(task: Task, start: int) -> bool:
    end = start + task.duration
    if task.visibility_window is None:
        return end <= 10**9
    return start >= task.visibility_window.start and end <= task.visibility_window.end


def _resources_ok(task: Task, usage: dict[int, dict[str, int]], capacities: dict[str, int], start: int) -> bool:
    """逐时间片检查资源是否越界。"""
    for t in range(start, start + task.duration):
        point = usage.setdefault(t, {"cpu": 0, "gpu": 0, "memory": 0, "power": 0})
        if point["cpu"] + task.cpu > capacities["cpu"]:
            return False
        if point["gpu"] + task.gpu > capacities["gpu"]:
            return False
        if point["memory"] + task.memory > capacities["memory"]:
            return False
        if point["power"] + task.power > capacities["power"]:
            return False
    return True


def _apply_usage(task: Task, usage: dict[int, dict[str, int]], start: int) -> None:
    for t in range(start, start + task.duration):
        point = usage.setdefault(t, {"cpu": 0, "gpu": 0, "memory": 0, "power": 0})
        point["cpu"] += task.cpu
        point["gpu"] += task.gpu
        point["memory"] += task.memory
        point["power"] += task.power


def build_initial_schedule(problem: ProblemInstance, seed: int = 666) -> HeuristicResult:
    """构建启发式初解。

    设计要点：
    1. 采用固定排序 + 固定扫描策略，确保同seed下可复现。
    2. 先满足前驱，再尝试最早可行起点。
    3. 若无法排入，输出结构化原因。
    """
    del seed  # 当前启发式完全确定性，保留参数是为了与后续扩展兼容。

    usage: dict[int, dict[str, int]] = {}
    scheduled: list[ScheduleItem] = []
    unscheduled: list[UnscheduledItem] = []
    finished_at: dict[str, int] = {}

    # 关键点：严格保持拓扑顺序，避免“子任务先于前驱”导致关键任务被错误阻塞。
    # 在当前一期中，优先保证依赖可行性，后续再演进为“就绪队列 + 多目标排序”。
    ordered_ids = list(problem.topological_tasks)

    for task_id in ordered_ids:
        task = problem.task_map[task_id]

        # 若前驱未完成，则当前任务无法排入。
        missing_preds = [pred for pred in task.predecessors if pred not in finished_at]
        if missing_preds:
            unscheduled.append(
                UnscheduledItem(
                    task_id=task.task_id,
                    reason_code="dependency_blocked",
                    reason_detail=f"predecessors not scheduled: {', '.join(missing_preds)}",
                )
            )
            continue

        earliest = 0 if not task.predecessors else max(finished_at[pred] for pred in task.predecessors)
        latest_bound = problem.horizon - task.duration
        if task.visibility_window is not None:
            earliest = max(earliest, task.visibility_window.start)
            latest_bound = min(latest_bound, task.visibility_window.end - task.duration)

        if latest_bound < earliest:
            unscheduled.append(
                UnscheduledItem(
                    task_id=task.task_id,
                    reason_code="window_infeasible",
                    reason_detail="no feasible start in visibility/horizon window",
                )
            )
            continue

        picked_start: int | None = None
        for candidate in range(earliest, latest_bound + 1):
            if not _fits_time_window(task, candidate):
                continue
            if _resources_ok(task, usage, problem.capacities, candidate):
                picked_start = candidate
                break

        if picked_start is None:
            unscheduled.append(
                UnscheduledItem(
                    task_id=task.task_id,
                    reason_code="resource_conflict",
                    reason_detail="no start time satisfies resource capacities",
                )
            )
            continue

        _apply_usage(task, usage, picked_start)
        end = picked_start + task.duration
        finished_at[task.task_id] = end
        scheduled.append(
            ScheduleItem(
                task_id=task.task_id,
                start=picked_start,
                end=end,
                value=task.value,
                is_key_task=task.is_key_task,
                visibility_window_id=task.visibility_window.window_id if task.visibility_window else None,
            )
        )

    scheduled.sort(key=lambda x: (x.start, x.task_id))
    return HeuristicResult(schedule=scheduled, unscheduled=unscheduled)
