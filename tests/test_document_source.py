"""Teaser URLs: source evidence, redirect boundaries and bounded reads."""
from __future__ import annotations

import hashlib
import io
import socket
import ssl
import shutil
import subprocess
import threading
import time
import urllib.request
from concurrent.futures import Future, ThreadPoolExecutor

import pytest

import document_source as ds


PDF = b"%PDF-1.7\nsynthetic document"


@pytest.fixture(autouse=True)
def close_test_dns_workers(monkeypatch):
    # The process-wide resolver serves the long-lived app. Each test owns and
    # joins its resolver workers so no idle executor thread outlives the test.
    with ThreadPoolExecutor(max_workers=2, thread_name_prefix="test-document-dns") as pool:
        monkeypatch.setattr(ds, "_DNS", pool)
        yield


class Response:
    def __init__(self, body=PDF, *, status=200, headers=None):
        self.status = status
        self.headers = {"Content-Type": "application/pdf", **(headers or {})}
        self.stream = io.BytesIO(body)

    def getheader(self, name):
        return self.headers.get(name)

    def read1(self, amount):
        return self.stream.read(amount)


def transport(monkeypatch, responses, *, addresses=None):
    """Replace sockets, keeping the real URL validation and redirect loop."""
    sent = []
    closed = []
    pending = list(responses)

    def resolve(host, port, **kwargs):
        ips = (addresses or {}).get(host, ["93.184.216.34"])
        return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (ip, port)) for ip in ips]

    class Connection:
        def __init__(self, host, endpoint, timeout):
            self.host, self.endpoint, self.timeout = host, endpoint, timeout
            self.sock = None

        def request(self, method, path, headers):
            sent.append(dict(host=self.host, endpoint=self.endpoint, method=method, path=path, headers=headers))

        def getresponse(self):
            response = pending.pop(0)
            if isinstance(response, BaseException):
                raise response
            return response

        def close(self):
            closed.append(self.host)

    monkeypatch.setattr(ds.socket, "getaddrinfo", resolve)
    monkeypatch.setattr(ds, "_PinnedHTTPS", Connection)
    return sent, closed


def test_public_pdf_has_a_downloaded_snapshot_and_no_credentials(monkeypatch):
    sent, closed = transport(monkeypatch, [Response()])
    got = ds.read_url("https://files.example/тизер.pdf?signature=private-token")
    assert got["data"] == PDF
    assert got["filename"] == "тизер.pdf"
    assert got["source"]["original_url"].endswith("signature=private-token")
    assert got["source"]["sha256"] == hashlib.sha256(PDF).hexdigest()
    assert got["source"]["fetched_at"]
    assert "%D1%82" in got["source"]["final_url"]
    assert sent[0]["headers"]["Accept-Encoding"] == "identity"
    assert not ({"Authorization", "Cookie", "Proxy-Authorization"} & sent[0]["headers"].keys())
    assert closed == ["files.example"]


@pytest.mark.parametrize("url", [
    "http://files.example/teaser.pdf", "https://name:secret@files.example/teaser.pdf",
    "https://files.example:8443/teaser.pdf", "file:///etc/passwd",
    "https://files.example/\r\nheader:injected", "https://files.example\\@localhost/a",
])
def test_invalid_url_does_not_issue_a_request(monkeypatch, url):
    sent, _ = transport(monkeypatch, [])
    with pytest.raises(ds.DocumentSourceError) as raised:
        ds.read_url(url)
    assert raised.value.code == "invalid_url"
    assert sent == []


@pytest.mark.parametrize("ip", ["127.0.0.1", "10.1.2.3", "169.254.169.254", "224.0.0.1", "0.0.0.0", "::1", "fe80::1"])
def test_nonpublic_endpoint_does_not_issue_a_request(monkeypatch, ip):
    sent, _ = transport(monkeypatch, [], addresses={"files.example": [ip]})
    with pytest.raises(ds.DocumentSourceError) as raised:
        ds.read_url("https://files.example/teaser.pdf")
    assert raised.value.code == "source_private"
    assert sent == []


