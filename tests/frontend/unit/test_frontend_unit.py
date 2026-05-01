import subprocess
from pathlib import Path


def test_frontend_javascript_units():
    script = Path(__file__).with_name("frontend_unit_tests.mjs")

    result = subprocess.run(
        ["node", str(script)],
        cwd=Path(__file__).resolve().parents[3],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr or result.stdout
