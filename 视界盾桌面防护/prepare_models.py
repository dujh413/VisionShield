from pathlib import Path
from ocr_worker import prepare

if __name__ == '__main__':
    prepare(Path(__file__).resolve().parent)
    print('OCR模型已复制到本项目models目录。后续运行使用本地路径。')
