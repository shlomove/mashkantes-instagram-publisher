"""Instagram Unified Login publisher. Validation is the default.

Deployment must supply persistent SQLite storage and a valid Instagram token.
Never delete a ledger entry to retry an uncertain publication.
"""
import argparse
import datetime as dt
import hashlib
import json
import os
import re
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo

ACCOUNT = "eliran_mashkantes"
API = "https://graph.facebook.com/v27.0"


def validate(manifest):
    if manifest.get("username") != ACCOUNT:
        raise ValueError("Unexpected destination account")
    date = dt.date.fromisoformat(manifest["date"])
    if date.isoformat() != manifest["date"]:
        raise ValueError("Date must use YYYY-MM-DD")
    caption = manifest.get("caption")
    if not isinstance(caption, str) or not caption.strip() or len(caption) > 2200:
        raise ValueError("Caption must contain 1 to 2200 characters")
    media = manifest.get("media", [])
    kind = manifest.get("format")
    if kind not in ("image", "carousel", "reel"):
        raise ValueError("Unsupported format")
    if not (2 <= len(media) <= 10 if kind == "carousel" else len(media) == 1):
        raise ValueError("Invalid media count")
    for item in media:
        url = urllib.parse.urlsplit(item["url"])
        if url.scheme != "https" or not url.hostname or url.username or url.password:
            raise ValueError("Media requires a public HTTPS URL without credentials")
        expected = "video/mp4" if kind == "reel" else "image/jpeg"
        if item.get("mime_type") != expected:
            raise ValueError("Media MIME type does not match format")
        if not re.fullmatch(r"[a-f0-9]{64}", item.get("sha256", "")):
            raise ValueError("Missing media SHA-256")
    if manifest.get("qa_passed") is not True:
        raise ValueError("Content QA has not passed")
    return hashlib.sha256(json.dumps(manifest, sort_keys=True,
                                    ensure_ascii=False).encode()).hexdigest()


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise RuntimeError("API redirect refused")


class Graph:
    def __init__(self, token):
        if not token:
            raise ValueError("Missing IG_ACCESS_TOKEN")
        self.token = token
        self.opener = urllib.request.build_opener(NoRedirect)

    def call(self, method, path, **params):
        if not re.fullmatch(r"(?:me|[0-9]+)(?:/[a-z_]+)?", path):
            raise ValueError("Invalid API path")
        encoded = urllib.parse.urlencode(params).encode()
        url = API + "/" + path
        if method == "GET":
            url += "?" + encoded.decode()
        req = urllib.request.Request(url, data=encoded if method == "POST" else None,
                                     method=method, headers={
                                         "Authorization": "Bearer " + self.token,
                                         "Content-Type": "application/x-www-form-urlencoded"})
        try:
            with self.opener.open(req, timeout=45) as response:
                result = json.load(response)
        except urllib.error.HTTPError as error:
            # Do not emit response bodies or request objects containing secrets.
            raise RuntimeError("Meta HTTP error " + str(error.code)) from None
        except (urllib.error.URLError, TimeoutError):
            raise RuntimeError("Meta transport failed; outcome may be unknown") from None
        if "error" in result:
            raise RuntimeError("Meta returned an API error")
        return result


class Ledger:
    def __init__(self, path):
        self.db = sqlite3.connect(path, timeout=10)
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute("CREATE TABLE IF NOT EXISTS posts (slot TEXT PRIMARY KEY, "
                        "digest TEXT NOT NULL, status TEXT NOT NULL, details TEXT NOT NULL)")
        self.db.commit()

    def claim(self, slot, digest):
        try:
            with self.db:
                self.db.execute("INSERT INTO posts VALUES (?, ?, 'claimed', '{}')",
                                (slot, digest))
        except sqlite3.IntegrityError:
            raise RuntimeError("Slot already claimed; inspect its record before any retry") from None

    def save(self, slot, status, details):
        with self.db:
            self.db.execute("UPDATE posts SET status=?, details=? WHERE slot=?",
                            (status, json.dumps(details), slot))

    def get(self, slot):
        return self.db.execute("SELECT digest,status,details FROM posts WHERE slot=?",
                               (slot,)).fetchone()


