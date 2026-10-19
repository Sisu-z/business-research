#!/usr/bin/env python3
"""Offline regression checks in disposable Git repositories."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


CHECKER = Path(__file__).with_name('check.py')


class PublicCheckTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='business-research-check-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root / 'scripts').mkdir()
        (self.root / 'data').mkdir()
        shutil.copyfile(CHECKER, self.root / 'scripts' / 'check.py')
        self.sample = {
            'schema_version': 1, 'id': 'TEST-001', 'platform': 'fixture',
            'url': 'https://example.invalid/item?id=123', 'title': 'Fixture',
            'observed_at': None, 'observed_date': '2026-10-18',
            'imported_at': '2026-10-18T00:00:00+08:00',
            'acquisition': 'legacy_browser_observation', 'access': 'unknown',
            'review_status': 'awaiting_review', 'publication': 'public_summary',
            'sampling': {}, 'direct_observations': [], 'prices': [],
            'metrics': [], 'mechanism_hypotheses': [], 'unverified': [],
            'anomalies': [], 'evidence': [], 'limitations': [],
        }
        self.write_sample()
        self.write('README.md', '[Samples](data/samples.jsonl)\n')
        self.git('init', '--quiet')
        self.git('add', '.')

    def write(self, name, content):
        (self.root / name).write_text(content, encoding='utf-8')

    def write_sample(self):
        self.write('data/samples.jsonl', json.dumps(self.sample) + '\n')

    def git(self, *arguments):
        subprocess.run(['git', *arguments], cwd=self.root, check=True,
                       capture_output=True)

    def check(self, staged=False):
        command = [sys.executable, str(self.root / 'scripts' / 'check.py')]
        if staged:
            command.append('--staged')
        return subprocess.run(command, cwd=self.root, capture_output=True,
                              text=True, encoding='utf-8')

    def assert_pass(self, result):
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def assert_private_url_rejected(self, result):
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn('tracking or access-bearing URL parameter', result.stdout)
        self.assertNotIn('synthetic-private-marker', result.stdout + result.stderr)

    def test_staged_sensitive_copy_is_checked_after_worktree_redaction(self):
        address = 'fixture' + '@' + 'example.invalid'
        self.write('README.md', address + '\n')
        self.git('add', 'README.md')
        self.write('README.md', 'Reviewed public summary.\n')
        result = self.check(staged=True)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn('possible email address', result.stdout)
        self.assertNotIn(address, result.stdout + result.stderr)
        self.assert_pass(self.check())

    def test_clean_index_is_independent_of_sensitive_worktree(self):
        self.write('README.md', 'fixture' + '@' + 'example.invalid\n')
        self.assert_pass(self.check(staged=True))
        self.assertEqual(self.check().returncode, 1)

    def test_staged_links_and_records_ignore_worktree_deletion(self):
        (self.root / 'data' / 'samples.jsonl').unlink()
        self.assert_pass(self.check(staged=True))

    def test_markdown_external_token_is_rejected(self):
        self.write('README.md', '[Source](https://example.invalid/item?id=123'
                   '&token=synthetic-private-marker)\n')
        self.assert_private_url_rejected(self.check())

    def test_nested_json_token_is_rejected(self):
        self.write('metadata.json', json.dumps({'sources': [{'links': {
            'url': 'https://example.invalid/item?id=123&ToKeN=synthetic-private-marker',
        }}]}))
        self.assert_private_url_rejected(self.check())

    def test_nested_jsonl_evidence_pointer_is_rejected(self):
        self.sample['evidence'] = [{
            'id': 'E-TEST', 'kind': 'public_excerpt', 'availability': 'public',
            'public_pointer': 'https://example.invalid/item?id=123&token=synthetic-private-marker',
            'integrity_sha256': '0' * 64,
        }]
        self.write_sample()
        self.git('add', 'data/samples.jsonl')
        self.assert_private_url_rejected(self.check(staged=True))

    def test_fragment_token_and_html_encoded_tracking_are_rejected(self):
        for url in ('https://example.invalid/#access_token=synthetic-private-marker',
                    'https://example.invalid/?id=123&amp;utm_source=synthetic-private-marker'):
            with self.subTest(url=url):
                self.write('README.md', '[Source](' + url + ')\n')
                self.assert_private_url_rejected(self.check())

    def test_normal_detail_parameters_and_anchors_remain_valid(self):
        url = 'https://example.invalid/item?id=123&itemId=456&page=2#code'
        self.write('README.md', '[Source](' + url + ')\n')
        self.write('metadata.json', json.dumps({'sources': [{'public_pointer': url}]}))
        self.sample['sampling']['source_url'] = url
        self.write_sample()
        self.git('add', '.')
        self.assert_pass(self.check())
        self.assert_pass(self.check(staged=True))


if __name__ == '__main__':
    unittest.main()
