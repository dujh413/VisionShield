# 视界盾 Windows 测试版

本阶段交付包含 `VisionShield.exe` 与 `_internal` 依赖目录的便携测试版。双击 exe 使用，不需要目标电脑预装 Python。分发必须复制或解压整个 VisionShield 文件夹，不能只取 exe。主界面、托盘、设置、本人登记、摄像头风险检测、桌面OCR与遮蔽均使用同一入口。

## 数据与更新

2026-10-05体验修复版在主界面直接提供模糊化、陌生人弹窗、陌生人音效三个选项，运行中修改立即传给后台。聊天对话区可在暂停状态下校准，图片等应用支持整窗保护；机主短暂姿态丢失使用最多2秒有界宽限。具体操作、默认应用名单及限制见 `应用遮蔽与姿态容错方案_20261005.md`。

公共 YuNet、SFace 和默认 ONNX OCR 模型随软件打包，运行时无需下载模型。个人模板、原文、截图、运行日志、开发环境和模型缓存不打入包。

打包版的本人模板位于 `%LOCALAPPDATA%\VisionShield\private\owner_templates.npz`，运行元数据日志位于 `%LOCALAPPDATA%\VisionShield\records`。设置沿用当前 Windows 用户的 QSettings 配置。更新前退出软件，替换完整软件文件夹，用户数据保持原位置。源码模式保留原有模块内的数据路径；测试版不自动迁移源码里的机主模板，请本人在设置中明确登记。

## 重建

在 Windows x64 / Python 3.12 环境中准备 `packaging/requirements-build.txt`。RapidOCR会依赖CPU版onnxruntime，而DirectML版提供同名Python模块；安装依赖后最后执行 `python -m pip install --force-reinstall --no-deps onnxruntime-directml==1.24.4`，确认实际导入版本为1.24.4且提供DmlExecutionProvider。OpenCV实际导入版本应为4.10.0。将公共模型放到 spec 列出的两个模块 models 目录，运行：

```powershell
& .\packaging\Build.ps1 -Python '完整路径\python.exe' -OutputName 'windows-test-v2'
```

输出为 `dist\windows-test-v2\VisionShield\VisionShield.exe`。输出目录已存在时脚本拒绝覆盖，请换新名称。默认ONNX运行版不包含实验Paddle和MediaPipe依赖；已支持的摄像头和OCR整体流程不受影响。后续改源码、测试并同步仓库，再重建包；已发出的旧 exe 不会自动更新。

## 显式包验收

```powershell
& '.\dist\windows-test-v2\VisionShield\VisionShield.exe' --package-check '完整路径\package-check.json'
```

此模式检查轻量界面、后台本机通信、摄像头与OCR并行、两轮启动停止、虚构文字OCR和敏感规则、公共人脸模型、用户数据路径、采集排除与原生文字读取依赖。会打开摄像头、短暂验证遮罩，但不会登记本人或保存照片、桌面原文；它不代表真实机主识别准确率或跨电脑性能测试。默认日常启动不执行验收模式。

本机包和验收日志被 Git 忽略，仅同步源码、打包配置与说明。当前为未签名的开发测试版，尚未完成新电脑联合验收或制作正式安装器。
