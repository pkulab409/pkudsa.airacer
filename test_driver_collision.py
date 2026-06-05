"""
碰撞罚停测试控制器（前车）—— 周期性倒车撞后车。
用法：前车提交此文件，后车提交 test_driver_still.py（静止不动）。

行为：每 ~14s 一个循环（前 4s 前进，后 10s 倒车撞后车）
"""
_frame = 0


def control(img_front, img_rear, speed):
    global _frame
    _frame += 1

    # 假设 timestep ≈ 32ms，约 125 帧 = 4s，约 438 帧 = 14s
    cycle = _frame % 438

    steering = 0.0


    target_speed = -1  # 倒车撞后车

    return steering, target_speed
