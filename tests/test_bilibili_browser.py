import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import uploader.bilibili_uploader.browser as bili_browser
from uploader.bilibili_uploader.browser import (
    BILIBILI_PUBLISH_STRATEGY_DRAFT,
    BilibiliBrowserUploader,
)


def _make_uploader(**overrides):
    params = dict(
        video_file="demo.mp4",
        title="标题",
        tags=[],
        account_file="/tmp/bilibili_creator.json",
        desc="简介",
        category="科技数码",
        declaration="个人观点，仅供参考",
        publish_strategy=BILIBILI_PUBLISH_STRATEGY_DRAFT,
        cdp_url="http://127.0.0.1:9223",
    )
    params.update(overrides)
    uploader = BilibiliBrowserUploader(**params)
    uploader.validate_video_file = MagicMock(return_value="demo.mp4")
    return uploader


def _mock_page():
    page = MagicMock()
    page.url = "https://member.bilibili.com/platform/upload/video/frame"
    page.goto = AsyncMock()
    page.wait_for_timeout = AsyncMock()
    page.close = AsyncMock()
    page.get_by_text = MagicMock()
    login_state = MagicMock()
    login_state.count = AsyncMock(return_value=0)
    page.get_by_text.return_value = login_state
    return page


class BilibiliBrowserLoginTests(unittest.TestCase):
    def test_invalid_login_fails_fast_and_only_closes_own_tab(self):
        uploader = _make_uploader()
        page = _mock_page()

        context = MagicMock()
        context.new_page = AsyncMock(return_value=page)
        context.close = AsyncMock()
        browser = MagicMock()
        browser.contexts = [context]
        browser.close = AsyncMock()
        playwright = MagicMock()
        playwright.chromium.connect_over_cdp = AsyncMock(return_value=browser)

        with (
            patch.object(bili_browser, "_attach_network_diagnostics"),
            patch.object(BilibiliBrowserUploader, "_check_login", AsyncMock(return_value=False)),
            self.assertRaisesRegex(RuntimeError, "登录态失效"),
        ):
            asyncio.run(uploader.upload(playwright))

        page.close.assert_awaited_once()   # CDP 模式只关自己的标签页
        context.close.assert_not_awaited()  # 绝不关用户的常驻浏览器
        browser.close.assert_not_awaited()

    def test_draft_submit_clicks_draft_span(self):
        uploader = _make_uploader()
        page = _mock_page()
        draft_span = MagicMock()
        draft_span.scroll_into_view_if_needed = AsyncMock()
        draft_span.click = AsyncMock()
        locator_chain = MagicMock()
        locator_chain.first = draft_span
        page.locator = MagicMock(return_value=locator_chain)

        asyncio.run(uploader._submit(page))
        page.locator.assert_called_with("span.submit-draft")
        draft_span.click.assert_awaited_once()

    def test_submit_success_signal_is_leaving_edit_page(self):
        uploader = _make_uploader()
        page = _mock_page()
        page.url = "https://member.bilibili.com/platform/upload-manager/article?group=draft"
        draft_span = MagicMock()
        draft_span.scroll_into_view_if_needed = AsyncMock()
        draft_span.click = AsyncMock()
        locator_chain = MagicMock()
        locator_chain.first = draft_span
        page.locator = MagicMock(return_value=locator_chain)

        asyncio.run(uploader._submit(page))
        draft_span.click.assert_awaited_once()
        self.assertEqual(page.wait_for_timeout.await_count, 1)  # 首轮即检测到跳转

    def test_set_cover_clicks_right_bottom_done_button(self):
        """取证 2026-11-07：确认按钮是右下角 div.button.submit「完成」，
        不是弹窗 footer 里隐藏预渲染的 button--primary「确定」。"""
        uploader = _make_uploader(cover_file="heng.png")
        page = MagicMock()
        page.wait_for_timeout = AsyncMock()
        entry = MagicMock()
        entry.scroll_into_view_if_needed = AsyncMock()
        entry.click = AsyncMock()
        entry_chain = MagicMock()
        entry_chain.first = entry
        page.get_by_text = MagicMock(return_value=entry_chain)

        file_input = MagicMock()
        file_input.wait_for = AsyncMock()
        file_input.set_input_files = AsyncMock()
        done_btn = MagicMock()
        done_btn.count = AsyncMock(return_value=1)
        done_btn.is_visible = AsyncMock(return_value=True)
        done_btn.is_enabled = AsyncMock(return_value=True)
        done_btn.click = AsyncMock()
        closed_dialog = MagicMock()
        closed_dialog.count = AsyncMock(return_value=0)

        def locate(selector):
            chain = MagicMock()
            if selector == ".bcc-dialog input[type=file]":
                chain.first = file_input
            elif selector == ".cover-editor-content-right-bottom .button.submit":
                chain.first = done_btn
            elif selector == ".cover-editor:visible":
                return closed_dialog
            return chain

        page.locator = MagicMock(side_effect=locate)

        asyncio.run(uploader._set_cover(page))
        done_btn.click.assert_awaited_once()

    def test_immediate_submit_clicks_publish_span(self):
        uploader = _make_uploader(publish_strategy="immediate")
        page = _mock_page()
        add_span = MagicMock()
        add_span.scroll_into_view_if_needed = AsyncMock()
        add_span.click = AsyncMock()
        locator_chain = MagicMock()
        locator_chain.first = add_span
        page.locator = MagicMock(return_value=locator_chain)

        asyncio.run(uploader._submit(page))
        page.locator.assert_called_with("span.submit-add")
        add_span.click.assert_awaited_once()

    def test_unsupported_strategy_rejected_before_browser(self):
        uploader = _make_uploader(publish_strategy="scheduled")
        with self.assertRaisesRegex(ValueError, "发布策略"):
            asyncio.run(uploader.upload(MagicMock()))


if __name__ == "__main__":
    unittest.main()
