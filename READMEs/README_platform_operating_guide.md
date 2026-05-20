# 平台运营指南

## 1. 部署架构

```
主机（Windows / Linux / macOS）
  |-- Frontend（浏览器访问 http://localhost:8000）
  |-- Backend（uvicorn server.app:app --port 8000）

Linux 仿真服务器（或同机）
  |-- Sim Node（uvicorn simnode.server:app --port 5000）
```

修改 `server/config/config.yaml` 中的 `SIMNODE_URL` 指向实际 SimNode 地址。

---

## 2. 启动步骤

### 2.1 启动 Sim Node

```bash
cd /opt/airacer
pip install -r requirements_simnode.txt
uvicorn simnode.server:app --host 0.0.0.0 --port 5000
```

### 2.2 启动 Backend

```bash
cd /opt/airacer
pip install -r requirements.txt
uvicorn server.app:app --host 0.0.0.0 --port 8000
```

### 2.3 访问前端

浏览器访问 `http://localhost:8000`。

---

## 3. 赛事运营流程

### 赛前准备

1. **创建赛区**：Admin 控制台 -> 新建赛区（填写 ID、名称、默认圈数）
2. **队伍注册**：学生通过前端或 `/api/register` 自注册，或管理员批量导入
3. **代码提交**：学生在 `/submit/` 上传代码到 `main`/`dev`/`backup` 槽位
4. **测试验证**：学生申请单车测试，确认代码可正常运行
5. **锁定提交**：管理员在 Admin 控制台点击"锁定提交"（赛区转入 `IDLE`）
   - 锁定后，所有队伍使用最后一次成功上传的版本参赛
   - 生产环境不建议在锁定后反复解锁；如需重新开放，可使用"解锁提交"功能

### 正赛推进

系统根据赛区队伍数**自动计算赛制**（`bracket.py`）：

| 队伍数 | 阶段 |
|--------|------|
| <= 4 | 排位赛 -> 决赛 |
| 5-8 | 排位赛 -> 半决赛 -> 决赛 |
| >= 9 | 排位赛 -> 小组赛 -> 半决赛 -> 决赛 |

**操作循环**（每个阶段重复）：

1. 点击**"开始比赛"**：系统自动从 `waiting` 队列取出下一场次，启动仿真
2. 比赛进行中：实时查看车辆状态、俯视画面、排行榜
3. 比赛结束：状态自动变为 `*_FINISHED`，积分榜更新
4. 当前阶段所有场次完成后，点击**"推进赛程"（finalize）**：
   - 系统自动计算晋级队伍
   - 蛇形分组（如需要）
   - 预创建下一阶段的所有 `waiting` 场次
   - 赛区回到 `IDLE`
5. 重复步骤 1~4，直到决赛结束

### 决赛与关闭

决赛结束后，点击**"推进赛程"**，状态机进入 `CLOSED`，赛事正式关闭。

---

## 4. 紧急操作

### 强制停止当前仿真

Admin 控制台 -> 选择赛区 -> **"停止比赛"**。

- 仿真立即终止，状态变为 `*_ABORTED` 或 `RECORDING_READY`
- 可通过 **"重置赛区"** 将状态回退至 `IDLE`，重新配置本场次

### 解锁/锁定提交

- **锁定**：赛区 `REGISTRATION` -> `IDLE`，拒绝新提交
- **解锁**：赛区 `IDLE` -> `REGISTRATION`，重新开放提交（仅限未开赛阶段，生产环境不建议反复操作）

### 删除赛区

Admin 控制台 -> 危险操作区 -> 删除赛区。

- 会级联删除该赛区的所有队伍、提交、比赛记录
- 不可逆，请谨慎操作

---

## 5. 录像回放

赛事结束后，录像文件存储在：

```
recordings/{session_id}/
    |-- metadata.json      # 比赛结果、最终排名
    |-- telemetry.jsonl    # NDJSON 遥测帧序列
    |-- live_view.jpg      # 俯视摄像头画面（如有）
```

前端 `/race/` 页面可按赛区、阶段筛选并回放任意录像。

---

**最后更新**：2026-05-20
