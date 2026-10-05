import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
import sys
import subprocess
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from PySide6.QtCore import QObject, QProcess, QSettings, QTimer, Signal
from PySide6.QtWidgets import QApplication, QCheckBox, QDialog, QDialogButtonBox, QPushButton
from app_shell import Shell, Backend


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
        code = "import sys, app_shell; print(any(m in sys.modules for m in ('desktop_guard','ocr_worker','cv2','numpy','gpu_blur')))"
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

    def test_effect_text_is_committed_only_when_enabling_and_saved_for_restart(self):
        self.panel.effect_input.setText('８')
        self.assertFalse(hasattr(self.backend, 'effect_text'))
        with patch('overlay_window.exclude_capture'):
            self.panel.toggle_guard()
        self.assertEqual(self.backend.effect_text, '８')
        self.panel.effect_input.setText('遮挡')
        self.panel.effect_checks['shield_enabled'].setChecked(False)
        self.assertEqual(self.backend.effect_text, '８')
        self.backend.changed.emit('running', '虚构状态')
        self.panel.toggle_guard()
        with patch('overlay_window.exclude_capture'):
            self.panel.toggle_guard()
        self.assertEqual(self.backend.effect_text, '遮挡')
        reopened=QSettings(self.path,QSettings.IniFormat)
        self.assertEqual(reopened.value('effect_text'), '遮挡')

    def test_empty_committed_mode_reports_detection_only(self):
        self.panel.effect_input.setText('  ')
        with patch('overlay_window.exclude_capture'):
            self.panel.toggle_guard()
        self.backend.changed.emit('running', '虚构状态')
        self.assertIn('不遮蔽', self.panel.status.text())
        self.assertEqual(self.backend.effect_text, '  ')

    def test_live_preferences_do_not_send_uncommitted_edits(self):
        backend=Backend()
        backend.peer=Mock()
        backend.effect_text='12'
        backend.send_preferences()
        packet=json.loads(backend.peer.write.call_args.args[0])
        self.assertEqual(packet['effect_text'],'12')
        self.assertIn('app_profiles',packet)

    def test_service_status_delivers_reminder_and_stopping_ignores_it(self):
        backend=Backend()
        alerts=[];updates=[]
        backend.alerted.connect(alerts.append)
        backend.updated.connect(updates.append)
        data={'state':'running','detail':'测试保护状态','alert':'测试隐私提醒','protecting':True}
        encoded=('VISION_SHIELD:'+json.dumps(data)+'\n').encode()
        with patch.object(backend.process,'readAllStandardOutput',return_value=encoded):
            backend.read_status()
            backend.stopping=True
            backend.read_status()
        self.assertEqual(alerts,['测试隐私提醒'])
        self.assertEqual(updates,[data])

    def test_reminder_uses_tray_and_sound(self):
        self.panel.has_tray=True
        with patch.object(self.panel.tray,'showMessage') as toast,patch('app_shell.QApplication') as application:
            self.panel.remind_owner('虚构测试风险')
            toast.assert_called_once()
            application.beep.assert_called_once()

    def test_reminder_choices_are_independent(self):
        self.panel.has_tray = True
        for sound in (False, True):
            for popup in (False, True):
                self.settings.setValue('sound_enabled', sound)
                self.settings.setValue('popup_enabled', popup)
                with patch.object(self.panel.tray, 'showMessage') as toast, patch('app_shell.QApplication.beep') as beep:
                    self.panel.remind_owner('虚构风险')
                    self.assertEqual(beep.call_count, int(sound))
                    self.assertEqual(toast.call_count, int(popup))

    def test_popup_without_tray_is_nonmodal_and_reused(self):
        self.settings.setValue('sound_enabled', False)
        self.panel.remind_owner('第一次虚构风险')
        popup = self.panel.reminder
        self.assertTrue(popup.isVisible())
        self.assertFalse(popup.isModal())
        self.panel.remind_owner('第二次虚构风险')
        self.assertIs(self.panel.reminder, popup)
        self.assertEqual(self.panel.reminder_text.text(), '第二次虚构风险')
        popup.hide()

    def test_effect_settings_persist_and_apply_next_session(self):
        def save_dialog():
            dialog = self.app.activeModalWidget()
            for name in ('shield_enabled', 'sound_enabled', 'popup_enabled'):
                dialog.findChild(QCheckBox, name).setChecked(False)
            dialog.accept()
        QTimer.singleShot(0, save_dialog)
        self.panel.open_settings()
        reopened = QSettings(self.path, QSettings.IniFormat)
        for name in ('shield_enabled', 'sound_enabled', 'popup_enabled'):
            self.assertFalse(reopened.value(name, True, type=bool))
        with patch('overlay_window.exclude_capture'):
            self.panel.toggle_guard()
        self.assertFalse(self.backend.shield_enabled)
        self.backend.changed.emit('running', '仅检测')
        self.assertIn('不遮蔽', self.panel.status.text())

    def test_backend_launch_transmits_shield_choice(self):
        backend = Backend()
        backend.shield_enabled = False
        backend.effect_text = '８'
        with patch('process_lifetime.ProcessJob'), patch.object(backend.server, 'listen', return_value=True), patch.object(backend.process, 'start'):
            backend.start()
        self.assertEqual(backend.process.processEnvironment().value('VISION_SHIELD_SHIELD_ENABLED'), '0')
        self.assertEqual(backend.process.processEnvironment().value('VISION_SHIELD_EFFECT_TEXT'), '８')
        backend.watchdog.stop()
        backend.finished(0, QProcess.NormalExit)

    def test_malformed_service_status_is_ignored(self):
        backend=Backend();updates=[]
        backend.updated.connect(updates.append)
        for data in ([],None,{}, {'state':'unknown','detail':'x'}, {'state':'running','detail':None}):
            encoded=('VISION_SHIELD:'+json.dumps(data)+'\n').encode()
            with patch.object(backend.process,'readAllStandardOutput',return_value=encoded):
                backend.read_status()
        self.assertFalse(updates)

    def test_service_timeout_kills_process_tree(self):
        backend=Backend();backend.job=Mock()
        with patch.object(backend.process,'kill') as kill:
            backend.timed_out()
            backend.job.close.assert_called_once()
            kill.assert_called_once()
        self.assertIn('启动超时',backend.failure_detail)

    def test_stop_before_service_connects_has_timeout(self):
        backend=Backend()
        with patch.object(backend.process,'state',return_value=QProcess.Starting):
            backend.stop()
        self.assertTrue(backend.watchdog.isActive())
        backend.watchdog.stop()

    def test_finished_closes_job_even_after_unexpected_exit(self):
        backend=Backend();job=Mock();backend.job=job
        backend.finished(1,QProcess.CrashExit)
        job.close.assert_called_once()
        self.assertIsNone(backend.job)

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

    def test_registration_does_not_silently_save_settings(self):
        def register_dialog():
            dialog=self.app.activeModalWidget()
            for checkbox in dialog.findChildren(QCheckBox):
                checkbox.setChecked(True)
            for button in dialog.findChildren(QPushButton):
                if button.text()=='登记 / 更新机主':
                    button.click();break
        QTimer.singleShot(0,register_dialog)
        with patch.object(self.panel,'register_owner') as register:
            self.panel.open_settings()
            register.assert_called_once()
        self.assertFalse(self.settings.value('auto_enable',False,type=bool))


if __name__ == '__main__':
    unittest.main()
