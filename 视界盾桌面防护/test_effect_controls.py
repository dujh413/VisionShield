"""原生滑杆的用户选择、兼容接口和框选绑定测试。"""
import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import unittest
from unittest.mock import patch

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLineEdit, QSlider

from effect_controls import EffectControls
from scope_picker import ScopePicker


class EffectControlsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])

    def test_slider_outputs_compatible_radius_and_explains_strength(self):
        control=EffectControls()
        changes=[];control.changed.connect(changes.append)
        try:
            self.assertEqual(control.slider.orientation(),Qt.Horizontal)
            self.assertFalse(control.findChildren(QLineEdit))
            control.slider.setValue(2)
            self.assertEqual(control.to_text(),'2')
            self.assertIn('较弱',control.strength.text())
            control.slider.setValue(64)
            self.assertEqual(changes[-1],'64')
            self.assertIn('较强',control.strength.text())
            self.assertIn('向右拖动',control.explanation.text())
        finally:control.deleteLater()

    def test_legacy_unicode_and_out_of_range_values_become_slider_positions(self):
        control=EffectControls('８')
        try:
            self.assertEqual(control.slider.value(),8)
            self.assertEqual(control.to_text(),'8')
            control.set_from_text('999')
            self.assertEqual(control.to_text(),'64')
            control.set_from_text('0')
            self.assertEqual(control.to_text(),'2')
        finally:control.deleteLater()

    def test_block_disables_slider_and_off_is_only_available_when_requested(self):
        control=EffectControls('遮挡')
        diagnostic=EffectControls('',allow_off=True)
        try:
            self.assertEqual(control.to_text(),'遮挡')
            self.assertFalse(control.slider.isEnabled())
            self.assertIn('仅作用于保护范围',control.explanation.text())
            control.set_from_text('')
            self.assertEqual(control.to_text(),'24')
            self.assertEqual(control.mode.findData('off'),-1)
            self.assertEqual(diagnostic.to_text(),'')
            self.assertIn('仅检测与提示',diagnostic.mode.currentText())
        finally:control.deleteLater();diagnostic.deleteLater()

    def test_slider_drag_is_possible_without_keyboard_or_number_input(self):
        control=EffectControls('2');control.resize(400,140);control.show()
        try:
            self.app.processEvents()
            slider=control.slider
            QTest.mousePress(slider,Qt.LeftButton,pos=QPoint(8,slider.height()//2))
            QTest.mouseMove(slider,QPoint(slider.width()-12,slider.height()//2))
            QTest.mouseRelease(slider,Qt.LeftButton,pos=QPoint(slider.width()-12,slider.height()//2))
            self.assertGreater(slider.value(),2)
        finally:control.hide();control.deleteLater()


class ScopePickerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])

    def picker(self,whole=False):
        window={'mode':'lines','rect':(100,120,600,420),'client':(105,125,590,400),
                'key':'fake-app','handle':321,'pid':123}
        with patch('app_scope.window_inventory',return_value=[window]):
            return ScopePicker(whole)

    def test_whole_window_selection_binds_actual_window_and_process(self):
        picker=self.picker(True);picker.show()
        try:
            self.app.processEvents()
            point=QPoint(round(180/picker.ratio),round(200/picker.ratio))
            QTest.mouseClick(picker,Qt.LeftButton,pos=point)
            self.assertEqual(picker.result_profile,('fake-app',{'mode':'window','binding':{'handle':321,'pid':123}}))
            self.assertIn('仅保护点击的窗口',picker.instruction)
        finally:picker.hide();picker.deleteLater()

    def test_local_selection_has_clear_help_and_is_enrollment_request(self):
        picker=self.picker();picker.show()
        try:
            self.app.processEvents()
            start=QPoint(round(180/picker.ratio),round(200/picker.ratio))
            end=QPoint(round(440/picker.ratio),round(380/picker.ratio))
            QTest.mousePress(picker,Qt.LeftButton,pos=start)
            QTest.mouseMove(picker,end)
            QTest.mouseRelease(picker,Qt.LeftButton,pos=end)
            key,profile=picker.result_profile
            self.assertEqual(key,'fake-app')
            self.assertEqual(profile['command'],'enroll')
            self.assertEqual(profile['binding'],{'handle':321,'pid':123})
            self.assertIn('仅保护框选部分',picker.instruction)
            self.assertIn('按住鼠标拖动',picker.hint)
        finally:picker.hide();picker.deleteLater()


if __name__=='__main__':unittest.main()
