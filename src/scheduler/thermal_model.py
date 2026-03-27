"""热模型内核：半经验模型与回退模型。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(slots=True)
class ThermalCoefficients:
    a_p: float
    a_c: float
    lambda_concurrency: float
    a_cpu: float
    a_gpu: float
    a_mem: float
    a_s: float
    k_cool: float
    b_att: float


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
        concurrency = float(features.get("concurrency", 0.0))
        cpu_util = float(features.get("cpu_util", 0.0))
        gpu_util = float(features.get("gpu_util", 0.0))
        memory_util = float(features.get("memory_util", 0.0))
        attitude_switch_rate = float(features.get("attitude_switch_rate", 0.0))
        attitude_cooling_disturbance = float(features.get("attitude_cooling_disturbance", 0.0))

        q_gen = (
            self._coeff.a_p * power_total
            + self._coeff.a_c * concurrency
            + self._coeff.lambda_concurrency * (concurrency**2)
            + self._coeff.a_cpu * cpu_util
            + self._coeff.a_gpu * gpu_util
            + self._coeff.a_mem * memory_util
            + self._coeff.a_s * attitude_switch_rate
        )
        q_cool = self._coeff.k_cool * (temperature - self._env_temperature) + self._coeff.b_att * attitude_cooling_disturbance

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
