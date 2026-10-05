import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from app_shell import Backend
import runtime_paths


class PackagingRuntimeTests(unittest.TestCase):
    def test_windowless_status_channel_handles_fragmented_packets(self):
        backend = Backend()
        updates = []
        backend.updated.connect(updates.append)
        value = {'state':'running', 'detail':'虚构状态', 'alert':None}
        packet = ('VISION_SHIELD:'+json.dumps(value)+'\n').encode()
        backend.consume_status(packet[:13])
        self.assertEqual(updates, [])
        backend.consume_status(packet[13:]+packet)
        self.assertEqual(updates, [value, value])
        backend.stopping = True
        backend.consume_status(packet)
        self.assertEqual(len(updates), 2)

    def test_frozen_data_is_external_and_source_paths_stay_compatible(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with patch.object(runtime_paths.sys, 'frozen', True, create=True), \
                    patch.object(runtime_paths.sys, '_MEIPASS', str(root/'bundle'), create=True), \
                    patch.dict(runtime_paths.os.environ, {'LOCALAPPDATA':str(root/'user')}):
                self.assertEqual(runtime_paths.camera_root(), root/'bundle'/'视界盾开发')
                self.assertEqual(runtime_paths.owner_file(runtime_paths.camera_root()), root/'user'/'VisionShield'/'private'/'owner_templates.npz')
                self.assertEqual(runtime_paths.records_directory(), root/'user'/'VisionShield'/'records')
                self.assertFalse(runtime_paths.owner_file(runtime_paths.camera_root()).is_relative_to(runtime_paths.resource_root()))
            with patch.object(runtime_paths.sys, 'frozen', False, create=True):
                self.assertEqual(runtime_paths.owner_file(root), root/'private'/'owner_templates.npz')


if __name__ == '__main__':
    unittest.main()
