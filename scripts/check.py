#!/usr/bin/env python3
"""Check public project structure; never browse or authenticate to platforms."""
import argparse
import datetime as dt
import html
import json
import math
import os
from pathlib import Path
import re
import subprocess
from urllib.parse import parse_qsl, unquote, urlsplit

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
URL_PATTERN = re.compile(r'https?://[^\s<>\"\x27`]+', re.IGNORECASE)


def public_files(staged):
    if staged:
        result = subprocess.run(
            ['git', 'ls-files', '--stage', '-z'], cwd=ROOT,
            capture_output=True, check=True,
        )
        paths = {}
        for entry in result.stdout.split(b'\0'):
            if not entry:
                continue
            metadata, name = entry.split(b'\t', 1)
            mode, object_id, stage = metadata.split()
            if stage != b'0':
                raise ValueError('unmerged index; resolve conflicts before checking')
            paths[ROOT / name.decode('utf-8')] = (mode, object_id.decode('ascii'))
        return paths
    paths = []
    for directory, folders, files in os.walk(ROOT):
        folders[:] = [f for f in folders if f not in IGNORED_DIRS]
        for name in files:
            if name == '.DS_Store' or name.endswith('.pyc'):
                continue
            paths.append(Path(directory) / name)
    return {path: None for path in sorted(paths)}


def urls_in(value):
    """Inspect string values at every JSON depth, including evidence pointers."""
    if isinstance(value, str):
        yield from URL_PATTERN.findall(value)
    elif isinstance(value, dict):
        for nested in value.values():
            yield from urls_in(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from urls_in(nested)


def url_privacy_issues(value):
    try:
        url = urlsplit(html.unescape(value))
    except ValueError:
        return ['invalid URL; inspect locally']
    issues = []
    if url.username is not None or url.password is not None:
        issues.append('URL contains access credentials')
    # Fragments can carry login tokens too; ordinary anchors remain valid.
    fragment_query = url.fragment.split('?', 1)[-1] if '=' in url.fragment else ''
    keys = {
        key.casefold()
        for query in (url.query, fragment_query)
        for key, _ in parse_qsl(query, keep_blank_values=True)
    }
    if keys & TRACKING_OR_SECRET:
        issues.append('tracking or access-bearing URL parameter')
    return issues


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
    parser.add_argument('--staged', action='store_true', help='check the actual file contents and modes in the Git index')
    args = parser.parse_args()
    errors = []
    ids = set()
    records = 0
    try:
        files = public_files(args.staged)
    except ValueError as error:
        print(f'FAILED: {error}; no remote pages were accessed.')
        return 1
    available_paths = set(files)
    if args.staged:
        for path in files:
            available_paths.update(parent for parent in path.parents if parent.is_relative_to(ROOT))

    def fail(location, message):
        # Do not print potentially sensitive matched text.
        errors.append(f'{location}: {message}')

    def check_urls(value, location):
        for url in set(urls_in(value)):
            for issue in url_privacy_issues(url):
                fail(location, issue)

    for path, index_entry in files.items():
        rel = str(path.relative_to(ROOT))
        if any(part in IGNORED_DIRS for part in path.relative_to(ROOT).parts):
            fail(rel, 'private/raw output is included in public selection')
            continue
        if path.suffix not in ALLOWED_SUFFIXES and path.name != '.gitignore':
            fail(rel, 'unexpected file type; review before publishing')
            continue
        if (index_entry is not None and index_entry[0] == b'120000') or (index_entry is None and path.is_symlink()):
            fail(rel, 'symlink needs explicit review')
            continue
        try:
            if index_entry is not None:
                result = subprocess.run(
                    ['git', 'cat-file', 'blob', index_entry[1]], cwd=ROOT,
                    capture_output=True, check=True,
                )
                text = result.stdout.decode('utf-8')
            else:
                text = path.read_text(encoding='utf-8')
        except UnicodeDecodeError:
            fail(rel, 'public text must be UTF-8')
            continue
        for label, pattern in SENSITIVE_PATTERNS:
            if pattern.search(text):
                fail(rel, f'possible {label}; inspect locally')
        if path.suffix == '.md':
            check_urls(text, rel)
            # Relative file links only. External availability is not checked.
            for target in re.findall(r'\]\(([^)]+)\)', text):
                target = target.strip().split(' "')[0].strip('<>')
                if not target or target.lower().startswith(('#', 'http://', 'https://')):
                    continue
                if '://' in target or target.startswith('mailto:'):
                    fail(rel, 'unexpected link scheme')
                    continue
                candidate = path.parent / unquote(target.split('#')[0])
                dest = Path(os.path.abspath(candidate)) if args.staged else candidate.resolve()
                exists = dest in available_paths if args.staged else dest.exists()
                if not dest.is_relative_to(ROOT) or not exists:
                    fail(rel, f'missing or outside-project relative link: {target}')
        if path.suffix == '.json':
            try:
                check_urls(json.loads(text), rel)
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
            check_urls(item, loc)
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
