"""Upload the code evaluators to LangSmith as dataset-attached evaluators.

Run from ``apps/api``: ``python -m evaluation.upload_evaluators [--dry-run]``. The CLI may
prompt for confirmation; its stdin/stdout are inherited so the owner answers. ``--yes`` is never
passed and the API key travels only through the environment.
"""

import argparse
import os
import shutil
import subprocess
from collections.abc import Callable, Sequence
from pathlib import Path

from dotenv import dotenv_values

from evaluation.evaluators.code import REPORT_CODE_EVALUATORS, TRAJECTORY_CODE_EVALUATORS
from evaluation.harness.runner import DATASETS

API_DIR = Path(__file__).resolve().parents[1]
EVALUATOR_FILE = "evaluation/evaluators/code.py"
_PLAN = (
    (DATASETS["trajectory"], TRAJECTORY_CODE_EVALUATORS),
    (DATASETS["reports"], REPORT_CODE_EVALUATORS),
)

Runner = Callable[[list[str], dict[str, str]], int]


def find_cli() -> str:
    """Resolve the langsmith CLI: LANGSMITH_CLI, then PATH, then the Windows install dir."""
    configured = os.environ.get("LANGSMITH_CLI")
    if configured:
        return configured
    on_path = shutil.which("langsmith")
    if on_path:
        return on_path
    local = os.environ.get("LOCALAPPDATA")
    if local:
        return str(Path(local) / "Programs" / "langsmith" / "bin" / "langsmith.exe")
    return "langsmith"


def build_commands(cli: str) -> list[list[str]]:
    return [
        [
            cli,
            "evaluator",
            "upload",
            EVALUATOR_FILE,
            "--name",
            function,
            "--function",
            function,
            "--dataset",
            dataset,
            "--replace",
        ]
        for dataset, functions in _PLAN
        for function in functions
    ]


def _environment() -> dict[str, str]:
    """Process env plus only the LANGSMITH_* entries of apps/api/.env (never printed)."""
    env = dict(os.environ)
    for key, value in dotenv_values(API_DIR / ".env").items():
        if key.startswith("LANGSMITH_") and value and key not in env:
            env[key] = value
    return env


def _run(command: list[str], env: dict[str, str]) -> int:
    try:
        return subprocess.run(command, env=env, cwd=API_DIR, check=False).returncode
    except FileNotFoundError:
        print(f"langsmith CLI not found ({command[0]}) - set LANGSMITH_CLI to its path.")
        return 1


def main(argv: Sequence[str] | None = None, runner: Runner = _run) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="print the commands only")
    args = parser.parse_args(argv)
    commands = build_commands(find_cli())
    if args.dry_run:
        for command in commands:
            print(" ".join(command))
        return 0
    env = _environment()
    failures = 0
    for command in commands:
        print(f"Uploading {command[command.index('--function') + 1]} ...", flush=True)
        if runner(command, env) != 0:
            failures += 1
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
