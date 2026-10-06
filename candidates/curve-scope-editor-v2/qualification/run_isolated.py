"""Run the installed reader suite through the one shared isolated test runner."""

from pathlib import Path
import subprocess
import sys

if __name__ == "__main__":
    repository = Path(__file__).resolve().parents[3]
    runner = repository / "candidates/curve-manual-plan-v2/qualification/run_isolated.py"
    raise SystemExit(subprocess.run([sys.executable, str(runner), "scope"], cwd=repository).returncode)
