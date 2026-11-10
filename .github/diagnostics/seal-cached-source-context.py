"""Local control seals only the pinned private context to this run's public key."""
from __future__ import annotations
import argparse
import datetime as dt
import importlib.util
import io
import os
from pathlib import Path
import subprocess
import sys
import zipfile

spec=importlib.util.spec_from_file_location('cached_source_capture',Path(__file__).with_name('cached-source-capture.py'))
capture=importlib.util.module_from_spec(spec);spec.loader.exec_module(capture)
PRIVATE_CONTEXT=Path('/tmp/plato-source-capture-transport/private-context.json')

def seal(public_zip,artifact_sha256,run_id,workflow_sha,expected_runtime,out):
    if (not capture.digest(artifact_sha256) or not capture.digest(workflow_sha,40)
            or not capture.digest(expected_runtime,40) or not isinstance(run_id,str)
            or not capture.re.fullmatch('[1-9][0-9]{0,19}',run_id)):
        raise capture.CaptureError('input')
    raw=capture.bounded_file(public_zip,65536)
    if capture.sha(raw)!=artifact_sha256:raise capture.CaptureError('fence')
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            if (len(archive.infolist())!=2 or set(archive.namelist())!={'public.pem','public.json'}
                    or any(info.file_size>16384 or info.is_dir() for info in archive.infolist())):
                raise capture.CaptureError('input')
            cert=archive.read('public.pem');metadata=capture.strict_json(archive.read('public.json'))
    except (ValueError,OSError,zipfile.BadZipFile):raise capture.CaptureError('input') from None
    required={'schema','repository','ref','run_id','run_attempt','workflow_sha','expected_runtime_commit','certificate_sha256','nonce','created_utc'}
    if (set(metadata)!=required or type(metadata['schema']) is not int or metadata['schema']!=1
            or metadata['repository']!=capture.REPOSITORY or metadata['ref']!=capture.BRANCH
            or metadata['run_id']!=run_id or type(metadata['run_attempt']) is not int or metadata['run_attempt']!=1
            or metadata['workflow_sha']!=workflow_sha or metadata['expected_runtime_commit']!=expected_runtime
            or metadata['certificate_sha256']!=capture.sha(cert) or not capture.digest(metadata['nonce'])
            or cert.count(b'-----BEGIN CERTIFICATE-----')!=1 or cert.count(b'-----END CERTIFICATE-----')!=1
            or b'PRIVATE KEY' in cert):raise capture.CaptureError('fence')
    try:
        created=dt.datetime.fromisoformat(metadata['created_utc']);age=(dt.datetime.now(dt.timezone.utc)-created).total_seconds()
    except (ValueError,TypeError):raise capture.CaptureError('fence') from None
    if created.utcoffset()!=dt.timedelta(0) or not 0<=age<capture.WAIT_SECONDS-60:raise capture.CaptureError('deadline')
    context=capture.bounded_file(PRIVATE_CONTEXT,capture.MAX_INPUT)
    if capture.sha(context)!=capture.CONTEXT_SHA256:raise capture.CaptureError('fence')
    capture.validate_context(capture.strict_json(context))
    try:out.mkdir(mode=0o700)
    except OSError:raise capture.CaptureError('output') from None
    public=out/'public.pem';public.write_bytes(cert)
    (out/'public.json').write_bytes(capture.encoded(metadata))
    try:
        checked=subprocess.run(['openssl','x509','-in',str(public),'-noout','-text'],stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,timeout=10,env=capture.clean_env())
        if checked.returncode or b'Public-Key: (3072 bit)' not in checked.stdout or b'rsaEncryption' not in checked.stdout:
            raise capture.CaptureError('crypto')
        target=out/'cached-source-context.cms'
        descriptor=os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(descriptor,'wb') as stream:
            result=subprocess.run(['openssl','cms','-encrypt','-aes-256-gcm','-binary','-outform','DER',
                '-recip',str(public),'-keyopt','rsa_padding_mode:oaep','-keyopt','rsa_oaep_md:sha256',
                '-keyopt','rsa_mgf1_md:sha256'],input=context,stdout=stream,stderr=subprocess.DEVNULL,
                timeout=20,env=capture.clean_env())
        if result.returncode:raise capture.CaptureError('crypto')
        cipher=capture.bounded_file(target,capture.MAX_INPUT)
        return {'sealed':True,'ciphertext_bytes':len(cipher),'ciphertext_sha256':capture.sha(cipher)}
    except (OSError,subprocess.SubprocessError):
        (out/'cached-source-context.cms').unlink(missing_ok=True)
        raise capture.CaptureError('crypto') from None
    except capture.CaptureError:
        (out/'cached-source-context.cms').unlink(missing_ok=True)
        raise

def main():
    parser=argparse.ArgumentParser()
    for field in ('public-zip','artifact-sha256','run-id','workflow-sha','expected-runtime-commit','out'):
        parser.add_argument('--'+field,required=True)
    args=parser.parse_args()
    try:
        os.umask(0o077)
        result=seal(Path(args.public_zip),args.artifact_sha256,args.run_id,args.workflow_sha,
                    args.expected_runtime_commit,Path(args.out))
        print(capture.json.dumps(result,sort_keys=True));return 0
    except capture.CaptureError as exc:
        print(capture.json.dumps({'sealed':False,'error_code':exc.code},sort_keys=True));return 1
    except Exception:
        print('{"sealed":false,"error_code":"setup"}');return 1

if __name__=='__main__':sys.exit(main())
