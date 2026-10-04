import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import queue
import unittest
from unittest.mock import Mock, patch
from PySide6.QtWidgets import QApplication
from owner_enrollment import EnrollmentDialog


class EnrollmentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])

    def setUp(self):
        context=Mock()
        self.queue=queue.Queue()
        context.Queue.return_value=self.queue
        self.process=context.Process.return_value
        self.process.pid=123
        self.process.is_alive.return_value=True
        with patch('owner_enrollment.mp.get_context',return_value=context),patch('process_lifetime.ProcessJob'):
            self.dialog=EnrollmentDialog()

    def tearDown(self):
        self.process.is_alive.return_value=False
        with patch.object(self.queue,'cancel_join_thread',create=True),patch.object(self.queue,'close',create=True):
            self.dialog.cleanup()
        self.dialog.deleteLater();self.app.processEvents()

    def test_cannot_enroll_before_preview_ready(self):
        self.assertFalse(self.dialog.begin.isEnabled())

    def test_child_exit_reports_failure_instead_of_waiting_forever(self):
        self.process.is_alive.return_value=False
        self.dialog.poll()
        self.assertIn('已退出',self.dialog.status.text())
        self.assertFalse(self.dialog.timer.isActive())
        self.assertFalse(self.dialog.begin.isEnabled())

    def test_terminal_error_is_not_overwritten_by_old_preview(self):
        self.queue.put({'error':'test error'})
        self.queue.put({'image':b'','message':'obsolete preview'})
        self.dialog.poll()
        self.assertIn('登记失败',self.dialog.status.text())
        self.assertFalse(self.dialog.begin.isEnabled())


if __name__=='__main__':unittest.main()
