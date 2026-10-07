# 视界盾封装模板

此模板生成 Windows x64 便携软件、第三方库对应源码包、封装模板 ZIP 和 SHA256 校验文件。普通使用者下载软件后完整解压并运行 VisionShield.exe，无需 Python；模板供维护者构建后续版本。

## 构建

将本目录放入私有源码仓库的 `packaging/release`。准备 `packaging/requirements-build.txt` 所列环境、公共模型和第三方库对应源码归档。源码归档目录包含 `sources.json`，每项为 `name`、`url`、`sha256`、`bytes`；归档版本须与实际随包库一致。归档仅用于许可及可替换库的对应源码分发，不执行其中代码。

```powershell
& .\packaging\release\Build-Public.ps1 -Repository '你的源码仓库完整路径' -Python '构建环境的python.exe完整路径' -SourceArchiveDirectory '第三方源码归档目录完整路径' -Version '0.1.0-preview.2'
```

`Build.ps1` 完成 EXE 构建、13项包验收和受限旧构建清理。随后模板补齐许可、生成文件摘要并排除个人模板、截图、日志和开发环境。输出在仓库 `dist` 下；相同版本资产存在时拒绝覆盖。

## 发布

在公开下载仓库创建与版本对应的 GitHub Release，上传生成的软件 ZIP、第三方源码 ZIP、模板 ZIP 和 SHA256SUMS 文件。预览版本选择 pre-release。Git 自动生成的 Source code 只包含下载仓库文件，软件位于 Assets 内带 Windows-x64 的 ZIP。

项目源码保留在私有仓库。不要将个人模板、设备日志、截图、环境或模型缓存提交至 Git；公共模型仅随已检查的软件发行包提供。

模板脚本采用本目录 `LICENSE` 中的 MIT 许可，该许可不适用于视界盾私有业务源码；依赖和模型分别遵循各自许可。
