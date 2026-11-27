import io
import urllib.error
import pytest
import developaid_contract_disk_source as disk

class Response(io.BytesIO):
    def __init__(self,raw,headers=None):
        super().__init__(raw);self.headers=headers or {}

@pytest.mark.parametrize('url',['http://downloader.disk.yandex.ru/file','https://evil.test/file','https://127.0.0.1/file','https://user@downloader.disk.yandex.ru/file','https://downloader.disk.yandex.ru:443/file'])
def test_download_allowlist_is_checked_before_open(url):
    client=disk.Client()
    client.opener=type('Opener',(),{'open':lambda *a,**kw:pytest.fail('unapproved transport')})()
    with pytest.raises(disk.DiskSourceProblem):
        client.read(url,100,download=True)

def test_redirect_to_unapproved_origin_is_not_followed():
    calls=[];client=disk.Client()
    def open_(request,**kw):
        calls.append(request.full_url)
        assert 'Authorization' not in request.headers
        assert 'Cookie' not in request.headers
        raise urllib.error.HTTPError(request.full_url,302,'redirect',{'Location':'https://127.0.0.1/internal'},None)
    client.opener=type('Opener',(),{'open':staticmethod(open_)})()
    with pytest.raises(disk.DiskSourceProblem):
        client.read('https://downloader.disk.yandex.ru/file',100,download=True)
    assert len(calls)==1

@pytest.mark.parametrize('headers,raw',[({'Content-Length':'1000'},b'small'),({},b'123456')])
def test_download_budget(headers,raw):
    client=disk.Client()
    client.opener=type('Opener',(),{'open':lambda *a,**kw:Response(raw,headers)})()
    with pytest.raises(disk.DiskSourceProblem):
        client.read('https://downloader.disk.yandex.ru/file',5,download=True)

def test_malicious_child_name_cannot_escape_the_folder():
    class Fake:
        def metadata(self,*a):
            return dict(type='dir',_embedded=dict(total=1,items=[dict(name='../private',type='dir')]))
    with pytest.raises(disk.DiskSourceProblem):
        disk.catalog(Fake(),'https://disk.yandex.ru/d/fixture-source')

# A normal Yandex public download currently redirects to this exact storage
# origin. This does not permit arbitrary *.storage.yandex.net or API redirects.
VENDOR_STORAGE = 'https://mds.storage.yandex.net/public-fixture'


def download_client(monkeypatch, raw=b'original-public-file', status=302, final_raw=None):
    import json
    calls=[]
    client=disk.Client()
    monkeypatch.setenv('DEVELOPAID_ADMIN_KEY','secret-that-must-not-leave-RAM')
    def open_(request,**kw):
        from urllib.parse import urlsplit
        calls.append(request)
        headers={key.lower():value for key,value in request.header_items()}
        assert not {'authorization','cookie','proxy-authorization','x-api-key'} & set(headers)
        assert 'secret-that-must-not-leave-RAM' not in request.full_url+repr(headers)
        assert request.data is None
        if urlsplit(request.full_url).hostname=='cloud-api.yandex.net':
            assert urlsplit(request.full_url).path.endswith('/public/resources/download')
            return Response(json.dumps({'href':'https://downloader.disk.yandex.ru/fixture'}).encode())
        if request.full_url=='https://downloader.disk.yandex.ru/fixture':
            raise urllib.error.HTTPError(request.full_url,status,'vendor redirect',{'Location':VENDOR_STORAGE},None)
        assert request.full_url==VENDOR_STORAGE
        value=raw if final_raw is None else final_raw
        return Response(value,{'Content-Length':str(len(value))})
    client.opener=type('Opener',(),{'open':staticmethod(open_)})()
    return client,calls


@pytest.mark.parametrize('status',[302,303,307,308])
def test_exact_vendor_redirect_download_preserves_metadata_hash_size_and_no_credentials(monkeypatch,status):
    import hashlib
    from urllib.parse import urlsplit
    raw=b'original-public-file'
    client,calls=download_client(monkeypatch,raw,status)
    assert client.download('https://disk.yandex.ru/d/fixture-source','/file.xlsx',
        hashlib.sha256(raw).hexdigest(),len(raw))==raw
    assert [urlsplit(request.full_url).hostname for request in calls]==[
        'cloud-api.yandex.net','downloader.disk.yandex.ru','mds.storage.yandex.net']


