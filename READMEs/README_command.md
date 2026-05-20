# 快速开始

## 一、首次配置

克隆仓库后，从模板创建本地配置文件（实际配置文件不进 git）：

```bash
cp server/config/config.yaml.example  server/config/config.yaml
cp simnode/config/config.yaml.example  simnode/config/config.yaml
```

然后编辑两个文件，按注释填入实际值：

| 文件 | 必填项 |
|------|--------|
| `server/config/config.yaml` | `ADMIN_PASSWORD`、`SIMNODE_URL` |
| `simnode/config/config.yaml` | `WEBOTS_BINARY`（Webots 安装路径）、`WEBOTS_WORLD`、`MAX_CONCURRENT_RACES` |

若省略配置文件，系统使用 `config.py` 中的内置默认值。

---

## 二、安装依赖

```bash
# Backend（Windows / Linux / macOS）
pip install -r requirements.txt

# Sim Node（Linux 服务器，含 headless OpenCV）
pip install -r requirements_simnode.txt
```

---

## 三、启动服务

```bash
# Sim Node（Linux 仿真服务器，默认端口 5000）
uvicorn simnode.server:app --host 0.0.0.0 --port 5000

# Backend（开发时加 --reload，默认端口 8000）
uvicorn server.app:app --host 0.0.0.0 --port 8000 --reload
```

启动后访问 `http://localhost:8000` 进入前端首页。

---

## 四、数据库初始化

数据库在 Backend 首次启动时自动创建（`app.py` 的 `lifespan` 中调用 `init_db`）。如需手动初始化：

```bash
python -c "from server.database.models import init_db; init_db('server/database/race.db')"
```

---

## 五、种子数据（可选）

```bash
# 写入两支演示队伍（密码均为 demo123）
python scripts/seed_demo_teams.py

# 写入实验赛区 + 24 支实验队伍（密码均为 test123）+ 提交记录
python scripts/seed_experiment.py
```

---

## 六、Mock SimNode（前端开发测试）

无需 Webots 时，可使用模拟仿真服务器生成随机遥测数据：

```bash
python scripts/mock_simnode.py --port 8001
```

环境变量：
- `MOCK_RACE_DURATION`：默认 `"5,10"`（随机时长范围，秒）
- `MOCK_SIM_SPEED`：默认 `3.0`（模拟时间倍率）

---

## 七、其他常用命令

### 验证学生代码

```bash
python sdk/validate_controller.py --code-path my_controller.py --rules-path sdk/rules.yaml
```

### 查看当前仿真状态

```bash
curl http://localhost:5000/races
curl http://localhost:5000/race/{race_id}/status
curl http://localhost:5000/race/{race_id}/live
```

### 手动触发测试仿真（调试用）

```bash
curl -X POST http://localhost:5000/race/create \
  -H "Content-Type: application/json" \
  -d '{
    "race_id": "test_debug",
    "session_type": "test",
    "total_laps": 2,
    "cars": [{"car_slot":"car_1","team_id":"debug","team_name":"调试队","code_b64":"..."}]
  }'
```

---

**最后更新**：2026-05-20
