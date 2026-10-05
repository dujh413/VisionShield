"""在软件包内验证真实窗口锚点、隔离校准进程和动态跟随。"""
import time


def check(app):
    from PySide6.QtWidgets import QWidget
    from app_scope import window_inventory, application_masks
    from region_anchor import native_nodes
    from region_tracker import RegionTracker
    from region_worker import RegionWorker
    from screen_capture import ScreenCapture
    window = QWidget()
    window.setWindowTitle('VisionShield synthetic region check')
    window.setGeometry(80, 130, 600, 400)
    child = QWidget(window)
    child.setGeometry(100, 80, 300, 200)
    child.setStyleSheet('background: #547b98')
    child.winId()
    window.show()
    app.processEvents()
    worker = RegionWorker()
    capture = ScreenCapture()
    tracker = RegionTracker()
    cases = []
    try:
        inventory = window_inventory(capture.monitor)
        target = next(w for w in inventory if w['handle'] == int(window.winId()))
        node = next(n for n in native_nodes(target['handle'], (0, 0)) if n['handle'] == int(child.winId()))
        cx, cy, cw, ch = target['client']
        x, y, width, height = node['rect']
        request = {'command': 'enroll', 'binding': {'handle': target['handle'], 'pid': target['pid']},
                   'region': [(x-cx)/cw, (y-cy)/ch, width/cw, height/ch]}
        deadline = time.monotonic()+12
        profile = None
        sent = False
        while time.monotonic() < deadline and profile is None:
            app.processEvents()
            for item in worker.poll():
                if 'error' in item:
                    raise RuntimeError(item['error'])
                if 'profile' in item:
                    profile = item['profile']
            if worker.ready and not sent:
                worker.submit(request)
                sent = True
            time.sleep(.02)
        if profile is None or profile['anchor']['type'] != 'native':
            raise RuntimeError('Packaged region enrollment failed')
        for name in ('initial', 'window_move', 'internal_move_resize'):
            if name == 'window_move':
                window.move(300, 180)
            if name == 'internal_move_resize':
                child.setGeometry(180, 120, 250, 160)
            app.processEvents()
            inventory = window_inventory(capture.monitor)
            target = next(w for w in inventory if w['handle'] == int(window.winId()))
            target = dict(target, mode='lines')  # 仅诊断自身窗口；产品默认排除自身。
            expected = next(n['rect'] for n in native_nodes(target['handle'], (0, 0)) if n['handle'] == int(child.winId()))
            scopes = tracker.resolve({target['key']: profile}, [target], capture.grab().image)
            actual = scopes[target['key']]['rect']
            if actual is None or max(abs(a-b) for a, b in zip(actual, expected)) > 2:
                raise RuntimeError('Packaged region tracking mismatch')
            masks, full = application_masks([target], [], False, {target['key']: profile}, scopes)
            if full or masks != [actual]:
                raise RuntimeError('Packaged mask mapping mismatch')
            cases.append(name)
        return {'passed': True, 'cases': cases, 'raw_images_saved': False}
    finally:
        tracker.close()
        worker.close()
        capture.close()
        window.close()
