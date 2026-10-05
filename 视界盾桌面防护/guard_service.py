"""隔离现有后端内存；停止服务时关闭采集与OCR子进程。"""
import json
import os
import sys


def status_payload(panel):
    failed = panel.error or (panel.camera.error if panel.camera else None)
    camera = panel.camera.last if panel.camera else None
    return {'state':'running' if panel.timer.isActive() and not failed else 'error',
            'detail':panel.status.text(), 'alert':panel.alert_message,
            'sensitive_lines':len(panel.hits), 'protecting':panel.protecting,
            'owner_verified':bool(camera and camera['owner_verified']),
            'faces_count':camera['faces_count'] if camera else None,
            'full_mask':panel.overlay.full if panel.overlay else False,
            'blur_regions':len(panel.overlay.blurs) if panel.overlay else 0}


def status_snapshot(payload):
    return tuple((key, value) for key, value in payload.items() if key != 'alert')


def main():
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    from PySide6.QtNetwork import QLocalSocket
    from screen_capture import enable_dpi
    from desktop_guard import ControlPanel
    enable_dpi()
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    panel = ControlPanel(integrated=True, shield_enabled=os.environ.get('VISION_SHIELD_SHIELD_ENABLED', '1') != '0')
    socket = QLocalSocket()
    socket.connectToServer(sys.argv[-1])
    if not socket.waitForConnected(3000):
        return 1
    stop_requested = False
    command_buffer = b''

    def request_stop():
        nonlocal stop_requested
        stop_requested = True

    def read_commands():
        nonlocal command_buffer
        command_buffer = (command_buffer+bytes(socket.readAll()))[-64:]
        if b'stop' in command_buffer:
            request_stop()

    socket.readyRead.connect(read_commands)
    socket.disconnected.connect(request_stop)
    read_commands()  # waitForConnected期间到达的停止指令不能丢失。
    last_status = None
    initialized = False

    def start():
        nonlocal initialized
        if not stop_requested:
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
        payload = status_payload(panel)
        snapshot = status_snapshot(payload)
        alert = payload['alert']
        if snapshot != last_status or alert:
            packet = 'VISION_SHIELD:'+json.dumps(payload, ensure_ascii=True)+'\n'
            socket.write(packet.encode('utf-8'))
            socket.flush()
            last_status = snapshot
            panel.alert_message = None

    timer = QTimer()
    timer.timeout.connect(tick)
    timer.start(250)
    app.aboutToQuit.connect(panel.pause)
    QTimer.singleShot(0, start)
    return app.exec()
