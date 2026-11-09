"""One fixed, reviewed source approval after the separately verified app release.

No discovery, arbitrary destinations, deployment, rollback or write retries.
Only booleans/counts leave stdout; private proof is authenticated ciphertext.
"""
from __future__ import annotations

import base64
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
INPUT_PATH = ROOT/'.github/diagnostics/gpr-approval-input.cms'
PUBLIC_RECIPIENT = ROOT/'.github/diagnostics/contract-audit-recipient.pem'
INPUT_SHA256 = 'a19625c23fc3265f8dfe724c543bb75c0c41570904fb8fbaca88b574dce23ba8'
PLAINTEXT_SHA256 = '0af1de9672f45aad90cd59311d96fe9bcf510c715420a8030eeb10c4ba06720a'
RECIPIENT_SHA256 = 'e4fab796b7269e2d2e681dc46a317f126f78b8f89250ba368bb160ec1ba69d32'
SOURCE_SHA256 = '2d383659382132cd1fee89e9b14660cd7d4d5f1c4d2d23f7c373f11d3204df72'
SOURCE_BYTES = 188692
EXPECTED_WORKS = 198
BASE = 'https://developaid.ru'
PREVIEW = '/monitor/schedule/version-preview'
APPROVE = '/monitor/schedule/version-approve'
PHYSICAL = '/monitor/schedule-gpr-physical/view'
POST_PATHS = frozenset({PREVIEW, APPROVE, PHYSICAL})
MAX_INPUT = 1024*1024
MAX_RESPONSE = 16*1024*1024
MAX_PROOF = 64*1024*1024
HTTP_SECONDS = 15
TOTAL_SECONDS = 240
BRANCH = 'refs/heads/ops/approve-corpus-gpr-once'
REPOSITORY = 'warstyle-plato/plato'
ACTOR = 'warstyle-plato'  # Explicit human login; never inferred from the org.

# Fixed numeric error codes keep exception text and server bodies out of logs.
SETUP, INPUT, CRYPTO, DEADLINE, TRANSPORT, HTTP, RESPONSE, RUNTIME, FENCE, POSTFLIGHT, PROOF = range(1, 12)


