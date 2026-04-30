# 快速开始

## 一、首次配置

克隆仓库后，需先从模板创建本地配置文件（模板已提交，实际配置文件不进 git）：

```bash
cp server/config/config.yaml.example  server/config/config.yaml
cp simnode/config/config.yaml.example simnode/config/config.yaml
```

然后编辑两个文件，按注释填入本机实际值：

| 文件 | 必填项 |
|------|--------|
| `server/config/config.yaml` | `ADMIN_PASSWORD`、`SIMNODE_URL` |
| `simnode/config/config.yaml` | `WEBOTS_BINARY`（Webots 安装路径）、`WEBOTS_HEADLESS` |

---

## 二、安装依赖

```bash
# Backend + Sim Node 共用
conda activate airacer
pip install -r requirements.txt

# 仅 Sim Node（Linux 服务器）
pip install -r requirements_simnode.txt
```

---

## 三、启动服务

```bash
# Sim Node（Linux 仿真服务器 或 本地 demo）
uvicorn simnode.server:app --host 0.0.0.0 --port 5000

# Backend（主机，开发时加 --reload）
uvicorn server.app:app --host 0.0.0.0 --port 8000 --reload
```

启动后访问 `http://localhost:8000` 进入前端首页。

---

## 四、其他常用命令

### 验证学生代码

```bash
python sdk/validate_controller.py --code-path my_controller.py
```

### 手动初始化数据库

```bash
python -c "from server.database.models import init_db; init_db('server/database/race.db')"
```

### 查看当前仿真状态

```bash
curl http://localhost:5000/races
curl http://localhost:5000/race/{race_id}/status
```

### 手动触发测试仿真（调试用）

```bash
curl -X POST http://localhost:5000/race/create \
  -H "Content-Type: application/json" \
  -d '{"race_id":"test_debug","session_type":"test","total_laps":2,"cars":[{"car_slot":"car_1","team_id":"debug","team_name":"调试队","code_b64":"..."}]}'
```
