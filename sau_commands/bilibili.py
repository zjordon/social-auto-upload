"""bilibili 的命令参数与执行逻辑。"""
from __future__ import annotations
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from uploader.bilibili_uploader.runtime import run_biliup_command
from sau_commands.arguments import (
    SCHEDULE_FORMAT,
    add_runtime_flags,
    existing_file_path,
    has_interactive_terminal,
    parse_tags,
    resolve_account_file,
    schedule_value,
)


def register(platform_parsers):
    """声明本平台命令、参数及合法选项。"""
    schedule_help = SCHEDULE_FORMAT.replace("%", "%%")
    bilibili_parser = platform_parsers.add_parser("bilibili", help="Bilibili operations")
    bilibili_actions = bilibili_parser.add_subparsers(dest="action", required=True)

    for action_name in ("login", "check"):
        action_parser = bilibili_actions.add_parser(action_name, help=f"Bilibili {action_name}")
        action_parser.add_argument("--account", required=True, help="Bilibili user-defined account_name")
        if action_name == "login":
            action_parser.add_argument(
                "--browser",
                action="store_true",
                help="Log in inside the persistent browser profile (scan QR there) instead of biliup's terminal QR",
            )
            add_runtime_flags(action_parser)

    bilibili_upload_video_parser = bilibili_actions.add_parser("upload-video", help="Upload one video to Bilibili")
    bilibili_upload_video_parser.add_argument("--account", required=True, help="Bilibili user-defined account_name")
    bilibili_upload_video_parser.add_argument("--file", required=True, type=existing_file_path, help="Video file path")
    bilibili_upload_video_parser.add_argument("--title", required=True, help="Video title")
    bilibili_upload_video_parser.add_argument("--desc", required=True, help="Video description")
    bilibili_upload_video_parser.add_argument(
        "--tid",
        type=int,
        help="Bilibili category id (biliup API mode); browser mode uses --category instead",
    )
    bilibili_upload_video_parser.add_argument(
        "--category",
        default=None,
        help="Category display name for browser mode, e.g. 科技数码 (draft/declaration require browser mode)",
    )
    bilibili_upload_video_parser.add_argument(
        "--declaration",
        default=None,
        help="Creation declaration text for browser mode, e.g. 个人观点，仅供参考",
    )
    bilibili_upload_video_parser.add_argument("--tags", default="", help="Comma-separated tags, such as tag1,tag2")
    bilibili_upload_video_parser.add_argument("--thumbnail", type=existing_file_path, help="Optional Bilibili cover image path")
    bilibili_upload_video_parser.add_argument("--schedule", type=schedule_value, help=f"Schedule time in {schedule_help}")
    publish_group = bilibili_upload_video_parser.add_mutually_exclusive_group()
    publish_group.add_argument("--draft", action="store_true", help="Save as draft instead of publishing (browser mode)")
    bilibili_upload_video_parser.add_argument(
        "--cdp-url",
        default=None,
        help="Attach to a long-running browser via CDP (e.g. http://127.0.0.1:9223); "
             "falls back to env SAU_BILIBILI_CDP_URL. Draft mode implies browser mode",
    )
    add_runtime_flags(bilibili_upload_video_parser)


@dataclass(slots=True)
class BilibiliVideoUploadRequest:
    account_name: str
    video_file: Path
    title: str
    description: str
    tid: int | None
    tags: list[str]
    publish_date: datetime | int
    thumbnail_file: Path | None = None
    category: str | None = None
    declaration: str | None = None
    publish_strategy: str = "immediate"
    cdp_url: str | None = None


async def login_bilibili_account(account_name: str) -> dict:
    account_file = resolve_account_file("bilibili", account_name)
    if not has_interactive_terminal():
        return {
            "success": False,
            "message": (
                "Bilibili login requires a local interactive terminal. "
                f"Please run `sau bilibili login --account {account_name}` yourself in a local terminal. "
                "If the terminal QR code does not render completely, open `./qrcode.png` and scan that image."
            ),
            "account_file": str(account_file),
        }

    result = run_biliup_command(["-u", str(account_file), "login"], interactive=True)
    success = result.returncode == 0
    return {
        "success": success,
        "message": (result.stderr or result.stdout or "").strip() or "Bilibili login completed" if success else (result.stderr or result.stdout or "").strip() or "Bilibili login failed",
        "account_file": str(account_file),
    }