def test_one_private_dns_answer_blocks_a_mixed_dns_result(monkeypatch):
    sent, _ = transport(monkeypatch, [], addresses={"files.example": ["93.184.216.34", "10.0.0.1"]})
    with pytest.raises(ds.DocumentSourceError):
        ds.read_url("https://files.example/teaser.pdf")
    assert sent == []


def test_redirect_to_metadata_is_rejected_before_connecting(monkeypatch):
    sent, closed = transport(monkeypatch, [Response(status=302, headers={"Location": "https://metadata.example/latest"})],
                             addresses={"metadata.example": ["169.254.169.254"]})
    with pytest.raises(ds.DocumentSourceError) as raised:
        ds.read_url("https://files.example/teaser.pdf")
    assert raised.value.code == "source_private"
    assert [r["host"] for r in sent] == ["files.example"]
    assert closed == ["files.example"]


def test_public_relative_redirect_revalidates_and_records_the_final_url(monkeypatch):
    sent, _ = transport(monkeypatch, [Response(status=302, headers={"Location": "/download/a.pdf"}), Response()])
    got = ds.read_url("https://files.example/preview")
    assert len(sent) == 2
    assert got["source"]["final_url"] == "https://files.example/download/a.pdf"


def test_redirect_loop_stops(monkeypatch):
    sent, _ = transport(monkeypatch, [Response(status=302, headers={"Location": "/a"})])
    with pytest.raises(ds.DocumentSourceError) as raised:
        ds.read_url("https://files.example/a")
    assert raised.value.code == "source_redirect"
    assert len(sent) == 1


@pytest.mark.parametrize("content_type,body", [
    ("application/pdf", b"<html><body>sign in</body></html>"),
    ("image/png", PDF), ("image/jpeg", b"not an image"), ("text/html", PDF),
])
def test_false_content_type_is_not_accepted_as_a_document(monkeypatch, content_type, body):
    transport(monkeypatch, [Response(body, headers={"Content-Type": content_type})])
    with pytest.raises(ds.DocumentSourceError) as raised:
        ds.read_url("https://files.example/a")
    assert raised.value.code == "source_type_mismatch"


@pytest.mark.parametrize("headers", [{"Content-Length": "9999"}, {}])
def test_size_limit_covers_advertised_and_streamed_bodies(monkeypatch, headers):
    transport(monkeypatch, [Response(b"x" * 200, headers=headers)])
    with pytest.raises(ds.DocumentSourceError) as raised:
        ds.read_url("https://files.example/a", max_bytes=100)
    assert raised.value.code == "source_size"
    assert raised.value.status_code == 413


def test_truncated_response_is_not_a_complete_snapshot(monkeypatch):
    transport(monkeypatch, [Response(headers={"Content-Length": "100"})])
    with pytest.raises(ds.DocumentSourceError) as raised:
        ds.read_url("https://files.example/a")
    assert raised.value.code == "source_incomplete"


def test_timeout_is_a_public_source_error_and_closes_connection(monkeypatch):
    sent, closed = transport(monkeypatch, [socket.timeout("internal detail")])
    with pytest.raises(ds.DocumentSourceError) as raised:
        ds.read_url("https://files.example/a")
    assert raised.value.status_code == 504
    assert "internal detail" not in str(raised.value)
    assert len(sent) == 1 and closed == ["files.example"]


def test_slow_body_is_checked_after_each_single_read_not_after_filling_64kb(monkeypatch):
    clock = [0.0]
    calls = {"read": 0, "read1": 0}

    class Trickle(Response):
        def read(self, amount):
            # The old read(n) could receive many tiny chunks, each below its
            # per-recv timeout, before returning to the caller's deadline check.
            calls["read"] += 1
            clock[0] += 50.0
            return PDF

        def read1(self, amount):
            calls["read1"] += 1
            clock[0] += 0.4
            return b"x"

    monkeypatch.setattr(ds.time, "monotonic", lambda: clock[0])
    sent, closed = transport(monkeypatch, [Trickle()])
    with pytest.raises(ds.DocumentSourceError) as raised:
        ds.read_url("https://files.example/a", timeout=1.0)
    assert raised.value.code == "source_timeout"
    assert calls == {"read": 0, "read1": 3}
    assert clock[0] < 1.3  # one single read, not a 50-second accumulating call
    assert len(sent) == 1 and closed == ["files.example"]


