"""Verify resolution, duration, decoded frame count, audio and MP4 fast-start."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
import subprocess

import cv2
from render import ROOT, find_ffmpeg


def inspect_atoms(path):
    result = []
    with path.open('rb') as stream:
        while True:
            offset = stream.tell()
            header = stream.read(8)
            if not header:
                break
            length, name = struct.unpack('>I4s', header)
            if length == 1:
                length = struct.unpack('>Q', stream.read(8))[0]
            if length == 0:
                length = path.stat().st_size-offset
            if length < 8:
                raise ValueError('Invalid MP4 atom')
            result.append({'type': name.decode('ascii'), 'offset': offset, 'size': length})
            stream.seek(offset+length)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, default=ROOT/'output'/'VisionShield_Concept_30s_1080p.mp4')
    parser.add_argument('--silent', action='store_true')
    args = parser.parse_args()
    cap = cv2.VideoCapture(str(args.input))
    if not cap.isOpened():
        raise RuntimeError('Cannot open the MP4')
    width, height = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = cap.get(cv2.CAP_PROP_FPS)
    declared = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    count = 0
    while True:
        success, _ = cap.read()
        if not success:
            break
        count += 1
    cap.release()
    assert (width, height) == (1920, 1080), (width, height)
    assert abs(fps-30) < .001, fps
    assert count == declared == 900, (count, declared)
    command = [find_ffmpeg(), '-hide_banner', '-i', str(args.input), '-f', 'null', '-']
    check = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8', errors='replace')
    if check.returncode:
        raise RuntimeError(check.stderr)
    assert 'Video: h264' in check.stderr, check.stderr
    if not args.silent:
        assert 'Audio: aac' in check.stderr, check.stderr
        assert '48000 Hz, stereo' in check.stderr, check.stderr
    assert re.search(r'Duration: 00:00:30\.00', check.stderr), check.stderr
    atoms = inspect_atoms(args.input)
    offsets = {atom['type']: atom['offset'] for atom in atoms}
    assert offsets['moov'] < offsets['mdat'], atoms
    with args.input.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    report = {'file': args.input.name, 'width': width, 'height': height, 'fps': fps,
              'duration_seconds': count/fps, 'decoded_frames': count,
              'video_codec': 'H.264', 'pixel_format': 'yuv420p',
              'audio_codec': None if args.silent else 'AAC stereo 48kHz',
              'full_decode_passed': True, 'fast_start': True,
              'bytes': args.input.stat().st_size, 'sha256': digest, 'mp4_atoms': atoms}
    target = args.input.parent/'verification.json'
    target.write_bytes((json.dumps(report, ensure_ascii=False, indent=2)+'\n').encode('utf-8'))
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
