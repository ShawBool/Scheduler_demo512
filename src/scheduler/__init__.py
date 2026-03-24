"""卫星任务规划器包。"""

from .config import load_config, validate_config
from .logging_utils import append_cycle_log, write_schedule_result, write_task_pool
from .models import ResourceSnapshot, ScheduleItem, ScheduleResult, Task
from .pipeline import run_pipeline
from .planner import plan_baseline
from .replanner import evaluate_replan_trigger
try:
    from .simulation import generate_task_pool
except ImportError:  # pragma: no cover - simulation 可在静态输入模式下缺省
    generate_task_pool = None

__all__ = [
    "Task",
    "ResourceSnapshot",
    "ScheduleItem",
    "ScheduleResult",
    "load_config",
    "validate_config",
    "plan_baseline",
    "evaluate_replan_trigger",
    "write_schedule_result",
    "write_task_pool",
    "append_cycle_log",
    "run_pipeline",
]

if generate_task_pool is not None:
    __all__.insert(6, "generate_task_pool")
