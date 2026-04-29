# team_controller.py — 官方默认模板（直行算法，用于无提交队伍）
import numpy as np

def control(left_img: np.ndarray,
            right_img: np.ndarray,
            timestamp: float) -> tuple[float, float]:
    """
    参数：
        left_img:  左目图像，shape=(480, 640, 3)，dtype=uint8，BGR 通道顺序
        right_img: 右目图像，shape=(480, 640, 3)，dtype=uint8，BGR 通道顺序
        timestamp: 仿真时间（秒），只读

    返回值：
        steering: float，范围 [-1.0, 1.0]，负值左转，正值右转
        speed:    float，范围 [0.0, 1.0]，0.0 停止，1.0 最大速度

    每次调用时限：20ms
    """
    steering = 0.0
    speed = 0.5
    return steering, speed
