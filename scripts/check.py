#!/usr/bin/env python3
"""Check public project structure; never browse or authenticate to platforms."""
import argparse
import datetime as dt
import json
import math
import os
from pathlib import Path
import re
import subprocess
from urllib.parse import parse_qs, unquote, urlsplit

ROOT = Path(__file__).resolve().parent.parent
IGNORED_DIRS = {'.git', 'private', 'raw', 'captures', 'outputs', '__pycache__'}
ALLOWED_SUFFIXES = {'.md', '.json', '.jsonl', '.py', '.yml', '.yaml', '.txt'}
REQUIRED = {
    'schema_version', 'id', 'platform', 'url', 'title', 'observed_at',
    'observed_date', 'imported_at', 'acquisition', 'access', 'review_status',
    'publication', 'sampling', 'direct_observations', 'prices', 'metrics',
    'mechanism_hypotheses', 'unverified', 'anomalies', 'evidence', 'limitations',
}
TRACKING_OR_SECRET = {
    'spm', 'utm_source', 'utm_medium', 'utm_campaign', 'utm_term', 'utm_content',
    'xsec_token', 'xsec_source', 'access_token', 'token', 'auth', 'cookie',
    'session', 'sessionid', 'signature', 'password', 'code',
}
SENSITIVE_PATTERNS = [
    ('personal absolute path', re.compile('/' + r'(?:Users|home)/[^\s]+')),
    ('Windows personal path', re.compile(r'[A-Za-z]:[\\/]Users[\\/]')),
    ('access credential', re.compile(r'\bgh[pousr]_[A-Za-z0-9]{20,}\b')),
    ('private key', re.compile(r'-----BEGIN [A-Z ]*PRIVATE KEY-----')),
    ('email address', re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b')),
    ('personal phone number', re.compile(r'(?<![A-Za-z0-9])1[3-9][0-9]{9}(?![A-Za-z0-9])')),
]


def public_files(staged):
    if staged:
        result = subprocess.run(
            ['git', 'ls-files', '--cached', '-z'], cwd=ROOT,
            capture_output=True, check=True,
        )
        return [ROOT / p.decode() for p in result.stdout.split(b'\0') if p]
    paths = []
    for directory, folders, files in os.walk(ROOT):
        folders[:] = [f for f in folders if f not in IGNORED_DIRS]
        for name in files:
            if name == '.DS_Store' or name.endswith('.pyc'):
                continue
            paths.append(Path(directory) / name)
    return sorted(paths)


def valid_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0


def check_timestamp(value):
    if not isinstance(value, str):
        return False
    try:
        return dt.datetime.fromisoformat(value.replace('Z', '+00:00')).tzinfo is not None
    except ValueError:
        return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--staged', action='store_true', help='check files in the Git index by reading their working copies')
    args = parser.parse_args()
    errors = []
    ids = set()
    records = 0
    files = public_files(args.staged)

    def fail(location, message):
        # Do not print potentially sensitive matched text.
        errors.append(f'{location}: {message}')

    for path in files:
        rel = str(path.relative_to(ROOT))
        if any(part in IGNORED_DIRS for part in path.relative_to(ROOT).parts):
            fail(rel, 'private/raw output is included in public selection')
            continue
        if path.suffix not in ALLOWED_SUFFIXES and path.name != '.gitignore':
            fail(rel, 'unexpected file type; review before publishing')
            continue
        if path.is_symlink():
            fail(rel, 'symlink needs explicit review')
            continue
        text = path.read_text(encoding='utf-8')
        for label, pattern in SENSITIVE_PATTERNS:
            if pattern.search(text):
                fail(rel, f'possible {label}; inspect locally')
        if path.suffix == '.md':
            # Relative file links only. External availability is not checked.
            for target in re.findall(r'\]\(([^)]+)\)', text):
                target = target.strip().split(' "')[0].strip('<>')
                if not target or target.startswith(('#', 'http://', 'https://')):
                    continue
                if '://' in target or target.startswith('mailto:'):
                    fail(rel, 'unexpected link scheme')
                    continue
                dest = (path.parent / unquote(target.split('#')[0])).resolve()
                if not dest.is_relative_to(ROOT) or not dest.exists():
                    fail(rel, f'missing or outside-project relative link: {target}')
        if path.suffix == '.json':
            try:
                json.loads(text)
            except json.JSONDecodeError:
                fail(rel, 'invalid JSON')
        if path.suffix != '.jsonl':
            continue
        for number, line in enumerate(text.splitlines(), 1):
            if not line.strip():
                continue
            loc = f'{rel}:{number}'
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                fail(loc, 'invalid JSONL record')
                continue
            if not isinstance(item, dict) or not REQUIRED.issubset(item):
                fail(loc, 'missing required record fields')
                continue
            records += 1
            sample_id = item['id']
            if not isinstance(sample_id, str) or not sample_id or sample_id in ids:
                fail(loc, 'missing or duplicate sample ID')
            ids.add(sample_id)
            if item['schema_version'] != 1 or item['publication'] != 'public_summary':
                fail(loc, 'unexpected schema or publication classification')
            if item['access'] not in {'public_web', 'logged_in_public', 'unknown'}:
                fail(loc, 'unknown access classification')
            if item['review_status'] not in {'checked_against_saved_text', 'awaiting_review', 'checked_at_source'}:
                fail(loc, 'unknown review classification')
            if item['acquisition'] not in {'legacy_browser_observation', 'browser_observation', 'user_provided_capture'}:
                fail(loc, 'unknown acquisition classification')
            if item['observed_at'] is not None and not check_timestamp(item['observed_at']):
                fail(loc, 'observed_at must include timezone or be null')
            if not check_timestamp(item['imported_at']):
                fail(loc, 'imported_at must include timezone')
            try:
                dt.date.fromisoformat(item['observed_date'])
            except (ValueError, TypeError):
                fail(loc, 'observed_date must be ISO date')
            url = urlsplit(item['url'])
            if url.scheme != 'https' or not url.netloc or url.username or url.password:
                fail(loc, 'invalid public HTTPS URL')
            if set(parse_qs(url.query)) & TRACKING_OR_SECRET:
                fail(loc, 'tracking or access-bearing URL parameter')
            for field in ['direct_observations', 'prices', 'metrics', 'mechanism_hypotheses', 'unverified', 'anomalies', 'evidence', 'limitations']:
                if not isinstance(item[field], list):
                    fail(loc, f'{field} must be an array')
            for price in item['prices']:
                if not {'amount', 'currency', 'unit', 'tier'}.issubset(price) or not valid_number(price.get('amount')):
                    fail(loc, 'price needs nonnegative amount, currency, unit and tier')
            for metric in item['metrics']:
                if not {'label', 'value', 'scope', 'meaning'}.issubset(metric) or not valid_number(metric.get('value')):
                    fail(loc, 'metric needs number and its original label, scope and meaning')
            for anomaly in item['anomalies']:
                if not {'detail', 'why_it_matters', 'next_check'}.issubset(anomaly):
                    fail(loc, 'anomaly needs detail, relevance and next check')
            for evidence in item['evidence']:
                if not {'id', 'kind', 'availability', 'public_pointer', 'integrity_sha256'}.issubset(evidence):
                    fail(loc, 'evidence metadata incomplete')
                    continue
                if not re.fullmatch(r'[0-9a-f]{64}', evidence['integrity_sha256']):
                    fail(loc, 'invalid evidence integrity hash')
                if evidence['availability'] == 'local_only' and evidence['public_pointer'] is not None:
                    fail(loc, 'local-only evidence must not claim public attachment')
    if not records:
        fail('data', 'no sample records found')
    if errors:
        print('\n'.join(errors))
        print(f'FAILED: {len(errors)} issue(s); no remote pages were accessed.')
        return 1
    print(f'PASS: {len(files)} public files, {records} sample records; no remote pages were accessed.')
    print('Structure checks do not verify market facts, sales, legality or profitability.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
