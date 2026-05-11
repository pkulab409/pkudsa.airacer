# Tesla Controller

`tesla_controller.py` 是给 `TeslaModel3` 节点使用的控制器脚本，读取 `left_camera` 和 `right_camera`，用 OpenCV 做车道线识别，并输出速度、转向与转向灯。

## 使用方式

1. 在 Webots 中将 Tesla 车辆的 controller 设置为 `tesla_controller`。
2. 确保车辆节点包含名为 `left_camera` 与 `right_camera` 的相机设备。
3. 运行仿真即可。

## 本地小测试

`tesla_controller_demo.py` 会生成简单的车道线图像，快速验证转向与速度策略。

## 常见问题

- **看不到车道线/不转向**：确认相机名称与脚本中的一致，且相机已启用。
- **转向灯无效**：TeslaModel3 未暴露指示灯设备时会忽略转向灯输出，不影响行驶。
- **缺少 OpenCV**：请安装 `opencv-python`（或无 GUI 环境使用 `opencv-python-headless`）。
