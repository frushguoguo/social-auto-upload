from __future__ import annotations

import asyncio
import random
from dataclasses import asdict
from pathlib import Path

from utils.log import followup_logger

from .douyin_adapter import DouyinCommentAdapter
from .models import FollowupRunReport
from .reply_engine import ReplyEngine
from .store import FollowupStore


async def run_douyin_followup_once(
    *,
    account_name: str,
    account_file: str,
    limit: int = 20,
    max_replies: int = 10,
    since_hours: int = 48,
    dry_run: bool = False,
    headless: bool = True,
    rules_file: str | None = None,
    bootstrap_skip_existing: bool = True,
    min_delay_seconds: float = 2.0,
    max_delay_seconds: float = 6.0,
    comment_page_url: str | None = None,
) -> FollowupRunReport:
    store = FollowupStore()
    engine = ReplyEngine.from_rules_file(Path(rules_file)) if rules_file else ReplyEngine()
    report = FollowupRunReport(platform="douyin", account_name=account_name, dry_run=dry_run)

    if since_hours > 0:
        recent_records = store.list_recent_publish_records(
            platform="douyin",
            account_name=account_name,
            since_hours=since_hours,
            limit=100,
        )
        if not recent_records:
            report.notes.append(f"No publish records found in last {since_hours} hours. Skip followup.")
            return report

    historical_count = store.count_comments(platform="douyin", account_name=account_name)
    delay_min = max(0.0, min(min_delay_seconds, max_delay_seconds))
    delay_max = max(delay_min, max_delay_seconds)
    max_replies_cap = max(0, max_replies)

    async with DouyinCommentAdapter(
        account_file=account_file,
        account_name=account_name,
        headless=headless,
        comment_page_url=comment_page_url,
    ) as adapter:
        comments = await adapter.fetch_comments(limit=max(1, limit))
        report.scanned_comments = len(comments)

        if report.scanned_comments == 0:
            report.notes.append("No comments fetched.")
            return report

        if historical_count == 0 and bootstrap_skip_existing:
            for comment in comments:
                if store.upsert_comment_event(comment):
                    report.new_comments += 1
            report.bootstrap_applied = True
            report.skipped += len(comments)
            report.notes.append("Bootstrap applied on first run. Historical comments are skipped in this round.")
            return report

        replied_now = 0
        for comment in comments:
            is_new_comment = store.upsert_comment_event(comment)
            if is_new_comment:
                report.new_comments += 1
            elif store.has_successful_reply(platform="douyin", comment_id=comment.comment_id):
                report.skipped += 1
                continue

            decision = engine.decide(comment.comment_text)
            if not decision.should_reply:
                store.log_reply(
                    platform="douyin",
                    account_name=account_name,
                    comment_id=comment.comment_id,
                    reply_text="",
                    status="skipped",
                    reason=decision.reason,
                )
                report.skipped += 1
                continue

            if replied_now >= max_replies_cap:
                store.log_reply(
                    platform="douyin",
                    account_name=account_name,
                    comment_id=comment.comment_id,
                    reply_text=decision.reply_text,
                    status="skipped",
                    reason="max_replies_reached",
                )
                report.skipped += 1
                continue

            if dry_run:
                store.log_reply(
                    platform="douyin",
                    account_name=account_name,
                    comment_id=comment.comment_id,
                    reply_text=decision.reply_text,
                    status="dry_run",
                    reason=decision.reason,
                )
                report.replied += 1
                replied_now += 1
                continue

            try:
                await adapter.reply_comment(comment, decision.reply_text)
                store.log_reply(
                    platform="douyin",
                    account_name=account_name,
                    comment_id=comment.comment_id,
                    reply_text=decision.reply_text,
                    status="success",
                    reason=decision.reason,
                )
                report.replied += 1
                replied_now += 1
                sleep_seconds = random.uniform(delay_min, delay_max)
                if sleep_seconds > 0:
                    await asyncio.sleep(sleep_seconds)
            except Exception as exc:
                error_text = str(exc)
                followup_logger.error(f"Reply failed comment_id={comment.comment_id}: {error_text}")
                store.log_reply(
                    platform="douyin",
                    account_name=account_name,
                    comment_id=comment.comment_id,
                    reply_text=decision.reply_text,
                    status="failed",
                    reason=decision.reason,
                    error_message=error_text,
                )
                report.failed += 1
                report.errors.append(f"{comment.comment_id}: {error_text}")

    return report


async def run_douyin_followup_daemon(
    *,
    account_name: str,
    account_file: str,
    interval_seconds: int = 60,
    max_rounds: int = 0,
    **kwargs,
) -> int:
    rounds = 0
    while True:
        rounds += 1
        report = await run_douyin_followup_once(
            account_name=account_name,
            account_file=account_file,
            **kwargs,
        )
        followup_logger.info(f"followup round={rounds} report={asdict(report)}")

        if max_rounds > 0 and rounds >= max_rounds:
            return rounds
        await asyncio.sleep(max(1, interval_seconds))

