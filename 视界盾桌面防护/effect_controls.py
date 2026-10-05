"""轻量原生效果选择；不加载图像库或识别模型。"""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QSlider, QVBoxLayout, QWidget

from mask_effect import parse_effect


DEFAULT_BLUR_RADIUS = 24


class EffectControls(QWidget):
    changed = Signal(str)

    def __init__(self, text=str(DEFAULT_BLUR_RADIUS), parent=None, allow_off=False):
        super().__init__(parent)
        self.shield_enabled = True
        self.mode = QComboBox()
        self.mode.setObjectName('mask_style')
        self.mode.setAccessibleName('屏幕遮蔽效果')
        self.mode.addItem('模糊', 'blur')
        self.mode.addItem('深色遮挡', 'block')
        if allow_off:
            self.mode.addItem('不遮蔽（仅检测与提示）', 'off')
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setObjectName('blur_radius')
        self.slider.setAccessibleName('模糊强度，向右拖动增强')
        self.slider.setRange(2, 64)
        self.slider.setValue(DEFAULT_BLUR_RADIUS)
        self.strength = QLabel()
        self.explanation = QLabel()
        self.explanation.setObjectName('caption')
        self.explanation.setWordWrap(True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        row = QHBoxLayout()
        row.addWidget(QLabel('遮蔽效果'))
        row.addWidget(self.mode, 1)
        layout.addLayout(row)
        layout.addWidget(self.strength)
        row = QHBoxLayout()
        row.addWidget(QLabel('较弱'))
        row.addWidget(self.slider, 1)
        row.addWidget(QLabel('较强'))
        layout.addLayout(row)
        layout.addWidget(self.explanation)
        self.set_from_text(text)
        self.mode.currentIndexChanged.connect(self._updated)
        self.slider.valueChanged.connect(self._updated)

    def to_text(self):
        mode = self.mode.currentData()
        return str(self.slider.value()) if mode == 'blur' else ('遮挡' if mode == 'block' else '')

    def set_from_text(self, text):
        effect = parse_effect(str(text))
        index = self.mode.findData(effect.mode)
        self.mode.blockSignals(True)
        self.slider.blockSignals(True)
        self.mode.setCurrentIndex(index if index >= 0 else self.mode.findData('blur'))
        if effect.mode == 'blur':
            self.slider.setValue(max(self.slider.minimum(), min(self.slider.maximum(), effect.radius)))
        self.mode.blockSignals(False)
        self.slider.blockSignals(False)
        self._updated()

    def set_shield_enabled(self, enabled):
        self.shield_enabled = bool(enabled)
        self._refresh()

    def _refresh(self):
        mode = self.mode.currentData()
        self.mode.setEnabled(self.shield_enabled)
        self.slider.setEnabled(self.shield_enabled and mode == 'blur')
        value = self.slider.value()
        strength = '较弱' if value < 16 else ('适中' if value < 40 else '较强')
        self.strength.setText('模糊强度：'+strength)
        self.strength.setEnabled(self.shield_enabled and mode == 'blur')
        descriptions = {
            'blur': '向右拖动使文字更难辨认；特别敏感的内容可选择深色遮挡。',
            'block': '使用不透明深色遮挡，仅作用于保护范围。',
            'off': '保留风险检测与提示，屏幕内容保持可见。',
        }
        self.explanation.setText(descriptions[mode] if self.shield_enabled else descriptions['off'])

    def _updated(self, *_):
        self._refresh()
        self.changed.emit(self.to_text())

    # 保留主程序/诊断代码的字符串接口；用户界面不再提供数字输入框。
    def text(self):
        return self.to_text()

    def setText(self, text):
        self.set_from_text(text)
