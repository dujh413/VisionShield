"""轻量原生效果选择；不加载图像库或识别模型。"""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QButtonGroup, QComboBox, QHBoxLayout, QLabel, QPushButton, QSlider, QVBoxLayout, QWidget

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
        self.slider.setMinimumHeight(28)
        self.slider.setValue(DEFAULT_BLUR_RADIUS)
        self.strength = QLabel()
        self.strength.setObjectName('summaryLabel')
        self.live_hint = QLabel('拖动后立即生效')
        self.live_hint.setObjectName('caption')
        self.explanation = QLabel()
        self.explanation.setObjectName('caption')
        self.explanation.setWordWrap(True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        row = QHBoxLayout()
        label = QLabel('遮蔽方式')
        label.setObjectName('summaryLabel')
        row.addWidget(label)
        self.mode_buttons = {}
        self.mode_group = QButtonGroup(self)
        if allow_off:
            row.addWidget(self.mode, 1)
        else:
            self.mode.setParent(self)
            self.mode.hide()
            row.addSpacing(16)
            for mode, title in (('blur', '模糊'), ('block', '深色')):
                button = QPushButton(title)
                button.setObjectName('segment')
                button.setCheckable(True)
                button.setAccessibleName('遮蔽方式：'+title)
                button.clicked.connect(lambda checked, value=mode: self.mode.setCurrentIndex(self.mode.findData(value)))
                self.mode_group.addButton(button)
                self.mode_buttons[mode] = button
                row.addWidget(button)
            row.addStretch()
        layout.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(self.strength)
        row.addStretch()
        row.addWidget(self.live_hint)
        layout.addLayout(row)
        layout.addWidget(self.slider)
        row = QHBoxLayout()
        row.addWidget(QLabel('弱'))
        row.addStretch()
        row.addWidget(QLabel('强'))
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
        for value, button in self.mode_buttons.items():
            button.setChecked(value == mode)
            button.setEnabled(self.shield_enabled)
        self.slider.setEnabled(self.shield_enabled and mode == 'blur')
        value = self.slider.value()
        strength = '较弱' if value < 16 else ('适中' if value < 40 else '较强')
        self.strength.setText('模糊程度 · '+strength)
        self.strength.setEnabled(self.shield_enabled and mode == 'blur')
        self.live_hint.setText('拖动后立即生效' if mode == 'blur' and self.shield_enabled else '当前未使用模糊')
        descriptions = {
            'blur': '向右拖动增强；较弱模糊可能仍可读。',
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
