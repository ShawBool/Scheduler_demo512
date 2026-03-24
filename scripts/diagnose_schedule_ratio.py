"""M5 诊断脚本：比较 A/B/C/D 四组对排程率与不可行占比的影响。"""

from __future__ import annotations

import argparse
import copy
import pathlib
import statistics
import sys
from dataclasses import dataclass

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from scheduler.config import load_config, validate_config
from scheduler.planner import plan_baseline
from scheduler.simulation import generate_task_pool


@dataclass(slots=True)
class GroupMetrics:
    name: str
    avg_scheduled_ratio: float
    infeasible_ratio: float
    median_scheduled_count: float


def _run_group(cfg: dict, seeds: list[int], group_name: str) -> GroupMetrics:
    scheduled_ratios: list[float] = []
    scheduled_counts: list[int] = []
    infeasible_runs = 0

    for seed in seeds:
        tasks = generate_task_pool(cfg, seed=seed)
        result = plan_baseline(tasks, cfg)

        scheduled_count = len(result.scheduled_items)
        scheduled_counts.append(scheduled_count)
        scheduled_ratios.append(scheduled_count / len(tasks) if tasks else 0.0)

        solver_status = str(result.constraint_stats.get("solver_status", "unknown"))
        if solver_status not in {"optimal", "feasible"}:
            infeasible_runs += 1

    return GroupMetrics(
        name=group_name,
        avg_scheduled_ratio=statistics.mean(scheduled_ratios) if scheduled_ratios else 0.0,
        infeasible_ratio=(infeasible_runs / len(seeds)) if seeds else 0.0,
        median_scheduled_count=statistics.median(scheduled_counts) if scheduled_counts else 0.0,
    )


def _variant_a_baseline(base_cfg: dict) -> dict:
    cfg = copy.deepcopy(base_cfg)
    cfg["runtime"]["solver_random_seed"] = 20260324
    cfg["runtime"]["solver_num_workers"] = 1
    cfg["simulation"]["key_task_probability"] = 0.06
    cfg["simulation"]["max_hard_key_tasks"] = int(cfg["simulation"]["task_count_max"])
    return cfg


def _variant_b_data_feasibility(base_cfg: dict) -> dict:
    cfg = copy.deepcopy(base_cfg)
    cfg["runtime"]["solver_random_seed"] = 20260324
    cfg["runtime"]["solver_num_workers"] = 1
    cfg["simulation"]["key_task_probability"] = 0.01
    cfg["simulation"]["max_hard_key_tasks"] = 1
    return cfg


def _variant_c_no_attitude_on_b(base_cfg: dict) -> dict:
    cfg = _variant_b_data_feasibility(base_cfg)
    cfg["constraints"]["attitude_time_per_degree"] = 0.0
    return cfg


def _variant_d_more_solver_time_on_b(base_cfg: dict) -> dict:
    cfg = _variant_b_data_feasibility(base_cfg)
    cfg["runtime"]["solver_timeout_sec"] = 30
    return cfg


def _render_summary_lines(metrics: list[GroupMetrics]) -> list[str]:
    lines = ["group,avg_scheduled_ratio,infeasible_ratio,median_scheduled_count"]
    for m in metrics:
        lines.append(
            f"{m.name},{m.avg_scheduled_ratio:.4f},{m.infeasible_ratio:.4f},{m.median_scheduled_count:.1f}"
        )
    return lines


def _print_summary(metrics: list[GroupMetrics]) -> None:
    for line in _render_summary_lines(metrics):
        print(line)


def main() -> None:
    parser = argparse.ArgumentParser(description="Diagnose schedule ratio across A/B/C/D groups")
    parser.add_argument("--config", default="config", help="配置目录，默认 config")
    parser.add_argument("--seed-start", type=int, default=1001, help="起始 seed")
    parser.add_argument("--runs", type=int, default=40, help="每组运行次数")
    parser.add_argument("--output", default="", help="可选：将结果写入 csv 文件")
    args = parser.parse_args()

    base_cfg = load_config(ROOT / args.config)
    validate_config(base_cfg)
    seeds = list(range(args.seed_start, args.seed_start + args.runs))

    metrics = [
        _run_group(_variant_a_baseline(base_cfg), seeds, "A_baseline"),
        _run_group(_variant_b_data_feasibility(base_cfg), seeds, "B_data_feasibility"),
        _run_group(_variant_c_no_attitude_on_b(base_cfg), seeds, "C_no_attitude_on_B"),
        _run_group(_variant_d_more_solver_time_on_b(base_cfg), seeds, "D_timeout30_on_B"),
    ]
    _print_summary(metrics)
    if args.output:
        out_path = ROOT / args.output
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text("\n".join(_render_summary_lines(metrics)) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
