# A：10 月 1 日摄像头与多人检测操作指南

> 日期：2026 年 10 月 1 日  
> 对应场景：公共学习空间敏感材料保护  
> 今天的目标：摄像头能读、至少两张脸能输出、结果与耗时有记录。  
> 本目录是起步代码，实际真人和摄像头运行需要按以下步骤验收。

> 已跑通的环境和感知无需重复准备。最新接续路线见[场景方案第24节](../视界盾项目完整实施方案_场景创新赛道.md)：先补多人验收、跨帧跟踪、手动机主选择与丢失回退，再形成防护闭环，最后增加持久机主验证。

## 1. 你现在已有的文件

| 文件 | 用途 |
|---|---|
| check_environment.py | 检查解释器、库、模型路径并保存环境记录 |
| camera_test.py | 显示摄像头画面，按 Q / Esc 或关窗口退出 |
| face_test.py | 实时显示多人关键点、人数和推理耗时，保存匿名数值日志 |
| requirements-a.txt | A 今天的依赖；使用有界面的 OpenCV 发行包 |

脚本不保存照片和录像。界面上的 frame face 1、2 只是当前帧显示编号，不能当作稳定人物身份，也不能用于判定主要使用者。

## 2. 先检查设备（约 10 分钟）

1. 打开 Windows 的相机应用，确认有画面。
2. 关闭相机、视频会议、其他可能占用摄像头的应用。
3. 让电脑固定在之后实验的摆放位置，使用正面正常光照。
4. 如果相机应用打不开，先处理设备或权限，不继续安装算法。

Windows 摄像头问题优先查看设置中的隐私与摄像头权限，确认桌面应用可访问。不同系统版本菜单名称可能略有差别。

## 3. 建立项目环境（约 20—40 分钟）

电脑上已发现 Python 3.12、VS Code 和 Git。A、B 共用下面的项目环境，今天先安装 A 所需的库；B 后续在同一环境增加界面依赖。

打开 PowerShell。下面每一段单独执行，前一步成功后继续。

```powershell
Set-Location -LiteralPath 'D:\ai比赛\VisionShield\视界盾开发'
```

```powershell
py -3.12 -m venv .venv
```

