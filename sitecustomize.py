"""Runtime compatibility patch for DevelopAid v0.12.26.

Python imports sitecustomize automatically during interpreter startup.  The
finder below delegates loading of ``main`` to Python's normal loader and then
applies the Telegram document fixes without relying on GitHub Actions.
"""

from __future__ import annotations

import importlib.abc
import importlib.machinery
import sys
from types import ModuleType


class _MainPatchLoader(importlib.abc.Loader):
    def __init__(self, wrapped: importlib.abc.Loader) -> None:
        self._wrapped = wrapped

    def create_module(self, spec):  # type: ignore[no-untyped-def]
        creator = getattr(self._wrapped, "create_module", None)
        return creator(spec) if creator else None

    def exec_module(self, module: ModuleType) -> None:
        self._wrapped.exec_module(module)
        _patch_main(module)


class _MainPatchFinder(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):  # type: ignore[no-untyped-def]
        if fullname != "main":
            return None
        spec = importlib.machinery.PathFinder.find_spec(fullname, path)
        if spec is None or spec.loader is None:
            return None
        spec.loader = _MainPatchLoader(spec.loader)
        return spec


def _patch_main(module: ModuleType) -> None:
    def send_document_bytes(
        chat_id: int,
        content: bytes,
        filename: str,
        caption: str = "",
        content_type: str | None = None,
    ):
        token = module._telegram_token()
        if not token:
            raise RuntimeError("TELEGRAM_BOT_TOKEN не задан")

        if content_type is None:
            content_type = (
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                if filename.lower().endswith(".xlsx")
                else "application/pdf"
            )

        boundary = "----DevelopAidBoundary" + module.hashlib.sha256(
            module.os.urandom(16)
        ).hexdigest()[:20]
        body = module.io.BytesIO()

        def field(name: str, value: str) -> None:
            body.write(f"--{boundary}\r\n".encode())
            body.write(
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode()
            )
            body.write(str(value).encode("utf-8"))
            body.write(b"\r\n")

        field("chat_id", str(int(chat_id)))
        if caption:
            field("caption", caption)
            field("parse_mode", "HTML")

        body.write(f"--{boundary}\r\n".encode())
        body.write(
            f'Content-Disposition: form-data; name="document"; filename="{filename}"\r\n'.encode(
                "utf-8"
            )
        )
        body.write(f"Content-Type: {content_type}\r\n\r\n".encode("ascii"))
        body.write(content)
        body.write(b"\r\n")
        body.write(f"--{boundary}--\r\n".encode())

        request = module.urllib.request.Request(
            f"https://api.telegram.org/bot{token}/sendDocument",
            data=body.getvalue(),
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            method="POST",
        )
        try:
            with module.urllib.request.urlopen(request, timeout=30) as response:
                result = module.json.loads(response.read().decode("utf-8"))
        except module.urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            raise RuntimeError(
                f"Telegram API sendDocument: HTTP {exc.code}: {detail}"
            ) from exc

        if not result.get("ok"):
            raise RuntimeError(
                "Telegram API sendDocument: "
                + str(result.get("description") or "неизвестная ошибка")
            )
        return result.get("result")

    def send_template(chat_id: int):
        return send_document_bytes(
            chat_id,
            module.base64.b64decode(module.MANUAL_TEP_TEMPLATE_B64),
            module.MANUAL_TEP_TEMPLATE_FILENAME,
            (
                "<b>Шаблон ручного ввода ТЭП DevelopAid</b>\n\n"
                "1. Заполните жёлтые ячейки.\n"
                "2. Не меняйте коды и названия строк.\n"
                "3. Отправьте заполненный .xlsx обратно в этот чат.\n\n"
                "Бот проверит файл и покажет сводку перед открытием модели."
            ),
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    module._telegram_send_document_bytes = send_document_bytes
    module._telegram_send_template = send_template
    if hasattr(module, "app"):
        module.app.version = "0.12.26"


sys.meta_path.insert(0, _MainPatchFinder())
