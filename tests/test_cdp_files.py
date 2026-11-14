# Language: 中文
"""大文件喂入回归测试。

背景：CDP 接管常驻浏览器时，Playwright 的 set_input_files 把文件内容经驱动
转发，>50MB 直接拒绝（"Cannot transfer files larger than 50Mb..."）。
utils/cdp_files.feed_file_input 按大小自动选路：小文件走原通道，
大文件走 CDP DOM.setFileInputFiles 下发本地路径（浏览器本机读盘，无上限）。
"""
import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from utils import cdp_files
from utils.cdp_files import (
    SET_INPUT_FILES_SIZE_LIMIT,
    feed_file_input,
    needs_cdp_file_transfer,
    set_input_files_via_cdp,
)


def _mock_cdp_session():
    session = MagicMock()
    session.send = AsyncMock(side_effect=lambda method, _=None, **params: {
        "DOM.getDocument": {"root": {"nodeId": 7}},
        "DOM.querySelector": {"nodeId": 42},
        "DOM.setFileInputFiles": {},
    }[method])
    session.detach = AsyncMock()
    return session


def _mock_page(session):
    page = MagicMock()
    page.context.new_cdp_session = AsyncMock(return_value=session)
    loc = MagicMock()
    loc.first = loc
    loc.set_input_files = AsyncMock()
    page.locator = MagicMock(return_value=loc)
    return page, loc


class NeedsCdpTransferTests(unittest.TestCase):
    def test_small_file_stays_on_playwright_channel(self):
        with tempfile.NamedTemporaryFile(suffix=".mp4") as f:
            f.write(b"x")
            f.flush()
            self.assertFalse(needs_cdp_file_transfer(f.name))

    def test_file_over_limit_needs_cdp(self):
        with tempfile.NamedTemporaryFile(suffix=".mp4") as f:
            f.write(b"x")
            f.flush()
            with patch.object(Path, "stat") as stat:
                stat.return_value.st_size = SET_INPUT_FILES_SIZE_LIMIT + 1
                self.assertTrue(needs_cdp_file_transfer(f.name))

    def test_missing_file_stays_on_playwright_channel(self):
        # 不存在的路径交给原有校验逻辑报错，不在这里拦截
        self.assertFalse(needs_cdp_file_transfer("Z:/nope/missing.mp4"))


class FeedFileInputTests(unittest.TestCase):
    def test_small_file_uses_locator_set_input_files(self):
        session = _mock_cdp_session()
        page, loc = _mock_page(session)
        with tempfile.NamedTemporaryFile(suffix=".mp4") as f:
            f.write(b"x")
            f.flush()
            used_cdp = asyncio.run(feed_file_input(page, "input[type=file]", f.name))
        self.assertFalse(used_cdp)
        loc.set_input_files.assert_awaited_once_with(f.name)
        page.context.new_cdp_session.assert_not_awaited()

    def test_large_file_sends_local_path_via_dom_setFileInputFiles(self):
        session = _mock_cdp_session()
        page, loc = _mock_page(session)
        path = r"D:\Videos\big.mp4"
        with patch.object(cdp_files, "needs_cdp_file_transfer", return_value=True):
            used_cdp = asyncio.run(feed_file_input(page, "input[accept*='.mp4']", path))
        self.assertTrue(used_cdp)
        loc.set_input_files.assert_not_awaited()
        calls = session.send.await_args_list
        self.assertEqual(calls[0].args[0], "DOM.getDocument")
        self.assertEqual(calls[1].args[0], "DOM.querySelector")
        self.assertEqual(calls[1].args[1]["selector"], "input[accept*='.mp4']")
        set_files = calls[2]
        self.assertEqual(set_files.args[0], "DOM.setFileInputFiles")
        self.assertEqual(set_files.args[1]["nodeId"], 42)
        self.assertEqual(set_files.args[1]["files"], [str(Path(path).resolve())])
        session.detach.assert_awaited_once()


    def test_forced_cdp_channel_used_even_for_small_files(self):
        """CDP 接管模式（force_cdp_channel=True）：小文件也走 CDP——
        实测 Playwright 负载通道传 37.9MB 要 ~30s（贴着 30s 默认超时）。"""
        session = _mock_cdp_session()
        page, loc = _mock_page(session)
        with tempfile.NamedTemporaryFile(suffix=".mp4") as f:
            f.write(b"x")
            f.flush()
            used_cdp = asyncio.run(
                feed_file_input(page, "input[type=file]", f.name, force_cdp_channel=True)
            )
        self.assertTrue(used_cdp)
        loc.set_input_files.assert_not_awaited()
        self.assertEqual(session.send.await_args_list[-1].args[0], "DOM.setFileInputFiles")


class SetInputFilesViaCdpTests(unittest.TestCase):
    def test_missing_selector_raises_actionable_error(self):
        session = _mock_cdp_session()
        session.send = AsyncMock(side_effect=lambda method, _=None, **params: {
            "DOM.getDocument": {"root": {"nodeId": 7}},
            "DOM.querySelector": {"nodeId": 0},  # 未命中
        }[method])
        page, _ = _mock_page(session)
        with self.assertRaisesRegex(RuntimeError, "找不到 file input"):
            asyncio.run(set_input_files_via_cdp(page, "input#nope", "x.mp4"))
        session.detach.assert_awaited_once()  # 失败也要释放 CDP 会话


if __name__ == "__main__":
    unittest.main()
