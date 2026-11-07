# 视频发布命令手册（抖音 / B 站）

> 日常发视频只看这一页。两条命令均已于 2026-11-07 在本机端到端验证（CDP 接管常驻浏览器，抖音 40 秒、B 站草稿+封面全流程）。
> 排查复盘见 `docs/douyin-stable-publish.md`；B 站选择器证据在 `uploader/bilibili_uploader/browser.py` 注释里。

## 0. 前提（一次性）

**常驻发布浏览器带调试端口运行**（就是平时用来发视频的那个 Chrome，需已登录抖音和 B 站）：

```
chrome.exe --remote-debugging-port=9223 <你的日常 profile>
```

- `--account creator` 里的 `creator` 是自定义账号名，不是固定值；CDP 模式下登录态取自常驻浏览器，不依赖本地 cookie 文件
- 可设环境变量省掉 `--cdp-url`：`$env:SAU_DOUYIN_CDP_URL="http://127.0.0.1:9223"`、`$env:SAU_BILIBILI_CDP_URL="http://127.0.0.1:9223"`
- `sau` 命令的安装（本机已装好）：在仓库目录执行一次 `uv tool install --editable .`，
  之后任意终端可用。报「无法将 sau 项识别为…」说明没装或换了机器，重跑这条即可；
  应急替代：`<仓库>\.venv\Scripts\sau.exe <同款参数>` 或激活 venv（`.venv\Scripts\Activate.ps1`）

## 1. 抖音：发视频草稿

```powershell
sau douyin upload-video --account creator --file "D:\Videos\test\final\2026-04-29-20-41-59.mp4" `
    --title "ai浏览器第五期-browse-use" --desc "browse-use 体验及技术原理" `
    --collection "AI浏览器合集" --declaration "无需添加自主声明" `
    --thumbnail-landscape <横版封面图> --thumbnail-portrait <竖版封面图> `
    --draft --cdp-url http://127.0.0.1:9223
```

| 提示词里的信息 | 参数 |
|---|---|
| 视频路径 | `--file` |
| 标题 | `--title` |
| 描述/简介 | `--desc` |
| 添加合集 | `--collection`（合集需已存在） |
| 自主声明 | `--declaration`（**原文精确匹配**，如「无需添加自主声明」） |
| 横版封面 | `--thumbnail-landscape` |
| 竖版封面 | `--thumbnail-portrait`（也可用 `--thumbnail`，等价） |
| 先暂存为草稿 | `--draft` |
| 用哪个浏览器 | `--cdp-url` |

变体：去掉 `--draft` 直接发布；`--schedule "2026-11-08 10:00"` 定时发布（与 `--draft` 互斥）。

成功信号：日志依次出现「视频已经传完啦」→「自主声明…」→「封面设置完成」→「**视频已存入草稿箱**」，exit 0。

已知遗留（不阻断，草稿里手动补）：合集可能未选中（选择器待精修）；横版封面生效情况未逐一确认。

## 2. B 站：发视频草稿

```powershell
sau bilibili upload-video --account creator --file "D:\Videos\test\final\2026-04-29-20-41-59.mp4" `
    --title "ai浏览器第五期-browse-use" --desc "browse-use 体验及技术原理" `
    --tags "浏览器Agent" --category 科技数码 `
    --declaration "个人观点，仅供参考" `
    --thumbnail "D:\dev\git\claude\skills-deom\ppt\browser-use\heng.png" `
    --draft --cdp-url http://127.0.0.1:9223
```

| 提示词里的信息 | 参数 |
|---|---|
| 视频路径 | `--file` |
| 标题 | `--title` |
| 简介 | `--desc` |
| 标签 | `--tags`（逗号分隔，最多 10 个） |
| 分区 | `--category`（**分区显示名**，如「科技数码」） |
| 创作声明 | `--declaration`（原文精确匹配） |
| 封面 | `--thumbnail` |
| 先暂存为草稿 | `--draft` |
| 用哪个浏览器 | `--cdp-url` |

路线说明：带 `--draft` / `--cdp-url` / `--category` 任一即走**浏览器路线**（草稿、创作声明、分区名只有它能做）；都不带则走 biliup API 直投，此时 `--tid <数字分区id>` 必填、且**没有草稿能力**。日常发草稿始终用上面的完整命令。

成功信号：日志「封面已设置」→「**『存草稿』成功，已离开编辑页: …upload-manager/article?group=draft**」，exit 0；B 站「稿件管理 → 草稿箱」肉眼可见。

## 3. 故障速查

| 现象 | 判断与处理 |
|---|---|
| 报 `Error: Frame was detached` / `Connection closed while reading from the driver` | 常驻浏览器会话里残留的 target 状态（如挂机过夜的标签、孤儿 OOPIF iframe）毒死 patchright 驱动的帧树捕获，重试无效。**重启 9223 浏览器即恢复**（2026-11-07 实证）。切勿对 iframe 类 target 调 CDP `/json/close`——实测会带崩整个浏览器 |
| 抖音停在「文件解析中 0%」不动 | 账号层频率限流（当日上传次数过多）。**当天别再测**，约数小时~一天自然衰减；先看浏览器页面实际状态再下结论 |
| B 站封面 30 秒后放弃继续 | 已修复：确认按钮是右下角 `div.button.submit`「完成」（2026-11-07 取证）。若再出现，看日志「可见弹窗内容」dump |
| 命令报登录态失效 | 常驻浏览器里抖音/B 站掉登录了，人工重新登录后重跑 |
| 上传等待超时报错 | 网络/风控偶发；`BILIBILI_UPLOAD_TIMEOUT` / `DOUYIN_UPLOAD_TIMEOUT`（默认 900 秒）内未完成会明确报错而非空转，可直接重跑 |
| biliup 报找不到 release 资产 | 已修复（v1.3.5+ 无便携包时自动向下找）；仍失败说明 GitHub 访问异常，重试即可 |

## 4. 频率纪律（防限流的铁律）

- **单日别反复测试真实上传**——抖音账号层风控按滚动窗口频率计分，排查期 10 次测试曾换来 9 小时挂起
- 冒烟验证用「打开上传页不上传」即可；要调试表单/封面，用**已存草稿的编辑页**（`upload/video/frame?type=draft&draftId=…`，视频已在表单里，零上传成本）
- 草稿保存也算一次提交行为，同样计数

## 5. 深入阅读

- 抖音三天排查全记录：`docs/douyin-stable-publish.md`（风控两层模型、对照实验表）
- B 站浏览器路线实现与选择器取证：`uploader/bilibili_uploader/browser.py`、`skills/bilibili-upload/`
- 相关提交：`1d57769` / `f607680`（抖音草稿+CDP）、`a4a88fc` / `c90e6a8`（B 站 runtime 修复+浏览器路线）
