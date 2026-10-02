import hashlib
import json
from pathlib import Path
import shutil
import rapidocr_onnxruntime


if __name__=='__main__':
    source=Path(rapidocr_onnxruntime.__file__).resolve().parent/'models'
    target=Path(__file__).resolve().parent/'models/rapid_onnx'
    target.mkdir(parents=True,exist_ok=True)
    manifest={}
    for file in source.glob('*.onnx'):
        shutil.copy2(file,target/file.name)
        manifest[file.name]=hashlib.sha256(file.read_bytes()).hexdigest()
    (target/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    print('Prepared local ONNX model files:',len(manifest))
