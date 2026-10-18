"""Download an authorized private preview release and smoke-test it on Windows.

Uses the runner's short-lived GH_TOKEN. Never copies developer credentials,
enrolls an owner, enables protection or opens the camera.
"""
import argparse
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile


class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, url):
        redirected = super().redirect_request(request, response, code, message, headers, url)
        if urllib.parse.urlparse(url).scheme != 'https':
            raise ValueError('Refusing a non-HTTPS asset redirect')
        if redirected and urllib.parse.urlparse(request.full_url).netloc != urllib.parse.urlparse(url).netloc:
            redirected.remove_header('Authorization')
        return redirected


def request(url, token, destination=None):
    if urllib.parse.urlparse(url).netloc != 'api.github.com':
        raise ValueError('Initial API request must target api.github.com')
    headers = {'User-Agent': 'VisionShield-Cloud-Check', 'Authorization': 'Bearer '+token,
               'Accept': 'application/octet-stream' if destination else 'application/vnd.github+json'}
    opener = urllib.request.build_opener(SafeRedirect())
    # Retry interrupted GETs with a fresh signed URL; never resume onto mixed bytes.
    for attempt in range(3):
        try:
            with opener.open(urllib.request.Request(url, headers=headers), timeout=60) as stream:
                if destination:
                    with destination.open('wb') as output:
                        while block := stream.read(1024*1024):
                            output.write(block)
                    return
                return json.load(stream)
        except (OSError, urllib.error.URLError) as error:
            if attempt == 2:
                code = getattr(error, 'code', None)
                raise RuntimeError(f'GitHub request failed (HTTP {code or "network error"})') from None
            time.sleep(2**attempt)


def select_release(releases, tag=None):
    choices = [item for item in releases if not item['draft'] and (not tag or item['tag_name'] == tag)]
    if not choices:
        raise ValueError('No accessible non-draft release; private downloads require repository access')
    return max(choices, key=lambda item: item.get('published_at') or item.get('created_at') or '')


def checksums(path):
    result = {}
    for line in path.read_text(encoding='utf-8-sig').splitlines():
        match = re.fullmatch(r'([0-9a-fA-F]{64})\s+\*?([^/\\:]+)', line.strip())
        if not match or match[2] in result:
            raise ValueError('Invalid or duplicate SHA256SUMS entry')
        result[match[2]] = match[1].lower()
    return result


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def validate_archive(archive):
    total = 0
    for info in archive.infolist():
        name = PurePosixPath(info.filename.replace('\\', '/'))
        if name.is_absolute() or '..' in name.parts or ':' in info.filename:
            raise ValueError('Unsafe archive path')
        if ((info.external_attr >> 16) & 0o170000) == 0o120000:
            raise ValueError('Archive contains a symbolic link')
        if info.filename.lower().endswith('.npz') or any(part.casefold() in {'private', 'records', '.venv'} for part in name.parts):
            raise ValueError('Private data in release archive')
        total += info.file_size
    if total > 6*1024**3:
        raise ValueError('Archive exceeds the extraction limit')
    if archive.testzip() is not None:
        raise ValueError('Archive CRC check failed')


