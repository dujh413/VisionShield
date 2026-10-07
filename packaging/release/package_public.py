"""Prepare a verified portable Windows release without personal data."""
import argparse
import hashlib
import importlib.metadata as metadata
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import zipfile


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def archive_files(destination, files):
    with zipfile.ZipFile(destination, 'x', zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path, name in files:
            archive.write(path, name)
    with zipfile.ZipFile(destination) as archive:
        if archive.testzip() is not None:
            raise RuntimeError('Archive integrity check failed')


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--repository',required=True,type=Path)
    parser.add_argument('--output-name',required=True)
    parser.add_argument('--version',required=True)
    parser.add_argument('--source-archives',required=True,type=Path)
    args=parser.parse_args()
    if not re.fullmatch(r'\d+\.\d+\.\d+(?:-(?:preview|alpha|beta)\.\d+)?',args.version):
        raise ValueError('Invalid version')
    if not re.fullmatch(r'windows-[A-Za-z0-9_-]+',args.output_name):
        raise ValueError('Invalid output name')
    root=args.repository.resolve()
    folder=root/'dist'/args.output_name/'VisionShield'
    receipt=json.loads((root/'dist/.verified'/f'{args.output_name}.json').read_text(encoding='utf-8-sig'))
    if not receipt['passed'] or receipt['output_name']!=args.output_name or sha(folder/'VisionShield.exe').upper()!=receipt['exe_sha256'].upper():
        raise RuntimeError('A matching verified package is required')
    prohibited={'qt6pdf.dll','qt6virtualkeyboard.dll','qpdf.dll','qtvirtualkeyboardplugin.dll'}
    for path in folder.rglob('*'):
        if path.is_symlink() or path.is_junction():raise RuntimeError('Reparse point in package')
        if any(part.casefold() in {'private','records','.venv','test_artifacts'} for part in path.relative_to(folder).parts) or path.suffix.casefold()=='.npz':
            raise RuntimeError('Private data in package')
        if path.name.casefold() in prohibited or path.name.casefold().startswith(('qt6qml','qt6quick','opencv_videoio_ffmpeg')):
            raise RuntimeError('Unused component in package')
    tag='v'+args.version
    destination=root/'dist'/f'VisionShield-Windows-x64-{tag}.zip'
    template_zip=root/'dist'/f'VisionShield-PackagingTemplate-{tag}.zip'
    sources_zip=root/'dist'/f'VisionShield-ThirdParty-Sources-{tag}.zip'
    checksum_file=root/'dist'/f'VisionShield-{tag}-SHA256SUMS.txt'
    if any(p.exists() for p in (destination,template_zip,sources_zip,checksum_file)):
        raise FileExistsError('Version assets already exist')

    template=Path(__file__).resolve().parent
    for name,target in (('QUICK_START.md','README.md'),('THIRD_PARTY_NOTICES.md','THIRD_PARTY_NOTICES.md')):
        shutil.copyfile(template/name,folder/target)
    licenses=folder/'LICENSES';licenses.mkdir(exist_ok=True)
    for path in (template/'licenses').glob('*.txt'):shutil.copyfile(path,licenses/path.name)
    shutil.copyfile(root/'packaging/YuNet-LICENSE.txt',licenses/'YuNet-LICENSE.txt')
    packages=('PySide6','PySide6_Essentials','shiboken6','numpy','opencv-python','onnxruntime-directml',
              'rapidocr_onnxruntime','mss','uiautomation','comtypes','Pillow','pyinstaller','shapely',
              'packaging','pyclipper','PyYAML','flatbuffers','sympy','mpmath')
    versions={}
    for name in packages:
        distribution=metadata.distribution(name);versions[name]=distribution.version
        for entry in distribution.files or []:
            relative=str(entry).lower()
            if not any(word in relative for word in ('license','copying','notice')):continue
            source=Path(distribution.locate_file(entry))
            if source.is_file() and source.suffix.lower() in ('','.txt','.md'):
                target=licenses/name/Path(entry)
                # Distribution records may contain paths outside site-packages.
                if '..' in Path(entry).parts:continue
                target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,target)
    python_license=Path(sys.base_prefix)/'LICENSE.txt'
    if python_license.is_file():shutil.copyfile(python_license,licenses/'Python-LICENSE.txt')

    sources=args.source_archives.resolve()
    source_records=json.loads((sources/'sources.json').read_text(encoding='utf-8'))
    import PySide6,shapely,cv2
    required={f'qtbase-everywhere-src-{PySide6.__version__}.tar.xz',f'qtsvg-everywhere-src-{PySide6.__version__}.tar.xz',
              f'qtimageformats-everywhere-src-{PySide6.__version__}.tar.xz',f'pyside-setup-everywhere-src-{PySide6.__version__}.tar.xz',
              f'geos-{shapely.geos_version_string}.tar.bz2'}
    if not required.issubset({r['name'] for r in source_records}):raise RuntimeError('Missing corresponding source version')
    source_files=[]
    for item in source_records:
        if Path(item['name']).name!=item['name']:raise ValueError('Invalid source filename')
        path=sources/item['name']
        if path.is_symlink() or sha(path)!=item['sha256'] or path.stat().st_size!=item['bytes']:
            raise RuntimeError('Source archive mismatch')
        source_files.append((path,path.name))
        with tarfile.open(path) as archive:
            for member in archive.getmembers():
                parts=Path(member.name).parts
                if not member.isfile() or member.size>1024*1024:continue
                if 'LICENSES' not in parts and Path(member.name).name not in {'COPYING','COPYING.LESSER','LICENSE'}:continue
                target=licenses/'corresponding-sources'/item['name']/(hashlib.sha1(member.name.encode()).hexdigest()[:10]+'-'+Path(member.name).name)
                if '..' in parts or Path(member.name).is_absolute():continue
                target.parent.mkdir(parents=True,exist_ok=True)
                with archive.extractfile(member) as stream:target.write_bytes(stream.read())
    versions['opencv-python']=cv2.__version__
    versions['python']=sys.version.split()[0]
    source_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=root).decode().strip()
    models={str(p.relative_to(folder)):sha(p) for p in folder.rglob('*.onnx')}
    manifest={'version':args.version,'platform':'Windows-x64','source_commit':source_commit,
              'source_dirty':bool(subprocess.check_output(['git','status','--porcelain'],cwd=root).strip()),
              'package_checks':13,'exe_sha256':sha(folder/'VisionShield.exe'),'runtime_versions':versions,'public_models':models}
    (folder/'release-manifest.json').write_text(json.dumps(manifest,ensure_ascii=True,indent=2),encoding='utf-8')
    files=[(p,'VisionShield/'+p.relative_to(folder).as_posix()) for p in folder.rglob('*') if p.is_file()]
    archive_files(destination,files)
    archive_files(template_zip,[(p,'VisionShield-PackagingTemplate/'+p.relative_to(template).as_posix())
                               for p in template.rglob('*') if p.is_file() and '__pycache__' not in p.parts])
    archive_files(sources_zip,source_files+[(sources/'sources.json','sources.json')])
    checksum_file.write_text(''.join(f'{sha(p)}  {p.name}\n' for p in (destination,template_zip,sources_zip)),encoding='ascii')
    result={'version':args.version,'source_commit':source_commit,'private_data_included':False,'assets':[
        {'name':p.name,'bytes':p.stat().st_size,'sha256':sha(p)} for p in (destination,template_zip,sources_zip,checksum_file)]}
    evidence=root/'test_artifacts'/f'public-release-{args.version}.json'
    evidence.write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result),flush=True)


if __name__=='__main__':main()
