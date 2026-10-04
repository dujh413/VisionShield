"""轻量界面不导入图像库；防护后端仅在启用时单独运行。"""
import argparse
import json
from pathlib import Path
import sys
import uuid

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, QSettings, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPixmap
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import (QApplication, QCheckBox, QDialog, QDialogButtonBox,
                              QHBoxLayout, QLabel, QMenu, QPushButton,
                              QSystemTrayIcon, QVBoxLayout, QWidget)


class Backend(QObject):
    changed = Signal(str, str)
    alerted = Signal(str)
    updated = Signal(dict)
    stopped = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.process = QProcess(self)
        self.process.readyReadStandardOutput.connect(self.read_status)
        self.process.readyReadStandardError.connect(self.discard_errors)
        self.process.finished.connect(self.finished)
        self.process.errorOccurred.connect(self.failed)
        self.process.started.connect(self.bind_process)
        self.buffer = b''
        self.stopping = False
        self.server = QLocalServer(self)
        self.server.newConnection.connect(self.accept_service)
        self.peer = None
        self.job = None
        self.failure_detail = None
        self.watchdog = QTimer(self)
        self.watchdog.setSingleShot(True)
        self.watchdog.timeout.connect(self.timed_out)

    def bind_process(self):
        try:
            self.job.attach(int(self.process.processId()))
        except OSError:
            self.failure_detail = '无法管理防护进程资源，服务已停止。'
            self.process.kill()

    def timed_out(self):
        self.failure_detail = '防护服务停止超时，已释放后台资源。' if self.stopping else '防护服务启动超时，请检查运行环境。'
        if self.job is not None:
            self.job.close()
        self.process.kill()

    def accept_service(self):
        self.peer = self.server.nextPendingConnection()
        if self.stopping:
            self.peer.write(b'stop')
            self.peer.flush()

    def start(self):
        if self.process.state() != QProcess.NotRunning:
            return
        self.stopping = False
        self.buffer = b''
        self.failure_detail = None
        from process_lifetime import ProcessJob
        try:
            self.job = ProcessJob()
        except OSError:
            self.changed.emit('error', '无法初始化防护进程资源管理。')
            self.stopped.emit()
            return
        name = 'VisionShield.Service.'+uuid.uuid4().hex
        if not self.server.listen(name):
            self.job.close()
            self.changed.emit('error', '无法建立本机防护服务连接。')
            self.stopped.emit()
            return
        launcher = str(Path(__file__).resolve().parents[1]/'VisionShield.py')
        arguments = ['--backend-service', name] if getattr(sys, 'frozen', False) else [launcher, '--backend-service', name]
        executable = sys.executable
        if not getattr(sys,'frozen',False) and Path(executable).name.lower()=='pythonw.exe':
            executable = str(Path(executable).with_name('python.exe'))
        # 与multiprocessing的Windows venv启动方式一致，绕过重定向启动器，
        # 使QProcess和Job管理的是实际服务进程，而不是另一层python启动器。
        environment = QProcessEnvironment.systemEnvironment()
        if not getattr(sys,'frozen',False) and sys.prefix != sys.base_prefix:
            base = Path(sys._base_executable).with_name('python.exe')
            environment.insert('__PYVENV_LAUNCHER__',executable)
            executable = str(base)
        self.process.setProcessEnvironment(environment)
        self.watchdog.start(30000)
        self.process.start(executable, arguments)

    def stop(self):
        self.stopping = True
        if self.process.state() == QProcess.NotRunning:
            self.stopped.emit()
        elif self.peer is not None:
            self.peer.write(b'stop')
            self.peer.flush()
        if self.process.state() != QProcess.NotRunning:
            self.watchdog.start(15000)

    def read_status(self):
        self.buffer += bytes(self.process.readAllStandardOutput())
        if len(self.buffer) > 65536:
            self.buffer = self.buffer[-65536:]
        while b'\n' in self.buffer:
            line, self.buffer = self.buffer.split(b'\n', 1)
            if not line.startswith(b'VISION_SHIELD:'):
                continue
            try:
                value = json.loads(line[len(b'VISION_SHIELD:'):])
            except (ValueError, UnicodeError):
                continue
            if (not isinstance(value, dict) or value.get('state') not in ('running','error')
                    or not isinstance(value.get('detail'),str)):
                continue
            if not self.stopping:
                self.watchdog.stop()
                self.updated.emit(value)
                self.changed.emit(value['state'], value['detail'])
                if value.get('alert'):
                    self.alerted.emit(value['alert'])

    def discard_errors(self):
        self.process.readAllStandardError()  # 排空输出，避免后台长期累积。

    def failed(self, error):
        if error == QProcess.FailedToStart:
            self.watchdog.stop()
            if self.job is not None:
                self.job.close()
            self.server.close()
            self.changed.emit('error', '防护服务未能启动，请检查运行环境。')
            self.stopped.emit()

    def finished(self, exit_code, exit_status):
        self.watchdog.stop()
        if self.job is not None:
            self.job.close()
            self.job = None
        if self.peer is not None:
            self.peer.disconnectFromServer()
            self.peer.deleteLater()
            self.peer = None
        self.server.close()
        if not self.stopping:
            self.changed.emit('error', self.failure_detail or '防护服务已退出，请重新启用。')
        self.stopped.emit()