@pytest.mark.parametrize('url',[
    'http://mds.storage.yandex.net/file',
    'https://mds.storage.yandex.net.evil.test/file',
    'https://evil.mds.storage.yandex.net/file',
    'https://other.storage.yandex.net/file',
    'https://storage.yandex.net/file',
    'https://yandex.net/file',
    'https://mds.storage.yandex.net:443/file',
    'https://user@mds.storage.yandex.net/file',
    'https://user:secret@mds.storage.yandex.net/file',
    'https://127.0.0.1/file',
    'https://169.254.169.254/latest/meta-data',
    'https://[::1]/file',
    'https://mԁs.storage.yandex.net/file',
    'https://mds.storage.yandex.net./file',
])
def test_storage_exception_never_broadens_to_other_origins_or_credentials(url):
    client=disk.Client()
    calls=[]
    def open_(request,**kwargs):
        calls.append(request.full_url)
        raise urllib.error.HTTPError(request.full_url,302,'redirect',{'Location':url},None)
    client.opener=type('Opener',(),{'open':staticmethod(open_)})()
    with pytest.raises(disk.DiskSourceProblem,match='неподдерживаемый адрес'):
        client.read('https://downloader.disk.yandex.ru/file',100,download=True)
    assert calls==['https://downloader.disk.yandex.ru/file']


def test_vendor_storage_is_not_an_api_origin_and_api_redirects_are_not_followed():
    client=disk.Client()
    client.opener=type('Opener',(),{'open':staticmethod(lambda *a,**kw:pytest.fail('unexpected API origin'))})()
    with pytest.raises(disk.DiskSourceProblem):
        client.read(VENDOR_STORAGE,100,download=False)
    calls=[]
    def open_(request,**kwargs):
        calls.append(request.full_url)
        raise urllib.error.HTTPError(request.full_url,302,'redirect',{'Location':VENDOR_STORAGE},None)
    client.opener=type('Opener',(),{'open':staticmethod(open_)})()
    with pytest.raises(disk.DiskSourceProblem,match='не отдал папку'):
        client.read(disk.API,100,download=False)
    assert calls==[disk.API]


def test_exact_vendor_redirects_still_stop_after_three_hops():
    client=disk.Client();calls=[]
    def open_(request,**kwargs):
        calls.append(request.full_url)
        destination=VENDOR_STORAGE if len(calls)%2 else 'https://downloader.disk.yandex.ru/file'
        raise urllib.error.HTTPError(request.full_url,303,'loop',{'Location':destination},None)
    client.opener=type('Opener',(),{'open':staticmethod(open_)})()
    with pytest.raises(disk.DiskSourceProblem,match='не отдал папку'):
        client.read('https://downloader.disk.yandex.ru/file',100,download=True)
    assert len(calls)==4


@pytest.mark.parametrize('headers,raw',[({'Content-Length':'1000'},b'small'),({},b'123456')])
def test_storage_response_keeps_declared_and_streaming_byte_limits(headers,raw):
    client=disk.Client();calls=[]
    def open_(request,**kwargs):
        calls.append(request.full_url)
        return Response(raw,headers)
    client.opener=type('Opener',(),{'open':staticmethod(open_)})()
    with pytest.raises(disk.DiskSourceProblem,match='превышает допустимый размер'):
        client.read(VENDOR_STORAGE,5,download=True)
    assert calls==[VENDOR_STORAGE]


@pytest.mark.parametrize('defect',['content_hash','metadata_size'])
def test_redirected_file_must_still_match_catalogue_sha_and_size(monkeypatch,defect):
    import hashlib
    raw=b'original-public-file'
    client,calls=download_client(monkeypatch,raw,final_raw=b'X'+raw[1:] if defect=='content_hash' else raw)
    with pytest.raises(disk.DiskSourceProblem,match='Файл изменился'):
        client.download('https://disk.yandex.ru/d/fixture-source','/file.xlsx',
            hashlib.sha256(raw).hexdigest(),len(raw)+(defect=='metadata_size'))
    assert len(calls)==3


@pytest.mark.parametrize('size,sha',[(True,'a'*64),(0,'a'*64),(disk.MAX_FILE+1,'a'*64),(1,'invalid')])
def test_invalid_catalogue_binding_is_rejected_before_any_network_open(size,sha):
    client=disk.Client()
    client.opener=type('Opener',(),{'open':staticmethod(lambda *a,**kw:pytest.fail('invalid catalogue caused network read'))})()
    with pytest.raises(disk.DiskSourceProblem,match='Размер или контрольная сумма'):
        client.download('https://disk.yandex.ru/d/fixture-source','/file.xlsx',sha,size)
