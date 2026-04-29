"""
向数据库写入两支 demo 队伍，密码均为 demo123。
运行前须先完成数据库初始化（init_db）。

用法：
    python scripts/seed_demo_teams.py
"""

import sqlite3
import sys
import pathlib

try:
    import bcrypt
except ImportError:
    print("ERROR: bcrypt 未安装，请先运行 pip install bcrypt")
    sys.exit(1)

DB_PATH = pathlib.Path("server/database/race.db")

if not DB_PATH.exists():
    print(f"ERROR: 数据库不存在 ({DB_PATH})，请先运行 init_db")
    sys.exit(1)

TEAMS = [
    ("team_alpha", "Alpha车队", "demo123"),
    ("team_beta",  "Beta车队",  "demo123"),
]

conn = sqlite3.connect(str(DB_PATH))
for team_id, name, password in TEAMS:
    pw_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    conn.execute(
        "INSERT OR IGNORE INTO teams (id, name, password_hash) VALUES (?, ?, ?)",
        (team_id, name, pw_hash),
    )
    print(f"  {name}  id={team_id}  密码=demo123")

conn.commit()
conn.close()
print("\n队伍写入完成。")
