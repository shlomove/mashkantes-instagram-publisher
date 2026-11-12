"""Fail-closed cloud publisher; repository commits are the durable journal."""
import base64
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import urllib.error
import urllib.request
from zoneinfo import ZoneInfo
from publisher import Graph, NoRedirect, publish
from render import render


class Repository:
    def __init__(self, name, token):
        if name != 'shlomove/mashkantes-instagram-publisher':
            raise ValueError('Unexpected repository')
        self.name, self.token = name, token
        self.opener = urllib.request.build_opener(NoRedirect)

    def request(self, method, path, body=None):
        req = urllib.request.Request('https://api.github.com/repos/' + self.name + path,
            data=json.dumps(body).encode() if body is not None else None,
            headers={'Authorization': 'Bearer ' + self.token, 'Accept': 'application/vnd.github+json',
                     'Content-Type': 'application/json'}, method=method)
        try:
            with self.opener.open(req, timeout=45) as res:
                return json.load(res)
        except urllib.error.HTTPError as e:
            if e.code == 404 and method == 'GET':
                return None
            raise RuntimeError('GitHub request failed: ' + str(e.code)) from None

    def get(self, path):
        result = self.request('GET', '/contents/' + path)
        if result is None:
            return None, None
        return base64.b64decode(result['content']), result['sha']

    def put(self, path, data, sha=None):
        body = {'message': 'Update Instagram ' + path, 'content': base64.b64encode(data).decode()}
        if sha:
            body['sha'] = sha
        result = self.request('PUT', '/contents/' + path, body)
        return result['content']['sha'], result['commit']['sha']


class RemoteLedger:
    def __init__(self, repo, date):
        self.repo, self.path = repo, 'state/' + date + '.json'
        self.record = None
        self.sha = None

    def claim(self, slot, digest):
        data, _ = self.repo.get(self.path)
        if data is not None:
            raise RuntimeError('Publication slot already claimed; no automatic retry')
        self.record = {'slot': slot, 'digest': digest, 'status': 'claimed', 'details': {}}
        self._persist()  # Create-only PUT makes concurrent claims fail.

    def _persist(self):
        sha, _ = self.repo.put(self.path, json.dumps(self.record).encode(), self.sha)
        self.sha = sha

    def save(self, slot, status, details):
        if self.record is None or self.record['slot'] != slot:
            raise RuntimeError('Wrong publication slot')
        self.record.update(status=status, details=details)
        self._persist()  # Must succeed remotely before the next Meta side effect.

    def get(self, slot):
        data, _ = self.repo.get(self.path)
        if data is None:
            return None
        r = json.loads(data)
        return r['digest'], r['status'], json.dumps(r['details'])


def main():
    now = dt.datetime.now(ZoneInfo('Asia/Jerusalem'))
    date = now.date().isoformat()
    if now.weekday() in (4, 5):
        print('No publication on Friday or Saturday'); return
    source_path = Path('content') / (date + '.json')
    if not source_path.exists():
        print('No approved content for today'); return
    source = json.loads(source_path.read_text())
    if source.get('date') != date or source.get('qa_passed') is not True:
        raise ValueError('Current, approved content is required')
    if source.get('source_verified') is not True or not source.get('source_urls'):
        raise ValueError('Verified sources are required')
    if source.get('username') != 'eliran_mashkantes':
        raise ValueError('Wrong destination')
    repo = Repository(os.environ['GITHUB_REPOSITORY'], os.environ['GH_REPO_TOKEN'])
    state, _ = repo.get('state/' + date + '.json')
    if state is not None:
        print('Publication slot already recorded; no retry'); return
    source_digest = hashlib.sha256(source_path.read_bytes()).hexdigest()
    prepared_path = 'prepared/' + date + '.json'
    prepared, prepared_sha = repo.get(prepared_path)
    if prepared:
        data = json.loads(prepared)
        if data['source_sha256'] != source_digest:
            raise ValueError('Approved source changed after rendering; manual review required')
        manifest = data['manifest']
    else:
        outputs = render(source, Path('rendered'))
        media = []
        for path in outputs:
            payload = path.read_bytes()
            public_path = 'media/' + date + '/' + path.name
            existing, _ = repo.get(public_path)
            if existing is not None:
                raise ValueError('Unfinished media upload exists; manual review required')
            _, commit = repo.put(public_path, payload)
            url = 'https://raw.githubusercontent.com/' + repo.name + '/' + commit + '/' + public_path
            # Confirm publicly retrievable identical bytes before ever sending to Meta.
            with urllib.request.urlopen(url, timeout=45) as response:
                remote = response.read()
            if hashlib.sha256(remote).digest() != hashlib.sha256(payload).digest():
                raise ValueError('Public media byte verification failed')
            media.append({'url': url, 'mime_type': 'video/mp4' if path.suffix == '.mp4' else 'image/jpeg',
                          'sha256': hashlib.sha256(payload).hexdigest()})
        manifest = {k: source[k] for k in ('username', 'date', 'format', 'caption', 'qa_passed')}
        manifest['media'] = media
        repo.put(prepared_path, json.dumps({'source_sha256':source_digest,'manifest':manifest},ensure_ascii=False).encode())
    if os.environ.get('IG_PUBLICATION_ENABLED') != 'true':
        print('Media prepared; publication disabled'); return
    if not 16 <= now.hour < 18:
        print('Media ready; outside 16:00 to 18:00 Israel publishing window'); return
    result = publish(manifest, Graph(os.environ['IG_ACCESS_TOKEN']), RemoteLedger(repo, date),
                     '17841435230882039', now=now)
    print(json.dumps(result))


if __name__ == '__main__':
    main()
