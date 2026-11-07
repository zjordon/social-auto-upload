# Language: 中文
"""抖音封面回归测试。

背景（2026-11-07 取证）：set_thumbnail 旧代码用 if/elif 互斥上传横/竖封面，
两图都传时横版分支永远被跳过——「手册命令发抖音，唯独横封面没传上」的根因。
弹窗默认在「设置横封面」tab，横/竖共用同一组 upload input，先竖后横依次
上传后一次「完成」两图同时生效（草稿零成本探针实测）。
"""
import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, call, patch

from uploader.douyin_uploader import main as douyin_main
from uploader.douyin_uploader.main import DouYinVideo


def _make_video(portrait=None, landscape=None):
    return DouYinVideo(
        "标题", "/tmp/demo.mp4", [], 0, "/tmp/cookie.json",
        thumbnail_portrait_path=portrait,
        thumbnail_landscape_path=landscape,
    )


def _mock_cover_page():
    """覆盖 set_thumbnail 全流程的 mock：弹窗一次点开、完成一次点关。"""
    page = MagicMock()
    page.evaluate = AsyncMock()
    page.wait_for_timeout = AsyncMock()
    page.wait_for_selector = AsyncMock()
    page.keyboard.press = AsyncMock()

    cover_area = MagicMock()
    cover_area.first = cover_area
    cover_area.filter = MagicMock(return_value=cover_area)
    cover_area.count = AsyncMock(return_value=1)
    cover_area.wait_for = AsyncMock()
    cover_area.hover = AsyncMock()

    entry_text = MagicMock()  # 「编辑封面」等入口：count=0 → 回退点封面区
    entry_text.first = entry_text
    entry_text.count = AsyncMock(return_value=0)

    cover_locator = MagicMock()
    cover_locator.first = cover_locator
    cover_locator.count = AsyncMock(return_value=0)  # 点完成后弹窗已关

    upload_input = MagicMock()
    upload_input.first = upload_input
    upload_input.count = AsyncMock(return_value=1)
    upload_input.set_input_files = AsyncMock()
    cover_locator.locator = MagicMock(return_value=upload_input)

    tab = MagicMock()  # 设置竖封面/设置横封面 tab
    tab.first = tab
    tab.click = AsyncMock()
    cover_locator.get_by_text = MagicMock(return_value=tab)

    done_btn = MagicMock()  # 「完成」按钮：未禁用
    done_btn.first = done_btn
    done_btn.count = AsyncMock(return_value=1)
    done_btn.is_visible = AsyncMock(return_value=True)
    done_btn.get_attribute = AsyncMock(return_value="semi-button-primary")
    done_btn.click = AsyncMock()
    cover_locator.get_by_role = MagicMock(return_value=done_btn)

    confirm_container = MagicMock()  # 二次确认容器：无按钮
    confirm_btn = MagicMock()
    confirm_btn.first = confirm_btn
    confirm_btn.count = AsyncMock(return_value=0)
    confirm_container.get_by_role = MagicMock(return_value=confirm_btn)

    def locate(selector):
        return {
            '[class*="cover-"]': cover_area,
            '[class*="cover"]': cover_area,
            "div.dy-creator-content-modal": cover_locator,
            ".semi-modal-content": confirm_container,
        }.get(selector, MagicMock())

    page.locator = MagicMock(side_effect=locate)
    page.get_by_text = MagicMock(return_value=entry_text)
    return page, upload_input, tab, done_btn


class DouyinThumbnailTests(unittest.TestCase):
    def run_set_thumbnail(self, video):
        page, upload_input, tab, done_btn = _mock_cover_page()
        with patch.object(douyin_main, "_native_click", AsyncMock()):
            asyncio.run(video.set_thumbnail(page))
        return page, upload_input, tab, done_btn

    def test_both_covers_upload_sequentially(self):
        """横竖都传：两个分支都要执行，先竖后横，tab 各点一次。"""
        video = _make_video(portrait="/tmp/shu.png", landscape="/tmp/heng.png")
        _, upload_input, tab, done_btn = self.run_set_thumbnail(video)

        self.assertEqual(upload_input.set_input_files.await_count, 2)
        upload_input.set_input_files.assert_has_awaits(
            [call("/tmp/shu.png"), call("/tmp/heng.png")]
        )
        self.assertEqual(tab.click.await_count, 2)
        done_btn.click.assert_awaited()

    def test_portrait_only_still_uploads_once(self):
        video = _make_video(portrait="/tmp/shu.png")
        _, upload_input, tab, _ = self.run_set_thumbnail(video)
        upload_input.set_input_files.assert_awaited_once_with("/tmp/shu.png")
        self.assertEqual(tab.click.await_count, 1)

    def test_landscape_only_still_uploads_once(self):
        video = _make_video(landscape="/tmp/heng.png")
        _, upload_input, _, _ = self.run_set_thumbnail(video)
        upload_input.set_input_files.assert_awaited_once_with("/tmp/heng.png")

    def test_no_covers_is_a_noop(self):
        video = _make_video()
        page = MagicMock()
        page.evaluate = AsyncMock()
        asyncio.run(video.set_thumbnail(page))
        page.evaluate.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
