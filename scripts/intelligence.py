#!/usr/bin/env python3
"""Public collection and transactional local records. Python 3.10+, stdlib only."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from urllib.parse import urlparse
from urllib.request import Request, urlopen
import uuid

SOURCES = ['whatnot-help', 'whatnot-blog', 'seller-academy', 'industry', 'seller-experience']
UTC = timezone.utc

def stamp():
    return datetime.now(UTC).isoformat(timespec='seconds')

def date(value):
    d = datetime.fromisoformat(value.replace('Z', '+00:00'))
    return d.replace(tzinfo=UTC) if d.tzinfo is None else d.astimezone(UTC)

def home():
    if sys.platform == 'darwin':
        return Path.home() / 'Library/Application Support/whatnot-seller-insights'
    if os.name == 'nt':
        return Path(os.environ.get('LOCALAPPDATA', Path.home() / 'AppData/Local')) / 'whatnot-seller-insights'
    return Path(os.environ.get('XDG_DATA_HOME', Path.home() / '.local/share')) / 'whatnot-seller-insights'

def connect(root):
    root.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(root / 'records.sqlite3')
    db.execute('CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
    return db

def get(db, key, default=None):
    row = db.execute('SELECT value FROM kv WHERE key=?', (key,)).fetchone()
    return json.loads(row[0]) if row else default

def put(db, key, value):
    db.execute('INSERT OR REPLACE INTO kv VALUES (?,?)', (key, json.dumps(value, ensure_ascii=False)))

def plan(db, end=None, start=None):
    end = date(end or stamp())
    initial = get(db, 'initial_start')
    if initial is None:
        initial = (end - timedelta(days=15)).isoformat()
        put(db, 'initial_start', initial)
    windows = {}
    for source in SOURCES:
        a = date(start or get(db, 'progress:' + source, initial))
        if a > end:
            raise ValueError('start must not be after end')
        windows[source] = {'start': a.isoformat(), 'end': end.isoformat()}
    return {'id': uuid.uuid4().hex, 'created_at': stamp(), 'custom_range': start is not None, 'windows': windows}

class Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.hidden = 0
    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style'):
            self.hidden += 1
        if tag in ('br', 'p', 'div', 'li', 'h1', 'h2', 'h3', 'tr'):
            self.parts.append(' ')
    def handle_endtag(self, tag):
        if tag in ('script', 'style'):
            self.hidden = max(0, self.hidden - 1)
        self.parts.append(' ')
    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)

def normalized(html):
    p = Text()
    p.feed(html or '')
    return ' '.join(''.join(p.parts).split())

def fetch(url):
    parsed = urlparse(url)
    if parsed.scheme != 'https' or parsed.netloc != 'help.whatnot.com' or not parsed.path.startswith('/api/v2/help_center/'):
        raise ValueError('Unexpected API pagination URL')
    with urlopen(Request(url, headers={'User-Agent': 'WhatnotSellerInsights/1.0', 'Accept': 'application/json'}), timeout=40) as response:
        data = response.read(20_000_001)
    if len(data) > 20_000_000:
        raise ValueError('API response too large')
    return json.loads(data)

def collect(db, run, loader=fetch):
    url = 'https://help.whatnot.com/api/v2/help_center/en-us/articles.json?per_page=100'
    seen, snapshots, candidates = set(), {}, []
    window = run['windows']['whatnot-help']
    try:
        while url:
            if url in seen or len(seen) >= 100:
                raise ValueError('Pagination cycle or limit')
            seen.add(url)
            result = loader(url)
            for article in result['articles']:
                key = str(article['id'])
                body = normalized(article.get('body'))
                digest = hashlib.sha256((article['title'] + '\n' + body).encode()).hexdigest()
                current = {k: article.get(k) for k in ('id', 'title', 'html_url', 'created_at', 'edited_at', 'updated_at', 'section_id')}
                current.update(text=body, hash=digest)
                snapshots[key] = current
                previous = get(db, 'article:' + key)
                edited = article.get('edited_at') or article.get('created_at')
                in_window = edited and date(window['start']) <= date(edited) <= date(window['end'])
                changed = previous and previous['hash'] != digest
                if changed or (not previous and in_window):
                    candidates.append(dict(current, detection='content_changed_since_snapshot' if changed else 'dated_candidate_without_prior_snapshot', previous=previous, observed_at=stamp()))
            url = result.get('next_page')
        status = 'retrieved'
        error = None
    except Exception as exc:
        status, error = 'partial_or_failed', str(exc)
    evidence = {'source': 'whatnot-help', 'status': status, 'error': error, 'fetched_at': stamp(), 'pages': len(seen), 'articles': len(snapshots), 'candidates': candidates,
                'warning': 'Current public inventory only; edit timestamps are not effective dates. Before/after evidence exists only for previously finalized snapshots. Deleted items and historical changes may be missing.'}
    put(db, 'staged:' + run['id'], snapshots)
    put(db, 'evidence:' + run['id'], evidence)
    return evidence

def finish(db, run, coverage, report):
    if get(db, 'finished:' + run['id']):
        raise ValueError('Run already finalized')
    if not report.strip():
        raise ValueError('Report is empty')
    for source, item in coverage.items():
        if source not in SOURCES or item['status'] not in ('complete', 'partial', 'failed'):
            raise ValueError('Invalid coverage entry')
        if not item.get('evidence'):
            raise ValueError('Coverage requires supporting evidence or failure reason')
        if item['status'] == 'complete':
            if source == 'whatnot-help' and get(db, 'evidence:' + run['id'], {}).get('status') != 'retrieved':
                raise ValueError('Official collection must succeed before completion')
            a, b = date(item['start']), date(item['end'])
            w = run['windows'][source]
            if a < date(w['start']) or b > date(w['end']) or b < a:
                raise ValueError('Coverage outside planned window')
            cursor = date(get(db, 'progress:' + source, get(db, 'initial_start')))
            # Explicit ranges may fill a gap, but may never jump over one.
            if a <= cursor <= b:
                put(db, 'progress:' + source, b.isoformat())
    help_coverage = coverage.get('whatnot-help', {})
    evidence = get(db, 'evidence:' + run['id'], {})
    if help_coverage.get('status') == 'complete' and evidence.get('status') == 'retrieved':
        previous_run = get(db, 'snapshot_time', '')
        if run['created_at'] >= previous_run:
            for key, value in get(db, 'staged:' + run['id'], {}).items():
                put(db, 'article:' + key, value)
            put(db, 'snapshot_time', run['created_at'])
    put(db, 'finished:' + run['id'], {'run': run, 'coverage': coverage, 'report': report, 'saved_at': stamp()})
    db.execute('DELETE FROM kv WHERE key=?', ('staged:' + run['id'],))

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', type=Path, default=home())
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('profile'); p.add_argument('--file', type=Path)
    p = sub.add_parser('plan'); p.add_argument('--start'); p.add_argument('--end')
    p = sub.add_parser('collect'); p.add_argument('run_id')
    p = sub.add_parser('finish'); p.add_argument('run_id'); p.add_argument('--coverage', type=Path, required=True); p.add_argument('--report', type=Path, required=True)
    sub.add_parser('history')
    p = sub.add_parser('clear'); p.add_argument('--scope', choices=['profile', 'records', 'all'], required=True)
    args = parser.parse_args()
    root = args.data_dir.expanduser().resolve()
    package = Path(__file__).resolve().parents[1]
    if root == package or package in root.parents:
        raise ValueError('Private data must be outside the Skill/repository')
    db = connect(root)
    with db:
        if args.command == 'profile':
            if args.file:
                put(db, 'profile', json.loads(args.file.read_text(encoding='utf-8')))
            result = get(db, 'profile', {})
        elif args.command == 'plan':
            result = plan(db, args.end, args.start)
            result['custom_range'] = bool(args.start or args.end)
            put(db, 'run:' + result['id'], result)
        elif args.command in ('collect', 'finish'):
            run = get(db, 'run:' + args.run_id)
            if not run:
                raise ValueError('Unknown run')
            if args.command == 'collect':
                result = collect(db, run)
                path = root / (run['id'] + '-evidence.json')
                path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
                result = {'evidence_file': str(path), 'status': result['status'], 'candidate_count': len(result['candidates']), 'error': result['error']}
            else:
                content = args.report.read_text(encoding='utf-8')
                finish(db, run, json.loads(args.coverage.read_text(encoding='utf-8')), content)
                path = root / (run['id'] + '-report.md')
                path.write_text(content, encoding='utf-8')
                result = {'report': str(path), 'saved': True}
        elif args.command == 'history':
            result = [{'id': k.split(':', 1)[1], 'saved_at': json.loads(v)['saved_at'], 'coverage': json.loads(v)['coverage']} for k, v in db.execute("SELECT key,value FROM kv WHERE key LIKE 'finished:%'")]
        else:
            if args.scope in ('profile', 'all'):
                db.execute("DELETE FROM kv WHERE key='profile'")
            if args.scope in ('records', 'all'):
                db.execute("DELETE FROM kv WHERE key!='profile'")
                for pattern in ('*-evidence.json', '*-report.md'):
                    for path in root.glob(pattern):
                        path.unlink()
            result = {'cleared': args.scope, 'note': 'Only this tool’s managed records; external copies/backups are unaffected.'}
    print(json.dumps(result, ensure_ascii=False, indent=2))

if __name__ == '__main__':
    main()