def test_slow_header_line_cannot_reset_timeout_past_total_deadline(monkeypatch):
    clock = [0.0]
    limits = []

    class Trickle(io.BytesIO):
        def read1(self, amount=-1):
            clock[0] += 0.2
            return super().read(1)  # one byte per recv, each below socket timeout

    class Socket:
        def makefile(self, mode):
            return Trickle(b"HTTP/1.1 200 OK\r\nContent-Type: application/pdf\r\n\r\n" + PDF)

        def settimeout(self, value):
            limits.append(value)

    monkeypatch.setattr(ds.time, "monotonic", lambda: clock[0])
    response = ds._DeadlineResponse(Socket(), deadline=0.5)
    try:
        with pytest.raises(ds.DocumentSourceError) as raised:
            response.begin()
        assert raised.value.code == "source_timeout"
        assert limits == pytest.approx([0.5, 0.3, 0.1])
        assert clock[0] == pytest.approx(0.6)
    finally:
        response.close()


def test_deadline_response_keeps_real_http_chunk_framing(monkeypatch):
    class Socket:
        def makefile(self, mode):
            return io.BytesIO(b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n3\r\nabc\r\n2\r\nde\r\n0\r\n\r\n")

        def settimeout(self, value):
            pass

    response = ds._DeadlineResponse(Socket(), deadline=time.monotonic() + 5)
    try:
        response.begin()
        assert response.read1(100) + response.read1(100) + response.read1(100) == b"abcde"
    finally:
        response.close()


@pytest.mark.parametrize("status", [401, 403])
def test_remote_auth_refusal_is_not_an_empty_document(monkeypatch, status):
    transport(monkeypatch, [Response(status=status)])
    with pytest.raises(ds.DocumentSourceError) as raised:
        ds.read_url("https://files.example/a")
    assert raised.value.code == "source_access"
    assert str(status) in str(raised.value)


def test_html_reads_visible_text_without_executing_or_following_links(monkeypatch):
    html = '''<html><head><script>price = 900000</script><style>.x{}</style></head>
    <body><nav>Цена сделки 900 млн</nav><article><h1>Публичный тизер проекта</h1>
    <p>Площадь участка 1,5 га. Цена сделки 400 млн рублей.</p>
    <a href="https://other.example/document.pdf">Описание проекта</a></article></body></html>'''
    sent, _ = transport(monkeypatch, [Response(html.encode(), headers={"Content-Type": "text/html; charset=utf-8"})])
    got = ds.read_url("https://files.example/project")
    assert "400 млн" in got["text"]
    assert "900" not in got["text"]
    assert got["text"].startswith("[стр. 1]\n")
    assert len(sent) == 1
    assert "data" not in got


def test_html_password_form_is_not_a_teaser(monkeypatch):
    body = b"<html><body><h1>Sign in</h1><p>Enter your account to view this project document.</p><input type='password'></body></html>"
    transport(monkeypatch, [Response(body, headers={"Content-Type": "text/html"})])
    with pytest.raises(ds.DocumentSourceError) as raised:
        ds.read_url("https://files.example/a")
    assert raised.value.code == "source_access"


def test_passwordless_signin_form_is_not_a_teaser(monkeypatch):
    body = b"<html><body><form action='/auth/login'>Enter email to continue to the private project document.</form></body></html>"
    transport(monkeypatch, [Response(body, headers={"Content-Type": "text/html"})])
    with pytest.raises(ds.DocumentSourceError) as raised:
        ds.read_url("https://files.example/a")
    assert raised.value.code == "source_access"


def test_meta_redirect_is_not_followed_or_misreported_as_document(monkeypatch):
    body = b"<html><head><meta http-equiv='refresh' content='0;url=https://127.0.0.1/'></head><body>Continue to the document loading page for this project.</body></html>"
    sent, _ = transport(monkeypatch, [Response(body, headers={"Content-Type": "text/html"})])
    with pytest.raises(ds.DocumentSourceError) as raised:
        ds.read_url("https://files.example/a")
    assert raised.value.code == "source_redirect"
    assert len(sent) == 1


def test_javascript_shell_does_not_mean_the_teaser_is_empty(monkeypatch):
    transport(monkeypatch, [Response(b"<html><body><div id='app'></div><script>loadDoc()</script></body></html>",
                                    headers={"Content-Type": "text/html"})])
    with pytest.raises(ds.DocumentSourceError) as raised:
        ds.read_url("https://files.example/a")
    assert raised.value.code == "source_no_text"
    assert "JavaScript" in str(raised.value)


def test_cloud_preview_is_not_reported_as_file_contents(monkeypatch):
    transport(monkeypatch, [Response(b"<html><body>File preview loading and download controls</body></html>",
                                    headers={"Content-Type": "text/html"})])
    with pytest.raises(ds.DocumentSourceError) as raised:
        ds.read_url("https://drive.google.com/file/d/abc/view")
    assert raised.value.code == "source_preview"


def test_real_transport_connects_only_to_the_checked_ip_but_uses_hostname_for_tls(monkeypatch):
    calls = []
    class Socket:
        def settimeout(self, value):
            calls.append(("timeout", value))
        def connect(self, address):
            calls.append(("connect", address))
        def close(self):
            calls.append(("close",))
    # HTTPSConnection on Python 3.11 also inspects verify_mode/check_hostname.
    # Use the real verified context and replace only the network handshake.
    context = ds.trust_context()
    def wrap_socket(sock, *, server_hostname):
        calls.append(("tls", server_hostname))
        return sock
    monkeypatch.setattr(context, "wrap_socket", wrap_socket)
    monkeypatch.setattr(ds.socket, "socket", lambda *args: Socket())
    monkeypatch.setattr(ds, "trust_context", lambda: context)
    monkeypatch.setattr(ds.socket, "getaddrinfo", lambda *args, **kwargs: pytest.fail("a second DNS lookup would allow rebinding"))
    endpoint = (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("93.184.216.34", 443))
    conn = ds._PinnedHTTPS("files.example", (endpoint,), timeout=5)
    conn.connect()
    assert conn._context is context
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname is True
    assert ("connect", ("93.184.216.34", 443)) in calls
    assert ("tls", "files.example") in calls


def test_pinned_tls_recomputes_remaining_after_tcp_and_handshake(monkeypatch):
    now=[0.0];monkeypatch.setattr(ds.time,'monotonic',lambda:now[0])
    timeouts=[];closed=[]
    class Socket:
        def settimeout(self,value):timeouts.append(value)
        def connect(self,address):now[0]+=0.30
        def close(self):closed.append(True)
    raw=Socket();context=ds.trust_context()
    def handshake(sock,**kwargs):
        assert timeouts[-1]==pytest.approx(0.10)
        now[0]+=0.04
        return sock
    monkeypatch.setattr(context,'wrap_socket',handshake)
    monkeypatch.setattr(ds,'trust_context',lambda:context)
    monkeypatch.setattr(ds.socket,'socket',lambda *args:raw)
    endpoint=(socket.AF_INET,socket.SOCK_STREAM,socket.IPPROTO_TCP,'',('93.184.216.34',443))
    connection=ds._PinnedHTTPS('files.example',(endpoint,),timeout=0.40)
    connection.connect()
    assert timeouts==pytest.approx([0.40,0.10,0.06])
    connection.close()
    assert closed==[True]


def test_pinned_tls_context_setup_cannot_restart_the_deadline(monkeypatch):
    now=[0.0];monkeypatch.setattr(ds.time,'monotonic',lambda:now[0])
    context=ds.trust_context()
    def setup():
        now[0]=0.50
        return context
    monkeypatch.setattr(ds,'trust_context',setup)
    monkeypatch.setattr(ds.socket,'socket',lambda *args:pytest.fail('Expired setup allocated a socket'))
    endpoint=(socket.AF_INET,socket.SOCK_STREAM,socket.IPPROTO_TCP,'',('93.184.216.34',443))
    connection=ds._PinnedHTTPS('files.example',(endpoint,),timeout=0.40)
    with pytest.raises(ds.DocumentSourceError) as expired:
        connection.connect()
    assert expired.value.code=='source_timeout' and connection._deadline==0.40


@pytest.mark.parametrize('phase',['before_tcp','after_tcp','after_tls','expired_retry'])
def test_pinned_tls_expiry_closes_unassigned_socket_and_stops_retries(monkeypatch,phase):
    now=[0.0];monkeypatch.setattr(ds.time,'monotonic',lambda:now[0])
    raws=[];wrapped=[];handshakes=[]
    class Wrapped:
        closed=False
        def settimeout(self,value):pass
        def close(self):self.closed=True
    class Raw(Wrapped):
        def connect(self,address):
            if phase in {'after_tcp','expired_retry'}:now[0]=0.50
            if phase=='expired_retry':raise OSError('synthetic TCP failure')
    def allocate(*args):
        value=Raw();raws.append(value);return value
    context=ds.trust_context()
    def handshake(raw,**kwargs):
        handshakes.append(True)
        value=Wrapped();wrapped.append(value)
        now[0]=0.50
        return value
    monkeypatch.setattr(context,'wrap_socket',handshake)
    monkeypatch.setattr(ds,'trust_context',lambda:context)
    monkeypatch.setattr(ds.socket,'socket',allocate)
    endpoint=(socket.AF_INET,socket.SOCK_STREAM,socket.IPPROTO_TCP,'',('93.184.216.34',443))
    connection=ds._PinnedHTTPS('files.example',(endpoint,endpoint),timeout=0.40)
    if phase=='before_tcp':now[0]=0.50
    with pytest.raises(ds.DocumentSourceError) as expired:
        connection.connect()
    assert expired.value.code=='source_timeout' and connection.sock is None
    assert len(raws)==(0 if phase=='before_tcp' else 1)
    assert all(value.closed for value in raws+wrapped)
    assert bool(handshakes)==(phase=='after_tls')


def test_pinned_tls_endpoint_retry_inherits_absolute_deadline(monkeypatch):
    now=[0.0];monkeypatch.setattr(ds.time,'monotonic',lambda:now[0])
    raws=[];timeouts=[]
    class Socket:
        closed=False
        def settimeout(self,value):timeouts.append(value)
        def connect(self,address):
            now[0]+=0.30 if len(raws)==1 else 0.02
            if len(raws)==1:raise OSError('synthetic first endpoint failure')
        def close(self):self.closed=True
    def allocate(*args):
        value=Socket();raws.append(value);return value
    context=ds.trust_context()
    monkeypatch.setattr(context,'wrap_socket',lambda raw,**kwargs:raw)
    monkeypatch.setattr(ds,'trust_context',lambda:context)
    monkeypatch.setattr(ds.socket,'socket',allocate)
    endpoint=(socket.AF_INET,socket.SOCK_STREAM,socket.IPPROTO_TCP,'',('93.184.216.34',443))
    connection=ds._PinnedHTTPS('files.example',(endpoint,endpoint),timeout=0.40)
    connection.connect()
    assert timeouts==pytest.approx([0.40,0.10,0.08,0.08])
    assert raws[0].closed
    connection.close()
    assert all(value.closed for value in raws)


def test_pinned_tls_does_not_swallow_non_network_failure_or_leak_raw_socket(monkeypatch):
    raw=type('Socket',(),{'settimeout':lambda *a:None,'connect':lambda *a:None,
                         'close':lambda self:setattr(self,'closed',True)})()
    context=ds.trust_context()
    def failure(*args,**kwargs):raise RuntimeError('synthetic handshake failure')
    monkeypatch.setattr(context,'wrap_socket',failure)
    monkeypatch.setattr(ds,'trust_context',lambda:context)
    allocations=[]
    monkeypatch.setattr(ds.socket,'socket',lambda *args:allocations.append(raw) or raw)
    endpoint=(socket.AF_INET,socket.SOCK_STREAM,socket.IPPROTO_TCP,'',('93.184.216.34',443))
    connection=ds._PinnedHTTPS('files.example',(endpoint,endpoint),timeout=1)
    with pytest.raises(RuntimeError,match='synthetic handshake failure'):
        connection.connect()
    assert raw.closed and connection.sock is None and allocations==[raw]


@pytest.fixture
def local_tls_endpoint(tmp_path):
    if not shutil.which('openssl'):
        pytest.skip('openssl is required for the real verified TLS check')
    cert=tmp_path/'test-localhost.pem';key=tmp_path/'test-localhost.key'
    subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-days','1',
        '-subj','/CN=localhost','-addext','subjectAltName=DNS:localhost,IP:127.0.0.1',
        '-keyout',str(key),'-out',str(cert)],check=True,capture_output=True,timeout=10)
    context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(str(cert),str(key))
    listener=socket.socket(socket.AF_INET,socket.SOCK_STREAM)
    listener.bind(('127.0.0.1',0));listener.listen(1);listener.settimeout(5)
    errors=[]
    def serve():
        raw=wrapped=None
        try:
            raw,_=listener.accept();raw.settimeout(5)
            wrapped=context.wrap_socket(raw,server_side=True)
            headers=b''
            while b'\r\n\r\n' not in headers:
                chunk=wrapped.recv(4096)
                if not chunk:break
                headers+=chunk
            head,_,pending=headers.partition(b'\r\n\r\n')
            length=next((int(line.split(b':',1)[1]) for line in head.split(b'\r\n')
                         if line.lower().startswith(b'content-length:')),0)
            while len(pending)<length:
                chunk=wrapped.recv(length-len(pending))
                if not chunk:break
                pending+=chunk
            body=b'{"tls":true}'
            wrapped.sendall(b'HTTP/1.1 200 OK\r\nContent-Length: '+str(len(body)).encode()+b'\r\n\r\n'+body)
        except (ssl.SSLError,OSError) as exc:
            errors.append(type(exc).__name__)
        finally:
            if wrapped is not None:wrapped.close()
            if raw is not None:raw.close()
            listener.close()
    thread=threading.Thread(target=serve,daemon=True);thread.start()
    try:
        yield cert,listener.getsockname()[1],errors
    finally:
        listener.close();thread.join(timeout=6)
        assert not thread.is_alive()