class ApplyError(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def day(value):
    try:
        parsed = dt.date.fromisoformat(value)
    except (TypeError, ValueError):
        raise ApplyError(FENCE) from None
    if parsed.isoformat() != value:
        raise ApplyError(FENCE)
    return parsed


def strict_json(raw):
    def pairs(values):
        result = {}
        for key, value in values:
            if key in result:
                raise ApplyError(RESPONSE)
            result[key] = value
        return result
    def nonfinite(_):
        raise ApplyError(RESPONSE)
    try:
        result = json.loads(raw, object_pairs_hook=pairs, parse_constant=nonfinite)
    except (ValueError, UnicodeError, RecursionError):
        raise ApplyError(RESPONSE) from None
    if not isinstance(result, dict):
        raise ApplyError(RESPONSE)
    return result


def bounded_file(path, limit):
    try:
        with path.open('rb') as stream:
            raw = stream.read(limit+1)
    except OSError:
        raise ApplyError(INPUT) from None
    if not raw or len(raw) > limit:
        raise ApplyError(INPUT)
    return raw


def trusted_checkout(environment, run=subprocess.run):
    expected = environment.get('GITHUB_SHA', '')
    if (environment.get('GITHUB_REPOSITORY') != REPOSITORY
            or environment.get('GITHUB_ACTOR') != ACTOR
            or environment.get('GITHUB_TRIGGERING_ACTOR') != ACTOR
            or environment.get('GITHUB_REF') != BRANCH
            or environment.get('GITHUB_EVENT_NAME') != 'workflow_dispatch'
            or environment.get('GITHUB_RUN_ATTEMPT') != '1'
            or not re.fullmatch('[0-9a-f]{40}', expected)
            or environment.get('GITHUB_WORKFLOW_SHA') != expected):
        raise ApplyError(SETUP)
    try:
        actual = run(['git', 'rev-parse', 'HEAD'], cwd=ROOT, stdout=subprocess.PIPE,
                     stderr=subprocess.DEVNULL, timeout=5,
                     env={'PATH': os.environ.get('PATH', '/usr/bin:/bin')})
        clean = run(['git', 'diff', '--quiet', 'HEAD'], cwd=ROOT,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5,
                    env={'PATH': os.environ.get('PATH', '/usr/bin:/bin')})
    except (OSError, subprocess.SubprocessError):
        raise ApplyError(SETUP) from None
    if actual.returncode or actual.stdout.strip() != expected.encode() or clean.returncode:
        raise ApplyError(SETUP)


def decrypt_bundle(envelope, key, runner_temp):
    if (not envelope or len(envelope) > MAX_INPUT or sha(envelope) != INPUT_SHA256
            or not isinstance(key, str) or not key.startswith('-----BEGIN PRIVATE KEY-----')
            or not 1000 <= len(key) <= 8192):
        raise ApplyError(INPUT)
    try:
        with tempfile.TemporaryDirectory(prefix='gpr-input-', dir=runner_temp) as directory:
            path = Path(directory)/'transport.pem'
            with os.fdopen(os.open(path, os.O_CREAT|os.O_EXCL|os.O_WRONLY, 0o600), 'w') as stream:
                stream.write(key)
            result = subprocess.run(['openssl', 'cms', '-decrypt', '-binary', '-inform', 'DER', '-inkey', str(path)],
                                    input=envelope, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                    timeout=20, env={'PATH': os.environ.get('PATH', '/usr/bin:/bin')})
    except (OSError, subprocess.SubprocessError):
        raise ApplyError(CRYPTO) from None
    if result.returncode or len(result.stdout) > MAX_INPUT or sha(result.stdout) != PLAINTEXT_SHA256:
        raise ApplyError(CRYPTO)
    bundle = strict_json(result.stdout)
    required = {'schema', 'project', 'old_source_sha256', 'new_source_sha256', 'source_base64',
                'old_cut', 'snapshot_id', 'source_as_of', 'baseline_proof_sha256', 'operation_nonce'}
    if (set(bundle) != required or type(bundle['schema']) is not int or bundle['schema'] != 1
            or not isinstance(bundle['project'], str) or not 1 <= len(bundle['project']) <= 200
            or bundle['project'] != bundle['project'].strip()
            or not re.fullmatch('[0-9a-f]{64}', bundle['old_source_sha256'])
            or bundle['old_source_sha256'] == SOURCE_SHA256
            or bundle['new_source_sha256'] != SOURCE_SHA256
            or not re.fullmatch('[0-9a-f]{64}', bundle['baseline_proof_sha256'])
            or not re.fullmatch('[0-9a-f]{64}', bundle['operation_nonce'])
            or not re.fullmatch(r'\d{4}-\d{2}-\d{2}-[0-9a-f]{64}', bundle['snapshot_id'])
            or bundle['snapshot_id'][:10] != bundle['old_cut']
            or day(bundle['source_as_of']) > day(bundle['old_cut'])):
        raise ApplyError(INPUT)
    try:
        source = base64.b64decode(bundle['source_base64'], validate=True)
    except (ValueError, TypeError):
        raise ApplyError(INPUT) from None
    if len(source) != SOURCE_BYTES or sha(source) != SOURCE_SHA256:
        raise ApplyError(INPUT)
    return bundle


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ApplyError(TRANSPORT)


class Operation:
    def __init__(self, expected, *, opener=None, clock=time.monotonic,
                 today=lambda: dt.datetime.now(dt.timezone.utc).date()):
        if not isinstance(expected, str) or not re.fullmatch('[0-9a-f]{40}', expected):
            raise ApplyError(SETUP)
        self.expected, self.clock, self.today = expected, clock, today
        self.deadline = clock()+TOTAL_SECONDS
        self.opener = opener or urllib.request.build_opener(NoRedirect())
        self.proof, self.key, self.bundle = {}, '', None
        self.runtime_version = None
        self.ready = False
        self.summary = {'ok': False, 'write_attempted': False, 'write_response_verified': False,
                        'already_active': False, 'old_cut_verified': False,
                        'current_source_verified': False, 'runtime_verified': False,
                        'postflight_verified': False, 'outcome_unknown': False,
                        'requests': 0, 'preview_works': 0, 'error_code': 0}

    def remaining(self):
        value = self.deadline-self.clock()
        if value <= 0:
            raise ApplyError(DEADLINE)
        return value

    def request(self, path, body=None):
        if (body is None and path != '/health') or (body is not None and path not in POST_PATHS):
            raise ApplyError(FENCE)
        headers = {'Cache-Control':'no-store', 'User-Agent':'PLATO-Approved-GPR-OneOff/1'}
        raw = None
        if body is not None:
            common = {'key', 'project'}
            expected_keys = (common|{'cut','offset'} if path == PHYSICAL else
                             common|{'effective_from','gpr_base64'} if path == PREVIEW else
                             common|{'effective_from','gpr_base64','expected_previous_sha256','expected_source_sha256'})
            if (not isinstance(body, dict) or set(body) != expected_keys
                    or self.bundle is None or body.get('project') != self.bundle['project']
                    or not self.key or body.get('key') != self.key):
                raise ApplyError(FENCE)
            if path == PHYSICAL:
                if type(body['offset']) is not int or body['offset'] != 0 or body['cut'] not in {self.bundle['old_cut'], self.effective}:
                    raise ApplyError(FENCE)
            elif (body['effective_from'] != self.effective or body['gpr_base64'] != self.bundle['source_base64']):
                raise ApplyError(FENCE)
            if path == APPROVE:
                if (not self.ready or self.summary['write_attempted']
                        or body['expected_previous_sha256'] != self.bundle['old_source_sha256']
                        or body['expected_source_sha256'] != SOURCE_SHA256):
                    raise ApplyError(FENCE)
                self.summary['write_attempted'] = True
                self.summary['outcome_unknown'] = True
                self.ready = False
            raw = json.dumps(body, ensure_ascii=False, allow_nan=False).encode()
            if len(raw) > MAX_INPUT:
                raise ApplyError(FENCE)
            headers['Content-Type'] = 'application/json'
        request = urllib.request.Request(BASE+path, data=raw, headers=headers, method='GET' if raw is None else 'POST')
        self.summary['requests'] += 1
        try:
            with self.opener.open(request, timeout=min(HTTP_SECONDS, self.remaining())) as response:
                if response.geturl() != BASE+path or response.status != 200:
                    raise ApplyError(HTTP)
                declared = response.headers.get('Content-Length')
                if declared is not None and (not str(declared).isdigit() or int(declared) > MAX_RESPONSE):
                    raise ApplyError(RESPONSE)
                chunks, size = [], 0
                while True:
                    self.remaining()
                    chunk = response.read1(min(65536, MAX_RESPONSE-size+1))
                    self.remaining()
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > MAX_RESPONSE:
                        raise ApplyError(RESPONSE)
                    chunks.append(chunk)
                payload = b''.join(chunks)
        except (urllib.error.HTTPError, urllib.error.URLError, OSError, TimeoutError):
            raise ApplyError(HTTP) from None
        result = strict_json(payload)
        if self.key and self.key in json.dumps(result,ensure_ascii=False,allow_nan=False):
            raise ApplyError(PROOF)
        return result

    def health(self):
        health = self.request('/health')
        if (health.get('status') != 'ok' or health.get('commit') != self.expected
                or health.get('data_writable') is not True
                or not isinstance(health.get('version'), str)
                or not re.fullmatch(r'\d{1,6}\.\d{1,6}\.\d{1,6}', health['version'])):
            raise ApplyError(RUNTIME)
        if self.runtime_version is not None and health['version'] != self.runtime_version:
            raise ApplyError(RUNTIME)
        self.runtime_version = health['version']
        return {key: health[key] for key in ('status','commit','version')}

    def physical(self, cut):
        result = self.request(PHYSICAL, {'key':self.key, 'project':self.bundle['project'], 'cut':cut, 'offset':0})
        if (result.get('source_kind') != 'gpr' or result.get('source_state') != 'approved_gpr'
                or result.get('snapshot_id') != self.bundle['snapshot_id']
                or type(result.get('revision')) is not int or result['revision'] < 0
                or type(result.get('source_changed')) is not bool
                or type(result.get('offset')) is not int or result['offset'] != 0 or type(result.get('item_count')) is not int
                or not 0 <= result['item_count'] <= 5000
                or not isinstance(result.get('configuration'), dict)
                or not isinstance(result.get('model'), dict) or not isinstance(result.get('tasks'), list)
                or not isinstance(result.get('items'), list)
                or len(result['items']) != min(200,result['item_count'])
                or any(not isinstance(item,dict) for item in result['items']+result['tasks'])):
            raise ApplyError(FENCE)
        task_ids = [task.get('task_id') for task in result['tasks']]
        item_ids = [item.get('item_id') for item in result['items']]
        if (any(not isinstance(tid,str) or not tid.strip() or len(tid)>200 for tid in task_ids)
                or len(set(task_ids)) != len(task_ids)
                or any(not isinstance(iid,str) or not re.fullmatch(r'\d{1,5}:\d{1,6}',iid) for iid in item_ids)
                or len(set(item_ids)) != len(item_ids)):
            raise ApplyError(FENCE)
        return result

    def preview(self):
        result = self.request(PREVIEW, {'key':self.key, 'project':self.bundle['project'],
            'effective_from':self.effective, 'gpr_base64':self.bundle['source_base64']})
        if (result.get('source_sha256') != SOURCE_SHA256 or result.get('effective_from') != self.effective
                or result.get('works') != EXPECTED_WORKS
                or type(result.get('works')) is not int or result.get('source_format') != 'corpus-gpr-v1'
                or result.get('requires_initial_baseline') is not False
                or type(result.get('current_revision')) is not int or result['current_revision'] < 0
                or type(result.get('already_approved')) is not bool):
            raise ApplyError(FENCE)
        self.summary['preview_works'] = result['works']
        return result

    @staticmethod
    def old_projection(result):
        def stable(value):
            if isinstance(value, dict):
                return {key: stable(item) for key,item in value.items()
                        if key not in {'generated_at','computed_at','checked_at','duration_ms','request_id'}}
            return [stable(item) for item in value] if isinstance(value,list) else value
        fields = ('source_kind','source_sha256','snapshot_id','revision','recorded_at',
                  'source_changed','configuration','source_state','item_count','offset','items','tasks','model')
        return stable({key:result.get(key) for key in fields})

    def active_fence(self, preview, current):
        effective = day(preview.get('approved_effective_from'))
        if (preview['current_revision'] != 1 or preview.get('expected_previous_sha256') != SOURCE_SHA256
                or preview['already_approved'] is not True
                or not day(self.bundle['old_cut']) < effective <= day(self.effective)
                or current.get('source_sha256') != SOURCE_SHA256
                or len(current['tasks']) != EXPECTED_WORKS):
            raise ApplyError(FENCE)

    def execute(self, bundle, key):
        if not isinstance(key, str) or not key.strip() or len(key) > 4096:
            raise ApplyError(SETUP)
        self.key, self.bundle = key.strip(), bundle
        self.effective = self.today().isoformat()
        if not day(bundle['old_cut']) < day(self.effective) or day(bundle['source_as_of']) > day(self.effective):
            raise ApplyError(FENCE)
        self.proof['input'] = {key:value for key,value in bundle.items() if key != 'source_base64'}
        old = self.physical(bundle['old_cut'])
        self.proof['old_before'] = old
        if old.get('source_sha256') != bundle['old_source_sha256']:
            raise ApplyError(FENCE)
        current = self.physical(self.effective)
        self.proof['current_before'] = current
        preview = self.preview()
        self.proof['preview_before'] = preview
        previous = preview.get('expected_previous_sha256')
        if previous == SOURCE_SHA256:
            self.active_fence(preview, current)
            self.summary['already_active'] = True
        else:
            if (previous != bundle['old_source_sha256'] or preview['current_revision'] != 0
                    or preview['already_approved'] is not False
                    or current.get('source_sha256') != bundle['old_source_sha256']):
                raise ApplyError(FENCE)
            self.proof['health_before_write'] = self.health()
            if self.today().isoformat() != self.effective:
                raise ApplyError(FENCE)
            self.ready = True
            response = self.request(APPROVE, {'key':self.key, 'project':bundle['project'],
                'effective_from':self.effective, 'gpr_base64':bundle['source_base64'],
                'expected_previous_sha256':bundle['old_source_sha256'], 'expected_source_sha256':SOURCE_SHA256})
            self.proof['approval_response'] = response
            try:
                approved_at = dt.datetime.fromisoformat(response.get('approved_at'))
            except (TypeError,ValueError):
                raise ApplyError(POSTFLIGHT) from None
            if (type(response.get('revision')) is not int or response['revision'] != 1
                    or response.get('source_sha256') != SOURCE_SHA256
                    or response.get('effective_from') != self.effective or response.get('unchanged') is not False
                    or approved_at.utcoffset() != dt.timedelta(0) or approved_at.date().isoformat() != self.effective):
                raise ApplyError(POSTFLIGHT)
            self.summary['write_response_verified'] = True
        after_preview = self.preview()
        old_after, current_after = self.physical(bundle['old_cut']), self.physical(self.effective)
        self.proof.update(preview_after=after_preview, old_after=old_after, current_after=current_after)
        if self.old_projection(old) != self.old_projection(old_after):
            raise ApplyError(POSTFLIGHT)
        self.summary['old_cut_verified'] = True
        self.active_fence(after_preview, current_after)
        if not self.summary['already_active'] and after_preview.get('approved_effective_from') != self.effective:
            raise ApplyError(POSTFLIGHT)
        self.summary['current_source_verified'] = True
        self.proof['health_after'] = self.health()
        self.summary.update(ok=True, runtime_verified=True, postflight_verified=True,outcome_unknown=False)
        return dict(self.summary)


def encrypt_proof(proof, recipient, target, runner_temp, secrets=()):
    if sha(recipient) != RECIPIENT_SHA256:
        raise ApplyError(PROOF)
    raw = json.dumps(proof, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()
    if (len(raw) > MAX_PROOF or b'-----BEGIN PRIVATE KEY-----' in raw
            or any(secret and secret.encode() in raw for secret in secrets)):
        raise ApplyError(PROOF)
    created = False
    try:
        with tempfile.TemporaryDirectory(prefix='gpr-proof-', dir=runner_temp) as directory:
            cert = Path(directory)/'recipient.pem'
            cert.write_bytes(recipient)
            os.chmod(cert,0o600)
            descriptor = os.open(target, os.O_CREAT|os.O_EXCL|os.O_WRONLY, 0o600)
            created = True
            with os.fdopen(descriptor,'wb') as stream:
                result = subprocess.run(['openssl','cms','-encrypt','-aes-256-gcm','-binary','-outform','DER',
                    '-recip',str(cert),'-keyopt','rsa_padding_mode:oaep','-keyopt','rsa_oaep_md:sha256',
                    '-keyopt','rsa_mgf1_md:sha256'], input=raw,stdout=stream,stderr=subprocess.DEVNULL,
                    timeout=30,env={'PATH':os.environ.get('PATH','/usr/bin:/bin')})
        if result.returncode or not target.is_file() or not target.stat().st_size:
            raise ApplyError(PROOF)
    except (OSError,subprocess.SubprocessError,ApplyError):
        if created:
            target.unlink(missing_ok=True)
        raise ApplyError(PROOF) from None


def main():
    started = time.monotonic()
    operation, proof_created = None, False
    summary = {'ok':False,'write_attempted':False,'write_response_verified':False,
               'already_active':False,'outcome_unknown':False,'error_code':SETUP}
    def expired(signum, frame):
        raise ApplyError(DEADLINE)
    try:
        os.umask(0o077)
        trusted_checkout(os.environ)
        operation = Operation(os.environ.get('EXPECTED_RUNTIME_COMMIT',''))
        envelope = bounded_file(INPUT_PATH,MAX_INPUT)
        recipient = bounded_file(PUBLIC_RECIPIENT,16384)
        if sha(envelope) != INPUT_SHA256 or sha(recipient) != RECIPIENT_SHA256:
            raise ApplyError(INPUT)
        temporary = Path(os.environ['RUNNER_TEMP'])
        if not temporary.is_absolute() or not temporary.is_dir():
            raise ApplyError(SETUP)
        target = temporary/'approved-gpr-apply-proof.cms'
        if target.exists():
            raise ApplyError(SETUP)
        signal.signal(signal.SIGALRM,expired)
        signal.alarm(TOTAL_SECONDS)
        operation.proof['health_before'] = operation.health()
        bundle = decrypt_bundle(envelope,os.environ.pop('GPR_ONCE_TRANSPORT_KEY',''),temporary)
        operation.proof['health_before_private_requests'] = operation.health()
        operation.execute(bundle,os.environ.pop('APPLY_ADMIN_KEY',''))
    except ApplyError as exc:
        summary['error_code'] = exc.code
        if operation is not None:
            operation.summary.update(ok=False,error_code=exc.code)
    except Exception:
        if operation is not None:
            operation.summary.update(ok=False,error_code=SETUP)
    finally:
        signal.alarm(0)
        if operation is not None:
            summary = dict(operation.summary)
            summary['outcome_unknown'] = summary['write_attempted'] and not summary['postflight_verified']
            operation.proof['result'] = dict(summary)
            if operation.proof.get('input'):
                try:
                    encrypt_proof(operation.proof,recipient,target,temporary,secrets=(operation.key,))
                    proof_created = True
                except Exception:
                    summary.update(ok=False,error_code=PROOF)
                    summary['outcome_unknown'] = summary['write_attempted']
            operation.key = ''
        summary['encrypted_proof_created'] = proof_created
        summary['elapsed_seconds'] = int(max(0,time.monotonic()-started))
        output = os.environ.get('GITHUB_OUTPUT')
        if output:
            with open(output,'a',encoding='utf-8') as stream:
                stream.write('proof_created='+str(proof_created).lower()+'\n')
        print(json.dumps(summary,sort_keys=True,allow_nan=False))
    return 0 if summary['ok'] else 1


if __name__ == '__main__':
    sys.exit(main())
