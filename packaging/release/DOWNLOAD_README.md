# 视界盾 · VisionShield 下载

面向公共学习与办公场景的 Windows 屏幕内容防护软件。源码仓库保持私有，本仓库只提供软件下载、使用说明和可复用封装模板。

## 下载 v0.1.0-preview.1

- [Windows x64 软件包](https://github.com/dujh413/VisionShield-Downloads/releases/download/v0.1.0-preview.1/VisionShield-Windows-x64-v0.1.0-preview.1.zip)
- [封装模板](https://github.com/dujh413/VisionShield-Downloads/releases/download/v0.1.0-preview.1/VisionShield-PackagingTemplate-v0.1.0-preview.1.zip)
- [第三方库对应源码](https://github.com/dujh413/VisionShield-Downloads/releases/download/v0.1.0-preview.1/VisionShield-ThirdParty-Sources-v0.1.0-preview.1.zip)
- [SHA256 校验文件](https://github.com/dujh413/VisionShield-Downloads/releases/download/v0.1.0-preview.1/VisionShield-v0.1.0-preview.1-SHA256SUMS.txt)
- [发行说明与附件列表](https://github.com/dujh413/VisionShield-Downloads/releases/tag/v0.1.0-preview.1)

在 Release 的 **Assets** 内选择带 `Windows-x64` 的ZIP。GitHub自动生成的Source code不是Windows软件包。此版本为预览版，发布状态和可下载附件以Release页面为准。

## 使用

完整解压ZIP，双击VisionShield.exe，并保留同目录的_internal。Windows 10/11 64位电脑无需安装Python，摄像头和模型由软件统一管理。首次使用在设置中由本人登记机主，选择遮蔽、音效和弹窗选项，再启用防护。

需要限定范围时，暂停防护后框选局部区域或点击目标整窗。关闭主窗口会留在托盘；完全退出使用托盘退出。更新前先退出旧版，解压到新文件夹，当前Windows用户的登记与设置保持原位置。

正常运行不保存摄像头画面、桌面截图或聊天原文；本人模板由使用者在自己的电脑上生成，不随软件提供。

## 预览版范围

主要验证主显示器的可见文字保护。严重模糊、遮挡和远处小脸仍可能漏检或误检，不能保证全部场景500ms响应。完整后端内存仍偏高，新电脑兼容及持续双人效果还需要更多实测。该版本未完成正式发布所需的全部验收。

包内提供使用说明、版本信息、公共模型摘要、第三方许可；Qt/PySide6及GEOS对应源码在同一Release提供。模板脚本采用MIT许可，依赖各自许可不变，私有业务源码不因模板许可而公开授权。

## 反馈

在 [Issues](https://github.com/dujh413/VisionShield-Downloads/issues) 提交版本、Windows版本、操作步骤及问题现象。不要上传个人面部模板、真实聊天、证件、验证码或其他私人内容。
