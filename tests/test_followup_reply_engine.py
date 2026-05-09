import unittest

from uploader.followup.reply_engine import ReplyEngine


class FollowupReplyEngineTests(unittest.TestCase):
    def test_decide_hits_keyword_rule(self):
        engine = ReplyEngine()
        result = engine.decide("How much is it?")
        self.assertTrue(result.should_reply)
        self.assertEqual(result.reason, "commercial_intent")
        self.assertTrue(result.reply_text)

    def test_decide_skips_blacklist(self):
        engine = ReplyEngine()
        result = engine.decide("This looks like scam")
        self.assertFalse(result.should_reply)
        self.assertIn("blacklist", result.reason)

    def test_decide_uses_fallback(self):
        engine = ReplyEngine()
        result = engine.decide("Nice work")
        self.assertTrue(result.should_reply)
        self.assertEqual(result.reason, "fallback")
        self.assertTrue(result.reply_text)


if __name__ == "__main__":
    unittest.main()
