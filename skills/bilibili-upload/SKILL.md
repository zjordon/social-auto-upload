---
name: bilibili-upload
description: 当 agent 需要通过已安装的 `sau` CLI 完成 Bilibili 登录、账号校验或视频上传时使用这个 skill。优先使用 `sau bilibili ...`，程序会自动准备 `biliup`，不要求用户手动安装。
license: MIT-0
slug: social-auto-upload-bilibili-upload
displayName: Bilibili 视频发布
version: 1.0.0
summary: 登录哔哩哔哩并发布视频，支持分区选择。
---

# Bilibili 上传 Skill

优先把 `sau` 作为主接口。

不要一开始就让用户自己找 `biliup` 或手动下载 release。
程序会在运行时自动检查、自动下载、自动更新 `biliup`。

## 功能概览

| 功能 | 命令入口 | 说明 |
| --- | --- | --- |
| 登录 | `sau bilibili login --account <name>` | 需要用户自己在本地真实终端里执行，用于生成或刷新登录信息 |
| 登录（浏览器档案） | `sau bilibili login --account <name> --browser` | 打开持久化浏览器档案扫码，供浏览器路线使用 |
| 校验 | `sau bilibili check --account <name>` | 检查指定账号当前是否有效 |
| 视频上传（API 路线） | `sau bilibili upload-video ... --tid <id>` | biliup CLI 直接投稿，无草稿/创作声明能力 |
| 视频上传（浏览器路线） | `sau bilibili upload-video ... --category <分区名> [--draft]` | CDP 接管常驻浏览器或持久化档案，支持草稿/创作声明/封面 |

## 默认工作流

1. 先确认 `references/runtime-requirements.md`
2. 再确认 `references/cli-contract.md`
3. 执行匹配的 `sau bilibili ...` 命令
4. 如果命令失败，再看 `references/troubleshooting.md`

## 命令选择建议

- 用户没有登录信息，先让用户自己在本地终端执行 `login`
- 用户只想确认账号状态，先用 `check`
- 用户要发视频，用 `upload-video`
- 用户要**存草稿不直接发布**、选**创作声明**、按**分区名**（如「科技数码」）投稿，
  或想复用已登录的常驻浏览器（`--cdp-url`）→ 必须走浏览器路线（见 cli-contract.md）
- 两条路线判定：带 `--draft` / `--cdp-url` / `--category` 任一即浏览器路线；
  否则 biliup API 路线（此时 `--tid` 必填）

## 执行前检查

- 优先确认当前环境能运行 `sau`
- 如果 `sau` 不在 PATH 中，可以用仓库里的 `sau_cli.py`
- 不要要求用户手动下载 `biliup`
- 第一次运行 Bilibili 命令时，程序可能会自动联网准备 `biliup`
- 对 agent 来说，不要在非交互环境里硬跑 `sau bilibili login`
- 正确做法是让用户自己在本地终端执行 `sau bilibili login --account <name>`
- 如果终端里的二维码显示不完整，提醒用户直接打开当前目录下的 `qrcode.png` 扫码

## 参考文档

- 运行前提：`references/runtime-requirements.md`
- CLI 契约：`references/cli-contract.md`
- 故障排查：`references/troubleshooting.md`
