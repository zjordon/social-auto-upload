# -*- coding: utf-8 -*-
"""大文件喂入：CDP 接管模式下绕过 Playwright 的 50MB 转发上限。

Playwright 对「非自己启动的浏览器」（connect_over_cdp 接管常驻浏览器）执行
set_input_files 时，会把文件内容经驱动转发给浏览器，超过 50MB 直接拒绝：

  Locator.set_input_files: Cannot transfer files larger than 50Mb
  to a browser not co-located with the server

而本场景浏览器就在本机——正确解法是直接用 CDP 的 DOM.setFileInputFiles
下发**本地绝对路径**，由浏览器进程自己读盘，零拷贝、无大小上限。
（Playwright 对自己启动的本地浏览器，内部用的正是同一个 CDP 命令。）
"""
from __future__ import annotations

from pathlib import Path

SET_INPUT_FILES_SIZE_LIMIT = 50 * 1024 * 1024


def needs_cdp_file_transfer(file_path) -> bool:
    """Playwright 转发通道是否放不下这个文件（>50MB）。"""
    try:
        return Path(file_path).stat().st_size > SET_INPUT_FILES_SIZE_LIMIT
    except OSError:
        return False


async def set_input_files_via_cdp(page, selector: str, file_path: str) -> None:
    """对主文档里的 file input 直接下发本地路径（只支持主 frame 的 input）。"""
    session = await page.context.new_cdp_session(page)
    try:
        doc = await session.send("DOM.getDocument", {"depth": 0})
        node = await session.send(
            "DOM.querySelector", {"nodeId": doc["root"]["nodeId"], "selector": selector}
        )
        if not node.get("nodeId"):
            raise RuntimeError(f"CDP 找不到 file input: {selector}")
        await session.send(
            "DOM.setFileInputFiles",
            {
                "files": [str(Path(file_path).resolve())],
                "nodeId": node["nodeId"],
            },
        )
    finally:
        try:
            await session.detach()
        except Exception:
            pass


async def feed_file_input(page, selector: str, file_path: str, force_cdp_channel: bool = False) -> bool:
    """喂入 file input，自动选路。

    - force_cdp_channel=True：CDP 接管常驻浏览器时使用。实测（2026-11-14，
      37.9MB 文件）：Playwright 通道要把文件读成 base64 经协议注入页面，
      耗时 ~30 秒（贴着 30s 默认超时，稍重即爆 Timeout）、>50MB 直接拒绝；
      CDP 本地路径通道 0.06 秒。接管模式下无论大小都应强制走后者。
    - 其余（本地启动的浏览器）：小文件走 Playwright 原通道（其内部本就传
      本地路径，无上限）；>50MB 兜底走 CDP。
    返回是否走了 CDP 通道（供调用方记日志）。
    """
    if force_cdp_channel or needs_cdp_file_transfer(file_path):
        await set_input_files_via_cdp(page, selector, file_path)
        return True
    await page.locator(selector).first.set_input_files(file_path)
    return False
