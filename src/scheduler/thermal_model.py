"""热模型内核：半经验模型与回退模型。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Protocol


@dataclass(slots=True)
class ThermalCoefficients:
    a_p: float
    a_c: float
    lambda_concurrency: float
    k_cool: float


def _clamp_01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def derive_concurrency(features: Mapping[str, float]) -> float:
    """由资源利用率推导并发度。

    优先使用 cpu/gpu 使用率推导，若缺失则回退到历史的 concurrency 字段。
    """
    has_cpu = "cpu_used" in features and "cpu_capacity" in features
    has_gpu = "gpu_used" in features and "gpu_capacity" in features
    if has_cpu or has_gpu:
        cpu_ratio = 0.0
        gpu_ratio = 0.0
        if has_cpu:
            cpu_capacity = max(float(features.get("cpu_capacity", 0.0)), 1e-6)
            cpu_ratio = float(features.get("cpu_used", 0.0)) / cpu_capacity
        if has_gpu:
            gpu_capacity = max(float(features.get("gpu_capacity", 0.0)), 1e-6)
            gpu_ratio = float(features.get("gpu_used", 0.0)) / gpu_capacity
        return _clamp_01(cpu_ratio + gpu_ratio)

    return _clamp_01(float(features.get("concurrency", 0.0)))


class ThermalModelProtocol(Protocol):
    def update(self, state: dict[str, float], features: dict[str, float], dt: float) -> dict[str, float]:
        """根据当前状态和特征更新下一步热状态。"""


class SemiEmpiricalThermalModelV1:
    """第一版半经验热模型。"""

    def __init__(self, coefficients: ThermalCoefficients, env_temperature: float) -> None:
        self._coeff = coefficients
        self._env_temperature = float(env_temperature)

    def update(self, state: dict[str, float], features: dict[str, float], dt: float) -> dict[str, float]:
        temperature = float(state.get("temperature", 0.0))
        dt_value = float(dt)

        power_total = float(features.get("power_total", 0.0))
        concurrency = derive_concurrency(features)

        q_gen = (
            self._coeff.a_p * power_total
            + self._coeff.a_c * concurrency
            + self._coeff.lambda_concurrency * (concurrency**2)
        )
        q_cool = self._coeff.k_cool * (temperature - self._env_temperature)

        next_temperature = temperature + (q_gen - q_cool) * dt_value
        next_state = dict(state)
        next_state["temperature"] = float(next_temperature)
        return next_state

    @staticmethod
    def max_continuous_warning_steps(flags: list[int]) -> int:
        max_len = 0
        current = 0
        for flag in flags:
            if int(flag) == 1:
                current += 1
                if current > max_len:
                    max_len = current
            else:
                current = 0
        return max_len


class NoOpThermalModel:
    """回退热模型：不改变温度。"""

    def update(self, state: dict[str, float], features: dict[str, float], dt: float) -> dict[str, float]:
        del features, dt
        return dict(state)
