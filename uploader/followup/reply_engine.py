from __future__ import annotations

import json
import random
from dataclasses import dataclass
from pathlib import Path

from .models import ReplyDecision


@dataclass(slots=True)
class ReplyRule:
    keywords: list[str]
    replies: list[str]
    reason: str = ""


DEFAULT_BLACKLIST_KEYWORDS = [
    "spam",
    "scam",
    "fraud",
    "\u9a97\u5b50",
    "\u8bc8\u9a97",
]

DEFAULT_RULES = [
    ReplyRule(
        keywords=[
            "price",
            "how much",
            "buy",
            "order",
            "\u591a\u5c11\u94b1",
            "\u4ef7\u683c",
            "\u94fe\u63a5",
            "\u4e0b\u5355",
        ],
        replies=[
            "Thanks for asking. I will send the price and purchase details via DM.",
            "Appreciate your comment. I will DM the link and pricing details.",
        ],
        reason="commercial_intent",
    ),
    ReplyRule(
        keywords=[
            "tutorial",
            "how to",
            "steps",
            "\u6559\u7a0b",
            "\u65b9\u6cd5",
            "\u6b65\u9aa4",
        ],
        replies=[
            "Great question. I will post a detailed tutorial soon.",
            "Thanks for the feedback. I will share step-by-step instructions later.",
        ],
        reason="tutorial_request",
    ),
]

DEFAULT_FALLBACK_REPLIES = [
    "Thanks for your comment. Feel free to ask more.",
    "Appreciate your interaction. You can leave more questions anytime.",
]


class ReplyEngine:
    def __init__(
        self,
        *,
        rules: list[ReplyRule] | None = None,
        fallback_replies: list[str] | None = None,
        blacklist_keywords: list[str] | None = None,
        rng: random.Random | None = None,
    ):
        self.rules = rules if rules is not None else list(DEFAULT_RULES)
        self.fallback_replies = fallback_replies if fallback_replies is not None else list(DEFAULT_FALLBACK_REPLIES)
        self.blacklist_keywords = blacklist_keywords if blacklist_keywords is not None else list(DEFAULT_BLACKLIST_KEYWORDS)
        self.rng = rng or random.Random()

    def decide(self, comment_text: str) -> ReplyDecision:
        normalized = (comment_text or "").strip()
        if not normalized:
            return ReplyDecision(should_reply=False, reason="empty_comment")

        lower_text = normalized.lower()
        for blocked in self.blacklist_keywords:
            if blocked and blocked.lower() in lower_text:
                return ReplyDecision(should_reply=False, reason=f"blacklist:{blocked}")

        if lower_text.startswith("@") and len(normalized) <= 3:
            return ReplyDecision(should_reply=False, reason="mention_only")

        for rule in self.rules:
            if not rule.keywords or not rule.replies:
                continue
            if any(keyword and keyword.lower() in lower_text for keyword in rule.keywords):
                return ReplyDecision(
                    should_reply=True,
                    reply_text=self.rng.choice(rule.replies),
                    reason=rule.reason or "rule_matched",
                )

        if not self.fallback_replies:
            return ReplyDecision(should_reply=False, reason="no_fallback_reply")

        return ReplyDecision(
            should_reply=True,
            reply_text=self.rng.choice(self.fallback_replies),
            reason="fallback",
        )

    @classmethod
    def from_rules_file(cls, rules_file: str | Path) -> "ReplyEngine":
        rules_path = Path(rules_file).expanduser().resolve()
        payload = json.loads(rules_path.read_text(encoding="utf-8"))
        loaded_rules: list[ReplyRule] = []
        for item in payload.get("rules", []):
            if not isinstance(item, dict):
                continue
            keywords = [str(keyword).strip() for keyword in item.get("keywords", []) if str(keyword).strip()]
            replies = [str(reply).strip() for reply in item.get("replies", []) if str(reply).strip()]
            if not keywords or not replies:
                continue
            loaded_rules.append(
                ReplyRule(
                    keywords=keywords,
                    replies=replies,
                    reason=str(item.get("reason", "")).strip(),
                )
            )

        fallback_replies = [str(reply).strip() for reply in payload.get("fallback_replies", []) if str(reply).strip()]
        blacklist_keywords = [str(keyword).strip() for keyword in payload.get("blacklist_keywords", []) if str(keyword).strip()]
        return cls(
            rules=loaded_rules or None,
            fallback_replies=fallback_replies or None,
            blacklist_keywords=blacklist_keywords or None,
        )

