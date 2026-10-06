"""Run prospective tests through the existing isolated Docker project, never shared."""

from pathlib import Path
import subprocess, sys

root = Path(__file__).resolve().parents[3]
targets = sys.argv[1:] or ["plane/curve/tests/manual_gate2_v2/"]
command = [
    "docker",
    "compose",
    "-p",
    "curve-manual-pilot-20261006",
    "-f",
    "deployments/curve-local-pilot/compose.test.yml",
    "run",
    "--rm",
    "-T",
    "-v",
    str(root / ".curve-local/gate2-api") + ":/code:ro",
    "-e",
    "DATABASE_URL=postgresql://curve_test:curve_test@db:5432/curve_gate2_candidate",
    "-e",
    "PYTHONPATH=/code:/code/plane/curve:/code/plane/curve/tests/manual_plan_v2:/code/plane/curve/tests/manual_plan_v2/host",
    "api-tests",
    "python",
    "-c",
    "import plane,pytest,sys; raise SystemExit(pytest.main(sys.argv[1:]))",
    "-c",
    "/code/pytest.ini",
    "-q",
    "--tb=short",
    "--maxfail=1",
    "-o",
    "addopts=--reuse-db --migrations",
    "-o",
    "cache_dir=/tmp/pytest-cache",
    *targets,
]
raise SystemExit(subprocess.run(command, cwd=root, stdin=subprocess.DEVNULL).returncode)
