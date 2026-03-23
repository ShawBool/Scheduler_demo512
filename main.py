"""卫星基线规划命令行入口。"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from scheduler.pipeline import run_pipeline


def main() -> None:
    parser = argparse.ArgumentParser(description="Satellite baseline scheduler demo / 卫星基线规划演示")
    parser.add_argument("--config", default="config", help="Path to config directory / 配置目录路径")
    parser.add_argument("--seed", type=int, default=666, help="Random seed override / 随机种子")
    parser.add_argument("--output-dir", default="output", help="Output directory override / 输出目录")
    args = parser.parse_args()

    result = run_pipeline(args.config, seed=args.seed, output_dir=args.output_dir)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
