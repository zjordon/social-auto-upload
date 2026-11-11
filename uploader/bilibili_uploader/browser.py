# -*- coding: utf-8 -*-
"""Bilibili 浏览器发布：CDP 接管常驻浏览器，或自有持久化档案兜底。

选择器依据 2026-11-07 对 member.bilibili.com 上传页的实测取证：
- 上传表单在喂入视频后才渲染，位于主 frame
- 存草稿/立即投稿是 span.submit-draft / span.submit-add（非 button 元素）
- 创作声明是 bcc-select 单选下拉，选项含「个人观点，仅供参考」等原文
- 分区是单列下拉，「科技数码」为一级分区选项
- 简介是 Quill 富文本（div.ql-editor，页面里有两个，第一个属于简介区）
- B 站会自动用文件名填标题并推荐标签，需要覆盖与清理
- 封面编辑器的确认是右下角 div.button.submit「完成」（不是 button、也不是
  弹窗 footer 里 button.bcc-button--primary「确定」——那是隐藏预渲染，永远不可见）
- .bcc-dialog 在页面里恒有 3 个隐藏预渲染实例，弹窗检测必须加 :visible
- 存草稿成功信号：离开编辑页跳 upload-manager/article?group=draft
"""
from __future__ import annotations

import asyncio
import os
import time
from datetime import datetime
from pathlib import Path

from patchright.async_api import Playwright
from patchright.async_api import async_playwright

from conf import BASE_DIR, DEBUG_MODE, LOCAL_CHROME_HEADLESS, LOCAL_CHROME_PATH
from uploader.base_video import BaseVideoUploader
from utils.cdp_files import feed_file_input
from utils.log import bilibili_logger as bili_logger

BILIBILI_PUBLISH_STRATEGY_IMMEDIATE = "immediate"
BILIBILI_PUBLISH_STRATEGY_DRAFT = "draft"

BILIBILI_UPLOAD_URL = "https://member.bilibili.com/platform/upload/video/frame"
BILIBILI_UPLOAD_TIMEOUT_SECONDS = int(os.environ.get("BILIBILI_UPLOAD_TIMEOUT", "900"))
BILIBILI_UPLOAD_MAX_RETRIES = 3


def _msg(emoji: str, text: str) -> str:
    return f"{emoji} {text}"


def _persistent_profile_dir(account_file) -> Path:
    """按账号分配持久化浏览器档案；一次性临时档案会被平台风控重点对待（见抖音侧实测）。"""
    stem = Path(account_file).stem
    profile = Path.home() / ".social-auto-upload" / "browser-profiles" / stem
    profile.mkdir(parents=True, exist_ok=True)
    return profile


def _attach_network_diagnostics(page) -> None:
    """网络诊断：失败请求与 4xx/5xx 响应（排除 blob 噪音）。"""
    def _on_request_failed(request):
        if request.url.startswith("blob:"):
            return
        bili_logger.warning(_msg("⚠️", f"请求失败: {request.method} {request.url[:120]} ({request.failure})"))

    def _on_response(response):
        if response.status >= 400:
            bili_logger.warning(_msg("⚠️", f"HTTP {response.status} ← {response.url[:120]}"))

    page.on("requestfailed", _on_request_failed)
    page.on("response", _on_response)


