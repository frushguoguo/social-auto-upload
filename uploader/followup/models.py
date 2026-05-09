from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class CommentEvent:
    platform: str
    account_name: str
    comment_id: str
    comment_text: str
    commenter_name: str = ""
    commenter_id: str = ""
    post_id: str = ""
    post_url: str = ""
    comment_time: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ReplyDecision:
    should_reply: bool
    reply_text: str = ""
    reason: str = ""


@dataclass(slots=True)
class FollowupRunReport:
    platform: str
    account_name: str
    scanned_comments: int = 0
    new_comments: int = 0
    replied: int = 0
    skipped: int = 0
    failed: int = 0
    dry_run: bool = False
    bootstrap_applied: bool = False
    notes: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

