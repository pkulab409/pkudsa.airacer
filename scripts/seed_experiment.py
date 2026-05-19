#!/usr/bin/env python3
"""
向数据库写入实验赛区和 24 支队伍 (experiment_01 ~ experiment_24)，
并为每队创建一份提交。幂等 —— 重复运行不会重复创建。

用法:
    python scripts/seed_experiment.py
"""

import datetime
import pathlib
import shutil
import sqlite3
import sys
import uuid

try:
    import bcrypt
except ImportError:
    print("ERROR: bcrypt 未安装，请先运行 pip install bcrypt")
    sys.exit(1)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "server" / "database" / "race.db"
SUBMISSIONS_DIR = PROJECT_ROOT / "submissions"
SDK_TEMPLATE = PROJECT_ROOT / "sdk" / "team_controller.py"

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
ZONE_ID = "experiment"
ZONE_NAME = "实验赛区"
ZONE_DESC = "24队实验平台 - 用于全功能测试"
ZONE_LAPS = 3

TEAM_PREFIX = "experiment"
TEAM_COUNT = 24
TEAM_PASSWORD = "test123"

# ---------------------------------------------------------------------------
# Check prerequisites
# ---------------------------------------------------------------------------
if not DB_PATH.exists():
    print(f"ERROR: 数据库不存在 ({DB_PATH})，请先初始化数据库")
    sys.exit(1)

if not SDK_TEMPLATE.exists():
    print(f"ERROR: SDK 模板不存在 ({SDK_TEMPLATE})")
    sys.exit(1)

SUBMISSIONS_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Connect
# ---------------------------------------------------------------------------
conn = sqlite3.connect(str(DB_PATH))
conn.row_factory = sqlite3.Row
now = datetime.datetime.now(datetime.timezone.utc).isoformat()

# ---------------------------------------------------------------------------
# 1. Create zone
# ---------------------------------------------------------------------------
conn.execute(
    "INSERT OR IGNORE INTO zones (id, name, description, total_laps, created_at) "
    "VALUES (?, ?, ?, ?, ?)",
    (ZONE_ID, ZONE_NAME, ZONE_DESC, ZONE_LAPS, now),
)
conn.commit()

zone_row = conn.execute("SELECT * FROM zones WHERE id = ?", (ZONE_ID,)).fetchone()
if zone_row:
    print(
        f"  Zone: {zone_row['name']}  (id={zone_row['id']})  laps={zone_row['total_laps']}"
    )
else:
    print("ERROR: 无法创建 zone")
    sys.exit(1)

# ---------------------------------------------------------------------------
# 2. Create teams
# ---------------------------------------------------------------------------
pw_hash = bcrypt.hashpw(TEAM_PASSWORD.encode(), bcrypt.gensalt()).decode()
teams_created = 0
teams_skipped = 0

for i in range(1, TEAM_COUNT + 1):
    team_id = f"{TEAM_PREFIX}_{i:02d}"
    team_name = f"实验队伍_{i:02d}"

    cur = conn.execute(
        "INSERT OR IGNORE INTO teams (id, name, password_hash, zone_id, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (team_id, team_name, pw_hash, ZONE_ID, now),
    )
    if cur.rowcount > 0:
        teams_created += 1
    else:
        teams_skipped += 1

conn.commit()
print(f"  Teams: {teams_created} created, {teams_skipped} skipped (already exist)")

# ---------------------------------------------------------------------------
# 3. Create submissions
# ---------------------------------------------------------------------------
subs_created = 0
subs_skipped = 0

for i in range(1, TEAM_COUNT + 1):
    team_id = f"{TEAM_PREFIX}_{i:02d}"

    # Check if this team already has an active submission in slot "main"
    existing = conn.execute(
        "SELECT id FROM submissions WHERE team_id = ? AND slot_name = 'main' AND is_active = 1",
        (team_id,),
    ).fetchone()

    if existing:
        subs_skipped += 1
        continue

    # Copy SDK template to submissions/{team_id}/
    team_dir = SUBMISSIONS_DIR / team_id
    team_dir.mkdir(parents=True, exist_ok=True)
    dest = team_dir / "team_controller.py"
    if not dest.exists():
        shutil.copy2(SDK_TEMPLATE, dest)

    sub_id = str(uuid.uuid4())
    code_path = str(dest.resolve())

    conn.execute(
        """INSERT INTO submissions (id, team_id, code_path, submitted_at, is_active, slot_name, is_race_active)
           VALUES (?, ?, ?, ?, 1, 'main', 1)""",
        (sub_id, team_id, code_path, now),
    )
    subs_created += 1

conn.commit()
print(f"  Submissions: {subs_created} created, {subs_skipped} skipped (already exist)")

# ---------------------------------------------------------------------------
# 4. Summary
# ---------------------------------------------------------------------------
conn.close()

print()
print("=" * 50)
print("  Seed complete!")
print(f"  Zone:       {ZONE_ID}  ({ZONE_NAME})")
print(f"  Teams:      {teams_created} new + {teams_skipped} existing")
print(f"  Submissions: {subs_created} new + {subs_skipped} existing")
print(f"  Password:   {TEAM_PASSWORD} (all teams)")
print()
print("  Frontend URLs:")
print(f"    Admin:  http://localhost:8000/admin/")
print(f"    Zone:   http://localhost:8000/zone/?id={ZONE_ID}")
print(f"    Submit: http://localhost:8000/submit/")
print(f"    Test:   http://localhost:8000/testrace/")
print("=" * 50)
