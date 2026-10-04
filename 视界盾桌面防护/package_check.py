"""显式--package-check验收模式；虚构OCR样本，不登记机主。"""
import json
from pathlib import Path
import sys
import tempfile
import time


def main():
    destination = Path(sys.argv[sys.argv.index('--package-check')+1]).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    from PySide6.QtCore import QProcess, QSettings, QTimer
    from PySide6.QtWidgets import QApplication
    from app_shell import Backend, Shell
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    result = {'frozen': bool(getattr(sys, 'frozen', False)), 'checks': {}}
    checks = result['checks']
    checks['light_frontend'] = not any(name in sys.modules for name in ('cv2', 'numpy', 'desktop_guard', 'ocr_worker'))
    backend = Backend()
    backend.shield_enabled = False
    cycles = 0
    ready_at = None
    stopping = False
    deadline = time.monotonic()+90
    temp = tempfile.TemporaryDirectory()
    settings = QSettings(str(Path(temp.name)/'settings.ini'), QSettings.IniFormat)
    settings.setValue('sound_enabled', False)
    settings.setValue('popup_enabled', False)
    panel = Shell(settings=settings, backend=backend, preview=True, tray_available=False)
    panel.show()

    def updated(value):
        nonlocal ready_at
        checks['local_status_channel'] = True
        if value['state'] == 'error':
            result['service_error'] = value['detail']
        if ('OCR：已就绪' in value['detail'] and value.get('faces_count') is not None
                and value['state'] == 'running'):
            checks['camera_and_ocr_parallel'] = True
            checks['mask_disabled'] = not value['protecting'] and not value['full_mask']
            if ready_at is None:
                ready_at = time.monotonic()

    def stopped():
        nonlocal cycles, stopping, ready_at
        cycles += 1
        checks['clean_stop'] = backend.job is None and backend.process.state() == QProcess.NotRunning
        if cycles == 1 and ready_at is not None and not result.get('service_error'):
            stopping, ready_at = False, None
            QTimer.singleShot(0, backend.start)
        else:
            checks['two_start_stop_cycles'] = cycles == 2 and ready_at is not None
            app.quit()

    def tick():
        nonlocal stopping
        if not stopping and ((ready_at is not None and time.monotonic()-ready_at>1)
                             or time.monotonic()>deadline or result.get('service_error')):
            stopping = True
            backend.stop()

    backend.updated.connect(updated)
    # 只统计实际进程退出，避免Qt关窗触发的重复stop通知影响轮次。
    backend.process.finished.connect(lambda *_: stopped())
    timer = QTimer()
    timer.timeout.connect(tick)
    timer.start(100)
    QTimer.singleShot(0, backend.start)
    QTimer.singleShot(110000, app.quit)
    app.exec()
    if backend.process.state() != QProcess.NotRunning:
        backend.stop()
        if not backend.process.waitForFinished(5000):
            backend.timed_out()
            backend.process.waitForFinished(2000)
    timer.stop()
    panel.hide()
    try:
        import cv2
        import numpy as np
        from fast_ocr import FastOCR
        image = np.full((220, 1000, 3), 255, dtype=np.uint8)
        cv2.putText(image, 'Phone: 13600000000', (30, 80), cv2.FONT_HERSHEY_SIMPLEX, 1.3, (0, 0, 0), 2)
        cv2.putText(image, 'Email: demo@example.com', (30, 170), cv2.FONT_HERSHEY_SIMPLEX, 1.1, (0, 0, 0), 2)
        lines = FastOCR(gpu=False).recognize(image)
        from sensitive_rules import detect
        checks['fictional_ocr_and_rules'] = bool(detect(lines))
        from runtime_paths import camera_root, owner_file, records_directory, resource_root
        from identity_test import load_models
        detector, recognizer = load_models(camera_root())
        detector.detect(np.zeros((480, 640, 3), dtype=np.uint8))
        recognizer.feature(np.zeros((112, 112, 3), dtype=np.uint8))
        checks['public_face_models'] = True
        checks['writable_data_outside_bundle'] = not owner_file(camera_root()).is_relative_to(resource_root()) and not records_directory().is_relative_to(resource_root())
        from screen_capture import ScreenCapture
        from overlay_window import OverlayWindow
        from capture_probe import verify_exclusion
        capture = ScreenCapture()
        overlay = OverlayWindow(app.primaryScreen())
        try:
            checks['native_capture_exclusion'] = verify_exclusion(capture, overlay)
        finally:
            overlay.close()
            capture.close()
        from native_text import read_window
        panel.show()
        app.processEvents()
        screen = app.primaryScreen().geometry()
        read_window(int(panel.winId()), {'left':screen.x(), 'top':screen.y(), 'width':screen.width(), 'height':screen.height()})
        checks['native_text_dependencies'] = True
    except Exception:
        import traceback
        result['diagnostic_error'] = traceback.format_exc()
    finally:
        panel.hide()
        temp.cleanup()
        result['completed_cycles'] = cycles
        result['passed'] = len(checks) == 11 and all(checks.values()) and not result.get('service_error') and not result.get('diagnostic_error')
        destination.write_text(json.dumps(result, ensure_ascii=True, indent=2), encoding='utf-8')
    return 0 if result['passed'] else 1
