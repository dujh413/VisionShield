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
            'shield_enabled':bool(panel.shield_enabled),
            'owner_verified':bool(camera and camera['owner_verified']),
            'owner_session_active':bool(camera and camera.get('owner_session_active',False)),
            'pose_grace':bool(camera and camera.get('pose_grace',False)),
            'stranger_detected':bool(camera and camera.get('stranger_detected',False)),
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
    panel = ControlPanel(integrated=True, shield_enabled=os.environ.get('VISION_SHIELD_SHIELD_ENABLED', '1') != '0',
                         effect_text=os.environ.get('VISION_SHIELD_EFFECT_TEXT', '遮挡')[:128],
                         diagnostics=os.environ.get('VISION_SHIELD_DIAGNOSTICS') == '1')
    socket = QLocalSocket()
    socket.connectToServer(sys.argv[-1])
    if not socket.waitForConnected(3000):
        return 1
    stop_requested = False
    command_buffer = b''
    pending_preferences = {}
    applying_preferences = False

    def request_stop():
        nonlocal stop_requested
        stop_requested = True

    def read_commands():
        nonlocal command_buffer, pending_preferences
        command_buffer = (command_buffer+bytes(socket.readAll()))[-262144:]
        # 兼容旧版无换行stop；新版JSON逐行处理，支持拆包和多次修改。
        if command_buffer == b'stop':
            request_stop()
            command_buffer = b''
        while b'\n' in command_buffer:
            line, command_buffer = command_buffer.split(b'\n', 1)
            if line == b'stop':
                request_stop()
                continue
            try:
                value = json.loads(line)
            except (ValueError, UnicodeError):
                continue
            if isinstance(value, dict) and not stop_requested:
                pending_preferences.update(value)


    socket.readyRead.connect(read_commands)
    socket.disconnected.connect(request_stop)
    read_commands()  # waitForConnected期间到达的停止指令不能丢失。
    last_status = None
    initialized = False

    def start():
        nonlocal initialized, pending_preferences
        if not stop_requested:
            panel.apply_preferences(pending_preferences)
            pending_preferences = {}
            panel.start()
        initialized = True

    def tick():
        nonlocal last_status, pending_preferences, applying_preferences
        # 启动探针会运行嵌套Qt事件循环，尚未启动控制定时器不代表异常。
        if not initialized or applying_preferences:
            return
        if stop_requested:
            panel.pause()
            app.quit()
            return
        if pending_preferences:
            preferences, pending_preferences = pending_preferences, {}
            applying_preferences = True
            try:
                panel.apply_preferences(preferences)
            finally:
                applying_preferences = False
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