async def check_bilibili_account(account_name: str) -> bool:
    account_file = resolve_account_file("bilibili", account_name)
    if not account_file.exists():
        return False
    result = run_biliup_command(["-u", str(account_file), "renew"])
    return result.returncode == 0


async def upload_bilibili_video(request: BilibiliVideoUploadRequest) -> Path:
    """biliup API 路线：直接投稿（无草稿能力，见 docs/douyin-stable-publish.md 同期取证）。"""
    account_file = resolve_account_file("bilibili", request.account_name)
    if not account_file.exists():
        raise RuntimeError(
            f"Bilibili account file is missing: {account_file}. Run `sau bilibili login --account {request.account_name}` first."
        )
    if request.tid is None:
        raise RuntimeError("biliup mode requires --tid (browser mode uses --category).")

    arguments = [
        "-u",
        str(account_file),
        "upload",
        str(request.video_file),
        "--title",
        request.title,
        "--desc",
        request.description,
        "--tid",
        str(request.tid),
    ]
    if request.tags:
        arguments.extend(["--tag", ",".join(request.tags)])
    if request.thumbnail_file:
        arguments.extend(["--cover", str(request.thumbnail_file)])
    if isinstance(request.publish_date, datetime):
        arguments.extend(["--dtime", str(int(request.publish_date.timestamp()))])

    result = run_biliup_command(arguments)
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout or "").strip() or "Bilibili upload failed")
    return account_file


async def upload_bilibili_video_via_browser(request: BilibiliVideoUploadRequest) -> Path:
    """浏览器路线：CDP 接管常驻浏览器或持久化档案，支持草稿/创作声明/分区名。"""
    from uploader.bilibili_uploader.browser import (
        BILIBILI_PUBLISH_STRATEGY_DRAFT,
        BILIBILI_PUBLISH_STRATEGY_IMMEDIATE,
        BilibiliBrowserUploader,
    )

    account_file = resolve_account_file("bilibili", request.account_name)
    if not request.category:
        raise RuntimeError("browser mode requires --category (e.g. --category 科技数码).")

    uploader = BilibiliBrowserUploader(
        video_file=request.video_file,
        title=request.title,
        tags=request.tags,
        account_file=str(account_file),
        desc=request.description,
        category=request.category,
        declaration=request.declaration,
        cover_file=str(request.thumbnail_file) if request.thumbnail_file else None,
        publish_strategy=(
            BILIBILI_PUBLISH_STRATEGY_DRAFT if request.publish_strategy == "draft"
            else BILIBILI_PUBLISH_STRATEGY_IMMEDIATE
        ),
        cdp_url=request.cdp_url,
    )
    await uploader.bilibili_upload_video()
    return account_file


async def run(args):
    """执行本平台命令；发布结果由平台实现核验。"""
    if args.action == "login":
        if getattr(args, "browser", False):
            from uploader.bilibili_uploader.browser import bilibili_browser_login

            account_file = resolve_account_file("bilibili", args.account)
            result = await bilibili_browser_login(str(account_file), headless=args.headless)
        else:
            result = await login_bilibili_account(args.account)
        if not result["success"]:
            raise RuntimeError(result["message"])
        print(f"Bilibili login flow completed: {result['account_file']}")
        return 0

    if args.action == "check":
        is_valid = await check_bilibili_account(args.account)
        print("valid" if is_valid else "invalid")
        return 0 if is_valid else 1

    if args.action == "upload-video":
        cdp_url = getattr(args, "cdp_url", None) or os.environ.get("SAU_BILIBILI_CDP_URL")
        use_browser = bool(getattr(args, "draft", False)) or bool(cdp_url) or bool(args.category)
        request = BilibiliVideoUploadRequest(
            account_name=args.account,
            video_file=args.file,
            title=args.title,
            description=args.desc,
            tid=args.tid,
            tags=parse_tags(args.tags),
            publish_date=args.schedule or 0,
            thumbnail_file=args.thumbnail,
            category=args.category,
            declaration=args.declaration,
            publish_strategy="draft" if getattr(args, "draft", False) else "immediate",
            cdp_url=cdp_url,
        )
        if use_browser:
            await upload_bilibili_video_via_browser(request)
            if request.publish_strategy == "draft":
                print(f"Bilibili video draft saved: {request.video_file}")
            else:
                print(f"Bilibili video upload submitted: {request.video_file}")
        else:
            await upload_bilibili_video(request)
            print(f"Bilibili video upload submitted: {request.video_file}")
        return 0

    raise RuntimeError(f"Unsupported Bilibili action: {args.action}")
