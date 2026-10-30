"""Safe unit tests for the Windows collector; no YouTube download or login needed."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import windows_short_collector as c


class LocalCollectorTests(unittest.TestCase):
    def test_config_uses_exact_three_approved_handles(self):
        cfg, sources = c.load_config()
        self.assertEqual({x["handle"] for x in sources}, c.APPROVED)
        self.assertTrue(cfg["mirror_horizontal"])

    def test_refuse_unapproved_fallback(self):
        with tempfile.TemporaryDirectory() as folder:
            config = Path(folder) / "config.json"
            config.write_text(json.dumps({
                "youtube_sources": [
                    {"handle": "@i11ush"},
                    {"handle": "@keymood_yt"},
                    {"handle": "@unapproved"},
                ]}), encoding="utf-8")
            with patch.object(c, "CONFIG", config):
                with self.assertRaisesRegex(RuntimeError, "unapproved"):
                    c.load_config()

    def test_ytdlp_command_keeps_login_on_owner_pc(self):
        plain = c.yt_command("none")
        self.assertNotIn("--cookies-from-browser", plain)
        edge = c.yt_command("edge")
        self.assertEqual(edge[-2:], ["--cookies-from-browser", "edge"])
        self.assertTrue(edge[1:3] == ["-m", "yt_dlp"])

    def test_errors_are_redacted(self):
        raw = "ERROR: Sign in to confirm you're not a bot; key=fake_value_xyz"
        reason = c.safe_failure(raw)
        self.assertIn("verification", reason)
        self.assertNotIn("fake_value_xyz", reason)

    def test_listing_keeps_valid_video_ids_only(self):
        data = {"entries": [
            {"id": "hp3q_LmqOnc", "title": "A"},
            {"id": "invalid", "title": "B"},
            {"id": "Sf123456789", "title": "C"},
        ]}
        with patch.object(c, "run_ytdlp", return_value=json.dumps(data)) as mock:
            found = c.listing("@i11ush", "none", 3)
        self.assertEqual([v["id"] for v in found], ["hp3q_LmqOnc", "Sf123456789"])
        self.assertTrue(all(v["handle"] == "@i11ush" for v in found))
        self.assertIn("https://www.youtube.com/@i11ush/shorts", mock.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