```powershell
.\.venv\Scripts\python.exe -m pip install --upgrade pip
```

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-a.txt
```

```powershell
.\.venv\Scripts\python.exe check_environment.py
```

成功标准：virtual_environment 为 true，cv2 和 mediapipe 的 import 为 OK。model_exists 此时可为 false，下一步下载模型。

无需激活虚拟环境或修改 PowerShell 执行策略，直接调用环境内 Python 即可。安装失败时保留完整错误，先解决兼容或网络问题；不要往全局 Python 里混装多个 OpenCV 包。opencv-python、opencv-contrib-python 与对应 headless 包使用同一个 cv2 命名空间，本环境只选择一个有界面的发行包。

## 4. 下载官方模型（约 5—15 分钟）

先创建目录：

```powershell
New-Item -ItemType Directory -Force -Path '.\models'
```

模型地址来自官方 Face Landmarker 模型页面：

```powershell
Invoke-WebRequest -Uri 'https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/latest/face_landmarker.task' -OutFile '.\models\face_landmarker.task'
```

```powershell
Get-Item -LiteralPath '.\models\face_landmarker.task'
```

```powershell
.\.venv\Scripts\python.exe check_environment.py
```

成功标准：文件存在，model_exists 为 true；有效性还需模型实际加载验证。下载遇到网络问题时，可在浏览器打开[官方模型页](https://developers.google.com/edge/mediapipe/solutions/vision/face_landmarker/index)，从 Models 表格下载 FaceLandmarker，保存为上述路径。不要把下载错误页面当作模型文件。

latest 地址可能更新。通过验收后保存模型校验值和实际依赖版本，不在正式测试中替换：

```powershell
Get-FileHash -LiteralPath '.\models\face_landmarker.task' -Algorithm SHA256 | Out-File -LiteralPath '.\records\model_sha256.txt' -Encoding utf8
```

```powershell
.\.venv\Scripts\python.exe -m pip freeze | Out-File -LiteralPath '.\requirements-locked.txt' -Encoding utf8
```

## 5. 先跑摄像头测试（约 15 分钟）

```powershell
.\.venv\Scripts\python.exe camera_test.py
```

你应该看到实时画面、分辨率和处理循环 FPS。持续观察约 1 分钟，移动身体，检查画面是否持续更新；按 Q / Esc 退出，再运行一次确认摄像头已释放。

若设备编号 0 错误，可以逐个尝试已有设备编号，例如：

```powershell
.\.venv\Scripts\python.exe camera_test.py --camera 1
```

若默认后端打不开或读帧失败，再尝试：

```powershell
.\.venv\Scripts\python.exe camera_test.py --backend dshow
```

或：

```powershell
.\.venv\Scripts\python.exe camera_test.py --backend msmf
```

记录实际通过的设备编号和后端，下一步保持一致。循环 FPS 是整个测试循环的速率，不一定等于摄像头硬件帧率。

## 6. 运行多人检测（约 30—45 分钟）

```powershell
.\.venv\Scripts\python.exe face_test.py --max-faces 3
```

如上一阶段需使用其他设备编号或后端，在本命令加上相同选项。

显示说明：Faces 为当前检测人数，绿色框为面部关键点外接范围，黄色点为部分关键点，infer 为本帧推理耗时，loop FPS 为循环速率。今天采用同步 VIDEO 模式简化测试；后续接入 Qt 时将推理放入工作线程。

多人检测需要显式设置 num_faces；官方默认值为 1。多脸设置下的输出平滑需要单独处理，不能把单脸平滑效果直接当作多人能力。[官方 Python 用法](https://developers.google.com/edge/mediapipe/solutions/vision/face_landmarker/python)

测试结束后按 Q / Esc，终端显示摘要，records 目录生成本次 CSV 和 summary JSON。CSV 保存帧号、时间、人数和推理耗时，没有原始画面。

## 7. 按顺序做真人检查（约 30 分钟）

让 B 或 C 配合；参与者知道测试内容。先正常光照、正面，再测更难条件。

| 场景 | 具体操作 | 要观察和记录什么 |
|---|---|---|
| 无人 | 人都离开画面约 10 秒 | 是否输出 0，是否偶发误检 |
| 单人正面 | 一人坐到电脑前约 20 秒 | 是否持续输出 1，有无明显掉脸 |
| 两人正面 | 两人同时进入摄像头范围约 20 秒 | 是否持续输出 2，位置是否分别标记 |
| 第二人进出 | 一人保持不动，另一人进入、离开，重复 3 次 | 人数是否能随场景改变 |
| 转头 | 两人在范围内，一人分别左右转头 | 哪些角度漏检；先不输出精确朝向结论 |
| 靠近或遮挡 | 一人靠近，另一人部分遮挡 | 输出是否不稳定，不能检测的情况是什么 |
| 正常背景变化 | 人不变，改变普通背景或坐姿 | 是否误检或掉脸 |

每种条件记录测试开始/结束相对时间。看到的真实人数由队员记录，与脚本输出区分。脚本只能报告模型输出，没有标签就不能计算准确率。

把结果写入 records/A_今日验收记录.md：设备和后端、实际分辨率、库版本、模型校验值、场景、真实人数、观察到的问题、日志名称。没有录像授权时只保留数值与文字。

## 8. 今天验收与交接给 B

- [ ] 虚拟环境内核心库可导入。
- [ ] 模型能实际加载，不只是文件存在。
- [ ] 摄像头测试可连续运行、退出并重新打开。
- [ ] 正常光照下至少两人可以分别输出。
- [ ] 有帧时间、人数和推理耗时日志。
- [ ] 漏检和失效条件已写进验收记录。
- [ ] B 知道启动命令、设备编号、后端和日志格式。

向 B 交付：本目录脚本、依赖锁定文件、模型来源与校验值、环境记录、一次正常和一次异常的观察记录。明天增加主要使用者指定、粗粒度风险、可靠性和 Qt 信号接口。

今天不把“人数大于 1”直接解释为窥屏，不把帧内编号解释为人物身份，不把 infer 解释为保护生效延迟。