class BilibiliBrowserUploader(BaseVideoUploader):
    def __init__(
        self,
        video_file,
        title: str,
        tags: list[str],
        account_file,
        desc: str = "",
        category: str = "科技数码",
        declaration: str | None = None,
        cover_file: str | None = None,
        publish_strategy: str = BILIBILI_PUBLISH_STRATEGY_IMMEDIATE,
        debug: bool = DEBUG_MODE,
        headless: bool = LOCAL_CHROME_HEADLESS,
        cdp_url: str | None = None,
    ):
        self.video_file = str(video_file)
        self.title = title
        self.desc = desc or ""
        self.tags = tags or []
        self.account_file = account_file
        self.category = category
        self.declaration = declaration
        self.cover_file = cover_file
        self.publish_strategy = publish_strategy
        self.debug = debug
        self.headless = headless
        self.cdp_url = cdp_url

    # ── 浏览器获取：CDP 接管 / 持久化档案 ──

    async def _acquire_context(self, playwright):
        """返回 (browser, context, owns_browser)。CDP 模式只管自己开的标签页。"""
        if self.cdp_url:
            browser = await playwright.chromium.connect_over_cdp(self.cdp_url)
            context = browser.contexts[0] if browser.contexts else await browser.new_context()
            bili_logger.info(_msg("🔗", f"已接管常驻浏览器: {self.cdp_url}"))
            return browser, context, False
        kwargs = {
            "headless": self.headless,
            "args": ["--no-sandbox", "--disable-blink-features=AutomationControlled"],
        }
        if LOCAL_CHROME_PATH:
            kwargs["executable_path"] = LOCAL_CHROME_PATH
        else:
            kwargs["channel"] = "chromium"
        browser = None
        context = await playwright.chromium.launch_persistent_context(
            str(_persistent_profile_dir(self.account_file)), **kwargs
        )
        return browser, context, True

    async def _check_login(self, page) -> bool:
        try:
            await page.goto(BILIBILI_UPLOAD_URL, wait_until="domcontentloaded", timeout=90000)
            await page.wait_for_timeout(3000)
            if "passport.bilibili.com" in page.url:
                return False
            login_ui = await page.get_by_text("扫码登录").count() + await page.get_by_text("登录后可投稿").count()
            return login_ui == 0 and "member.bilibili.com" in page.url
        except Exception:
            return False

    # ── 表单操作（选择器均有取证依据） ──

    async def _feed_video(self, page) -> None:
        selector = "input[accept*='.mp4']"
        file_input = page.locator(selector).first
        await file_input.wait_for(state="attached", timeout=60000)
        if await feed_file_input(page, selector, self.video_file):
            bili_logger.info(_msg("📦", "视频超 50MB，已走 CDP 本地路径喂入（绕过 Playwright 转发上限）"))
        bili_logger.info(_msg("🏃", "视频已喂入，等待上传与表单渲染"))

    async def _wait_upload_complete(self, page) -> None:
        deadline = time.monotonic() + BILIBILI_UPLOAD_TIMEOUT_SECONDS
        retries = 0
        while True:
            done = await page.locator(".task-status-success").count()
            if done > 0:
                bili_logger.success(_msg("🥳", "视频上传完成"))
                return
            failed = await page.get_by_text("上传失败").count() + await page.get_by_text("失败重传").count()
            if failed > 0:
                if retries >= BILIBILI_UPLOAD_MAX_RETRIES:
                    raise RuntimeError("Bilibili 视频上传连续失败 3 次，中止重试。")
                retries += 1
                bili_logger.error(_msg("😵", f"检测到上传失败，重传（第 {retries}/3 次）"))
                await self._feed_video(page)
            if time.monotonic() > deadline:
                raise RuntimeError(
                    f"Bilibili 视频上传 {BILIBILI_UPLOAD_TIMEOUT_SECONDS} 秒内未完成"
                    "（可用 BILIBILI_UPLOAD_TIMEOUT 调整）。"
                )
            bili_logger.info(_msg("🏃", "正在上传视频"))
            await asyncio.sleep(2)

    async def _wait_form_ready(self, page) -> None:
        title_input = page.locator("input.input-val[placeholder='请输入稿件标题']").first
        await title_input.wait_for(state="visible", timeout=120000)
        bili_logger.info(_msg("🥳", "投稿表单已渲染"))

    async def _fill_title(self, page) -> None:
        title_input = page.locator("input.input-val[placeholder='请输入稿件标题']").first
        await title_input.fill(self.title[:80])  # B 站上限 80 字
        bili_logger.info(_msg("✍️", f"标题已填: {self.title[:30]}"))

    async def _select_category(self, page) -> None:
        """分区为单列下拉，「科技数码」是一级分区选项（取证 2026-11-07）。"""
        try:
            trigger = page.locator(".selector-container").first
            await trigger.scroll_into_view_if_needed(timeout=5000)
            await trigger.click(timeout=5000)
            await page.wait_for_timeout(1200)
            option = page.get_by_text(self.category, exact=True).first
            if not await option.count():
                # 兜底：子串匹配，并 dump 已有选项供排查
                option = page.get_by_text(self.category).first
            if not await option.count():
                options = await page.evaluate(
                    "() => Array.from(document.querySelectorAll('[class*=\"select-item\"]'))"
                    ".map(el => (el.innerText||'').trim()).filter(Boolean).slice(0, 30)")
                raise RuntimeError(f"分区「{self.category}」未找到，可选分区: {options}")
            await option.click(timeout=5000)
            await page.wait_for_timeout(800)
            bili_logger.success(_msg("🥳", f"分区已选: {self.category}"))
        except RuntimeError:
            raise
        except Exception as exc:
            raise RuntimeError(f"选择分区「{self.category}」失败: {exc}")

    async def _apply_declaration(self, page) -> None:
        if not self.declaration:
            return
        try:
            trigger = page.locator(
                "input.bcc-select-input-inner[placeholder*='创作声明']").first
            if not await trigger.count():
                bili_logger.warning(_msg("😵", "未找到创作声明下拉，跳过声明"))
                return
            await trigger.click(timeout=5000)
            await page.wait_for_timeout(1000)
            option = page.locator(".bcc-select-option-list li, [class*='bcc-select'] [class*='option']").filter(
                has_text=self.declaration).first
            if not await option.count():
                bili_logger.warning(_msg("😵", f"创作声明「{self.declaration}」未找到，跳过（不阻断）"))
                await page.keyboard.press("Escape")
                return
            await option.click(timeout=5000)
            await page.wait_for_timeout(500)
            bili_logger.success(_msg("🥳", f"创作声明已选: {self.declaration}"))
        except Exception as exc:
            bili_logger.warning(_msg("😵", f"设置创作声明失败，跳过继续: {exc}"))

    async def _fill_tags(self, page) -> None:
        """B 站会自动推荐标签；先清掉推荐残留，再逐个输入并回车创建。"""
        if not self.tags:
            return
        try:
            tag_input = page.locator("input.input-val[placeholder*='创建标签']").first
            await tag_input.scroll_into_view_if_needed(timeout=5000)
            # 清理平台自动推荐的标签（点每项的关闭叉，若有）
            for close in await page.locator("[class*='tag-list'] [class*='close'], [class*='tag'] [class*='delete']").all():
                try:
                    await close.click(timeout=1500)
                except Exception:
                    pass
            for tag in self.tags[:10]:
                await tag_input.fill(tag)
                await page.keyboard.press("Enter")
                await page.wait_for_timeout(500)
            bili_logger.success(_msg("🥳", f"已添加 {len(self.tags[:10])} 个标签"))
        except Exception as exc:
            bili_logger.warning(_msg("😵", f"添加标签失败，跳过继续: {exc}"))

    async def _fill_desc(self, page) -> None:
        if not self.desc.strip():
            return
        try:
            editor = page.locator("div.ql-editor").first  # 取证：第一个 ql-editor 属于简介区
            await editor.scroll_into_view_if_needed(timeout=5000)
            await editor.click()
            await page.keyboard.press("Control+KeyA")
            await page.keyboard.type(self.desc)
            bili_logger.info(_msg("✍️", "简介已填"))
        except Exception as exc:
            bili_logger.warning(_msg("😵", f"填写简介失败，跳过继续: {exc}"))

    async def _set_cover(self, page) -> None:
        """五轮实跑教训（2026-11-07）：
        1. 封面必须喂弹窗自己的 input（页面级 first 是视频框，喂错报"不支持png"）
        2. 确认按钮是右下角 div.button.submit「完成」；弹窗 footer 的
           button.bcc-button--primary「确定」是隐藏预渲染，等 30 秒也等不到
        3. 裁剪界面渲染慢，可见按钮要轮询等待（3 秒不够）
        4. Escape 关不掉这个弹窗，失败兜底必须走右上角 X 关闭链
        5. 弹窗检测必须 :visible——DOM 里恒有 3 个隐藏预渲染 .bcc-dialog
        """
        if not self.cover_file:
            return
        try:
            entry = page.get_by_text("添加封面").first
            await entry.scroll_into_view_if_needed(timeout=5000)
            await entry.click(timeout=5000)
            await page.wait_for_timeout(2000)
            cover_input = page.locator(".bcc-dialog input[type=file]").first
            await cover_input.wait_for(state="attached", timeout=10000)
            await cover_input.set_input_files(self.cover_file)
            bili_logger.info(_msg("🖼️", "封面图已喂入弹窗，等待裁剪界面与「完成」按钮"))

            confirm_selector = ".cover-editor-content-right-bottom .button.submit"
            confirm = None
            for _ in range(15):  # 最多 30 秒：裁剪界面渲染完成按钮才出现
                cand = page.locator(confirm_selector).first
                try:
                    if await cand.count() and await cand.is_visible() and await cand.is_enabled():
                        confirm = cand
                        break
                except Exception:
                    pass
                await page.wait_for_timeout(2000)
            if confirm is None:
                bili_logger.warning(_msg("😵", "封面弹窗 30 秒内未出现可用的「完成」，放弃封面继续"))
                await self._dump_dialog(page)
                await self._close_cover_dialog(page)
                return

            # 三级点击递进：常规 → force → JS（浮层拦截时 force 可穿透，JS 兜底）
            clicked = False
            for attempt in ("normal", "force", "js"):
                try:
                    if attempt == "js":
                        await page.eval_on_selector(confirm_selector, "el => el.click()")
                    else:
                        await confirm.click(timeout=5000, force=(attempt == "force"))
                    clicked = True
                    break
                except Exception:
                    continue
            if not clicked:
                bili_logger.warning(_msg("😵", "封面「完成」点击失败，放弃封面继续"))
                await self._dump_dialog(page)
                await self._close_cover_dialog(page)
                return
            bili_logger.info(_msg("🖼️", "已点封面「完成」，等待弹窗关闭"))
            for _ in range(15):
                if await page.locator(".cover-editor:visible").count() == 0:
                    bili_logger.success(_msg("🥳", "封面已设置"))
                    return
                await page.wait_for_timeout(1000)
            bili_logger.warning(_msg("😵", "封面弹窗未关闭，dump DOM 后走 X 关闭链"))
            await self._dump_dialog(page)
            await self._close_cover_dialog(page)
        except Exception as exc:
            bili_logger.warning(_msg("😵", f"设置封面失败，跳过继续: {exc}"))
            await self._close_cover_dialog(page)

    async def _close_cover_dialog(self, page) -> None:
        """Escape 对封面弹窗无效；走右上角 X，并处理可能的放弃确认。"""
        try:
            close_btn = page.locator(".bcc-dialog .cover-editor-head-close").first
            if await close_btn.count():
                await close_btn.click(timeout=3000, force=True)
                await page.wait_for_timeout(1500)
                # 可能弹出「放弃封面编辑」二次确认
                for text in ("确定", "放弃"):
                    confirm_quit = page.locator(
                        f".bcc-dialog button:has-text('{text}'):visible").first
                    if await confirm_quit.count():
                        await confirm_quit.click(timeout=3000, force=True)
                        break
            await page.wait_for_timeout(1500)
            if await page.locator(".bcc-dialog").count():
                await page.keyboard.press("Escape")
        except Exception:
            pass

    async def _dump_dialog(self, page) -> None:
        try:
            html = await page.evaluate(
                "() => { const el = document.querySelector('.bcc-dialog:visible, [class*=\"dialog\"]:visible');"
                "return el ? el.innerText.slice(0, 300) : '(无可见弹窗)'; }")
            bili_logger.warning(_msg("🧾", f"可见弹窗内容: {html}"))
        except Exception:
            pass

    async def _submit(self, page) -> None:
        """成功信号：离开编辑页（实测存草稿后跳 upload-manager/article?group=draft）。"""
        if self.publish_strategy == BILIBILI_PUBLISH_STRATEGY_DRAFT:
            action, span = "存草稿", page.locator("span.submit-draft").first
        else:
            action, span = "立即投稿", page.locator("span.submit-add").first
        await span.scroll_into_view_if_needed(timeout=5000)
        await span.click(timeout=8000)
        for _ in range(15):
            await page.wait_for_timeout(1000)
            if "upload/video/frame" not in page.url:
                bili_logger.success(_msg("🥳", f"「{action}」成功，已离开编辑页: {page.url[:80]}"))
                return
        bili_logger.warning(_msg("⚠️", f"点击「{action}」后 15 秒仍未离开编辑页，请人工核验"))

    # ── 主流程 ──

    async def upload(self, playwright: Playwright) -> None:
        if self.publish_strategy not in {
            BILIBILI_PUBLISH_STRATEGY_IMMEDIATE,
            BILIBILI_PUBLISH_STRATEGY_DRAFT,
        }:
            raise ValueError(f"不支持的发布策略: {self.publish_strategy}")
        self.video_file = str(self.validate_video_file(self.video_file))
        if self.cover_file:
            self.cover_file = str(self.validate_image_file(self.cover_file))

        browser, context, owns_browser = await self._acquire_context(playwright)
        our_page = None
        try:
            page = await context.new_page()
            our_page = page
            _attach_network_diagnostics(page)
            if not await self._check_login(page):
                raise RuntimeError(
                    f"Bilibili 登录态失效（浏览器未登录或被跳到登录页）。"
                    "CDP 模式请确认常驻浏览器已登录 B 站；"
                    "持久化模式请先执行 `sau bilibili login --account <name> --browser` 扫码。"
                )
            bili_logger.info(_msg("🥳", "登录态有效"))
            await self._feed_video(page)
            await self._wait_form_ready(page)
            await self._wait_upload_complete(page)
            await self._fill_title(page)
            await self._select_category(page)
            await self._apply_declaration(page)
            await self._fill_tags(page)
            await self._fill_desc(page)
            await self._set_cover(page)
            # 提交前哨兵：残留弹窗会拦截存草稿/投稿的点击；必须 :visible
            # （DOM 里恒有 3 个隐藏预渲染 .bcc-dialog，裸 count 恒真）
            if await page.locator(".bcc-dialog:visible").count():
                bili_logger.warning(_msg("⚠️", "检测到残留弹窗，先关闭再提交"))
                await self._close_cover_dialog(page)
            await self._submit(page)
        finally:
            if owns_browser:
                closers = [context.close] + ([browser.close] if browser is not None else [])
            else:
                closers = [our_page.close] if our_page is not None else []
            for close in closers:
                try:
                    await close()
                except Exception:
                    pass

    async def bilibili_upload_video(self):
        async with async_playwright() as playwright:
            await self.upload(playwright)