def publish(manifest, graph, ledger, account_id, now=None, sleep=time.sleep):
    digest = validate(manifest)
    if not re.fullmatch(r"[0-9]+", account_id):
        raise ValueError("A verified Instagram account ID is required")
    now = now or dt.datetime.now(ZoneInfo("Asia/Jerusalem"))
    if now.astimezone(ZoneInfo("Asia/Jerusalem")).date().isoformat() != manifest["date"]:
        raise ValueError("Stale or future content cannot be published")
    assigned = graph.call("GET", "me/assigned_instagram_accounts", fields="id,username", limit=100)
    # Fail closed if the exact intended account is not in the token's assigned assets.
    matches = [item for item in assigned.get("data", [])
               if item.get("username") == ACCOUNT and str(item.get("id")) == account_id]
    if len(matches) != 1:
        raise RuntimeError("Token account does not match the expected Instagram account")
    slot = ACCOUNT + ":" + manifest["date"] + ":instagram-daily-16:00"
    ledger.claim(slot, digest)
    details = {"containers": [], "account_id": account_id}

    def create(params):
        ledger.save(slot, "container_create_pending", details)
        result = graph.call("POST", account_id + "/media", **params)
        container_id = str(result.get("id", ""))
        if not container_id.isdigit():
            raise RuntimeError("Missing container ID")
        details["containers"].append(container_id)
        ledger.save(slot, "container_created", details)
        return container_id

    def ready(container_id):
        for attempt in range(6):
            result = graph.call("GET", container_id, fields="status_code")
            status = result.get("status_code")
            if status == "FINISHED":
                return
            if status != "IN_PROGRESS":
                raise RuntimeError("Container is not ready: " + str(status))
            if attempt < 5:
                sleep(60)
        raise RuntimeError("Container processing exceeded five minutes")

    try:
        kind = manifest["format"]
        if kind == "carousel":
            children = []
            for item in manifest["media"]:
                child = create({"image_url": item["url"], "is_carousel_item": "true"})
                ready(child)
                children.append(child)
            container = create({"media_type": "CAROUSEL", "children": ",".join(children),
                                "caption": manifest["caption"]})
        elif kind == "reel":
            container = create({"media_type": "REELS", "video_url": manifest["media"][0]["url"],
                                "caption": manifest["caption"], "share_to_feed": "true"})
        else:
            container = create({"image_url": manifest["media"][0]["url"],
                                "caption": manifest["caption"]})
        ready(container)
        details["publish_container"] = container
        # Persist intent before the irreversible request. A crash or timeout never auto-retries.
        ledger.save(slot, "publish_pending", details)
        result = graph.call("POST", account_id + "/media_publish", creation_id=container)
        media_id = str(result.get("id", ""))
        if not media_id.isdigit():
            raise RuntimeError("Publication result is uncertain")
        details["media_id"] = media_id
        ledger.save(slot, "published", details)
        return {"status": "published", "media_id": media_id, "slot": slot}
    except Exception:
        status = ledger.get(slot)[1]
        ledger.save(slot, "uncertain" if status == "publish_pending" else "blocked", details)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest")
    parser.add_argument("--publish", action="store_true")
    parser.add_argument("--ledger", default="state.sqlite3")
    args = parser.parse_args()
    with open(args.manifest, encoding="utf-8") as source:
        manifest = json.load(source)
    digest = validate(manifest)
    if not args.publish:
        print(json.dumps({"status": "validated_only", "sha256": digest}))
        return
    if os.environ.get("IG_PUBLICATION_ENABLED") != "true":
        raise RuntimeError("Publication is disabled")
    result = publish(manifest, Graph(os.environ.get("IG_ACCESS_TOKEN")),
                     Ledger(args.ledger), os.environ.get("IG_ACCOUNT_ID", ""))
    print(json.dumps(result))


if __name__ == "__main__":
    main()
