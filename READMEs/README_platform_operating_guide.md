# 平台运营指南


## 1. 部署架构

```
Windows 主机
  ├── Frontend（浏览器访问 http://localhost:8000）
  └── Backend（uvicorn server.app:app --port 8000）

Linux 仿真服务器
  └── Sim Node（uvicorn simnode.server:app --port 8001）
```

修改 `server/config/config.yaml` 中的 `SIMNODE_URL` 指向实际 Linux 服务器 IP。

---

## 2. 启动步骤

### 2.1 启动 Sim Node（Linux 服务器）

```bash
cd /opt/airacer
pip install -r requirements_simnode.txt
uvicorn simnode.server:app --host 0.0.0.0 --port 8001
```

### 2.2 启动 Backend（Windows 主机）

```bash
cd D:\pkudsa.airacer
pip install -r requirements.txt
uvicorn server.app:app --host 0.0.0.0 --port 8000 --reload
```

### 2.3 访问前端

打开浏览器访问 `http://localhost:8000`。

---

## 3. 赛事推进流程

### 3.1 排位赛

1. 进入助教控制台（`/admin/`，密码见 `config.yaml`）
2. 配置第 1 批排位赛参数（选择参赛队伍、圈数=2）
3. 点击「启动仿真」→ 等待比赛结束
4. 查看录像确认无误
5. 重复步骤 2~4，共 7 批次
6. 点击「结算排位赛」→ 系统自动写入积分，推进至 `QUALIFYING_DONE`

### 3.2 分组赛

重复 7 次「配置 → 启动 → 结算」循环，每次完成后系统进入 `GROUP_RACE_FINISHED`。
7 场全部完成后，点击「结算分组赛」。

### 3.3 半决赛 → 决赛

类似操作，各阶段名称：`finalize-semi`、`close-event`。

---

## 4. 紧急操作

### 强制停止当前仿真

助教控制台 → 「强制停止」→ 仿真立即终止，状态变为 `*_ABORTED`。

可通过「重置赛道」将状态回退至 IDLE，重新配置本批次。

### 提交锁定

助教控制台 → 「锁定提交」→ 二次确认 → 系统拒绝所有新提交。

**不可逆操作**，请在截止时间后执行。

---

## 5. 录像回放

赛事结束后，录像文件存储在：

```
recordings/{race_id}/
    ├── telemetry.jsonl    ← 遥测帧序列
    └── metadata.json      ← 场次元数据
```

前端 `/race/` 页面可直接选择任意录像进行回放。

---

**最后更新**：2026-04-28
