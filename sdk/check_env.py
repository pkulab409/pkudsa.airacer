"""Simple environment checker for local development.

Checks for Python version, numpy and optional OpenCV. Exits with code 0 if
requirements appear satisfied, non-zero otherwise.
"""

import sys


def main():
    ok = True

    ver_str = sys.version.split()[0]
    if sys.version_info < (3, 8):
        print(f"Python 3.8+ is recommended, current: {ver_str}")
        ok = False
    else:
        print(f"Python: {ver_str}")

    try:
        import numpy  # noqa: F401
        print("numpy: installed")
    except Exception:
        print("numpy: MISSING — install with: pip install numpy")
        ok = False

    try:
        import cv2  # noqa: F401
        print("opencv (cv2): installed")
    except Exception:
        print("opencv (cv2): not found — optional, install with: pip install opencv-python")

    if ok:
        print("Environment appears OK for running the local SDK.")
        return 0
    else:
        print("Environment is missing required components.")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())


