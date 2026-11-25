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
