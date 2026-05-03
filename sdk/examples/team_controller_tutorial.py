"""
team_controller_tutorial.py — AI Racer 循线控制器教学版

目标读者：AI Racer 参赛学生（已有 Python 基础，没用过 Webots / OpenCV）。
本文件展示"最小可用"的循线赛车逻辑，共约 120 行，注释占一半以上。
复制一份到你自己的工程，改参数、改算法即可开始比赛。

────────────────────────────────────────────────────────────────────
接口契约（线上沙箱强约束，不要改签名）

    def control(left_img, right_img, timestamp) -> tuple[float, float]:
        ...

    left_img, right_img : np.ndarray, shape=(480, 640, 3), dtype=uint8, BGR
    timestamp           : float，当前仿真时间（秒）
    返回 (steering, speed)
        steering ∈ [-1.0, 1.0]   负=左  正=右
        speed    ∈ [ 0.0, 1.0]   0=停  1=全速

执行限制：单帧 20ms 上限，超时 3 次 → 本圈作废。
────────────────────────────────────────────────────────────────────

设计思路
========
1) 只用左摄像头做循线（右摄像头学生可自行拓展：立体匹配估测距离、侦测对手车等）
2) 图像 → 灰度 → 取图像下半部（道路区域） → 行扫描找赛道中心 x
3) 误差 = (道路中心 x - 图像中心 x) / (图像宽/2) ∈ [-1, 1]
4) PID 控制：把误差映射为 steering
5) 转向越大 → 速度越低，避免甩尾
"""

from __future__ import annotations

import numpy as np

# ═══════════════════════════════════════════════════════════════════
# ❶ 可调参数区 —— 学生主要改这里
# ═══════════════════════════════════════════════════════════════════

IMG_H, IMG_W = 480, 640          # 画幅，由 Webots 固定
ROI_TOP_RATIO = 0.55             # 行扫描起点（从画面顶部起算的比例）
ROI_BOT_RATIO = 0.95             # 行扫描终点；下半 40% ≈ 近景赛道

# 赛道相对地面偏暗 → 用"低于阈值"的像素代表赛道。根据赛道实际颜色微调。
TRACK_THRESHOLD = 80             # 灰度阈值，0-255

# PID 系数：先只调 Kp，再微调 Kd；Ki 容易积分饱和，慎用
KP = 0.9
KI = 0.0
KD = 0.25

# 速度策略
BASE_SPEED = 0.75                # 直道目标速度
MIN_SPEED = 0.30                 # 急弯下限
SPEED_TURN_PENALTY = 0.8         # steering 幅度对速度的折扣系数

# 安全策略
LOST_TRACK_SPEED = 0.15          # 找不到赛道时的保守速度
STEERING_CLAMP = 1.0             # 转向硬上限（接口要求 [-1, 1]）

# ═══════════════════════════════════════════════════════════════════
# ❷ 控制器内部状态（用函数属性保存，避免 global）
# ═══════════════════════════════════════════════════════════════════

_state = {
    "prev_error": 0.0,
    "integral":   0.0,
    "prev_t":     None,
}


# ═══════════════════════════════════════════════════════════════════
# ❸ 视觉处理：估计赛道中心 x（返回 None 代表丢线）
# ═══════════════════════════════════════════════════════════════════

def _estimate_track_center_x(bgr: np.ndarray) -> float | None:
    """对 BGR 图做行扫描，返回近景赛道中心的 x 坐标（0..IMG_W-1）。"""
    # 1) 灰度：平均三通道比 cv2.cvtColor 更便携
    gray = bgr.mean(axis=2)

    # 2) 只看画面下半的 ROI（赛道近处），远处反光/天空干扰大
    y0 = int(IMG_H * ROI_TOP_RATIO)
    y1 = int(IMG_H * ROI_BOT_RATIO)
    roi = gray[y0:y1]

    # 3) 低于阈值的像素视作"赛道"。布尔掩码求 x 坐标的重心
    mask = roi < TRACK_THRESHOLD
    total = mask.sum()
    if total < 20:                # 太少像素 → 丢线
        return None

    # 每列被命中的行数（x 方向）
    col_hits = mask.sum(axis=0)   # shape=(IMG_W,)
    xs = np.arange(IMG_W)
    cx = float((xs * col_hits).sum() / col_hits.sum())
    return cx


# ═══════════════════════════════════════════════════════════════════
# ❹ 主接口 control()
# ═══════════════════════════════════════════════════════════════════

def control(left_img: np.ndarray,
            right_img: np.ndarray,
            timestamp: float) -> tuple[float, float]:
    """返回 (steering, speed)。遵循沙箱接口，不做任何 I/O。"""

    # ---- 1. 估计赛道中心 ----
    cx = _estimate_track_center_x(left_img)

    if cx is None:
        # 丢线：沿用上一帧转向、以极低速前行，等重新看到赛道
        return float(np.clip(_state["prev_error"] * KP, -1.0, 1.0)), LOST_TRACK_SPEED

    # ---- 2. 误差归一化到 [-1, 1] ----
    #        负 = 赛道在图像左侧 → 应该左转；正则右转
    error = (cx - IMG_W / 2) / (IMG_W / 2)

    # ---- 3. PID ----
    prev_t = _state["prev_t"]
    dt = 0.032 if prev_t is None else max(1e-3, timestamp - prev_t)
    derivative = (error - _state["prev_error"]) / dt
    _state["integral"] += error * dt
    # 积分抗饱和
    _state["integral"] = float(np.clip(_state["integral"], -1.0, 1.0))

    steering_raw = KP * error + KI * _state["integral"] + KD * derivative
    steering = float(np.clip(steering_raw, -STEERING_CLAMP, STEERING_CLAMP))

    # ---- 4. 速度：转向越大越慢 ----
    speed = BASE_SPEED * (1.0 - SPEED_TURN_PENALTY * abs(steering))
    speed = float(np.clip(speed, MIN_SPEED, 1.0))

    # ---- 5. 更新状态 ----
    _state["prev_error"] = error
    _state["prev_t"] = timestamp

    return steering, speed


# ═══════════════════════════════════════════════════════════════════
# ❺ 本地冒烟自测：`python team_controller_tutorial.py`
#    （提交到服务器时这段不会被执行，留着方便本机调试）
# ═══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    # 黑图（代表看不到赛道）：预期丢线，输出保守速度
    blank = np.zeros((IMG_H, IMG_W, 3), dtype=np.uint8)
    print("blank      →", control(blank, blank, 0.0))

    # 左侧带一条黑色"赛道"：中心应偏左 → 输出负向 steering（左转）
    img = np.full((IMG_H, IMG_W, 3), 200, dtype=np.uint8)
    img[:, 100:180, :] = 20
    print("left lane  →", control(img, img, 0.032))

    # 右侧黑条 → 正向 steering
    img = np.full((IMG_H, IMG_W, 3), 200, dtype=np.uint8)
    img[:, 460:540, :] = 20
    print("right lane →", control(img, img, 0.064))
