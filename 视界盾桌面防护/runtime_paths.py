"""只读软件资源与可写用户数据分离；源码运行保留原有目录。"""
import os
from pathlib import Path
import sys


def resource_root():
    return Path(sys._MEIPASS) if getattr(sys, 'frozen', False) else Path(__file__).resolve().parents[1]


def desktop_root():
    return resource_root()/'视界盾桌面防护'


def camera_root():
    return resource_root()/'视界盾开发'


def user_root():
    return Path(os.environ.get('LOCALAPPDATA', str(Path.home())))/'VisionShield'


def owner_file(camera_directory):
    folder = user_root() if getattr(sys, 'frozen', False) else Path(camera_directory)
    return folder/'private'/'owner_templates.npz'


def records_directory():
    return (user_root() if getattr(sys, 'frozen', False) else desktop_root())/'records'
