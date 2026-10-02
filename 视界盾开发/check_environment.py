"""A 的环境检查；不读取摄像头，也不下载模型。"""
import importlib
import json
from pathlib import Path
import platform
import sys


def main():
    root = Path(__file__).resolve().parent
    result = {
        "python": sys.version,
        "executable": sys.executable,
        "platform": platform.platform(),
        "virtual_environment": sys.prefix != sys.base_prefix,
        "packages": {},
        "model_exists": (root / "models" / "face_landmarker.task").is_file(),
    }
    failed = False
    for name in ("cv2", "mediapipe"):
        try:
            module = importlib.import_module(name)
            result["packages"][name] = {"version": module.__version__, "import": "OK"}
        except Exception as error:
            result["packages"][name] = {"import": "FAILED", "error": str(error)}
            failed = True
    if not result["virtual_environment"]:
        print("注意：当前不是项目虚拟环境。请使用 .venv\\Scripts\\python.exe。")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    records = root / "records"
    records.mkdir(exist_ok=True)
    (records / "environment.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
