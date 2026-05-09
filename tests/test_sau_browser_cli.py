import asyncio
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import AsyncMock, patch

import sau_cli
from uploader.followup.models import FollowupRunReport


class BrowserCliParserTests(unittest.TestCase):
    def test_build_parser_accepts_xiaohongshu_login(self):
        parser = sau_cli.build_parser()
        args = parser.parse_args(["xiaohongshu", "login", "--account", "creator"])
        self.assertEqual(args.platform, "xiaohongshu")
        self.assertEqual(args.action, "login")

    def test_douyin_upload_video_accepts_desc(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            video_path = Path(tmp_dir) / "demo.mp4"
            video_path.write_bytes(b"video")

            parser = sau_cli.build_parser()
            args = parser.parse_args(
                [
                    "douyin",
                    "upload-video",
                    "--account",
                    "creator",
                    "--file",
                    str(video_path),
                    "--title",
                    "title",
                    "--desc",
                    "description",
                ]
            )

        self.assertEqual(args.desc, "description")

    def test_kuaishou_upload_note_accepts_title_and_note(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            image_path = Path(tmp_dir) / "1.png"
            image_path.write_bytes(b"image")

            parser = sau_cli.build_parser()
            args = parser.parse_args(
                [
                    "kuaishou",
                    "upload-note",
                    "--account",
                    "creator",
                    "--images",
                    str(image_path),
                    "--title",
                    "note title",
                    "--note",
                    "note body",
                ]
            )

        self.assertEqual(args.title, "note title")
        self.assertEqual(args.note, "note body")

    def test_xiaohongshu_upload_video_defaults_to_headless(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            video_path = Path(tmp_dir) / "demo.mp4"
            video_path.write_bytes(b"video")

            parser = sau_cli.build_parser()
            args = parser.parse_args(
                [
                    "xiaohongshu",
                    "upload-video",
                    "--account",
                    "creator",
                    "--file",
                    str(video_path),
                    "--title",
                    "video title",
                ]
            )

        self.assertTrue(args.headless)

    def test_xiaohongshu_upload_note_accepts_headed(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            image_path = Path(tmp_dir) / "1.png"
            image_path.write_bytes(b"image")

            parser = sau_cli.build_parser()
            args = parser.parse_args(
                [
                    "xiaohongshu",
                    "upload-note",
                    "--account",
                    "creator",
                    "--images",
                    str(image_path),
                    "--title",
                    "note title",
                    "--note",
                    "note body",
                    "--headed",
                ]
            )

        self.assertFalse(args.headless)

    def test_build_parser_accepts_followup_run(self):
        parser = sau_cli.build_parser()
        args = parser.parse_args(
            [
                "followup",
                "run",
                "--platform",
                "douyin",
                "--account",
                "creator",
            ]
        )

        self.assertEqual(args.platform, "followup")
        self.assertEqual(args.action, "run")
        self.assertEqual(args.target_platform, "douyin")
        self.assertTrue(args.headless)


class BrowserCliDispatchTests(unittest.TestCase):
    def test_dispatch_xiaohongshu_check_prints_valid(self):
        args = Namespace(platform="xiaohongshu", action="check", account="creator")
        with patch("sau_cli.check_xiaohongshu_account", new=AsyncMock(return_value=True)):
            code = asyncio.run(sau_cli.dispatch(args))
        self.assertEqual(code, 0)

    def test_dispatch_douyin_upload_note_uses_new_request_fields(self):
        args = Namespace(
            platform="douyin",
            action="upload-note",
            account="creator",
            images=[Path("1.png")],
            title="note title",
            note="note body",
            tags="tag1,tag2",
            schedule=0,
            debug=False,
            headless=True,
        )
        with patch("sau_cli.upload_note", new=AsyncMock()) as mock_upload:
            asyncio.run(sau_cli.dispatch(args))

        request = mock_upload.await_args.args[0]
        self.assertEqual(request.title, "note title")
        self.assertEqual(request.note, "note body")

    def test_dispatch_xiaohongshu_upload_video_uses_headed_request(self):
        args = Namespace(
            platform="xiaohongshu",
            action="upload-video",
            account="creator",
            file=Path("demo.mp4"),
            title="video title",
            desc="video description",
            tags="tag1,tag2",
            schedule=0,
            thumbnail=None,
            debug=False,
            headless=False,
        )
        with patch("sau_cli.upload_xiaohongshu_video", new=AsyncMock()) as mock_upload:
            asyncio.run(sau_cli.dispatch(args))

        request = mock_upload.await_args.args[0]
        self.assertEqual(request.title, "video title")
        self.assertEqual(request.description, "video description")
        self.assertFalse(request.headless)

    def test_dispatch_xiaohongshu_upload_note_uses_headless_request(self):
        args = Namespace(
            platform="xiaohongshu",
            action="upload-note",
            account="creator",
            images=[Path("1.png"), Path("2.png")],
            title="note title",
            note="note body",
            tags="tag1,tag2",
            schedule=0,
            debug=False,
            headless=True,
        )
        with patch("sau_cli.upload_xiaohongshu_note", new=AsyncMock()) as mock_upload:
            asyncio.run(sau_cli.dispatch(args))

        request = mock_upload.await_args.args[0]
        self.assertEqual(request.title, "note title")
        self.assertEqual(request.note, "note body")
        self.assertTrue(request.headless)
        self.assertEqual(len(request.image_files), 2)

    def test_dispatch_followup_run_calls_runner(self):
        args = Namespace(
            platform="followup",
            action="run",
            target_platform="douyin",
            account="creator",
            limit=20,
            since_hours=48,
            max_replies=10,
            dry_run=True,
            headless=True,
            rules_file=None,
            reply_existing=False,
            min_delay_seconds=2.0,
            max_delay_seconds=6.0,
            comment_page_url="",
            debug=False,
        )
        report = FollowupRunReport(platform="douyin", account_name="creator")
        with patch("sau_cli.run_followup_once", new=AsyncMock(return_value=report)) as mock_runner:
            with patch("sau_cli._print_followup_report") as mock_print:
                code = asyncio.run(sau_cli.dispatch(args))

        self.assertEqual(code, 0)
        mock_runner.assert_awaited_once()
        mock_print.assert_called_once()


if __name__ == "__main__":
    unittest.main()
