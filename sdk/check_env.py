"""Simple environment checker for local development.

Checks that the local machine meets the AI Racer SDK baseline:

  * Python **3.10+** (matches the server-side Sim Node interpreter)
  * ``numpy`` installed (required by the sandbox-facing ``control()``)
  * ``pyyaml`` installed (required by ``validate_controller.py`` to consume
    ``sdk/rules.yaml``; validator will otherwise fall back to a built-in copy
    and print a warning)
  * ``opencv-python`` / ``opencv-python-headless`` (optional — server uses
    ``opencv-python-headless``)
  * ``pytest`` (optional — required to run ``sdk/tests/test_validator.py``)

Exit code:
  * ``0`` — everything required is present (optional items may be missing)
  * ``2`` — at least one required component is missing
"""

from __future__ import annotations

import importlib
import sys
from typing import Optional


MIN_PY = (3, 10)


def _check_import(mod: str) -> Optional[str]:
    """Return the module version string if import succeeds, else None."""
    try:
        m = importlib.import_module(mod)
    except Exception:
        return None
    ver = getattr(m, "__version__", None)
    return str(ver) if ver else "unknown"


def main() -> int:
    ok = True
    ver_str = sys.version.split()[0]

    if sys.version_info < MIN_PY:
        print(
            f"Python {MIN_PY[0]}.{MIN_PY[1]}+ required (server runs 3.10), "
            f"current: {ver_str}"
        )
        ok = False
    else:
        print(f"Python: {ver_str}  (ok, >= {MIN_PY[0]}.{MIN_PY[1]})")

    # --- required ---
    for pkg, hint in [
        ("numpy",  "pip install numpy"),
        ("yaml",   "pip install pyyaml"),
    ]:
        v = _check_import(pkg)
        label = "pyyaml" if pkg == "yaml" else pkg
        if v is None:
            print(f"{label}: MISSING — install with: {hint}")
            ok = False
        else:
            print(f"{label}: installed ({v})")

    # --- optional ---
    cv_ver = _check_import("cv2")
    if cv_ver is None:
        print(
            "opencv (cv2): not found — optional. "
            "Server uses opencv-python-headless; install with:\n"
            "  pip install opencv-python-headless"
        )
    else:
        print(f"opencv (cv2): installed ({cv_ver})")

    pytest_ver = _check_import("pytest")
    if pytest_ver is None:
        print(
            "pytest: not found — optional (needed to run sdk/tests). "
            "Install with: pip install pytest"
        )
    else:
        print(f"pytest: installed ({pytest_ver})")

    if ok:
        print("\nEnvironment appears OK for running the local SDK.")
        return 0
    print("\nEnvironment is missing required components (see above).")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())


