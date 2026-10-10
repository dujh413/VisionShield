"""Export controlled Qt interface textures for the product concept film.

This script imports the current UI only. It uses an in-memory fake backend,
temporary settings and a fictional owner-registration marker. It never starts
camera/OCR workers, displays a system-tray icon or reads personal templates.
Generated PNGs are fixtures, not evidence of real detection performance.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path,
                        default=Path(__file__).resolve().parent / "output" / "assets")
    parser.add_argument("--scale", type=float, default=2.0,
                        help="Qt device-pixel scale; default 2 exports crisp UI textures")
    args = parser.parse_args()
    if not 1 <= args.scale <= 4:
        parser.error("--scale must be between 1 and 4")

    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    os.environ["QT_SCALE_FACTOR"] = str(args.scale)
    os.environ["QT_AUTO_SCREEN_SCALE_FACTOR"] = "0"
    os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "1"
    repository = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(repository / "视界盾桌面防护"))

    from PySide6.QtCore import QObject, QPoint, QRect, QSettings, QTimer, Qt, Signal
    from PySide6.QtGui import QFont, QFontDatabase, QScreen
    from PySide6.QtWidgets import QApplication, QLabel, QScrollArea, QWidget
    from app_shell import Shell
    import runtime_paths

    class FakeBackend(QObject):
        changed = Signal(str, str)
        updated = Signal(dict)
        stopped = Signal()

        def __init__(self):
            super().__init__()
            self.shield_enabled = True
            self.effect_text = "24"
            self.app_profiles = {}
            self.starts = 0

        def start(self):
            self.starts += 1
            raise RuntimeError("The controlled UI exporter cannot start a backend")

        def stop(self):
            self.stopped.emit()

        def send_preferences(self):
            pass

    class FictionalOwnerMarker:
        def is_file(self):
            return True  # A fictional enrolled-owner state; no filesystem access.

    app = QApplication.instance() or QApplication(["VisionShieldConceptUI"])
    app.setQuitOnLastWindowClosed(False)
    # Qt's offscreen platform has no automatic Windows font discovery.
    # Register the same system font used by the production stylesheet.
    font_directory = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
    for font_name in ("msyh.ttc", "msyhbd.ttc", "msyhl.ttc"):
        font_path = font_directory / font_name
        if font_path.is_file():
            QFontDatabase.addApplicationFont(str(font_path))
    if "Microsoft YaHei UI" not in QFontDatabase.families():
        raise RuntimeError("Microsoft YaHei UI is required for faithful UI textures")
    app.setFont(QFont("Microsoft YaHei UI", 10))
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    metadata = {
        "fixture_only": True,
        "backend_started": False,
        "camera_started": False,
        "owner_template_read": False,
        "settings": "temporary INI, deleted after export",
        "scale": args.scale,
        "coordinate_system": "physical pixels of exported PNGs",
        "assets": {},
    }

    def rectangle(widget, ancestor):
        origin = widget.mapTo(ancestor, QPoint(0, 0))
        return [round(origin.x() * args.scale), round(origin.y() * args.scale),
                round(widget.width() * args.scale), round(widget.height() * args.scale)]

    def export(widget, name, extra=None):
        app.processEvents()
        focus = app.focusWidget()
        if focus is not None:
            focus.clearFocus()
        pixmap = widget.grab()
        target = output / name
        if not pixmap.save(str(target), "PNG"):
            raise OSError(f"Could not save {target}")
        asset = {
            "size": [pixmap.width(), pixmap.height()],
            "logical_size": [widget.width(), widget.height()],
            "device_pixel_ratio": pixmap.devicePixelRatio(),
        }
        if extra:
            asset.update(extra)
        metadata["assets"][name] = asset

    with tempfile.TemporaryDirectory(prefix="visionshield-concept-ui-") as temporary:
        settings = QSettings(str(Path(temporary) / "fixture.ini"), QSettings.IniFormat)
        for key, value in {"shield_enabled": True, "sound_enabled": True,
                           "popup_enabled": False, "effect_text": "24",
                           "blur_radius": 24, "auto_enable": False,
                           "start_hidden": False, "app_profiles": "{}"}.items():
            settings.setValue(key, value)
        settings.sync()
        backend = FakeBackend()
        panel = Shell(settings=settings, backend=backend, preview=False, tray_available=False)
        # Retain the production tray-capable layout without calling tray.show().
        panel.has_tray = True
        panel.hide_button.setVisible(True)
        panel.tray_hint.setText("关闭窗口后仍在托盘运行")
        panel.setAttribute(Qt.WA_ShowWithoutActivating, True)
        panel.resize(520, max(658, panel.minimumSizeHint().height()))
        panel.show()
        app.processEvents()

        def running(risk=False):
            panel.set_state("running", "检测到旁观风险，正在保护敏感内容。" if risk
                            else "正在监测旁观风险")
            panel.backend_updated({"owner_verified": True,
                                   "faces_count": 2 if risk else 1,
                                   "stranger_detected": risk,
                                   "protecting": risk})

        def main_export(name):
            export(panel, name, {
                "effect_crop_rect": rectangle(panel.effect_input, panel),
                "slider_rect": rectangle(panel.effect_input.slider, panel),
                "strength_label_rect": rectangle(panel.effect_input.strength, panel),
                "state": panel.state,
                "effect_text": panel.effect_input.to_text(),
                "simulated_detection": panel.state == "running",
            })

        main_export("main-paused.png")
        running()
        main_export("main-safe.png")
        running(True)
        main_export("main-risk.png")
        panel.effect_input.setText("遮挡")
        panel.apply_effect_text()
        main_export("main-dark.png")
        panel.effect_input.setText("24")
        running()
        for value in range(2, 65):
            panel.effect_input.slider.setValue(value)
            panel.apply_effect_text()
            main_export(f"main-blur-{value}.png")
        panel.effect_input.slider.setValue(24)
        panel.apply_effect_text()
        panel.set_state("paused")

        def settings_export(name):
            errors = []

            def capture_dialog():
                dialog = app.activeModalWidget()
                try:
                    if dialog is None:
                        raise RuntimeError("Settings dialog did not become active")
                    dialog.resize(560, 820)
                    scroll = dialog.findChild(QScrollArea)
                    if scroll is not None:
                        scroll.verticalScrollBar().setValue(0)
                    app.processEvents()
                    headings = {label.text(): label for label in dialog.findChildren(QLabel)
                                if label.text() in ("防护效果", "保护范围")}
                    top = headings["防护效果"].mapTo(dialog, QPoint(0, 0)).y()
                    bottom = headings["保护范围"].mapTo(dialog, QPoint(0, 0)).y() - 10
                    crop = [round(28 * args.scale), round(top * args.scale),
                            round((dialog.width() - 56) * args.scale),
                            round((bottom - top) * args.scale)]
                    export(dialog, name, {"effects_crop_rect": crop, "state": "paused"})
                except Exception as exc:
                    errors.append(exc)
                finally:
                    if dialog is not None:
                        dialog.reject()

            QTimer.singleShot(0, capture_dialog)
            # Override screen sizing only for reproducible offscreen rendering.
            # The owner marker is fictional and never resolves a personal path.
            with patch.object(QScreen, "availableGeometry", return_value=QRect(0, 0, 1920, 1080)), \
                    patch.object(runtime_paths, "owner_file", return_value=FictionalOwnerMarker()):
                panel.open_settings()
            if errors:
                raise errors[0]

        settings_export("settings.png")
        settings.setValue("popup_enabled", True)
        settings_export("settings-popup.png")
        panel.hide()
        panel.tray.hide()
        panel.deleteLater()
        app.processEvents()
        if backend.starts:
            raise RuntimeError("A backend start was attempted during UI export")

    forbidden = [name for name in ("cv2", "numpy", "ocr_worker", "desktop_guard", "identity_test")
                 if name in sys.modules]
    if forbidden:
        raise RuntimeError(f"Unexpected backend imports: {forbidden}")
    (output / "layout.json").write_bytes((json.dumps(metadata, ensure_ascii=False, indent=2)
                                         + "\n").encode("utf-8"))
    print(f"Exported {len(metadata['assets'])} controlled UI textures to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
