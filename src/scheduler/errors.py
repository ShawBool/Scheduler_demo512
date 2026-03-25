"""规划器统一异常定义。"""

from __future__ import annotations


class SchedulerError(Exception):
    """规划模块基础异常。"""


class InputValidationError(SchedulerError):
    """输入数据结构或字段非法。"""


class PlanningError(SchedulerError):
    """求解阶段出现问题，但通常可以输出 best-effort 结果。"""


class SystemExecutionError(SchedulerError):
    """系统级错误，比如文件写入失败等。"""
