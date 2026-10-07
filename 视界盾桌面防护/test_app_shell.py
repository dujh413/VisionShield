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
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QCheckBox, QDialog, QDialogButtonBox, QLabel, QLineEdit, QPushButton, QScrollArea
from app_shell import Shell, Backend


class FakeBackend(QObject):
    changed = Signal(str, str)
    updated = Signal(dict)
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

    def test_slider_and_mode_apply_live_and_save_for_restart(self):
        self.panel.effect_input.setText('８')
        self.assertFalse(hasattr(self.backend, 'effect_text'))
        with patch('overlay_window.exclude_capture'):
            self.panel.toggle_guard()
        self.assertEqual(self.backend.effect_text, '8')
        self.backend.changed.emit('running', '虚构状态')
        self.backend.send_preferences=Mock()
        self.panel.effect_input.slider.setValue(35)
        QTest.qWait(150)
        self.assertEqual(self.backend.effect_text, '35')
        self.backend.send_preferences.assert_called_once()
        self.panel.effect_input.setText('遮挡')
        QTest.qWait(150)
        self.assertEqual(self.backend.effect_text, '遮挡')
        reopened=QSettings(self.path,QSettings.IniFormat)
        self.assertEqual(reopened.value('effect_text'), '遮挡')
        self.assertFalse(self.panel.findChildren(QLineEdit))

    def test_default_enabled_shield_has_actual_blur_and_off_is_explicit(self):
        with patch('overlay_window.exclude_capture'):
            self.panel.toggle_guard()
        self.backend.changed.emit('running', '虚构状态')
        self.assertEqual(self.backend.effect_text, '24')
        self.assertNotIn('不遮蔽', self.panel.status.text())
        self.panel.effect_checks['shield_enabled'].setChecked(False)
        self.assertIn('不遮蔽', self.panel.status.text())
        self.assertFalse(self.panel.effect_input.slider.isEnabled())
        self.assertFalse(self.panel.effect_input.mode.isEnabled())

    def test_old_empty_effect_migrates_to_blur_without_loading_models(self):
        self.settings.setValue('effect_text','')
        extra=Shell(self.settings,FakeBackend(),tray_available=False)
        try:
            self.assertTrue(extra.effect_checks['shield_enabled'].isChecked())
            self.assertEqual(extra.effect_input.to_text(),'24')
        finally:
            extra.hide();extra.deleteLater();self.app.processEvents()

    def test_main_window_leaves_enough_height_for_slider_and_labels(self):
        self.panel.show();self.app.processEvents()
        self.assertGreaterEqual(self.panel.effect_input.height(),self.panel.effect_input.minimumSizeHint().height())
        self.assertGreater(self.panel.effect_input.slider.width(),100)
        self.assertTrue(self.panel.rect().contains(self.panel.toggle.geometry()))
        self.assertTrue(self.panel.rect().contains(self.panel.scope_summary.geometry()))

    def test_settings_scroll_leaves_save_and_cancel_visible(self):
        def inspect_dialog():
            dialog=self.app.activeModalWidget();self.app.processEvents()
            self.assertLessEqual(dialog.height(),self.panel.screen().availableGeometry().height())
            scroll=dialog.findChild(QScrollArea)
            self.assertIsNotNone(scroll)
            scroll.verticalScrollBar().setValue(scroll.verticalScrollBar().maximum())
            self.app.processEvents()
            buttons=dialog.findChild(QDialogButtonBox)
            for button in buttons.buttons():
                self.assertTrue(button.isVisibleTo(dialog))
                self.assertTrue(dialog.rect().contains(button.mapTo(dialog,button.rect().bottomRight())))
            dialog.reject()
        QTimer.singleShot(0,inspect_dialog)
        self.panel.open_settings()

    def test_status_updates_do_not_repeatedly_raise_control_window(self):
        self.panel.show()
        with patch.object(self.panel,'raise_') as raise_window:
            for _ in range(5):
                self.backend.changed.emit('running','匿名状态')
            raise_window.assert_not_called()

    def test_scope_settings_explain_local_boundaries_and_disable_while_running(self):
        self.panel.state='running'
        descriptions=[]
        buttons=[]
        def inspect_dialog():
            dialog=self.app.activeModalWidget()
            descriptions.extend(label.text() for label in dialog.findChildren(QLabel))
            buttons.extend(dialog.findChild(QPushButton, name)
                           for name in ('selectLocalScope', 'selectWindowScope', 'textAction'))
            descriptions.extend(button.toolTip() for button in buttons)
            self.assertEqual(len(buttons),3)
            self.assertTrue(all(not button.isEnabled() for button in buttons))
            dialog.reject()
        QTimer.singleShot(0,inspect_dialog)
        with patch('overlay_window.exclude_capture') as exclusion:
            self.panel.open_settings()
        exclusion.assert_called_once()
        text='\n'.join(descriptions)
        self.assertIn('其他区域保持清晰',text)
        self.assertIn('暂停该选区遮蔽',text)
        self.assertIn('保护该窗口的全部可见内容',text)

    def test_configured_scope_summary_and_reset_update_immediately(self):
        self.panel.save_profiles({'app':{'mode':'window'}})
        self.assertIn('1 个已选范围',self.panel.scope_summary.text())
        self.assertIn('0 处局部、1 个整窗',self.panel.scope_summary.toolTip())
        self.panel.save_profiles({})
        self.assertIn('自动按应用与内容保护',self.panel.scope_summary.text())

    def test_quitting_immediately_after_slider_change_preserves_latest_choice(self):
        self.panel.effect_input.slider.setValue(61)
        self.assertTrue(self.panel.effect_update_timer.isActive())
        with patch.object(self.app,'quit') as quit_app:
            self.panel.quit_app()
        self.assertFalse(self.panel.effect_update_timer.isActive())
        reopened=QSettings(self.path,QSettings.IniFormat)
        self.assertEqual(reopened.value('effect_text'),'61')
        quit_app.assert_called_once()

    def test_dark_style_preserves_previous_blur_strength_after_restart(self):
        self.panel.effect_input.slider.setValue(53)
        self.panel.effect_input.setText('遮挡')
        self.panel.apply_effect_text()
        reopened=QSettings(self.path,QSettings.IniFormat)
        extra=Shell(reopened,FakeBackend(),tray_available=False)
        try:
            self.assertEqual(extra.effect_input.mode.currentData(),'block')
            extra.effect_input.mode.setCurrentIndex(extra.effect_input.mode.findData('blur'))
            self.assertEqual(extra.effect_input.to_text(),'53')
        finally:
            extra.hide();extra.deleteLater();self.app.processEvents()

    def test_saved_radius_does_not_override_legacy_numeric_effect(self):
        self.settings.setValue('effect_text','８')
        self.settings.setValue('blur_radius',53)
        extra=Shell(self.settings,FakeBackend(),tray_available=False)
        try:self.assertEqual(extra.effect_input.to_text(),'8')
        finally:extra.hide();extra.deleteLater();self.app.processEvents()

    def test_scope_buttons_save_pending_form_before_leaving_settings(self):
        for prefix,whole in (('selectLocalScope',False),('selectWindowScope',True)):
            with self.subTest(prefix=prefix):
                self.settings.setValue('shield_enabled',True)
                self.settings.setValue('auto_enable',False)
                def choose_dialog():
                    dialog=self.app.activeModalWidget()
                    dialog.findChild(QCheckBox,'shield_enabled').setChecked(False)
                    for checkbox in dialog.findChildren(QCheckBox):
                        if checkbox.text()=='打开软件后自动启用防护':checkbox.setChecked(True)
                    dialog.findChild(QPushButton, prefix).click()
                QTimer.singleShot(0,choose_dialog)
                with patch.object(self.panel,'calibrate_scope') as choose:
                    self.panel.open_settings()
                choose.assert_called_once_with(whole)
                reopened=QSettings(self.path,QSettings.IniFormat)
                self.assertFalse(reopened.value('shield_enabled',True,type=bool))
                self.assertTrue(reopened.value('auto_enable',False,type=bool))

    def test_clear_scope_saves_form_immediately_and_cancel_only_discards_later_edits(self):
        self.panel.save_profiles({'app':{'mode':'window'}})
        def clear_dialog():
            dialog=self.app.activeModalWidget()
            checkbox=dialog.findChild(QCheckBox,'shield_enabled')
            checkbox.setChecked(False)
            dialog.findChild(QPushButton, 'textAction').click()
            checkbox.setChecked(True)
            dialog.reject()
        QTimer.singleShot(0,clear_dialog)
        self.panel.open_settings()
        reopened=QSettings(self.path,QSettings.IniFormat)
        self.assertFalse(reopened.value('shield_enabled',True,type=bool))
        self.assertEqual(json.loads(reopened.value('app_profiles')), {})
        self.assertEqual(self.panel.load_profiles(),{})

    def test_restart_requires_whole_window_reselection_but_session_binding_is_kept(self):
        profile={'app':{'mode':'window','binding':{'handle':1,'pid':10}}}
        self.panel.save_profiles(profile)
        self.assertEqual(self.panel.load_profiles(),profile)
        self.assertNotIn('重启后需',self.panel.scope_summary.text())
        reopened=Shell(QSettings(self.path,QSettings.IniFormat),FakeBackend(),tray_available=False)
        try:
            self.assertEqual(reopened.load_profiles(),{'app':{'mode':'window'}})
            self.assertIn('需重新选择',reopened.scope_summary.text())
            self.assertIn('软件重启后需',reopened.scope_summary.toolTip())
        finally:
            reopened.hide();reopened.deleteLater();self.app.processEvents()

    def test_reselecting_same_application_replaces_previous_scope(self):
        self.panel.save_profiles({'app':{'mode':'tracked','anchor':{'type':'visual'}}})
        picker=Mock()
        picker.exec.return_value=QDialog.Accepted
        picker.result_profile=('app',{'mode':'window','binding':{'handle':44,'pid':55}})
        with patch('scope_picker.ScopePicker',return_value=picker):
            self.panel.calibrate_scope(True)
        self.assertEqual(len(self.panel.load_profiles()),1)
        self.assertEqual(self.panel.load_profiles()['app']['mode'],'window')
        self.assertIn('仅保护刚才点击的窗口',self.panel.detail.text())

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
        with patch('overlay_window.exclude_capture') as exclusion:
            self.panel.remind_owner('第一次虚构风险')
            popup = self.panel.reminder
            self.assertTrue(popup.isVisible())
            self.assertFalse(popup.isModal())
            self.panel.remind_owner('第二次虚构风险')
            self.assertIs(self.panel.reminder, popup)
            self.assertEqual(self.panel.reminder_text.text(), '第二次虚构风险')
            popup.hide()
            exclusion.assert_called_once_with(popup)

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
            dialog.findChild(QPushButton, 'enrollOwner').click()
        QTimer.singleShot(0,register_dialog)
        with patch.object(self.panel,'register_owner') as register:
            self.panel.open_settings()
            register.assert_called_once()
        self.assertFalse(self.settings.value('auto_enable',False,type=bool))

    def test_switch_click_and_preview_reflect_actual_backend_state(self):
        self.panel.preview = True
        self.panel.toggle.click()
        self.assertFalse(self.panel.toggle.isChecked())
        self.assertEqual(self.backend.starts, 0)
        self.panel.preview = False
        with patch('overlay_window.exclude_capture', side_effect=RuntimeError):
            self.panel.toggle.click()
        self.assertFalse(self.panel.toggle.isChecked())
        with patch('overlay_window.exclude_capture'):
            self.panel.toggle.click()
        self.assertTrue(self.panel.toggle.isChecked())
        self.backend.changed.emit('running', '模拟已启动')
        self.panel.toggle.click()
        self.assertFalse(self.panel.toggle.isChecked())
        self.assertEqual(self.backend.stops, 1)

    def test_identity_labels_require_backend_evidence_and_reset_on_pause(self):
        self.backend.changed.emit('running', '模拟检测')
        self.assertIn('等待', self.panel.owner_status.text())
        self.assertNotIn('未检测到旁人', self.panel.bystander_status.text())
        self.backend.updated.emit({'owner_verified': True, 'faces_count': 1})
        self.assertEqual(self.panel.owner_status.text(), '机主已确认')
        self.assertEqual(self.panel.bystander_status.text(), '当前未检测到旁人')
        self.backend.updated.emit({'owner_verified': True, 'faces_count': 2})
        self.assertIn('旁人', self.panel.bystander_status.text())
        self.backend.updated.emit({'owner_verified': False, 'faces_count': 0})
        self.assertIn('未检测到人脸', self.panel.bystander_status.text())
        self.panel.set_state('paused')
        self.assertIn('尚未启动', self.panel.owner_status.text())
        self.assertFalse(self.panel.latest_status)

    def test_settings_switches_keep_cancel_and_running_registration_boundaries(self):
        self.panel.set_state('running', '模拟检测')
        def inspect():
            dialog = self.app.activeModalWidget()
            self.assertFalse(dialog.findChild(QPushButton, 'enrollOwner').isEnabled())
            dialog.findChild(QCheckBox, 'shield_enabled').click()
            dialog.reject()
        QTimer.singleShot(0, inspect)
        with patch('overlay_window.exclude_capture'):
            self.panel.open_settings()
        self.assertTrue(self.settings.value('shield_enabled', True, type=bool))
        self.assertTrue(self.panel.effect_input.slider.isEnabled())


if __name__ == '__main__':
    unittest.main()
