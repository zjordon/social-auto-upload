# Bilibili CLI 契约

这个 skill 默认假设当前环境已经安装并可调用 `sau` 命令。

## 命令列表

### 登录

```bash
sau bilibili login --account <account>
```

- 必填参数：
  - `--account`
- 作用：
  - 自动准备 `biliup`
  - 触发 Bilibili 登录流程
- 账号说明：
  - `--account` 传的是用户自定义的 `account_name`，不是固定只能叫 `creator`
  - 一个 `account_name` 对应一个账号文件，可用于多账号隔离和并发任务
- 登录方式说明：
  - 这个命令应该由用户自己在本地真实终端里运行
  - 如果终端二维码显示不完整，可直接打开当前目录下的 `qrcode.png` 扫码
  - agent 不应该在非交互环境里硬跑这个命令
  - 加 `--browser` 则打开持久化浏览器档案扫码（浏览器路线的兜底登录方式；
    走 `--cdp-url` 接管常驻浏览器时不需要这一步）

### 校验账号

```bash
sau bilibili check --account <account>
```

- 必填参数：
  - `--account`
- 预期输出：
  - `valid`
  - `invalid`

### 上传视频

**API 路线**（biliup CLI，直接投稿）：

```bash
sau bilibili upload-video \
  --account <account> \
  --file <video-path> \
  --title "<title>" \
  --desc "<desc>" \
  --tid <category-id> \
  [--tags tag1,tag2] \
  [--thumbnail <cover-path>] \
  [--schedule "YYYY-MM-DD HH:MM"]
```

**浏览器路线**（CDP 接管常驻浏览器或持久化档案；草稿/创作声明/分区名需要它）：

```bash
sau bilibili upload-video \
  --account <account> \
  --file <video-path> \
  --title "<title>" \
  --desc "<desc>" \
  --category 科技数码 \
  --declaration "个人观点，仅供参考" \
  --tags "浏览器Agent" \
  --thumbnail <cover-path> \
  --draft \
  --cdp-url http://127.0.0.1:9223
```

- 必填参数（两条路线共有）：
  - `--account` `--file` `--title` `--desc`
- 路线专属：
  - API 路线：`--tid`（数字分区 id）必填
  - 浏览器路线：`--category`（分区显示名）必填
- 浏览器路线可选：
  - `--draft`：存草稿不直接发布（成功信号：跳转到稿件管理草稿页）
  - `--declaration`：创作声明原文，如「个人观点，仅供参考」
  - `--cdp-url`：接管已登录的常驻浏览器（也可用环境变量 `SAU_BILIBILI_CDP_URL`）
- 可选参数：
  - `--tags`（逗号分隔）、`--thumbnail`（封面图）、`--schedule`（API 路线）

## 额外说明

- 路线判定：带 `--draft` / `--cdp-url`（含环境变量） / `--category` 任一 → 浏览器路线；否则 API 路线
- `--cdp-url` 模式只操作自己打开的标签页，不会关闭用户浏览器；要求该浏览器已登录 B 站
- 无 `--cdp-url` 的浏览器路线使用 `~/.social-auto-upload/browser-profiles/` 持久化档案，
  首次需 `sau bilibili login --account <name> --browser` 扫码
- `--tags` 使用逗号分隔
- `--schedule` 走 `sau` 统一时间格式（仅 API 路线生效）
- 程序会自动准备和更新 `biliup`（API 路线）
