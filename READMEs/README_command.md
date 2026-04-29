# 常用命令


## 启动服务

```bash
# Sim Node（Linux 仿真服务器）
uvicorn simnode.server:app --host 0.0.0.0 --port 8001

# Backend（Windows 主机）
uvicorn server.app:app --host 0.0.0.0 --port 8000 --reload
```

## 验证学生代码

```bash
python sdk/validate_controller.py --code-path my_controller.py
```

## 手动初始化数据库

```bash
python -c "from server.database.models import init_db; init_db('server/database/race.db')"
```

## 查看当前比赛状态

```bash
curl http://localhost:8001/races
curl http://localhost:8001/race/{race_id}/status
```

## 手动触发测试仿真（调试用）

```bash
curl -X POST http://localhost:8001/race/create \
  -H "Content-Type: application/json" \
  -d '{"race_id":"test_debug","session_type":"test","total_laps":2,"cars":[{"car_slot":"car_1","team_id":"debug","team_name":"调试队","code_b64":"..."}]}'
```