@pytest.mark.parametrize('trusted',[True,False])
def test_native_document_post_uses_real_verified_tls_and_closes_sockets(
        local_tls_endpoint,monkeypatch,trusted):
    import document_processing as processing
    cert,port,errors=local_tls_endpoint
    context=ds.trust_context()
    if trusted:context.load_verify_locations(cafile=str(cert))
    assert context.verify_mode==ssl.CERT_REQUIRED and context.check_hostname
    monkeypatch.setattr(ds,'trust_context',lambda:context)
    raw_sockets=[];tls_sockets=[];caller=threading.get_ident()
    allocate=socket.socket;wrap=context.wrap_socket
    def tracked_socket(*args,**kwargs):
        sock=allocate(*args,**kwargs)
        if threading.get_ident()==caller:raw_sockets.append(sock)
        return sock
    def tracked_wrap(*args,**kwargs):
        sock=wrap(*args,**kwargs);tls_sockets.append(sock);return sock
    monkeypatch.setattr(ds.socket,'socket',tracked_socket)
    monkeypatch.setattr(context,'wrap_socket',tracked_wrap)
    request=urllib.request.Request('https://localhost:'+str(port)+'/',data=b'{}')
    with processing.operation(seconds=5):
        if trusted:
            assert processing.post_bytes(request,180)==b'{"tls":true}'
        else:
            with pytest.raises(ssl.SSLCertVerificationError):
                processing.post_bytes(request,180)
    assert raw_sockets and all(sock.fileno()==-1 for sock in raw_sockets+tls_sockets)


def test_dns_wait_has_a_deadline_and_cancels_queued_work(monkeypatch):
    pending = Future()
    class Resolver:
        def submit(self, *args, **kwargs):
            return pending
    monkeypatch.setattr(ds, "_DNS", Resolver())
    with pytest.raises(ds.DocumentSourceError) as raised:
        ds._resolve("files.example", time.monotonic() + 0.001)
    assert raised.value.code == "source_timeout"
    assert raised.value.status_code == 504
    assert pending.cancelled()


def test_excess_dns_work_is_rejected_before_queuing(monkeypatch):
    class Slots:
        def acquire(self, **kwargs):
            return False
    monkeypatch.setattr(ds, "_DNS_SLOTS", Slots())
    with pytest.raises(ds.DocumentSourceError) as raised:
        ds._resolve("files.example", time.monotonic() + 5)
    assert raised.value.code == "source_busy"
