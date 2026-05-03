Local SDK & Webots quickstart
=============================

This document explains how to run and test controllers locally so students can
develop and validate code before submitting to the server.

Prerequisites
-------------
- Python 3.8+ (recommended)
- numpy (required)
- OpenCV (cv2) optional — example controllers are numpy-only
- Webots installed (version consistent with course guide)

Files of interest
-----------------
- `sdk/team_controller.py` — official template shipped with the course
- `sdk/example_controller.py` — a simple, numpy-only example controller
- `sdk/examples/team_controller_tutorial.py` — heavily-commented tutorial
  (PID line-follower); copy this as the starting point for your own code
- `sdk/validate_controller.py` — local validator (AST + mock call) with
  JSON output, exit-code contract and `--strict` mode
- `sdk/rules.yaml` — validator rules (import allow/deny list, builtin blacklist,
  return ranges, timing budget). Tweak it for stricter local checks; note it
  **only affects the local validator** — the on-server sandbox has its own
  copy in `simnode/car_sandbox.py`
- `sdk/run_local.py` — one-shot launcher: validate -> make config -> start Webots
- `sdk/make_local_config.py` — helper to create a sample race_config.json
- `sdk/check_env.py` — quick dependency check
- `simnode/webots/controllers/car/car_controller.py` — Webots controller that
  launches the sandbox and exchanges frames
- `simnode/webots/controllers/car/sandbox_runner.py` — sandbox runner that
  imports student code with a restricted import hook and communicates via
  stdin/stdout

For a Chinese student-facing walkthrough see `sdk/docs/local_test_guide.md`.

Quick local workflow
--------------------

### Option A — one-shot (recommended)

```powershell
python sdk/run_local.py --code-path sdk/examples/team_controller_tutorial.py
```

This runs the validator, writes `sdk/local_race_config.json`, auto-discovers
Webots (via `WEBOTS_HOME` / `PATH` / common install paths) and launches the
simulation. Pass `--validate-only`, `--skip-validate`, `--fast`, `--minimize`
or `--webots <path>` for variants.

### Option B — step by step

1. Check environment (optional):

```powershell
python sdk/check_env.py
```

2. Validate your controller (AST + mock call, optionally JSON):

```powershell
python sdk/validate_controller.py --code-path sdk/example_controller.py
python sdk/validate_controller.py --code-path my_controller.py --json --strict
```

3. Create a local race config for Webots. Edit the generated JSON to point
   `code_path` at an absolute path to your controller file and set `car_slot`
   to match the robot name in the world if needed (the script defaults to
   `car_0`; the bundled `airacer.wbt` uses `car_1`).

```powershell
python sdk/make_local_config.py --code-path "%CD%\sdk\example_controller.py" --car-slot car_1 --out sdk/local_race_config.json --force
```

4. Launch Webots and open `simnode/webots/worlds/airacer.wbt`. In the Car
   controller's custom data or environment, set the `RACE_CONFIG_PATH` to the
   absolute path of the JSON created in step 3. Alternatively, place the file
   next to the controller so the default 'race_config.json' is found.

Set the environment variable (PowerShell example):

```powershell
$env:RACE_CONFIG_PATH = "C:\full\path\to\pkudsa.airacer\sdk\local_race_config.json"
webots "C:\full\path\to\pkudsa.airacer\simnode\webots\worlds\airacer.wbt"
```

5. Run the simulation. The Webots car controller will spawn the sandbox runner
   which loads your controller and exchanges frames. Use `stderr` from the
   controller (Webots' controller console) to inspect sandbox logs.

Notes & troubleshooting
-----------------------
- If `validate_controller.py` reports a banned import, remove the import or
  replace it with allowed libraries. The sandbox blocks modules such as
  `os`, `sys` (top-level imports), `socket`, `subprocess`, etc.
- If frames time out (no response within 20 ms), the simulator will reuse
  the previous command and may eventually impose a stop penalty. Keep the
  control loop fast and avoid heavy per-frame allocations.
- If you need OpenCV functionality during development, install it in the
  Python environment that Webots will use (or activate a conda env and set
  `CONDA_PREFIX` so the controller uses that Python).

If you want, I can also add a small PowerShell script that launches Webots with
the correct environment automatically.

