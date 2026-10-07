from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules

root = Path(SPECPATH).parent
desktop = root/'视界盾桌面防护'
camera = root/'视界盾开发'
models = [
    (camera/'models/face_detection_yunet_2023mar.onnx', '视界盾开发/models'),
    (camera/'models/face_detection_yunet_2026may.onnx', '视界盾开发/models'),
    (camera/'models/face_recognition_sface_2021dec.onnx', '视界盾开发/models'),
]
for name in ('ch_PP-OCRv4_det_infer.onnx', 'ch_PP-OCRv4_rec_infer.onnx', 'ch_ppocr_mobile_v2.0_cls_infer.onnx'):
    models.append((desktop/'models/rapid_onnx'/name, '视界盾桌面防护/models/rapid_onnx'))
for source, _ in models:
    if not source.is_file():
        raise FileNotFoundError('Missing public model: '+str(source))

data = [(str(path), target) for path, target in models]
data.append((str(root/'packaging/YuNet-LICENSE.txt'), 'licenses'))
data += collect_data_files('rapidocr_onnxruntime', excludes=['models/*'])
data += collect_data_files('uiautomation')
data += collect_data_files('comtypes', include_py_files=True)
hidden = ['guard_service', 'app_shell', 'desktop_guard', 'camera_worker', 'owner_enrollment', 'face_detection', 'onnx_yunet',
          'fast_ocr', 'gpu_blur', 'native_text', 'package_check', 'identity_test', 'camera_test',
          'owner_tracking', 'identity_state', 'identity_sender', 'owner_presence', 'app_scope', 'scope_picker',
          'region_tracker', 'region_features', 'region_anchor', 'region_worker']
hidden += collect_submodules('rapidocr_onnxruntime')
hidden += collect_submodules('comtypes', filter=lambda name: not name.startswith('comtypes.test'))

a = Analysis([str(root/'VisionShield.py')], pathex=[str(root), str(desktop), str(camera)],
             binaries=collect_dynamic_libs('onnxruntime'), datas=data, hiddenimports=hidden,
             excludes=['paddle', 'paddleocr', 'paddlex', 'torch', 'tensorflow', 'mediapipe',
                       'matplotlib', 'scipy', 'pandas', 'PySide6.QtWebEngineCore',
                       'PySide6.QtWebEngineWidgets', 'PySide6.QtQml', 'PySide6.QtQuick',
                       'PySide6.QtPdf', 'PySide6.QtVirtualKeyboard'],
             noarchive=False)
# Qt 6.11使用Windows原生ICU接口，不能被其他工具的同名ICU DLL覆盖。
# OpenCL.dll and vendor drivers belong to Windows/the installed display driver.
# Never redistribute an accidentally discovered host OpenCL loader with the app.
a.binaries = [entry for entry in a.binaries if Path(entry[0]).name.lower() not in ('icuuc.dll', 'icuin.dll', 'icu.dll', 'opencl.dll')
              and not ('opencv_videoio_ffmpeg' in entry[0] and '4100' not in entry[0])]
# The widget-based application does not use PDF/QML or the optional Qt virtual
# keyboard. Plugin collection can otherwise pull these modules in indirectly.
unused_qt = {'qt6pdf.dll', 'qt6virtualkeyboard.dll', 'qpdf.dll', 'qtvirtualkeyboardplugin.dll'}
a.binaries = [entry for entry in a.binaries if Path(entry[0]).name.lower() not in unused_qt
              and not Path(entry[0]).name.lower().startswith(('qt6qml', 'qt6quick', 'opencv_videoio_ffmpeg'))]
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='VisionShield',
          debug=False, strip=False, upx=False, console=False,
          disable_windowed_traceback=True)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='VisionShield')
