"""Window-selection races use fictional inventory; no desktop or camera reads."""
import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from PySide6.QtCore import QPointF, Qt
from PySide6.QtWidgets import QApplication
from scope_picker import ScopePicker


def window(handle=1,pid=11,key='a.exe|A',rect=(100,100,500,400),client=None,mode='lines'):
    return {'handle':handle,'pid':pid,'key':key,'rect':rect,'client':client or rect,'mode':mode}


class ScopePickerRaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])

    def make_picker(self,whole=False):
        self.inventory=[window()]
        self.reader=patch('app_scope.window_inventory',side_effect=lambda *args:list(self.inventory))
        self.reader_mock=self.reader.start();self.addCleanup(self.reader.stop)
        picker=ScopePicker(whole)
        self.addCleanup(picker.deleteLater)
        self.addCleanup(picker.close)
        return picker

    def event(self,picker,x=130,y=130):
        return SimpleNamespace(button=lambda:Qt.LeftButton,
                               position=lambda:QPointF(x/picker.ratio,y/picker.ratio))

    def assert_cancelled(self,picker):
        self.assertIsNone(picker.result_profile)
        self.assertIsNone(picker.first)
        self.assertIsNone(picker.pressed_window)
        self.assertIn('重新',picker.notice)

    def test_whole_click_refreshes_inventory_after_selector_opens(self):
        picker=self.make_picker(True)
        self.inventory=[window(2,22,'b.exe|B'),window(rect=(700,100,500,400))]
        event=self.event(picker)
        picker.mousePressEvent(event);picker.mouseReleaseEvent(event)
        self.assertEqual(picker.result_profile,('b.exe|B',{'mode':'window','binding':{'handle':2,'pid':22}}))
        self.assertEqual(self.reader_mock.call_count,3)

    def test_whole_release_cancels_when_another_window_takes_clicked_position(self):
        picker=self.make_picker(True);event=self.event(picker)
        picker.mousePressEvent(event)
        self.inventory=[window(2,22,'b.exe|B'),window(rect=(700,100,500,400))]
        picker.mouseReleaseEvent(event)
        self.assert_cancelled(picker)

    def test_whole_click_can_bind_same_window_at_its_current_position(self):
        picker=self.make_picker(True);event=self.event(picker)
        picker.mousePressEvent(event)
        self.inventory=[window(rect=(110,110,500,400))]
        picker.mouseReleaseEvent(event)
        self.assertEqual(picker.result_profile,('a.exe|A',{'mode':'window','binding':{'handle':1,'pid':11}}))

    def test_whole_drag_onto_another_window_does_not_select_down_window(self):
        picker=self.make_picker(True)
        self.inventory.append(window(2,22,'b.exe|B',rect=(650,100,100,200)))
        picker.mousePressEvent(self.event(picker))
        picker.mouseReleaseEvent(self.event(picker,680,130))
        self.assert_cancelled(picker)

    def test_local_stable_drag_keeps_exact_fraction_of_selected_client(self):
        picker=self.make_picker()
        picker.mousePressEvent(self.event(picker))
        picker.mouseReleaseEvent(self.event(picker,230,210))
        key,profile=picker.result_profile
        self.assertEqual(key,'a.exe|A')
        self.assertEqual(profile['binding'],{'handle':1,'pid':11})
        self.assertEqual(profile['region'],[.06,.075,.2,.2])

    def test_local_drag_cancels_outer_or_client_geometry_changes(self):
        variants=(window(rect=(110,100,500,400)),window(rect=(100,100,510,400)),
                  window(client=(105,100,495,400)),window(client=(100,100,500,390)))
        for changed in variants:
            with self.subTest(window=changed):
                picker=self.make_picker()
                picker.mousePressEvent(self.event(picker))
                self.inventory=[changed]
                picker.mouseReleaseEvent(self.event(picker,230,210))
                self.assert_cancelled(picker)

    def test_local_drag_snapshot_is_independent_of_inventory_dictionary_mutation(self):
        picker=self.make_picker()
        picker.mousePressEvent(self.event(picker))
        self.inventory[0]['client']=(110,100,490,400)
        picker.mouseReleaseEvent(self.event(picker,230,210))
        self.assert_cancelled(picker)

    def test_local_drag_cancels_when_start_point_is_covered_by_different_window(self):
        picker=self.make_picker()
        picker.mousePressEvent(self.event(picker))
        self.inventory.insert(0,window(2,22,'b.exe|B',rect=(120,120,50,50)))
        picker.mouseReleaseEvent(self.event(picker,230,210))
        self.assert_cancelled(picker)

    def test_reused_handle_with_different_process_cancels_both_modes(self):
        for whole in (False,True):
            with self.subTest(whole=whole):
                picker=self.make_picker(whole)
                picker.mousePressEvent(self.event(picker))
                self.inventory=[window(pid=99)]
                picker.mouseReleaseEvent(self.event(picker,230,210))
                self.assert_cancelled(picker)

    def test_window_disappearing_before_release_cancels_both_modes(self):
        for whole in (False,True):
            with self.subTest(whole=whole):
                picker=self.make_picker(whole)
                picker.mousePressEvent(self.event(picker))
                self.inventory=[]
                picker.mouseReleaseEvent(self.event(picker,230,210))
                self.assert_cancelled(picker)

    def test_unavailable_inventory_cancels_without_retaining_prior_selection(self):
        for stage in ('press','release'):
            with self.subTest(stage=stage):
                picker=self.make_picker(True)
                if stage=='release':picker.mousePressEvent(self.event(picker))
                with patch.object(picker,'read_windows',side_effect=OSError('fictional enumeration failure')):
                    getattr(picker,'mousePressEvent' if stage=='press' else 'mouseReleaseEvent')(self.event(picker))
                self.assert_cancelled(picker)

    def test_selector_own_window_stays_ignored_by_current_inventory(self):
        picker=self.make_picker(True)
        self.inventory.insert(0,window(picker.selection_handle,88,'own',rect=(0,0,800,800),mode='ignore'))
        event=self.event(picker)
        picker.mousePressEvent(event);picker.mouseReleaseEvent(event)
        self.assertEqual(picker.result_profile[1]['binding'],{'handle':1,'pid':11})

    def test_ignored_foreground_surface_cannot_redirect_click_to_underlying_app(self):
        for whole in (False,True):
            with self.subTest(whole=whole):
                picker=self.make_picker(whole)
                self.inventory.insert(0,window(picker.selection_handle+100,88,'own-other',rect=(0,0,800,800),mode='ignore'))
                event=self.event(picker)
                picker.mousePressEvent(event);picker.mouseReleaseEvent(event)
                self.assert_cancelled(picker)


if __name__=='__main__':unittest.main()
