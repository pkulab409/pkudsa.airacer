# Sim Node 包文档

此文档介绍 `simnode/` 包的功能、使用方式和接口。

---

## 1. 环境配置

- **Python 版本**：3.10+
- **依赖**：`fastapi`, `uvicorn`, `httpx`, `pyyaml`, `numpy`, `opencv-python-headless`
- **外部依赖**：Webots（Linux 上通常为 `/usr/bin/webots`）

配置文件：`simnode/config/config.yaml`（从 `.example` 复制），关键项：

```yaml
SIMNODE_HOST:         "0.0.0.0:5000"
RECORDINGS_DIR:       "./recordings"
WEBOTS_BINARY:        "/usr/bin/webots"
WEBOTS_WORLD:         "./simnode/webots/worlds/track_complex.wbt"
RACE_TIMEOUT_SECONDS: 600
MAX_CONCURRENT_RACES: 4
```

启动方式：

```bash
uvicorn simnode.server:app --host 0.0.0.0 --port 5000
```

---

## 2. `race_manager.py`

**单例模式**管理所有比赛生命周期。

### `RaceManager`

| 方法 | 说明 |
|------|------|
| `start_race(race_id, session_type, total_laps, cars, ws_push_callback)` | 创建并启动比赛线程 |
| `cancel_race(race_id) -> bool` | 优雅停止（STOP 文件 + 等待），超时强制 kill |
| `get_race_status(race_id) -> Optional[str]` | 查询状态 |
| `get_race_result(race_id) -> Optional[dict]` | 查询结果（仅 completed） |
| `get_all_races() -> List[(race_id, status)]` | 列出所有比赛 |
| `get_webots_pid(race_id) -> Optional[int]` | 获取 Webots 进程 PID |

**并发控制**：默认最大 4 场同时运行（`MAX_CONCURRENT_RACES`），超出时返回 HTTP 409。

---

## 3. `race_runner.py`

每场比赛一个独立 `RaceRunner` 实例，在线程中执行完整生命周期。

### 执行流程

1. `_decode_car_codes()`：Base64 解码学生代码，写入临时目录
2. `_write_race_config()`：生成 `race_config.json`（含车辆配置、圈数、录制路径）
3. `_launch_webots()`：启动 Webots 子进程，传入 `RACE_CONFIG_PATH` 环境变量
   - headless 模式：`--batch --no-sandbox`
   - 非 headless：`--minimize`
4. `_wait_for_webots()`：阻塞等待进程结束（最长 10 分钟）
5. `_read_result()`：读取 `metadata.json`

### 关于 headless 与摄像头

- `--batch` 模式会禁用 GPU 渲染，导致 `Camera.saveImage()` 输出全黑帧（俯视摄像头失效）
- 若需要实时俯视画面（`/frame` 端点），请在配置文件中设置 `WEBOTS_HEADLESS: false`，此时使用 `--minimize` 启动，保留 GPU 渲染能力
- 生产环境 Linux 服务器若无显示器，可保持 `--batch`，但 `/frame` 将不可用

### 优雅停止

`graceful_stop()`：写入 `STOP` 文件，等待 Webots 读取后退出（最长 15 秒）；超时则 `force_stop()`（SIGKILL）。

---

## 4. `telemetry_observer.py`

记录比赛快照并推流。

### `TelemetryObserver`

- `make_snapshot(event_type, event_data)`：记录事件并触发 `ws_push_callback`
- `pop_snapshots()`：获取并清空缓冲区
- `get_snapshots()`：获取不清空
- `confirm_telemetry_file()`：确认文件存在且非空

存储路径：`recordings/{race_id}/simnode_events.jsonl`

---

## 5. `car_sandbox.py`

学生代码执行环境限制。

### 功能

- **`RESTRICTED_BUILTINS`**：受限 `__builtins__` 字典（移除 `open`, `eval`, `exec`, `globals`, `locals`, `compile`）
- **`SandboxImportHook`**：`sys.meta_path` 拦截器，禁止 `os`, `sys`, `socket`, `threading` 等模块
- **`apply_resource_limits()`**：Linux 下限制内存 512 MB、CPU 30 秒

### 白名单

允许：`numpy`, `cv2`, `math`, `collections`, `heapq`, `functools`, `itertools`, `typing`, `__future__`, `pathlib`, `dataclasses`, `re`

禁止（包括但不限于）：`os`, `sys`, `socket`, `subprocess`, `multiprocessing`, `threading`, `time`, `datetime`, `io`, `builtins`, `ctypes`, `shutil`, `tempfile`, `glob`, `fnmatch`, `winreg`, `nt`, `_winapi`, `requests`, `urllib`, `http`, `ftplib`, `smtplib`, `signal`, `gc`, `inspect`, `importlib`, `pickle`

---

## 6. `server.py`

SimNode HTTP/WebSocket 服务层。

### REST 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/race/create` | 创建比赛 |
| `POST` | `/race/{id}/cancel` | 取消比赛 |
| `GET`  | `/race/{id}/status` | 查询状态 |
| `GET`  | `/race/{id}/result` | 查询结果 |
| `GET`  | `/race/{id}/live` | 实时遥测（内存缓存） |
| `GET`  | `/race/{id}/frame` | 俯视摄像头帧（内存缓存） |
| `POST` | `/race/{id}/push` | Supervisor 直推遥测 |
| `GET`  | `/races` | 列出所有比赛 |
| `GET`  | `/health` | 健康检查 |

### WebSocket

`WS /race/{race_id}/stream`：实时事件推流。

### 后台缓存线程

`_cache_updater_loop`：每 50 ms 读取磁盘 `live.json` + `live_view.jpg`，更新内存缓存，供 `/live` 和 `/frame` 热路径使用。

---

## 7. Webots 控制器

### Supervisor（`simnode/webots/controllers/supervisor/supervisor.py`）

- 每仿真步（64 ms）更新所有车辆位置、速度、朝向
- 检查点序列检测（CP0 ~ CP8），CP0 兼作起点与终点
- 碰撞检测：pairwise 距离 < 0.5 m；相对速度 >= 3 m/s 为 major
- 违规判定：3 次 major -> `disqualified`；60 秒未过检查点 -> `disqualified`
- 结束逻辑：
  - 首车完赛后 60 秒宽限期（非排位赛）
  - 所有车辆完赛/违规/超时后结束
  - 全局超时 600 秒
- 每步写入 `telemetry.jsonl`；每 2 步保存 `live_view.jpg` 和 `live.json`

### Car Controller（`simnode/webots/controllers/car/car_controller.py`）

- 每步读取 `left_camera` / `right_camera` 图像
- 通过 `RACE_CONFIG_PATH` 加载对应车辆的 `team_controller.py`
- **In-process 调用**：直接执行学生 `control(left_img, right_img, timestamp)`，零延迟
- 学生代码缺失或异常时，车辆**静止不动**（速度=0，转向=0）
- 通过 `customData` 接收 Supervisor 指令：`disqualify` / `stop`

---

**最后更新**：2026-05-20
