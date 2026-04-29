import runpy
import pathlib

runpy.run_path(
    str(pathlib.Path(__file__).parent / "car_controller.py"),
    run_name="__main__",
)
