# Sim Node 包文档：仿真节点核心模块

此文档介绍 `simnode/` 包的功能、使用方式和接口。

---

## 1. 环境配置

- **Python 版本**：3.10+（需运行在 Linux 上）
- **依赖**：
  - `fastapi`, `uvicorn`：HTTP/WebSocket 服务
  - `httpx`：Backend 与 Sim Node 之间的 HTTP 请求
  - `pyyaml`：配置文件解析
  - Webots 安装包（Linux，`/usr/bin/webots`）

配置文件位于 `simnode/config/config.yaml`，需在部署前修改路径：

```yaml
SIMNODE_HOST:         "0.0.0.0:8001"
RECORDINGS_DIR:       "/data/airacer/recordings"
WEBOTS_BINARY:        "/usr/bin/webots"
WEBOTS_WORLD:         "/opt/airacer/simnode/webots/worlds/airacer.wbt"
RACE_TIMEOUT_SECONDS: 600
```

启动方式：

```bash
cd /opt/airacer
uvicorn simnode.server:app --host 0.0.0.0 --port 8001
```

---

## 2. `race_manager.py` 模块

对应 Avalon 的 `battle_manager.py`，采用**单例模式**管理所有比赛。

### 2.1 核心类：`RaceManager`

| 方法 | 参数 | 返回值 | 描述 |
|------|------|--------|------|
| `start_race(race_id, session_type, total_laps, cars, ws_push_callback)` | 比赛参数，可选 WS 推流回调 | `race_id` | 创建 RaceRunner 并启动线程 |
| `cancel_race(race_id)` | `race_id` | `bool` | 终止 Webots 进程 |
| `get_race_status(race_id)` | `race_id` | 状态字符串 | 查询比赛状态 |
| `get_race_result(race_id)` | `race_id` | 结果字典或 `None` | 查询已完成比赛结果 |
| `get_all_races()` | 无 | `[(race_id, status)]` | 列出所有比赛 |

与 `BattleManager` 的对应：

```
BattleManager.create_battle()     → RaceManager.start_race()
BattleManager.cancel_battle()     → RaceManager.cancel_race()
BattleManager.get_battle_status() → RaceManager.get_race_status()
BattleManager.get_battle_result() → RaceManager.get_race_result()
BattleManager.get_all_battles()   → RaceManager.get_all_races()
BattleManager.get_snapshots_queue() → [由 WebSocket 推流代替]
```

### 2.2 创建比赛线程的具体流程（`start_race()`）

1. 创建 `TelemetryObserver`（对应 Avalon 中创建 `Observer`）
2. 创建 `RaceRunner`（对应 Avalon 中创建 `AvalonReferee`）
3. 定义线程执行函数，启动 `threading.Thread`
4. 将 `_RaceRecord` 存入 `_races` 字典，返回 `race_id`

---

## 3. `race_runner.py` 模块

对应 Avalon 的 `referee.py`（`AvalonReferee`），负责驱动完整的仿真流程。

### 3.1 核心类：`RaceRunner`

```python
class RaceRunner:
    def __init__(self, race_id, session_type, total_laps, cars, observer)
    def run_race(self) -> Dict[str, Any]
    def force_stop(self) -> None
    def _decode_car_codes(self) -> List[Dict]   # 对应 Avalon _load_codes()
    def _write_race_config(self, car_configs) -> str
    def _launch_webots(self, config_path) -> None
    def _wait_for_webots(self) -> int
    def _read_result(self, exit_code) -> Dict
    def _abort(self, reason) -> None             # 对应 Avalon suspend_game()
```

#### 3.1.1 学生代码加载流程

与 Avalon `_load_codes()` + `load_player_codes()` 的对应：

| Avalon | AiRacer | 说明 |
|--------|---------|------|
| `exec(code_content, module.__dict__)` | Base64 解码 → 写入 tmp 文件 | 代码在独立子进程中执行 |
| `Player()` 实例化 | `sandbox_runner.py` 子进程启动 | 在 CarController 内执行 |
| `safe_execute()` 包装调用 | `sandbox_runner.py` stdin/stdout 协议 | 每帧通信 |

#### 3.1.2 仿真流程

