# AI Racer Demo 测试指南

> 适用版本：含赛区管理 + 多 Controller 槽位 + 自动赛制 + 统一赛事的最新系统。
> 命令行示例基于 Windows PowerShell；含中文 Body 时需用 UTF-8 字节数组。

---

## 目录

1. [环境启动](#1-环境启动)
2. [创建赛区](#2-创建赛区)
3. [队伍注册](#3-队伍注册)
4. [上传 Controller 与槽位管理](#4-上传-controller-与槽位管理)
5. [Admin 比赛控制](#5-admin-比赛控制)
6. [多赛区并发验证](#6-多赛区并发验证)
7. [赛制自适应验证](#7-赛制自适应验证)
8. [测试赛事（用户自主发起）](#8-测试赛事用户自主发起)
9. [积分榜与录像](#9-积分榜与录像)
10. [常见问题](#10-常见问题)

---

## 准备：Admin 认证变量

```powershell
$cred = [Convert]::ToBase64String([Text.Encoding]::ASCII.GetBytes("admin:admin123"))
```

> 密码在 `server/config/config.yaml` 的 `ADMIN_PASSWORD` 中配置。

---

## 1. 环境启动

### 1.1 启动 Sim Node

```powershell
conda activate airacer
uvicorn simnode.server:app --host 0.0.0.0 --port 5000
```

### 1.2 启动 Backend

```powershell
conda activate airacer
uvicorn server.app:app --host 0.0.0.0 --port 8000 --reload
```

### 1.3 打开前端

浏览器访问 `http://localhost:8000`。

---

## 2. 创建赛区

**方式一：Admin 控制台 UI**

进入 `http://localhost:8000/admin/`，密码 `admin123`，左侧底部点击新建赛区。

**方式二：PowerShell API**

```powershell
Invoke-RestMethod -Uri "http://localhost:8000/api/admin/zones" -Method POST `
  -Headers @{ Authorization = "Basic $cred" } `
  -ContentType "application/json; charset=utf-8" `
  -Body ([Text.Encoding]::UTF8.GetBytes('{"id":"cs","name":"计算机科学班","description":"CS组","total_laps":3}'))

Invoke-RestMethod -Uri "http://localhost:8000/api/admin/zones" -Method POST `
  -Headers @{ Authorization = "Basic $cred" } `
  -ContentType "application/json; charset=utf-8" `
  -Body ([Text.Encoding]::UTF8.GetBytes('{"id":"is","name":"信息科学班","description":"IS组","total_laps":3}'))
```

**验证**：

```powershell
Invoke-RestMethod -Uri "http://localhost:8000/api/admin/zones" -Headers @{ Authorization = "Basic $cred" }
```

---

## 3. 队伍注册

```powershell
# cs 赛区注册 4 支队伍
foreach ($i in 1..4) {
  $json = "{`"zone_id`":`"cs`",`"team_id`":`"cs_team$i`",`"team_name`":`"CS队$i`",`"password`":`"pass$i`"}"
  Invoke-RestMethod -Uri "http://localhost:8000/api/register" -Method POST `
    -ContentType "application/json; charset=utf-8" `
    -Body ([Text.Encoding]::UTF8.GetBytes($json))
}

# is 赛区注册 6 支队伍
foreach ($i in 1..6) {
  $json = "{`"zone_id`":`"is`",`"team_id`":`"is_team$i`",`"team_name`":`"IS队$i`",`"password`":`"pass$i`"}"
  Invoke-RestMethod -Uri "http://localhost:8000/api/register" -Method POST `
    -ContentType "application/json; charset=utf-8" `
    -Body ([Text.Encoding]::UTF8.GetBytes($json))
}
```

**验证**：

```powershell
(Invoke-RestMethod -Uri "http://localhost:8000/api/zones/cs").team_count   # 期望: 4
(Invoke-RestMethod -Uri "http://localhost:8000/api/zones/is").team_count   # 期望: 6
```

---

## 4. 上传 Controller 与槽位管理

### 4.1 准备测试文件

```powershell
Set-Content -Path "test_driver_fast.py" -Encoding utf8 -Value @"
def control(left_img, right_img, timestamp):
    return 0.0, 0.8
"@

Set-Content -Path "test_driver_cautious.py" -Encoding utf8 -Value @"
def control(left_img, right_img, timestamp):
    return 0.0, 0.4
"@
```

### 4.2 上传到不同槽位

```powershell
$fast     = [Convert]::ToBase64String([IO.File]::ReadAllBytes("$PWD	est_driver_fast.py"))
$cautious = [Convert]::ToBase64String([IO.File]::ReadAllBytes("$PWD	est_driver_cautious.py"))

# main 槽位
Invoke-RestMethod -Uri "http://localhost:8000/api/submit" -Method POST `
  -ContentType "application/json" `
  -Body "{`"team_id`":`"cs_team1`",`"password`":`"pass1`",`"code`":`"$fast`",`"slot_name`":`"main`"}"

# dev 槽位
Invoke-RestMethod -Uri "http://localhost:8000/api/submit" -Method POST `
  -ContentType "application/json" `
  -Body "{`"team_id`":`"cs_team1`",`"password`":`"pass1`",`"code`":`"$cautious`",`"slot_name`":`"dev`"}"
```

### 4.3 查询槽位状态

```powershell
$teamCred = [Convert]::ToBase64String([Text.Encoding]::ASCII.GetBytes("cs_team1:pass1"))
Invoke-RestMethod -Uri "http://localhost:8000/api/test-status/cs_team1" `
  -Headers @{ Authorization = "Basic $teamCred" }
```

### 4.4 切换激活槽位

```powershell
Invoke-RestMethod -Uri "http://localhost:8000/api/activate" -Method POST `
  -ContentType "application/json" `
  -Body '{"team_id":"cs_team1","password":"pass1","slot_name":"dev"}'
```

---

## 5. Admin 比赛控制

先为其余队伍批量上传 controller：

```powershell
$base = [Convert]::ToBase64String([IO.File]::ReadAllBytes("$PWD	est_driver_fast.py"))
foreach ($i in 2..4) {
  Invoke-RestMethod -Uri "http://localhost:8000/api/submit" -Method POST `
    -ContentType "application/json" `
    -Body "{`"team_id`":`"cs_team$i`",`"password`":`"pass$i`",`"code`":`"$base`",`"slot_name`":`"main`"}" | Out-Null
}
```

### 5.1 设置并启动 cs 赛区排位赛

**方式一：Admin 控制台 UI**

选择 `cs` 赛区 -> 比赛控制 -> 设置场次 -> 选择 `placement` -> 开始比赛。

**方式二：API**

```powershell
# 设置场次
Invoke-RestMethod -Uri "http://localhost:8000/api/admin/zones/cs/set-session" `
  -Method POST -Headers @{ Authorization = "Basic $cred" } `
  -ContentType "application/json" `
  -Body '{"session_type":"placement","session_id":"cs_p1","team_ids":["cs_team1","cs_team2","cs_team3","cs_team4"],"total_laps":2}'

# 启动
Invoke-RestMethod -Uri "http://localhost:8000/api/admin/zones/cs/start-race" `
  -Method POST -Headers @{ Authorization = "Basic $cred" }
```

**验证**：Admin 控制台状态变为 `PLACEMENT_RUNNING`，车辆实时数据通过 WebSocket 推送。

### 5.2 停止与重置

```powershell
# 强制停止
Invoke-RestMethod -Uri "http://localhost:8000/api/admin/zones/cs/stop-race" `
  -Method POST -Headers @{ Authorization = "Basic $cred" }

# 重置赛区
Invoke-RestMethod -Uri "http://localhost:8000/api/admin/zones/cs/reset" `
  -Method POST -Headers @{ Authorization = "Basic $cred" }
```

### 5.3 推进赛程

当一场比赛正常结束后，调用 finalize 自动计算下一阶段对阵：

```powershell
Invoke-RestMethod -Uri "http://localhost:8000/api/admin/zones/cs/finalize" `
  -Method POST -Headers @{ Authorization = "Basic $cred" }
```

此操作会：
1. 将状态机推进到下一阶段（如 `PLACEMENT_DONE`）
2. 根据 bracket 计算对阵
3. 预创建所有下阶段的 `waiting` 场次
4. 回到 `IDLE`，等待管理员再次点击"开始比赛"

---

## 6. 多赛区并发验证

为 is 赛区批量上传并启动：

```powershell
$base = [Convert]::ToBase64String([IO.File]::ReadAllBytes("$PWD	est_driver_fast.py"))
foreach ($i in 1..6) {
  Invoke-RestMethod -Uri "http://localhost:8000/api/submit" -Method POST `
    -ContentType "application/json" `
    -Body "{`"team_id`":`"is_team$i`",`"password`":`"pass$i`",`"code`":`"$base`",`"slot_name`":`"main`"}" | Out-Null
}

Invoke-RestMethod -Uri "http://localhost:8000/api/admin/zones/is/set-session" `
  -Method POST -Headers @{ Authorization = "Basic $cred" } `
  -ContentType "application/json" `
  -Body '{"session_type":"placement","session_id":"is_p1","team_ids":["is_team1","is_team2","is_team3","is_team4"],"total_laps":2}'

Invoke-RestMethod -Uri "http://localhost:8000/api/admin/zones/is/start-race" `
  -Method POST -Headers @{ Authorization = "Basic $cred" }
```

**验证隔离性**：
- 浏览器开发者工具 -> WS `/ws/admin`：切换 `cs` / `is` 赛区，`sim_time` 独立更新
- 停止 `cs` 后，`is` 继续运行，互不干扰

---

## 7. 赛制自适应验证

查询自动计算的 bracket：

```powershell
Invoke-RestMethod -Uri "http://localhost:8000/api/admin/zones/cs/bracket" `
  -Headers @{ Authorization = "Basic $cred" }

Invoke-RestMethod -Uri "http://localhost:8000/api/admin/zones/is/bracket" `
  -Headers @{ Authorization = "Basic $cred" }
```

| 赛区队伍数 | 期望 stages |
|-----------|-------------|
| <= 4       | `placement -> final` |
| 5-8       | `placement -> semi -> final` |
| >= 9       | `placement -> group_stage -> semi -> final` |

Python 快速验证：

```powershell
python -c "
from server.race.bracket import compute_bracket
for n in [2, 4, 6, 8, 12, 16, 20, 24]:
    b = compute_bracket(n)
    print(f'n={n:>2}: stages={b['stages']}')
    print(f'       sessions={b['sessions_per_stage']}')
    print(f'       advancement={b['advancement']}')
"
```

---

## 8. 测试赛事（用户自主发起）

参赛同学可通过前端 `/testrace/` 或 API 自主发起 2~4 队测试赛。

> **注意**：每场仿真最多支持 4 辆车同时运行（由 `bracket.py` 的 `CARS` 配置决定）。发起时建议邀请 1~3 名对手（含自己共 2~4 队）。

```powershell
# 以 cs_team1 身份发起，邀请 cs_team2、cs_team3
Invoke-RestMethod -Uri "http://localhost:8000/api/races" -Method POST `
  -ContentType "application/json" `
  -Body '{
    "team_id":"cs_team1",
    "password":"pass1",
    "world":"complex",
    "total_laps":3,
    "opponents":["cs_team2","cs_team3"],
    "name":"三队对抗测试"
  }'

# 查询状态
Invoke-RestMethod -Uri "http://localhost:8000/api/races/{race_id}"

# 查询历史
Invoke-RestMethod -Uri "http://localhost:8000/api/races?team_id=cs_team1&limit=10"
```

---

## 9. 积分榜与录像

### 积分榜

```powershell
Invoke-RestMethod -Uri "http://localhost:8000/api/admin/zones/cs/standings" `
  -Headers @{ Authorization = "Basic $cred" }
```

公开页面：`http://localhost:8000/zone/?id=cs`

### 录像

```powershell
Invoke-RestMethod -Uri "http://localhost:8000/api/recordings" `
  -Headers @{ Authorization = "Basic $cred" }
```

回放页面：`http://localhost:8000/race/`

---

## 10. 常见问题

### Q: 中文名称乱码
**A:** PowerShell 含中文 Body 必须：
```powershell
-ContentType "application/json; charset=utf-8" `
-Body ([Text.Encoding]::UTF8.GetBytes('{"name":"中文"}'))
```

### Q: 启动后端报 `zone_id column already exists`
**A:** 正常现象。`models.py` 的迁移脚本对已有列执行 `ALTER TABLE` 会静默跳过。

### Q: 并发启动报 `已达到最大并发仿真数`
**A:** SimNode 默认 `MAX_CONCURRENT_RACES = 4`。可在 `simnode/config/config.yaml` 中调大。

### Q: `set-session` 后提示某队伍没有可用 controller
**A:** 需先通过 `POST /api/submit` 上传代码。系统优先使用 `is_race_active=1` 的槽位，无则回退到 `main` 最新版本。

### Q: `Invoke-RestMethod` 报 `Unable to connect`
**A:** 确认后端 `:8000` 与 SimNode `:5000` 均已启动，且防火墙未拦截。

### Q: 前端首页赛区卡片为空
**A:** 确认 `GET /api/zones` 返回非空，并硬刷新页面（Ctrl+Shift+R）。

---

*文档维护：与系统代码同步更新。*
