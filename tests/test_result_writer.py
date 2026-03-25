from pathlib import Path

from scheduler.result_writer import initialize_iteration_log


def test_iteration_log_file_created_before_solver(tmp_path: Path):
    log_path = tmp_path / "solver_progress.jsonl"
    initialize_iteration_log(log_path)
    assert log_path.exists()
    assert log_path.read_text(encoding="utf-8") == ""
