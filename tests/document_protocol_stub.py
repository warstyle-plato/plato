"""A compatible external core for tests whose subject is the native signed document."""
import email.message
import io
import json
import document_intake_protocol as protocol


def compatible_document_core(monkeypatch, core):
    origin = protocol.target_origin(core._TELEGRAM_WEB_APP_BASE_URL)
    monkeypatch.setenv(protocol.ADMISSION_ENV, json.dumps({'schema':1, 'origin':origin,
        'protocol':protocol.PROTOCOL, 'core_commit':'a'*40, 'completed_rollout':True}))
    original = core.urllib.request.build_opener
    class Reply(io.BytesIO):
        status = 200
        def __init__(self):
            super().__init__(json.dumps(protocol.capability()).encode())
            self.headers=email.message.Message();self.headers['Content-Type']='application/json'
        def geturl(self):return origin+protocol.CAPABILITY_PATH
    class Opener:
        def open(self, request, timeout):
            assert request.full_url==origin+protocol.CAPABILITY_PATH and request.data is None and timeout==5
            return Reply()
        def close(self):pass
    def build(*handlers):
        if any(isinstance(handler,core._DocumentProtocolNoRedirect)for handler in handlers):return Opener()
        return original(*handlers)
    monkeypatch.setattr(core.urllib.request,'build_opener',build)
