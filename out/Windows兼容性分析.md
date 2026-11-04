# social-auto-upload - Windows 兼容性分析

> 生成时间: 2026-11-04
> 数据来源: `windows-compat-checker.sh` 扫描（out/05）+ 源码逐项核验
> 结论先行：**主线 CLI 在 Windows 上为一等公民，兼容性良好（评级 A-）**。项目内置大量 Windows 专项处理；遗留问题集中在 Web 遗留层与少量边角。

## 1. 总体评估

| 维度 | 评级 | 说明 |
|------|------|------|
| 主线 CLI（sau） | ✅ A | 明确支持 Windows，有专项代码与 .bat 启动器 |
| 浏览器自动化（patchright） | ✅ A | chromium 全平台，无系统依赖 |
| Bilibili biliup 托管 | ✅ A | windows-x86_64 资产 + `.exe` + 免 chmod 特判 |
| 文章渲染（Node） | ✅ A- | `npm.cmd` 已特判；需用户自装 Node 22+ |
| 终端二维码 | ✅ B+ | UTF-8 优雅降级 ASCII；建议 Windows Terminal |
| 历史遗留 Web 版 | ⚠️ B | 声明非主线；前端需 npm 工具链 |
| Docker | ❌ 不适用 | Dockerfile 仅面向 Linux 容器 |
| 根目录 shell 脚本 | ⚠️ 小问题 | `export_douyin_cookie.sh` 无 PowerShell 对应版 |

## 2. Windows 专项支持（已验证的正面清单）

项目对 Windows 的适配不是"碰巧能跑"，而是有意识的工程决策：

| # | 位置 | 适配内容 |
|---|------|----------|
| 1 | `utils/login_qrcode.py:39-48` | **cv2 中文路径问题**：Windows 下 `cv2.imread` 对含中文/非 ASCII 路径不稳定，先走 `np.fromfile + cv2.imdecode`，失败才回退 `cv2.imread` |
| 2 | `utils/login_qrcode.py:81-87` | **终端编码**：尝试 `sys.stdout.reconfigure(encoding="utf-8")` 后渲染二维码；`UnicodeEncodeError` 时降级为纯 ASCII 块状二维码，并提示"Windows 下建议使用 Windows Terminal" |
| 3 | `utils/article_render.py:87` | **npm 可执行名**：`shutil.which("npm.cmd" if os.name == "nt" else "npm")`——Windows 下 npm 是 `.cmd`，直接 `which("npm")` 找不到 |
| 4 | `uploader/bilibili_uploader/runtime.py:43-45,54` | biliup 资产矩阵含 `windows-x86_64`（zip 格式），可执行名自动切换 `biliup.exe` |
| 5 | `uploader/bilibili_uploader/runtime.py:148-149` | 下载后仅非 Windows 才 `chmod +x`，Windows 正确跳过 |
| 6 | `uploader/bilibili_uploader/runtime.py:145-147` | 临时文件 + 原子 `replace()` 更新二进制，避免 Windows 下文件占用导致覆盖失败 |
| 7 | `start-win.bat` | 一键启动脚本：`START` 拉起两个 `cmd /k` 窗口分别跑 Python 后端与 Vue 前端 |
| 8 | `conf.example.py:5` | 注释直接给出 Windows Chrome 路径示例 `C:/Program Files/...` |
| 9 | `skills/*/scripts/examples/*.ps1` | 18 个 Skill 全部提供 `.sh` + `.ps1` 双平台调用示例（扫描器已确认 10 组配对） |
| 10 | 全仓库 95 处 `from pathlib import Path` | 路径统一 pathlib，无手拼 `/` 或 `\` |
| 11 | `subprocess` 全部列表参数 | 无一处 `shell=True`（grep 验证 0 命中），不受 Windows/cmd 引号解析差异影响 |
| 12 | 无 signal/symlink 依赖 | `import signal`、`os.symlink` 均 0 命中——这两类是典型 POSIX-only 陷阱，本项目干净 |

## 3. 发现的问题与风险

### 3.1 【中】`requirements.txt` 是 UTF-16 LE 编码

**证据**: `file requirements.txt` → "UTF-16, little-endian, CRLF"；文件头 `FF FE` BOM（xxd 验证）。

**影响**:
- pip 本身能识别 BOM（auto_decode），安装不受影响；
- 但大量工具链默认按 UTF-8 读取会乱码——本次分析所用的依赖扫描脚本读出的就是乱码（`out/03-依赖分析.md` 中依赖列表为间隔空格的乱字符）；CI、依赖审计工具（pip-audit、Renovate 等）也可能解析异常。
- 成因大概率是某次在 PowerShell 中用重定向/错误编码写出（PowerShell 5.1 `Out-File` 默认 UTF-16）。

**建议**: 转存为 UTF-8（无 BOM）+ LF：
```powershell
# PowerShell 7+ 或 Python 一行：
python -c "open('requirements.txt','w',encoding='utf-8',newline='\n').write(open('requirements.txt',encoding='utf-16').read())"
```

### 3.2 【低】cookie JSON 读取未显式指定编码

**位置**: `uploader/alipay_uploader/main.py:195`、`uploader/douyin_uploader/main.py:307`

```python
_d = _json.load(open(account_file))   # 无 encoding=
```

**影响**: Windows 中文系统默认 locale 编码是 GBK（cp936）。Playwright 写出的 `storage_state` cookie JSON 是 UTF-8；若其中含非 ASCII 字符（localStorage 里的中文用户名、昵称等），GBK 解码可能 `UnicodeDecodeError` 或产生乱码键名。Python 3.15 起默认将切换 UTF-8，但 3.10–3.12（本项目支持范围）仍是 locale 依赖。

**建议**: 改为 `open(account_file, encoding="utf-8")`（与仓库其他位置的写法保持一致，如 `_read_verify_code`、`utils/files_times.py` 已显式 utf-8）。

### 3.3 【低】根目录 `export_douyin_cookie.sh` 仅 Bash

**证据**: 扫描器输出 "shebang: `#!/bin/bash` — PS1: ✗, CMD: ✗"。skills/ 下的示例脚本都有 `.ps1` 配对，唯独这个根目录工具没有。

