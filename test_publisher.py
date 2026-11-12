import copy
import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from zoneinfo import ZoneInfo
from publisher import Ledger, publish, validate

NOW = dt.datetime(2026, 11, 11, 16, tzinfo=ZoneInfo("Asia/Jerusalem"))
POST = {"date": "2026-11-11", "username": "eliran_mashkantes", "format": "image",
        "caption": "תוכן בדיקה", "qa_passed": True,
        "media": [{"url": "https://example.com/media.jpg", "mime_type": "image/jpeg",
                   "sha256": "a" * 64}]}


class FakeGraph:
    def __init__(self, fail_publish=False, username="eliran_mashkantes"):
        self.calls = []
        self.fail_publish = fail_publish
        self.username = username
        self.counter = 100

    def call(self, method, path, **params):
        self.calls.append((method, path, params))
        if path == "me/assigned_instagram_accounts":
            return {"data": [{"id": "123", "username": self.username}]}
        if method == "GET":
            return {"status_code": "FINISHED"}
        if path.endswith("/media_publish"):
            if self.fail_publish:
                raise TimeoutError("simulated lost response")
            return {"id": "999"}
        self.counter += 1
        return {"id": str(self.counter)}


class PublisherTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.ledger = Ledger(str(Path(self.temp.name) / "state.sqlite3"))
        self.slot = "eliran_mashkantes:2026-11-11:instagram-daily-16:00"

    def tearDown(self):
        self.ledger.db.close()
        self.temp.cleanup()

    def test_image_and_duplicate_block(self):
        graph = FakeGraph()
        self.assertEqual(publish(POST, graph, self.ledger, "123", NOW)["media_id"], "999")
        self.assertEqual(self.ledger.get(self.slot)[1], "published")
        with self.assertRaisesRegex(RuntimeError, "already claimed"):
            publish(POST, graph, self.ledger, "123", NOW)
        self.assertEqual(sum(p.endswith("media_publish") for _, p, _ in graph.calls), 1)

    def test_lost_publish_response_is_never_retried(self):
        graph = FakeGraph(fail_publish=True)
        with self.assertRaises(TimeoutError):
            publish(POST, graph, self.ledger, "123", NOW)
        self.assertEqual(self.ledger.get(self.slot)[1], "uncertain")
        details = json.loads(self.ledger.get(self.slot)[2])
        self.assertIn("publish_container", details)
        with self.assertRaisesRegex(RuntimeError, "already claimed"):
            publish(POST, graph, self.ledger, "123", NOW)
        self.assertEqual(sum(p.endswith("media_publish") for _, p, _ in graph.calls), 1)

    def test_wrong_account_never_writes(self):
        graph = FakeGraph(username="someone_else")
        with self.assertRaisesRegex(RuntimeError, "does not match"):
            publish(POST, graph, self.ledger, "123", NOW)
        self.assertFalse(any(m == "POST" for m, _, _ in graph.calls))
        self.assertIsNone(self.ledger.get(self.slot))

    def test_stale_content_never_calls_api(self):
        graph = FakeGraph()
        with self.assertRaisesRegex(ValueError, "Stale"):
            publish(POST, graph, self.ledger, "123", NOW + dt.timedelta(days=1))
        self.assertEqual(graph.calls, [])

    def test_carousel_order_and_caption(self):
        manifest = copy.deepcopy(POST)
        manifest["format"] = "carousel"
        manifest["media"].append({**manifest["media"][0], "url": "https://example.com/second.jpg"})
        graph = FakeGraph()
        publish(manifest, graph, self.ledger, "123", NOW)
        creates = [params for method, path, params in graph.calls
                   if method == "POST" and path.endswith("/media")]
        self.assertEqual([item["image_url"] for item in creates[:2]],
                         [item["url"] for item in manifest["media"]])
        self.assertEqual(creates[2]["children"], "101,102")
        self.assertEqual(creates[2]["caption"], POST["caption"])

    def test_reel(self):
        manifest = copy.deepcopy(POST)
        manifest["format"] = "reel"
        manifest["media"][0].update(url="https://example.com/reel.mp4", mime_type="video/mp4")
        graph = FakeGraph()
        publish(manifest, graph, self.ledger, "123", NOW)
        create = [p for m, path, p in graph.calls if m == "POST" and path.endswith("/media")][0]
        self.assertEqual(create["media_type"], "REELS")
        self.assertIn("video_url", create)

    def test_qa_and_media_required(self):
        for change in ({"qa_passed": False}, {"media": []}, {"username": "other"}):
            with self.assertRaises(ValueError):
                validate({**POST, **change})


if __name__ == "__main__":
    unittest.main()
