"""准备可变输入YuNet；仅下载公开模型，不读取面部模板。"""
import hashlib
from pathlib import Path
import urllib.request

from onnx_yunet import MODEL_NAME, MODEL_SHA256, MODEL_URL


def prepare_model(folder):
    target = Path(folder)/MODEL_NAME
    if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest() == MODEL_SHA256:
        return target
    with urllib.request.urlopen(MODEL_URL,timeout=30) as response:
        data = response.read()
    if hashlib.sha256(data).hexdigest() != MODEL_SHA256:
        raise ValueError('Downloaded YuNet checksum mismatch')
    target.parent.mkdir(parents=True,exist_ok=True)
    temporary = target.with_suffix('.onnx.tmp')
    try:
        temporary.write_bytes(data)
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
    return target


if __name__ == '__main__':
    print(prepare_model(Path(__file__).resolve().parent/'models'))
