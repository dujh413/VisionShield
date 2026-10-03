"""隔离现有后端内存；停止服务时关闭采集与OCR子进程。"""
import json
import sys


def main():
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    from PySide6.QtNetwork import QLocalSocket
    from screen_capture import enable_dpi
    from desktop_guard import ControlPanel
    enable_dpi()
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    panel = ControlPanel()
    socket = QLocalSocket()
    socket.connectToServer(sys.argv[-1])
    if not socket.waitForConnected(3000):
        return 1
    stop_requested = False

    def request_stop():
        nonlocal stop_requested
        stop_requested = True

    def read_commands():
        if b'stop' in bytes(socket.readAll()):
            request_stop()

    socket.readyRead.connect(read_commands)
    socket.disconnected.connect(request_stop)
    last_status = None
    initialized = False

    def start():
        nonlocal initialized
        panel.start()
        initialized = True

    def tick():
        nonlocal last_status
        # 启动探针会运行嵌套Qt事件循环，尚未启动控制定时器不代表异常。
        if not initialized:
            return
        if stop_requested:
            panel.pause()
            app.quit()
            return
        status = panel.status.text()
        state = 'running' if panel.timer.isActive() else 'error'
        snapshot = (state, status)
        if snapshot != last_status:
            print('VISION_SHIELD:'+json.dumps({'state': state, 'detail': status}, ensure_ascii=True), flush=True)
            last_status = snapshot

    timer = QTimer()
    timer.timeout.connect(tick)
    timer.start(250)
    app.aboutToQuit.connect(panel.pause)
    QTimer.singleShot(0, start)
    return app.exec()
