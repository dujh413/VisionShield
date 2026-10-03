import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
import sys
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from PySide6.QtCore import QObject, QSettings, QTimer, Signal
from PySide6.QtWidgets import QApplication, QCheckBox, QDialog, QDialogButtonBox
from app_shell import Shell


class FakeBackend(QObject):
    changed = Signal(str, str)
    stopped = Signal()

    def __init__(self):
        super().__init__()
        self.starts = self.stops = 0

    def start(self):
        self.starts += 1

    def stop(self):
        self.stops += 1
        self.stopped.emit()


class ShellTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.path = str(Path(self.folder.name)/'settings.ini')
        self.settings = QSettings(self.path, QSettings.IniFormat)
        self.backend = FakeBackend()
        self.panel = Shell(self.settings, self.backend, tray_available=False)

    def tearDown(self):
        self.panel.tray.hide()
        self.panel.hide()
        self.panel.deleteLater()
        self.app.processEvents()
        self.folder.cleanup()

    def test_idle_does_not_load_models(self):
        self.assertEqual(self.backend.starts, 0)
        self.assertEqual(self.panel.state, 'paused')
        # 其他测试会导入NumPy；以全新解释器检查前端自身的导入边界。
        code = "import sys, app_shell; print(any(m in sys.modules for m in ('desktop_guard','ocr_worker','cv2','numpy')))"
        result = subprocess.check_output([sys.executable, '-c', code], cwd=Path(__file__).resolve().parent)
        self.assertEqual(result.strip(), b'False')

    def test_start_pause_and_late_status(self):
        with patch('overlay_window.exclude_capture'):
            self.panel.toggle_guard()
        self.assertEqual(self.backend.starts, 1)
        self.assertEqual(self.panel.state, 'starting')
        self.assertFalse(self.panel.toggle.isEnabled())
        self.backend.changed.emit('running', '测试状态')
        self.assertEqual(self.panel.state, 'running')
        # 停止完成前的迟到结果不得重新启用前端。
        self.backend.stop = lambda: None
        self.panel.toggle_guard()
        self.backend.changed.emit('running', '迟到状态')
        self.assertEqual(self.panel.state, 'stopping')
        self.backend.stopped.emit()
        self.assertEqual(self.panel.state, 'paused')

    def test_error_requires_stop_before_retry(self):
        self.backend.changed.emit('error', '异常')
        self.assertEqual(self.panel.state, 'error')
        self.panel.toggle_guard()
        self.assertEqual(self.backend.stops, 1)
        self.assertEqual(self.panel.state, 'paused')

    def test_preview_never_starts_backend(self):
        self.panel.preview = True
        self.panel.toggle_guard()
        self.assertEqual(self.backend.starts, 0)
        self.assertEqual(self.panel.state, 'paused')

    def test_close_hides_without_stopping_when_tray_exists(self):
        self.panel.has_tray = True
        self.panel.show()
        self.panel.close()
        self.assertFalse(self.panel.isVisible())
        self.assertEqual(self.backend.stops, 0)
        self.panel.show_panel()
        self.assertTrue(self.panel.isVisible())

    def test_no_tray_close_stops_before_quit(self):
        with patch.object(self.app, 'quit') as quit_app:
            self.panel.show()
            self.panel.close()
            self.assertEqual(self.backend.stops, 1)
            quit_app.assert_called_once()

    def test_settings_saved_and_cancel_does_not_overwrite(self):
        def save_dialog():
            dialog = self.app.activeModalWidget()
            for checkbox in dialog.findChildren(QCheckBox):
                checkbox.setChecked(True)
            dialog.accept()
        QTimer.singleShot(0, save_dialog)
        self.panel.open_settings()
        reopened = QSettings(self.path, QSettings.IniFormat)
        self.assertTrue(reopened.value('auto_enable', False, type=bool))
        self.assertTrue(reopened.value('start_hidden', False, type=bool))
        def cancel_dialog():
            dialog = self.app.activeModalWidget()
            for checkbox in dialog.findChildren(QCheckBox):
                checkbox.setChecked(False)
            dialog.reject()
        QTimer.singleShot(0, cancel_dialog)
        self.panel.open_settings()
        reopened.sync()
        self.assertTrue(reopened.value('auto_enable', False, type=bool))


if __name__ == '__main__':
    unittest.main()