def smoke(executable, root):
    if sys.platform != 'win32':
        raise RuntimeError('EXE startup verification requires Windows')
    data = root/'clean-user-data'
    data.mkdir()
    environment = dict(os.environ, LOCALAPPDATA=str(data), APPDATA=str(data))
    # Real Windows platform for the EXE; Qt offscreen is for source tests only.
    environment.pop('QT_QPA_PLATFORM', None)
    environment.pop('QT_PLUGIN_PATH', None)
    environment.pop('QT_QPA_PLATFORM_PLUGIN_PATH', None)
    user32 = ctypes.WinDLL('user32', use_last_error=True)
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    window = []
    process = subprocess.Popen([str(executable), '--preview'], cwd=executable.parent, env=environment)
    try:
        deadline = time.monotonic()+45
        while time.monotonic() < deadline and not window:
            if process.poll() is not None:
                raise RuntimeError(f'EXE exited before a main window appeared: {process.returncode}')

            @callback_type
            def inspect(handle, _):
                pid = wintypes.DWORD()
                thread = user32.GetWindowThreadProcessId(handle, ctypes.byref(pid))
                if pid.value == process.pid:
                    title = ctypes.create_unicode_buffer(512)
                    class_name = ctypes.create_unicode_buffer(256)
                    user32.GetWindowTextW(handle, title, len(title))
                    user32.GetClassNameW(handle, class_name, len(class_name))
                    if title.value == '视界盾' and class_name.value.startswith('Qt'):
                        window.append((handle, thread))
                return True

            user32.EnumWindows(inspect, 0)
            time.sleep(.25)
        if not window:
            raise RuntimeError('EXE did not create its main window')
        time.sleep(5)
        if process.poll() is not None:
            raise RuntimeError('EXE closed during its preview observation period')
        if list(data.rglob('*.npz')) or list(data.rglob('*error.log')):
            raise RuntimeError('Preview produced an identity template or an error log')
        # End the preview event loop without enabling protection or using a camera.
        if not user32.PostThreadMessageW(window[0][1], 0x0012, 0, 0):
            raise RuntimeError('Cannot request a clean preview exit')
        code = process.wait(timeout=15)
        if code != 0:
            raise RuntimeError(f'Preview exit was not clean: {code}')
        return {'main_window_created': True, 'survived_observation': True, 'clean_exit': True,
                'mode': '--preview', 'camera_tested': False, 'real_person_detection_tested': False}
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=10)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repository', default=os.environ.get('GITHUB_REPOSITORY', 'dujh413/VisionShield'))
    parser.add_argument('--tag')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--download-only', action='store_true')
    args = parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', args.repository):
        raise ValueError('Invalid repository')
    token = os.environ.get('GH_TOKEN') or os.environ.get('GITHUB_TOKEN')
    if not token:
        raise RuntimeError('An authorized GH_TOKEN is required for this private repository')
    root = args.output.resolve()
    root.mkdir(parents=True, exist_ok=False)
    report = {'repository': args.repository, 'passed': False, 'assets': []}
    try:
        api = f'https://api.github.com/repos/{args.repository}'
        releases = request(api+'/releases?per_page=100', token)
        release = select_release(releases, args.tag)
        report.update(tag=release['tag_name'], prerelease=release['prerelease'])
        assets = release['assets']
        sums = [a for a in assets if a['name'].endswith('-SHA256SUMS.txt')]
        packages = [a for a in assets if a['name'].startswith('VisionShield-Windows-x64-') and a['name'].endswith('.zip')]
        if len(sums) != 1 or len(packages) != 1:
            raise ValueError('Expected exactly one checksum file and Windows x64 package')
        chosen = sums + [a for a in assets if a['name'].endswith('.zip')]
        for asset in chosen:
            name = asset['name']
            if Path(name).name != name or '/' in name or '\\' in name or ':' in name:
                raise ValueError('Unsafe asset filename')
            destination = root/name
            request(f'{api}/releases/assets/{asset["id"]}', token, destination)
            if destination.stat().st_size != asset['size']:
                raise ValueError('Downloaded asset size mismatch')
            print(f'Downloaded {name}: {destination.stat().st_size} bytes', flush=True)
        expected = checksums(root/sums[0]['name'])
        for asset in chosen:
            file = root/asset['name']
            digest = sha(file)
            if file.suffix == '.zip':
                if expected.get(file.name) != digest:
                    raise ValueError('Release SHA256 mismatch')
                with zipfile.ZipFile(file) as archive:
                    validate_archive(archive)
            report['assets'].append({'name': file.name, 'bytes': file.stat().st_size, 'sha256': digest})
        package = root/packages[0]['name']
        unpacked = root/'unpacked'
        with zipfile.ZipFile(package) as archive:
            archive.extractall(unpacked)  # Paths, link types and CRCs were checked above.
        executable = unpacked/'VisionShield'/'VisionShield.exe'
        if not executable.is_file() or not (executable.parent/'_internal').is_dir():
            raise ValueError('Portable package is incomplete')
        manifest = json.loads((executable.parent/'release-manifest.json').read_text(encoding='utf-8-sig'))
        if sha(executable) != manifest['exe_sha256']:
            raise ValueError('Executable does not match the embedded manifest')
        for relative, digest in manifest['public_models'].items():
            model = (executable.parent/relative).resolve()
            if not model.is_relative_to(executable.parent.resolve()) or sha(model) != digest:
                raise ValueError('Bundled model does not match the embedded manifest')
        report['release_source_commit'] = manifest['source_commit']
        report['public_models_checked'] = len(manifest['public_models'])
        if not args.download_only:
            report['startup'] = smoke(executable, root)
        report['passed'] = True
    except Exception as error:
        report['error'] = str(error)
        raise
    finally:
        (root/'cloud-report.json').write_text(json.dumps(report, ensure_ascii=True, indent=2), encoding='utf-8')
        print(json.dumps(report, ensure_ascii=True), flush=True)


if __name__ == '__main__':
    main()