def shield_icon():
    pixmap = QPixmap(48, 48)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor('#12856f'))
    path = QPainterPath()
    path.moveTo(24, 3)
    path.lineTo(41, 10)
    path.lineTo(39, 29)
    path.quadTo(35, 40, 24, 45)
    path.quadTo(13, 40, 9, 29)
    path.lineTo(7, 10)
    path.closeSubpath()
    painter.drawPath(path)
    painter.setPen(QColor('white'))
    painter.drawLine(16, 24, 22, 30)
    painter.drawLine(22, 30, 33, 17)
    painter.end()
    return QIcon(pixmap)


class Shell(QWidget):
    def __init__(self, settings=None, backend=None, preview=False, tray_available=None):
        super().__init__()
        self.settings = settings if settings is not None else QSettings('VisionShield', 'Desktop')
        self.backend = backend if backend is not None else Backend(self)
        self.preview, self.quitting, self.state = preview, False, 'paused'
        self.setWindowTitle('视界盾')
        self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)
        self.setWindowIcon(shield_icon())
        self.setFixedSize(420, 340)
        self.setStyleSheet('''
            QWidget { background: #f5f7f8; color: #23312e; font: 10pt "Microsoft YaHei UI"; }
            QLabel#title { font-size: 23px; font-weight: 600; }
            QLabel#caption { color: #6d7b77; }
            QLabel#state { font-size: 18px; font-weight: 600; }
            QLabel#detail { color: #66746f; }
            QPushButton { border: 1px solid #d6e0dd; border-radius: 8px; padding: 9px 16px; background: white; }
            QPushButton:hover { background: #eaf2ef; }
            QPushButton#primary { background: #12856f; border: none; color: white; font-weight: 600; }
            QPushButton#primary:hover { background: #0d715e; }
            QPushButton:disabled { background: #dce5e2; color: #74817d; }
        ''')
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(10)
        title, caption = QLabel('视界盾'), QLabel('公共场景下的屏幕隐私防护')
        title.setObjectName('title')
        caption.setObjectName('caption')
        self.status, self.detail = QLabel(), QLabel()
        self.status.setObjectName('state')
        self.detail.setObjectName('detail')
        self.detail.setWordWrap(True)
        self.detail.setMinimumHeight(58)
        self.toggle = QPushButton()
        self.toggle.setObjectName('primary')
        self.toggle.clicked.connect(self.toggle_guard)
        actions = QHBoxLayout()
        settings_button, hide_button = QPushButton('设置'), QPushButton('后台运行')
        settings_button.clicked.connect(self.open_settings)
        hide_button.clicked.connect(self.hide)
        actions.addWidget(settings_button)
        actions.addWidget(hide_button)
        layout.addWidget(title)
        layout.addWidget(caption)
        layout.addSpacing(12)
        for widget in (self.status, self.detail, self.toggle):
            layout.addWidget(widget)
        layout.addStretch()
        layout.addLayout(actions)
        self.tray = QSystemTrayIcon(self.windowIcon(), self)
        menu = QMenu(self)
        menu.addAction('打开视界盾').triggered.connect(self.show_panel)
        self.tray_toggle = menu.addAction('启用防护')
        self.tray_toggle.triggered.connect(self.toggle_guard)
        menu.addSeparator()
        menu.addAction('退出视界盾').triggered.connect(self.quit_app)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self.tray_activated)
        self.has_tray = QSystemTrayIcon.isSystemTrayAvailable() if tray_available is None else tray_available
        if self.has_tray:
            self.tray.show()
        else:
            hide_button.hide()
        self.backend.changed.connect(self.backend_changed)
        self.backend.stopped.connect(self.backend_stopped)
        if hasattr(self.backend,'alerted'):
            self.backend.alerted.connect(self.remind_owner)
        self.set_state('paused')

    def set_state(self, state, detail=None):
        self.state = state
        labels = {'paused': ('防护未启用', '启用防护'), 'starting': ('正在启动', '启动中…'),
                  'running': ('防护已启用', '暂停防护'), 'stopping': ('正在停止', '停止中…'),
                  'error': ('防护异常', '停止并重试')}
        title, action = labels[state]
        self.status.setText(title)
        self.toggle.setText(action)
        self.toggle.setEnabled(state not in ('starting', 'stopping'))
        self.tray_toggle.setText(action)
        self.tray_toggle.setEnabled(self.toggle.isEnabled())
        self.detail.setText(detail or ('当前桌面未受保护。启用后开始本地检测。' if state == 'paused' else '请稍候。'))
        self.tray.setToolTip('视界盾 · '+title)

    def toggle_guard(self):
        if self.preview:
            self.detail.setText('界面预览模式：防护未运行。正常启动软件后可启用。')
            return
        if self.state == 'paused':
            from overlay_window import exclude_capture
            try:
                exclude_capture(self)
            except Exception:
                self.detail.setText('无法将控制窗口排除出屏幕采集，请检查Windows支持情况。')
                return
            self.set_state('starting', '正在加载本地防护服务。')
            self.backend.start()
        elif self.state in ('running', 'error'):
            self.set_state('stopping')
            self.backend.stop()

    def backend_changed(self, state, detail):
        if self.state != 'stopping' and not self.quitting:
            self.set_state(state, detail)
            if self.isVisible():
                self.raise_()

    def backend_stopped(self):
        if self.quitting:
            self.tray.hide()
            QApplication.instance().quit()
        elif self.state != 'error':
            self.set_state('paused')

    def remind_owner(self, message):
        if self.has_tray:
            self.tray.showMessage('视界盾隐私提醒', message, QSystemTrayIcon.Warning, 4000)
        QApplication.beep()

    def show_panel(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def tray_activated(self, reason):
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self.show_panel()

    def open_settings(self):
        dialog = QDialog(self)
        dialog.setWindowTitle('设置')
        layout = QVBoxLayout(dialog)
        auto = QCheckBox('打开软件后自动启用防护')
        hidden = QCheckBox('打开软件后直接驻留托盘')
        auto.setChecked(self.settings.value('auto_enable', False, type=bool))
        hidden.setChecked(self.settings.value('start_hidden', False, type=bool))
        hidden.setEnabled(self.has_tray)
        layout.addWidget(auto)
        layout.addWidget(hidden)
        layout.addWidget(QLabel('设置在下次打开软件时生效。'))
        enroll = QPushButton('登记 / 更新机主')
        layout.addWidget(enroll)
        def register():
            if self.state != 'paused':
                self.detail.setText('请先暂停防护，再登记机主。')
                dialog.reject()
                return
            dialog.reject()
            self.register_owner()
        enroll.clicked.connect(register)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText('保存')
        buttons.button(QDialogButtonBox.Cancel).setText('取消')
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() == QDialog.Accepted:
            self.settings.setValue('auto_enable', auto.isChecked())
            self.settings.setValue('start_hidden', hidden.isChecked())
            self.settings.sync()
        dialog.deleteLater()

    def register_owner(self):
        if self.preview:
            self.detail.setText('预览模式不打开摄像头。')
            return
        from owner_enrollment import EnrollmentDialog
        try:
            EnrollmentDialog(self).exec()
        except Exception:
            self.detail.setText('机主登记无法启动，请检查运行环境后重试。')

    def quit_app(self):
        self.quitting = True
        self.set_state('stopping', '正在释放防护资源。')
        self.backend.stop()

    def closeEvent(self, event):
        event.ignore()
        if self.has_tray:
            self.hide()
        else:
            self.quit_app()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--preview', action='store_true', help='仅预览界面，不加载防护后端')
    args = parser.parse_args()
    app = QApplication(sys.argv[:1])
    app.setQuitOnLastWindowClosed(False)
    name = 'VisionShield.Desktop.'+('Preview' if args.preview else 'Main')
    socket = QLocalSocket()
    socket.connectToServer(name)
    if socket.waitForConnected(150):
        socket.write(b'show')
        socket.waitForBytesWritten(150)
        return 0
    server = QLocalServer(app)
    QLocalServer.removeServer(name)
    if not server.listen(name):
        return 1
    panel = Shell(preview=args.preview)

    def activate():
        peer = server.nextPendingConnection()
        if peer is not None:
            peer.disconnectFromServer()
            peer.deleteLater()
        panel.show_panel()

    server.newConnection.connect(activate)
    if args.preview or not panel.has_tray or not panel.settings.value('start_hidden', False, type=bool):
        panel.show()
    if not args.preview and panel.settings.value('auto_enable', False, type=bool):
        QTimer.singleShot(0, panel.toggle_guard)
    result = app.exec()
    server.close()
    return result
