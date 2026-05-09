from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from patchright.async_api import Browser
from patchright.async_api import BrowserContext
from patchright.async_api import Page
from patchright.async_api import Playwright
from patchright.async_api import async_playwright

from conf import LOCAL_CHROME_HEADLESS
from utils.base_social_media import set_init_script
from utils.log import followup_logger

from .models import CommentEvent

TEXT_COMMENT = "\u8bc4\u8bba"
TEXT_REPLY = "\u56de\u590d"
TEXT_SEND = "\u53d1\u9001"


@dataclass(slots=True)
class _CommentSnapshot:
    comment_id: str
    commenter_name: str
    comment_text: str
    comment_time: str
    row_token: str
    raw_text: str


class DouyinCommentAdapter:
    COMMENT_PAGE_CANDIDATES = [
        "https://creator.douyin.com/creator-micro/interactive/comment",
        "https://creator.douyin.com/creator-micro/interaction/comment/manage",
        "https://creator.douyin.com/creator-micro/interaction/comment",
        "https://creator.douyin.com/creator-micro/content/comment",
        "https://creator.douyin.com/creator-micro/content/manage",
    ]

    def __init__(
        self,
        *,
        account_file: str,
        account_name: str,
        headless: bool = LOCAL_CHROME_HEADLESS,
        comment_page_url: str | None = None,
    ):
        self.account_file = account_file
        self.account_name = account_name
        self.headless = headless
        self.comment_page_url = comment_page_url
        self.playwright: Playwright | None = None
        self.browser: Browser | None = None
        self.context: BrowserContext | None = None
        self.page: Page | None = None

    async def __aenter__(self) -> "DouyinCommentAdapter":
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(headless=self.headless, channel="chrome")
        self.context = await self.browser.new_context(storage_state=self.account_file)
        self.context = await set_init_script(self.context)
        self.page = await self.context.new_page()
        await self._goto_comment_page()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        if self.context:
            try:
                await self.context.storage_state(path=self.account_file)
            except Exception:
                pass
            await self.context.close()
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()

    async def _goto_comment_page(self) -> None:
        if not self.page:
            raise RuntimeError("Douyin comment page not initialized")

        candidates = [self.comment_page_url] if self.comment_page_url else []
        candidates.extend(self.COMMENT_PAGE_CANDIDATES)
        seen: set[str] = set()
        for candidate in candidates:
            if not candidate or candidate in seen:
                continue
            seen.add(candidate)
            try:
                await self.page.goto(candidate)
                await self.page.wait_for_timeout(2000)
                if "login" in self.page.url:
                    continue
                if await self._looks_like_comment_page(self.page):
                    followup_logger.info(f"Opened Douyin comment page: {self.page.url}")
                    return
            except Exception as exc:
                followup_logger.warning(f"Failed to open comment page {candidate}: {exc}")

        raise RuntimeError("Cannot locate Douyin comment management page. Use --comment-page-url to specify one.")

    @staticmethod
    async def _looks_like_comment_page(page: Page) -> bool:
        if "interactive/comment" in page.url or "interaction/comment" in page.url or "content/comment" in page.url:
            return True

        try:
            has_comment_manager = await page.get_by_text(TEXT_COMMENT + "\u7ba1\u7406", exact=False).count()
            has_reply = await page.get_by_text(TEXT_REPLY, exact=False).count()
            if has_comment_manager and has_reply:
                return True
        except Exception:
            pass
        return False

    async def fetch_comments(self, *, limit: int = 20) -> list[CommentEvent]:
        if not self.page:
            raise RuntimeError("Douyin adapter page is not ready")

        await self.page.wait_for_timeout(6000)

        snapshots: list[dict[str, Any]] = await self.page.evaluate(
            """
            ({replyToken}) => {
              const normalize = (value) => (value || "").replace(/\\s+/g, " ").trim();
              const hashCode = (value) => {
                let hash = 0;
                for (let i = 0; i < value.length; i += 1) {
                  hash = ((hash << 5) - hash) + value.charCodeAt(i);
                  hash |= 0;
                }
                return Math.abs(hash);
              };

              const rows = Array.from(document.querySelectorAll("div[class*='container-']"))
                .sort((left, right) => {
                  const leftText = normalize(left.innerText || left.textContent || "");
                  const rightText = normalize(right.innerText || right.textContent || "");
                  return leftText.length - rightText.length;
                });
              const results = [];
              for (let idx = 0; idx < rows.length; idx += 1) {
                const row = rows[idx];
                const fullText = normalize(row.innerText || row.textContent || "");
                if (!fullText || fullText.length < 2) {
                  continue;
                }
                const commentNode = row.querySelector("div[class*='comment-content-text-']");
                const operationsNode = row.querySelector("div[class*='operations-']");
                if (!commentNode || !operationsNode) {
                  continue;
                }
                const hasReplyAction = Array.from(operationsNode.querySelectorAll("button,a,span,div")).some((node) => {
                  const text = normalize(node.innerText || node.textContent || "");
                  return text === replyToken || text.includes(replyToken);
                });
                if (!hasReplyAction) {
                  continue;
                }
                const commentText = normalize(commentNode.innerText || commentNode.textContent || "").slice(0, 500);
                if (!commentText) {
                  continue;
                }
                const nameNode = row.querySelector("[class*='username-'],[class*='name'],[class*='nick'],[class*='author'],a[href*='user']");
                const timeNode = row.querySelector("time,[class*='time'],[class*='date']");
                const commenterName = normalize(nameNode ? (nameNode.innerText || nameNode.textContent || "") : "");
                const commentTime = normalize(timeNode ? (timeNode.innerText || timeNode.textContent || "") : "");
                const signature = `${commenterName}|${commentTime}|${commentText}`;
                const commentId = `dom-${hashCode(signature || `${commentText}|${idx}`)}`;
                const rowToken = signature || `row-${idx}`;
                results.push({
                  comment_id: commentId,
                  commenter_name: commenterName,
                  comment_text: commentText,
                  comment_time: commentTime,
                  row_token: rowToken,
                  raw_text: fullText.slice(0, 1000),
                });
              }
              return results;
            }
            """,
            {"replyToken": TEXT_REPLY},
        )

        events: list[CommentEvent] = []
        seen_ids: set[str] = set()
        for item in snapshots:
            try:
                snapshot = _CommentSnapshot(
                    comment_id=str(item.get("comment_id", "")).strip(),
                    commenter_name=str(item.get("commenter_name", "")).strip(),
                    comment_text=str(item.get("comment_text", "")).strip(),
                    comment_time=str(item.get("comment_time", "")).strip(),
                    row_token=str(item.get("row_token", "")).strip(),
                    raw_text=str(item.get("raw_text", "")).strip(),
                )
            except Exception:
                continue
            if not snapshot.comment_id or not snapshot.comment_text:
                continue
            if snapshot.comment_id in seen_ids:
                continue
            seen_ids.add(snapshot.comment_id)
            events.append(
                CommentEvent(
                    platform="douyin",
                    account_name=self.account_name,
                    comment_id=snapshot.comment_id,
                    comment_text=snapshot.comment_text,
                    commenter_name=snapshot.commenter_name,
                    comment_time=snapshot.comment_time,
                    post_url=self.page.url,
                    raw={
                        "row_token": snapshot.row_token,
                        "raw_text": snapshot.raw_text,
                    },
                )
            )
            if len(events) >= max(1, limit):
                break

        return events

    async def reply_comment(self, comment: CommentEvent, reply_text: str) -> None:
        if not self.page:
            raise RuntimeError("Douyin adapter page is not ready")
        if not reply_text.strip():
            raise ValueError("reply text cannot be empty")

        clicked = await self.page.evaluate(
            """
            ({snippet, commenterName, commentTime, replyToken}) => {
              const normalize = (value) => (value || "").replace(/\\s+/g, " ").trim();
              const rows = Array.from(document.querySelectorAll("div[class*='container-']"))
                .sort((left, right) => {
                  const leftText = normalize(left.innerText || left.textContent || "");
                  const rightText = normalize(right.innerText || right.textContent || "");
                  return leftText.length - rightText.length;
                });
              const target = rows.find((row) => {
                const commentNode = row.querySelector("div[class*='comment-content-text-']");
                const operationsNode = row.querySelector("div[class*='operations-']");
                if (!commentNode || !operationsNode) {
                  return false;
                }
                const rowComment = normalize(commentNode.innerText || commentNode.textContent || "");
                const nameNode = row.querySelector("[class*='username-'],[class*='name'],[class*='nick'],[class*='author']");
                const timeNode = row.querySelector("time,[class*='time'],[class*='date']");
                const rowName = normalize(nameNode ? (nameNode.innerText || nameNode.textContent || "") : "");
                const rowTime = normalize(timeNode ? (timeNode.innerText || timeNode.textContent || "") : "");
                if (snippet && rowComment !== snippet) {
                  return false;
                }
                if (commenterName && rowName && !rowName.includes(commenterName)) {
                  return false;
                }
                if (commentTime && rowTime && !rowTime.includes(commentTime)) {
                  return false;
                }
                return true;
              });
              if (!target) {
                return false;
              }
              const operationsNode = target.querySelector("div[class*='operations-']") || target;
              const buttons = Array.from(operationsNode.querySelectorAll("button,a,span,div"));
              const replyButton = buttons.find((button) => {
                const text = normalize(button.innerText || button.textContent || "");
                return text === replyToken || text.includes(replyToken);
              });
              if (!replyButton) {
                return false;
              }
              replyButton.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
              return true;
            }
            """,
            {
                "snippet": comment.comment_text,
                "commenterName": comment.commenter_name,
                "commentTime": comment.comment_time,
                "replyToken": TEXT_REPLY,
            },
        )
        if not clicked:
            raise RuntimeError(f"Reply action not found for comment: {comment.comment_id}")

        await asyncio.sleep(1)
        filled = await self._fill_reply_input(reply_text)
        if not filled:
            raise RuntimeError(f"Reply input not found for comment: {comment.comment_id}")

        submitted = await self._submit_reply()
        if not submitted:
            await self.page.keyboard.press("Enter")
        await asyncio.sleep(1)

    async def _fill_reply_input(self, reply_text: str) -> bool:
        if not self.page:
            return False

        selectors = [
            f"div[contenteditable='true'][placeholder*='{TEXT_REPLY}']",
            f"textarea[placeholder*='{TEXT_REPLY}']",
            f"textarea[placeholder*='{TEXT_COMMENT}']",
            f"div[contenteditable='true'][placeholder*='{TEXT_COMMENT}']",
            "textarea",
            "div[contenteditable='true']",
        ]
        for selector in selectors:
            locator = self.page.locator(selector).first
            try:
                if not await locator.count():
                    continue
                await locator.wait_for(state="visible", timeout=3000)
            except Exception:
                continue

            try:
                if selector.startswith("div[contenteditable"):
                    await locator.click()
                    await self.page.keyboard.press("Control+KeyA")
                    await self.page.keyboard.press("Delete")
                    await self.page.keyboard.type(reply_text)
                else:
                    await locator.fill("")
                    await locator.fill(reply_text)
                return True
            except Exception:
                continue
        return False

    async def _submit_reply(self) -> bool:
        if not self.page:
            return False

        candidates = [
            self.page.get_by_role("button", name=TEXT_SEND).first,
            self.page.get_by_role("button", name=TEXT_REPLY).first,
            self.page.get_by_text(TEXT_SEND, exact=True).first,
            self.page.get_by_text(TEXT_REPLY, exact=True).first,
        ]
        for candidate in candidates:
            try:
                if await candidate.count() and await candidate.is_visible():
                    await candidate.click(force=True)
                    return True
            except Exception:
                continue
        return False
