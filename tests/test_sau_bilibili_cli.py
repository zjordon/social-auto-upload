import sau_commands.arguments
import sau_commands.bilibili
import asyncio
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import sau_cli


class BilibiliCliTests(unittest.TestCase):
    def test_build_parser_accepts_bilibili_login(self):
        parser = sau_cli.build_parser()
        args = parser.parse_args(["bilibili", "login", "--account", "creator"])
        self.assertEqual(args.platform, "bilibili")
        self.assertEqual(args.action, "login")

    def test_browser_mode_parses_without_tid(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            video_path = Path(temp_dir) / "demo.mp4"
            video_path.write_bytes(b"video")
            parser = sau_cli.build_parser()
            args = parser.parse_args([
                "bilibili", "upload-video", "--account", "creator",
                "--file", str(video_path), "--title", "hello", "--desc", "hello",
                "--category", "科技数码", "--declaration", "个人观点，仅供参考",
                "--draft", "--cdp-url", "http://127.0.0.1:9223",
            ])
        self.assertTrue(args.draft)
        self.assertIsNone(args.tid)
        self.assertEqual(args.category, "科技数码")
        self.assertEqual(args.declaration, "个人观点，仅供参考")
        self.assertEqual(args.cdp_url, "http://127.0.0.1:9223")

    def test_biliup_mode_without_tid_raises_at_runtime(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            account_file = Path(temp_dir) / "account.json"
            account_file.write_text("{}", encoding="utf-8")
            request = sau_commands.bilibili.BilibiliVideoUploadRequest(
                "creator", Path("demo.mp4"), "hello", "hello", None, ["t"], 0)
            with patch("sau_commands.bilibili.resolve_account_file", return_value=account_file):
                with self.assertRaisesRegex(RuntimeError, "--tid"):
                    asyncio.run(sau_commands.bilibili.upload_bilibili_video(request))

    def test_dispatch_browser_draft_uses_browser_uploader(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            video_path = Path(temp_dir) / "demo.mp4"
            video_path.write_bytes(b"video")
            args = Namespace(
                platform="bilibili", action="upload-video", account="creator",
                file=video_path, title="hello", desc="hello", tid=None,
                category="科技数码", declaration=None, tags="", thumbnail=None,
                schedule=None, draft=True, cdp_url="http://127.0.0.1:9223",
                debug=False, headless=False,
            )
            with patch(
                "sau_commands.bilibili.upload_bilibili_video_via_browser",
                new=AsyncMock(return_value=Path("cookies/bilibili_creator.json")),
            ) as browser_upload:
                code = asyncio.run(sau_cli.dispatch(args))
        self.assertEqual(code, 0)
        browser_upload.assert_awaited_once()
        request = browser_upload.call_args.args[0]
        self.assertEqual(request.publish_strategy, "draft")

    def test_dispatch_bilibili_check_prints_valid(self):
        args = Namespace(platform="bilibili", action="check", account="creator")
        with patch("sau_commands.bilibili.check_bilibili_account", new=AsyncMock(return_value=True)):
            code = asyncio.run(sau_cli.dispatch(args))
        self.assertEqual(code, 0)

    def test_login_bilibili_account_returns_friendly_message_without_terminal(self):
        with patch("sau_commands.bilibili.has_interactive_terminal", return_value=False):
            result = asyncio.run(sau_commands.bilibili.login_bilibili_account("creator"))
        self.assertFalse(result["success"])
        self.assertIn("local interactive terminal", result["message"].lower())
        self.assertIn("qrcode.png", result["message"].lower())

    def test_upload_bilibili_video_passes_thumbnail_to_biliup(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            account_file = Path(temp_dir) / "account.json"
            account_file.write_text("{}", encoding="utf-8")
            request = sau_commands.bilibili.BilibiliVideoUploadRequest("creator", Path("demo.mp4"), "hello", "hello", 249, ["test"], 0, Path("cover.png"))
            with patch("sau_commands.bilibili.resolve_account_file", return_value=account_file), patch("sau_commands.bilibili.run_biliup_command", return_value=SimpleNamespace(returncode=0, stdout="", stderr="")) as run_biliup:
                asyncio.run(sau_commands.bilibili.upload_bilibili_video(request))
        self.assertIn("--cover", run_biliup.call_args.args[0])
        self.assertIn("cover.png", run_biliup.call_args.args[0])
