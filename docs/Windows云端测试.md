# Windows 云端测试与下载验证

## 项目基本信息

视界盾（VisionShield）是面向公共学习和办公场景的 Windows 屏幕内容防护软件。统一入口为 `VisionShield.py`，使用原生 PySide6 界面，可驻留托盘。启用后摄像头与屏幕文字识别在独立后端中并行运行；暂停后释放采集和模型资源。

人脸部分使用 YuNet 检测和 SFace 机主特征比对；文字部分使用 RapidOCR、PP-OCRv4 ONNX 模型和格式／上下文规则。DirectML 可用时使用显卡，否则回退 CPU。机主登记由本人操作，日常重新识别不需要重复登记。

软件支持用户选择局部或具体整窗范围，主界面水平滑杆调整模糊程度，也可改为深色遮挡。遮蔽、音效、弹窗独立配置。风险稳定消失后恢复。所选局部追踪失配时暂停该选区并提示重选，不擅自扩大保护范围。普通屏幕的遮蔽效果对机主也可见，并非按观看角度防窥。

当前已发行的软件版本是 `v0.1.0`，适用于 Windows 10/11 x64，完整 ZIP 含 EXE、`_internal`、公共模型和许可，使用者无需安装 Python。源码后续提交不自动更新已发行 EXE，具体二进制来源以包内 `release-manifest.json` 为准。

仓库与Release公开可读，软件ZIP可直接下载。默认不保存摄像头画面、桌面截图或聊天原文；机主特征模板、设置及运行元数据保存在使用者电脑。模板目前未增加应用层加密。

## 新建云端环境

本仓库提供 GitHub Actions 工作流 `.github/workflows/windows-cloud-check.yml`，每次手动运行使用新的 Windows Server 2022 托管运行器和 Python 3.12。无需把本机登录凭据、机主模板、真实聊天或开发环境上传到运行器。

有权限的维护者打开仓库 **Actions → Windows cloud verification → Run workflow**。版本参数留空时从非草稿发行中选择最近发布的一项，包含预览版；也可填写具体标签。不要使用只查正式版的 `releases/latest` 接口判断本项目是否存在预览版。

工作流只授予临时 `GITHUB_TOKEN` 的 `contents: read` 权限，不写仓库、修改权限、登记机主或启用摄像头。云端运行消耗账号的 Actions 额度，受账号可用额度和 GitHub 服务状态影响。

## 验证内容

1. 在独立 Python 环境安装 CPU 测试依赖，运行桌面、人脸和下载逻辑回归测试。GPU 真机测试默认跳过。
2. 使用当前仓库的临时令牌实际下载 Release 的 Windows 软件 ZIP、封装模板 ZIP、第三方源码 ZIP 和校验文件；跨域重定向不转发令牌。
3. 比对文件大小、SHA256、ZIP CRC，拒绝路径穿越、符号链接和机主模板等私人文件；完整解压 Windows 包。
4. 核对包内清单中的 EXE 和公共模型摘要，记录二进制对应的源码提交。使用下载的公共模型在CPU上识别虚构手机／邮箱样本、执行YuNet空白图推理和SFace有限输出检查；不使用个人图像。
5. 在 Windows 中以 `--preview` 启动下载的 EXE，确认原生 Qt 主窗口创建并维持运行，再请求退出事件循环，检查退出码。不会启用真实防护或打开摄像头。
6. 保存不含个人数据的 `cloud-report.json` 为 Actions artifact，保留 14 天。不上传解压软件、运行画面或个人数据。

本机只检查下载可使用：

```powershell
# GH_TOKEN 在当前进程中预先安全配置，不要写入源码或把令牌发到聊天。
python packaging/cloud_release_check.py --output test_artifacts/private-download-check --download-only
```

输出目录必须不存在，避免覆盖已有验收证据。在 Windows 中省略 `--download-only` 会额外运行 EXE 预览测试。

## 结果边界

云端预览启动检查不能替代双人实测、摄像头兼容性、实际桌面捕获排除或真实遮蔽验证。托管运行器没有可用于本项目的真实摄像头和实际使用者；不能据此声称身后旁人识别已解决。Windows Server 上通过也不等于所有 Windows 10/11 机器均兼容。

当前仍待完善：远处小脸、模糊及遮挡下的持续双人检测；完整后端内存占用；更多设备兼容和端到端延迟验证。现阶段不承诺全部场景 500ms 响应，也未实现通用私人聊天语义分类。

每次验证结果以对应Actions运行记录及其cloud-report.json为准。

公开下载不要求协作者权限。出现404时检查版本标签和附件名称；旧版本源码不会自动生成新的软件附件。
