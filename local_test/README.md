本地测试方法：
1.确保已安装python和webots，
2.找到webotsw.exe和此文件夹中的standalone_run.py的绝对路径，
3.在终端输入：
python standalone_run.py的绝对路径 --webots "webots.exe的绝对路径"
示例：python D:\local_test\standalone_run.py --webots "D:\Webots\webotsw.exe"

注：请在team_controller.py中修改小车的运行逻辑