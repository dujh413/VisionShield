import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
import json
from pathlib import Path
import sys
import tempfile
import unittest
import subprocess
from unittest.mock import Mock, patch
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication
from app_shell import Backend, Shell
from guard_service import status_payload, status_snapshot
from runtime_errors import install_exception_logging


class RuntimeRegressions(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_already_buffered_first_packet_is_delivered(self):
        backend = Backend()
        peer = Mock()
        packet = {'state':'running', 'detail':'虚构首包'}
        peer.readAll.return_value = ('VISION_SHIELD:'+json.dumps(packet)+'\n').encode()
        updates = []
        backend.updated.connect(updates.append)
        with patch.object(backend.server, 'nextPendingConnection', return_value=peer):
            backend.accept_service()
        self.assertEqual(updates, [packet])

    def test_backend_limits_blas_before_fresh_child_import_without_changing_parent(self):
        backend = Backend()
        try:
            with patch.dict(os.environ, {'OPENBLAS_NUM_THREADS':'8', 'VISION_SHIELD_TEST_INHERITED':'yes'}), \
                    patch('process_lifetime.ProcessJob'), patch.object(backend.process, 'start'):
                backend.start()
                environment = backend.process.processEnvironment()
                self.assertEqual(os.environ['OPENBLAS_NUM_THREADS'], '8')
                child_environment = dict(item.split('=', 1) for item in environment.toStringList())
                # Real fresh interpreter imports NumPy only after receiving the
                # service environment; no camera, OCR model or screen capture.
                command = ('import os,json,numpy as np; '
                           'v=np.arange(128,dtype=np.float32); '
                           'print(json.dumps({"threads":os.environ.get("OPENBLAS_NUM_THREADS"),'
                           '"inherited":os.environ.get("VISION_SHIELD_TEST_INHERITED"),'
                           '"dot":float(v@v)}))')
                run = subprocess.run([sys.executable, '-c', command], env=child_environment,
                                     capture_output=True, text=True, timeout=15, check=True)
                result = json.loads(run.stdout)
                self.assertEqual(result, {'threads':'1', 'inherited':'yes', 'dot':690880.0})
        finally:
            backend.watchdog.stop()
            backend.server.close()
            if backend.job is not None:
                backend.job.close()
            backend.deleteLater()

    def test_malformed_alert_does_not_break_valid_status(self):
        backend = Backend()
        alerts, updates = [], []
        backend.alerted.connect(alerts.append)
        backend.updated.connect(updates.append)
        packet = {'state':'running', 'detail':'虚构状态', 'alert':{'unexpected':True}}
        backend.consume_status(('VISION_SHIELD:'+json.dumps(packet)+'\n').encode())
        self.assertEqual(updates, [packet])
        self.assertFalse(alerts)

    def test_face_and_mask_changes_are_not_hidden_by_same_status_text(self):
        panel = Mock(error=None, hits=[], alert_message=None, protecting=True)
        panel.status.text.return_value = '相同状态文字'
        panel.timer.isActive.return_value = True
        panel.camera.error = None
        panel.camera.last = {'owner_verified':False, 'faces_count':2}
        panel.overlay.full = False
        panel.overlay.blurs = []
        first = status_snapshot(status_payload(panel))
        panel.camera.last['faces_count'] = 3
        self.assertNotEqual(first, status_snapshot(status_payload(panel)))
        second = status_snapshot(status_payload(panel))
        panel.overlay.blurs = [object()]
        self.assertNotEqual(second, status_snapshot(status_payload(panel)))

    def test_repeated_exit_only_stops_once(self):
        with tempfile.TemporaryDirectory() as folder:
            backend = Mock()
            panel = Shell(QSettings(str(Path(folder)/'settings.ini'), QSettings.IniFormat), backend, tray_available=False)
            panel.quit_app()
            panel.quit_app()
            backend.stop.assert_called_once()
            event = Mock()
            panel.closeEvent(event)
            event.accept.assert_called_once()
            backend.stop.assert_called_once()
            panel.deleteLater()

    def test_windowless_callback_errors_have_bounded_local_log(self):
        original = sys.excepthook
        try:
            with tempfile.TemporaryDirectory() as folder, patch('runtime_errors.user_root', return_value=Path(folder)), patch.object(sys, 'stderr', None):
                install_exception_logging()
                sys.excepthook(RuntimeError, RuntimeError('first fictional failure'), None)
                sys.excepthook(RuntimeError, RuntimeError('second fictional failure'), None)
                text = (Path(folder)/'runtime_error.log').read_text(encoding='utf-8')
                self.assertIn('second fictional failure', text)
                self.assertNotIn('first fictional failure', text)
        finally:
            sys.excepthook = original


if __name__ == '__main__':
    unittest.main()
