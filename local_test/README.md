Local test helper for AI_car
===========================

This folder contains a tiny wrapper that starts a local Webots race using
the repository SDK.

What is provided
- `run.py` — wrapper that delegates to `sdk/run_local.py` using
  `sdk/my_controller.py` (a simple sample controller) and the built-in
  worlds in `sdk/webots/worlds` / `simnode/webots/worlds`.

Minimal requirements
- Python (same interpreter you use to run the script)
- Webots installed and discoverable on PATH or via `--webots` argument or
  `WEBOTS_HOME` environment variable.

Quick start
-----------
From the repository root (where this README is located):

1) Run default local race (uses `sdk/my_controller.py` and `track_complex` by default):

```powershell
python local_test/run.py
```

2) If Webots is not on PATH or auto-detected, pass the path explicitly:

```powershell
python local_test/run.py --webots "C:\\Program Files\\Webots\\webots.exe"
```

3) To list available worlds:

```powershell
python local_test/run.py --list-worlds
```

Notes & tips
------------
- `run.py` simply calls `sdk/run_local.py`, which performs three steps:
  1. validate controller code (`sdk/validate_controller.py`)
  2. generate a `race_config.json` using `sdk/make_local_config.py`
  3. launch Webots with `RACE_CONFIG_PATH` set so the supervisor and car
     controllers read the configuration
- If you want the simnode/backend integration (automatic result callback),
  set `BACKEND_RESULT_CALLBACK_URL` in the environment before launching
  the simnode or Webots (see project config). For local-only runs you do
  not need that.

If you prefer a different controller, pass `--code-path` directly to
`sdk/run_local.py` (or edit `local_test/run.py` to change `DEFAULT_CODE`).

