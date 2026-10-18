# Windows便携版构建与验收

发行目录包含`VisionShield.exe`和`_internal`。使用者完整解压后运行EXE，无需Python，不能只复制EXE。当前发行版`v0.1.0-preview.3`使用统一原生界面、托盘及后台服务，下载权限与更新操作见[下载指南](下载与版本更新.md)。

## 构建条件

使用Windows x64、Python 3.12独立虚拟环境，以及`packaging/requirements-build.txt`。RapidOCR可能安装CPU版ONNX Runtime，与DirectML版共享模块名；按[协作指南](协作启动与同步.md)最后安装并验证DirectML，GPU不可用时软件保留CPU回退。

准备三个公共人脸ONNX模型和三个OCR ONNX模型，路径及名称由`packaging/VisionShield.spec`校验。模型准备脚本与发行包里的公共模型均可用于准备源码环境。个人模板、截图、聊天原文、日志和开发环境不打入包。公共模型及依赖的许可和对应源码分发不可省略。

## 构建与验收

```powershell
& .\packaging\Build.ps1 -Python '虚拟环境\Scripts\python.exe' -OutputName 'windows-新版本名称'
```

脚本依次执行PyInstaller构建、13项包验收和受限旧构建清理。同名输出已存在时拒绝覆盖；验收失败不清理旧包。验收需要本机摄像头和Windows桌面，会执行两轮实际启停、捕获排除、虚构OCR、公共人脸模型及范围追踪检查。请在设备可用时运行，不与其他摄像头测试同时执行。

生成路径为`dist/<OutputName>/VisionShield/VisionShield.exe`。软件目录必须整体分发，保留`_internal`。验收报告与凭证留在本机忽略目录，清理规则见[构建产物清理](构建验收与清理.md)。已有机主模板不会打入软件包，新使用者由本人在设置中登记。

使用[发行模板](../packaging/release/README.md)补齐许可、对应源码、版本清单和SHA256SUMS，生成新的私有Release附件。不覆盖旧版本附件，不自动将仓库改为公开。当前未签名便携版仍需更多Windows 10/11设备验收，正式安装器另行开发。

## 云端与实机的区别

[Windows云端工作流](Windows云端测试.md)可以验证私有下载、源码回归、虚构文字和空白图模型推理，以及下载版的预览启动。它没有实人和摄像头，不能代替上述13项本机包验收、持续双人检测或真实桌面防护测试。最近的云端证据见[验收报告](Windows云端验收报告_20261018.md)。