**建议**: 补一个 `export_douyin_cookie.ps1`，或在脚本头部注明 Windows 用户用 Git Bash 执行。

### 3.4 【低】测试代码使用 POSIX 风格假路径

**位置**: `tests/test_douyin_declaration.py:13` 等多处 `"/tmp/demo.mp4"`、`"/tmp/cookie.json"`。

**影响**: 这些字符串仅作为参数传给 `DouYinVideo` 构造器（单元测试不访问文件系统），因此**当前不会失败**；但若未来测试真的落盘，`/tmp` 在 Windows 不存在。属代码卫生问题，非功能缺陷。

### 3.5 【信息】终端二维码在旧版 conhost 下无法完整显示

`print_terminal_qrcode` 已做三级兜底（reconfigure UTF-8 → Unicode 字符 → ASCII 块），且会提示打开 PNG 文件扫码，实际不会阻塞。仅体验层面：老式 conhost 字符宽度渲染可能让二维码偏移，建议 Windows Terminal。

### 3.6 【信息】历史遗留 Web 版与 Docker

- Web 版（`sau_backend.py` + `sau_frontend/`）：官方声明非主线（`docs/legacy-web.md`）；Windows 运行需 `pip install -r requirements.txt`（注意 §3.1 编码问题）+ 前端 Node 工具链，`start-win.bat` 已铺好启动路径。属"能用但不保证"。
- `Dockerfile`：`FROM node:22.21.1` builder + `FROM python:3.10.19`，Linux 容器专用；Windows 上通过 Docker Desktop/WSL2 运行没有障碍，但无法用 Windows 容器原生构建。

### 3.7 【信息】asyncio 事件循环

代码未显式设置事件循环策略。Python 3.8+ Windows 默认 `ProactorEventLoop`，正是 Playwright/patchright 异步子进程所需；`sau_cli.py` 统一 `asyncio.run()` 起入口，无策略冲突。遗留 Web 层在线程内 `new_event_loop()`（`sau_backend.py:689`）在 Windows 上亦可用。无风险。

## 4. Windows 用户快速上手清单

```powershell
# 1. 克隆 + 配置
git clone https://github.com/dreammis/social-auto-upload.git; cd social-auto-upload
Copy-Item conf.example.py conf.py

# 2. 安装（uv 优先）
uv tool install .          # 或 pip install -e .

# 3.（可选,仅 Markdown 文章）Node.js 22+ 后:
sau article setup

# 4. 登录并发布（建议在 Windows Terminal 中运行）
sau douyin login --account creator
sau douyin upload-video --account creator --file videos\demo.mp4 --title "标题" --desc "简介"

# 5. 运行测试
python -m unittest discover tests
```

## 5. 修复建议汇总（按优先级）

| 优先级 | 项 | 动作 | 工作量 |
|--------|----|------|--------|
| P1 | requirements.txt 编码 | 转 UTF-8 + LF，并在 CI 加编码检查 | 5 分钟 |
| P2 | cookie JSON 读取编码 | 两处补 `encoding="utf-8"` | 2 分钟 |
| P3 | export_douyin_cookie.sh | 补 .ps1 或注明 Git Bash | 小 |
| P4 | 测试假路径 /tmp | 改 `tempfile` 或 pathlib 跨平台写法 | 小 |
| — | 二维码 / Web / Docker | 已有合理降级或官方定位说明，无需改动 | — |

**总评**: 这是一个对 Windows 相当友好的 Python 自动化项目——路径、编码、可执行文件、终端渲染四个高频翻车点都有针对性处理；遗留问题均为边角（P1/P2 合计不到 10 分钟工作量），不阻塞日常使用。
