"""Metadata-only inbox shared by PLATO task chats; never a release authority.

Reads/writes the EXISTING issue1019 using each chat's GitHub connection.
No credentials, conversation IDs, prompts, files or client data are transported.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from dataclasses import dataclass

REPO = 'warstyle-plato/plato'
INBOX = 1019
MARKER = '<!-- PLATO-SESSION-EVENT:v1 -->\n'
FOOTER = '\n<!-- Report only; no release approval. -->'
ROLES = {'control', 'worker', 'security_guard', 'visual_guard', 'excel_guard', 'normative_guard'}
TASK = re.compile(r'(?:control|legal|models|gpr|sales|platform):([1-9][0-9]{0,8})\Z')
HEAD = re.compile(r'[0-9a-f]{40}\Z')
KINDS = {'assign', 'progress', 'handoff', 'review'}
FIELDS = {'task', 'kind', 'role', 'pr', 'head', 'checks', 'verdict', 'runs'}


class BridgeError(Exception):
    """Messages must be fixed text, never raw input or GitHub error bodies."""


def integer(value):
    return isinstance(value, int) and not isinstance(value, bool) and 0 < value < 10**12


def validate(event):
    if not isinstance(event, dict) or not set(event) <= FIELDS:
        raise BridgeError('Unexpected event fields.')
    if not {'task', 'kind', 'role'} <= set(event):
        raise BridgeError('Missing event fields.')
    if not isinstance(event['task'], str) or not TASK.fullmatch(event['task']):
        raise BridgeError('Invalid task reference.')
    if (not isinstance(event['kind'], str) or event['kind'] not in KINDS
            or not isinstance(event['role'], str) or event['role'] not in ROLES):
        raise BridgeError('Invalid event kind or role.')
    kind, role = event['kind'], event['role']
    if (kind == 'assign' and role != 'control'
            or kind in {'progress', 'handoff'} and role != 'worker'
            or kind == 'review' and not role.endswith('_guard')):
        raise BridgeError('Event kind does not match the reported role.')
    # Role is a reported label, not proof of independent review or permission.
    if ('pr' in event) != ('head' in event):
        raise BridgeError('PR and exact source must be supplied together.')
    if kind in {'handoff', 'review'} and 'pr' not in event:
        raise BridgeError('A result requires a PR and exact source.')
    if 'pr' in event and (not integer(event['pr']) or not isinstance(event['head'], str)
                          or not HEAD.fullmatch(event['head'])):
        raise BridgeError('Invalid PR or source.')
    if 'checks' in event:
        checks = event['checks']
        if (not isinstance(checks, dict) or set(checks) != {'passed', 'failed', 'skipped'}
                or any(not isinstance(v, int) or isinstance(v, bool) or not 0 <= v < 10**7
                       for v in checks.values())):
            raise BridgeError('Invalid test counts.')
    if (kind == 'review') != ('verdict' in event):
        raise BridgeError('Only review reports require a verdict.')
    if 'verdict' in event and (not isinstance(event['verdict'], str)
                              or event['verdict'] not in {'pass', 'changes_requested', 'blocked'}):
        raise BridgeError('Invalid reported verdict.')
    if 'runs' in event and (not isinstance(event['runs'], list) or len(event['runs']) > 20
                            or any(not integer(v) for v in event['runs'])):
        raise BridgeError('Invalid workflow references.')
    return event


def canonical(event):
    return json.dumps(validate(event), sort_keys=True, separators=(',', ':'), ensure_ascii=True)


def encode(event):
    return MARKER + canonical(event) + FOOTER


def decode(body):
    if (not isinstance(body, str) or len(body) > 4096 or not body.startswith(MARKER)
            or not body.endswith(FOOTER)):
        raise BridgeError('Not a bridge event.')
    try:
        event = json.loads(body[len(MARKER):-len(FOOTER)])
        if encode(event) != body:
            raise BridgeError('Noncanonical bridge event.')
        return event
    except (ValueError, TypeError, KeyError):
        raise BridgeError('Invalid bridge event.') from None


def digest(event):
    return hashlib.sha256(canonical(event).encode()).hexdigest()


@dataclass
class GitHub:
    def _request(self, path, *, data=None, paginate=False):
        args = ['gh', 'api', '--hostname', 'github.com', path]
        if paginate:
            args += ['--paginate', '--slurp']
        if data is not None:
            args += ['--method', 'POST', '--input', '-']
        try:
            result = subprocess.run(args, input=json.dumps(data) if data is not None else None,
                                    text=True, capture_output=True, timeout=45, check=True)
            return json.loads(result.stdout)
        except (OSError, subprocess.SubprocessError, ValueError):
            message = ('Ambiguous publication; inspect inbox before retrying.' if data is not None
                       else 'GitHub read unavailable; no raw response was printed.')
            raise BridgeError(message) from None

    def api(self, path, *, data=None, paginate=False):
        return self._request(f'repos/{REPO}/{path}', data=data, paginate=paginate)

    def identity(self):
        return self._request('user')

    def comments(self):
        pages = self.api(f'issues/{INBOX}/comments?per_page=100', paginate=True)
        if not isinstance(pages, list) or any(not isinstance(p, list) for p in pages):
            raise BridgeError('Invalid comment listing.')
        return [comment for page in pages for comment in page]


def events(comments):
    """Ignore all legacy text, unknown identities and malformed/untrusted data."""
    found = {}
    for comment in comments:
        if not isinstance(comment, dict) or not integer(comment.get('id')):
            continue
        user = comment.get('user') or {}
        if not isinstance(user, dict) or user.get('login') != 'warstyle-plato' or user.get('type') != 'User':
            continue
        try:
            event = decode(comment.get('body'))
        except (BridgeError, TypeError):
            continue
        key = digest(event)
        if key not in found or comment['id'] < found[key]['comment_id']:
            found[key] = {'comment_id': comment['id'], 'event_id': key, 'event': event}
    return sorted(found.values(), key=lambda row: row['comment_id'])


def publish(github, event):
    validate(event)
    identity = github.identity()
    if (not isinstance(identity, dict) or identity.get('login') != 'warstyle-plato'
            or identity.get('type') != 'User'):
        raise BridgeError('The connected GitHub identity is not accepted by this inbox.')
    issue_number = int(TASK.fullmatch(event['task']).group(1))
    issue = github.api(f'issues/{issue_number}')
    if not isinstance(issue, dict) or issue.get('number') != issue_number:
        raise BridgeError('Task issue not confirmed.')
    if 'pr' in event:
        pr = github.api(f'pulls/{event["pr"]}')
        try:
            same = (pr['number'] == event['pr'] and pr['head']['sha'] == event['head']
                    and pr['head']['repo']['full_name'] == REPO
                    and pr['base']['repo']['full_name'] == REPO
                    and pr['base']['ref'] == 'main')
        except (KeyError, TypeError):
            same = False
        if not same:
            raise BridgeError('Live PR source does not match the report.')
    key = digest(event)
    for row in events(github.comments()):
        if row['event_id'] == key:
            return {'state': 'already_received', 'event_id': key, 'comment_id': row['comment_id']}
    result = github.api(f'issues/{INBOX}/comments', data={'body': encode(event)})
    if (not isinstance(result, dict) or not integer(result.get('id'))
            or result.get('body') != encode(event) or result.get('user') != identity):
        raise BridgeError('Ambiguous publication; inspect inbox before retrying.')
    return {'state': 'report_received', 'event_id': key, 'comment_id': result['id']}


def latest(rows):
    grouped = {}
    for row in rows:
        event = row['event']
        grouped[(event['task'], event['role'], event['kind'])] = row
    # Preserve source SHA on every result. Never turn a reported pass into approval.
    return sorted(grouped.values(), key=lambda row: row['comment_id'])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('inbox', help='Read safe machine events from the existing issue1019.')
    submit = sub.add_parser('submit', help='Read metadata JSON from stdin; preview by default.')
    submit.add_argument('--publish', action='store_true', help='Publish validated metadata to issue1019.')
    args = parser.parse_args(argv)
    try:
        if args.command == 'inbox':
            out = {'state': 'reports_only', 'events': latest(events(GitHub().comments()))}
        else:
            # Strict byte bound, field allowlist and enums before any output/network.
            raw = sys.stdin.read(4097)
            if len(raw) > 4096:
                raise BridgeError('Event too large.')
            try:
                event = validate(json.loads(raw))
            except (ValueError, TypeError, KeyError):
                raise BridgeError('Invalid event JSON.') from None
            out = publish(GitHub(), event) if args.publish else {'state': 'preview_only', 'event': event}
        print(json.dumps(out, sort_keys=True))
        return 0
    except BridgeError as error:
        print(json.dumps({'state': 'error', 'reason': str(error)}), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