async def bilibili_browser_login(account_file, headless: bool = LOCAL_CHROME_HEADLESS) -> dict:
    """持久化档案模式下扫码登录 B 站：打开创作中心，等待用户扫码后回到登录后页面。"""
    async with async_playwright() as playwright:
        kwargs = {
            "headless": headless,
            "args": ["--no-sandbox", "--disable-blink-features=AutomationControlled"],
        }
        if LOCAL_CHROME_PATH:
            kwargs["executable_path"] = LOCAL_CHROME_PATH
        else:
            kwargs["channel"] = "chromium"
        context = await playwright.chromium.launch_persistent_context(
            str(_persistent_profile_dir(account_file)), **kwargs
        )
        ok = False
        try:
            page = await context.new_page()
            await page.goto(BILIBILI_UPLOAD_URL, wait_until="domcontentloaded", timeout=90000)
            bili_logger.info(_msg("🧍", "请在浏览器中扫码登录 B 站，小人等待跳转…"))
            for _ in range(100):
                await page.wait_for_timeout(3000)
                if "passport.bilibili.com" not in page.url and "member.bilibili.com" in page.url:
                    await page.wait_for_timeout(2000)
                    if "passport.bilibili.com" not in page.url:
                        ok = True
                        break
        finally:
            await context.close()
        return {"success": ok, "account_file": str(account_file),
                "message": "Bilibili 浏览器登录完成" if ok else "登录超时或未完成"}