1. 解码各队代码，写入临时目录（`_decode_car_codes`）
2. 生成 `race_config.json`（`_write_race_config`）
3. 启动 Webots 子进程，传入 `RACE_CONFIG_PATH` 环境变量（`_launch_webots`）
4. 等待 Webots 进程结束（`_wait_for_webots`，最长 10 分钟）
5. 读取 Supervisor 写入的 `metadata.json`（`_read_result`）
6. 通过 `TelemetryObserver` 发送 `race_ended` 事件

#### 3.1.3 异常终止（对应 Avalon `suspend_game()`）

```python
_abort(reason: str)
→ observer.make_snapshot("race_error", {"error_type": ..., "message": reason})
→ force_stop()   # SIGKILL Webots 进程
```

---

## 4. `telemetry_observer.py` 模块

对应 Avalon 的 `observer.py`，记录比赛快照并推流至 Backend。

### 4.1 核心类：`TelemetryObserver`

#### 4.1.1 方法

- **`make_snapshot(event_type: str, event_data: Any) -> None`**

  记录一次仿真事件。**与 Avalon `Observer.make_snapshot()` 同名同意**。
  额外功能：将快照推送至 Backend WebSocket 连接。

- **`pop_snapshots() -> List[Dict]`**

  获取并清空快照队列（对应 Avalon `pop_snapshots()`）。

- **`confirm_telemetry_file() -> bool`**

  确认 `telemetry.jsonl` 存在且非空（对应 Avalon `snapshots_to_json()`）。

#### 4.1.2 存储格式

与 Avalon `archive_game_{id}.json` 的区别：
- 改用 NDJSON 格式（每行一条快照），支持流式读取
- 文件路径：`recordings/{race_id}/telemetry.jsonl`

---

## 5. `car_sandbox.py` 模块

对应 Avalon 的 `restrictor.py`，限制学生代码的执行环境。

### 5.1 提供的功能

- **`RESTRICTED_BUILTINS`**：受限 `__builtins__` 字典（同 Avalon 同名常量）
- **`_restricted_importer()`**：白名单导入器（同 Avalon）
- **`SandboxImportHook`**：`sys.meta_path` 拦截器（Avalon 无此类，新增）
- **`apply_resource_limits()`**：Linux `resource.setrlimit`（Avalon 无，新增）

### 5.2 白名单对比

| Avalon `restrictor.py` | AiRacer `car_sandbox.py` |
|------------------------|--------------------------|
| `random, re, collections, math, json` | `numpy, cv2, math, collections, heapq, functools, itertools` |

### 5.3 使用方式

`car_sandbox.py` 被 `simnode/webots/controllers/car/sandbox_runner.py` 使用：

```python
# sandbox_runner.py 启动时（子进程）：
from car_sandbox import SandboxImportHook, RESTRICTED_BUILTINS, apply_resource_limits

apply_resource_limits()               # Linux 资源限制
sys.meta_path.insert(0, SandboxImportHook())  # 安装导入拦截

# 加载学生代码时替换 __builtins__：
module.__dict__["__builtins__"] = RESTRICTED_BUILTINS
```

---

## 6. `server.py` 模块

Sim Node HTTP/WebSocket 接口层，暴露 `/race/*` 端点。

详细接口说明见 `READMEs/README_simnode_interface.md`。

---

## 7. Webots 控制器

### 7.1 Supervisor（对应 Avalon `AvalonReferee` 的游戏逻辑部分）

文件：`simnode/webots/controllers/supervisor/supervisor.py`

- 每仿真步读取各车位置，调用 `TelemetryObserver.make_snapshot("TelemetryFrame", data)`
- 计圈判定（4 检查点序列），触发 `"LapComplete"` 事件
- 碰撞检测，触发 `"Collision"` 事件并施加停车惩罚
- 竞速赛制结束逻辑：领先者完赛 → 60 秒宽限 → `"RaceEnd"`
- 仿真结束后写入 `recordings/{race_id}/metadata.json`

### 7.2 CarController（对应 Avalon `safe_execute()` 包装层）

文件：`simnode/webots/controllers/car/car_controller.py`

- 每仿真步读取左右摄像头图像
- 将图像序列化，通过 stdin 传给 `sandbox_runner.py` 子进程
- 接收返回的 `{"steering": float, "speed": float}` JSON 行
- 超时（20ms）时沿用上一帧指令（对应 Avalon 超时默认行为）
- 连续 3 次超时：触发 `"TimeoutWarn"` 事件

---

**最后更新**：2026-04-28
