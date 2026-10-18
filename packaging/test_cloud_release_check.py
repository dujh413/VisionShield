import io
from pathlib import Path
import tempfile
import unittest
import urllib.request
import zipfile

from cloud_release_check import SafeRedirect, checksums, select_release, validate_archive


class CloudDownloadTests(unittest.TestCase):
    def test_newest_preview_is_selectable_without_a_stable_release(self):
        releases = [{'tag_name':'v1-preview.1', 'draft':False, 'published_at':'2026-10-01'},
                    {'tag_name':'draft', 'draft':True, 'published_at':'2026-10-20'},
                    {'tag_name':'v1-preview.2', 'draft':False, 'published_at':'2026-10-02'}]
        self.assertEqual(select_release(releases)['tag_name'], 'v1-preview.2')
        self.assertEqual(select_release(releases, 'v1-preview.1')['tag_name'], 'v1-preview.1')
        with self.assertRaises(ValueError):
            select_release(releases, 'missing')

    def test_private_token_never_follows_a_cross_host_redirect(self):
        request = urllib.request.Request('https://api.github.com/asset', headers={'Authorization':'Bearer fictional'})
        redirect = SafeRedirect().redirect_request(request, None, 302, 'Found', {}, 'https://release-assets.githubusercontent.com/asset')
        self.assertIsNone(redirect.get_header('Authorization'))
        with self.assertRaises(ValueError):
            SafeRedirect().redirect_request(request, None, 302, 'Found', {}, 'http://example.com/asset')

    def test_checksum_file_rejects_traversal_and_duplicate_names(self):
        with tempfile.TemporaryDirectory() as folder:
            file = Path(folder)/'SHA256SUMS.txt'
            good = 'a'*64+'  sample.zip\n'
            file.write_text(good, encoding='ascii')
            self.assertEqual(checksums(file), {'sample.zip':'a'*64})
            for bad in (good+good, 'a'*64+'  ../sample.zip\n', 'not a hash'):
                file.write_text(bad, encoding='ascii')
                with self.assertRaises(ValueError):
                    checksums(file)

    def test_archive_rejects_escape_and_private_templates(self):
        for name in ('../escape.txt', 'C:/escape.txt', 'VisionShield/private/data.txt', 'VisionShield/owner.npz'):
            memory = io.BytesIO()
            with zipfile.ZipFile(memory, 'w') as archive:
                archive.writestr(name, 'fictional')
            memory.seek(0)
            with zipfile.ZipFile(memory) as archive, self.assertRaises(ValueError):
                validate_archive(archive)


if __name__ == '__main__':
    unittest.main()
