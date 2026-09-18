from __future__ import annotations

import argparse
import json
import logging
import secrets
import socket
import threading
import time
import webbrowser

from desktop.runtime import data_directory, load_engine
from desktop.storage import Store


def main():
    parser = argparse.ArgumentParser(description="DevelopAid Desktop")
    parser.add_argument("--browser", action="store_true", help="Открыть локальное приложение в браузере")
    parser.add_argument("--smoke", action="store_true", help="Проверить упакованный движок без окна")
    args = parser.parse_args()
    directory = data_directory()
    directory.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=directory / "desktop.log", level=logging.INFO)
    core = load_engine(directory)
    from desktop.app import create_app
    import uvicorn
    store = Store(directory / "developaid.sqlite3")
    token = secrets.token_hex(32)
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    origin = f"http://127.0.0.1:{listener.getsockname()[1]}"
    app = create_app(core, store, token, origin)
    if args.smoke:
        import ssl
        import certifi
        # Online search must trust HTTPS without a separately installed Python.
        assert ssl.create_default_context(cafile=certifi.where()).get_ca_certs()
        from fastapi.testclient import TestClient
        with TestClient(app, base_url=origin, headers={"X-DevelopAid-Token": token}) as client:
            boot = client.get("/api/bootstrap").json()
            payload = {**boot["form"]["defaults"], "rates": [], "sensitivity": False,
                       "reference_version": boot["references"]["pack"]["version"]}
            response = client.post("/api/calculate", json=payload)
            response.raise_for_status()
            record = response.json()
            for kind in ("pdf", "xlsx"):
                response = client.get(f'/api/snapshots/{record["snapshot_id"]}/export/{kind}')
                response.raise_for_status()
            (directory / "smoke.json").write_text(json.dumps({
                "ok": True, "engine_version": core.VERSION,
                "exports": ["pdf", "xlsx"]}), encoding="utf-8")
        listener.close()
        return
    server = uvicorn.Server(uvicorn.Config(app, log_config=None, access_log=False))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    thread.start()
    deadline = time.monotonic() + 15
    while not server.started:
        if not thread.is_alive() or time.monotonic() > deadline:
            raise RuntimeError("Локальный сервер не запустился. См. desktop.log")
        time.sleep(0.05)
    try:
        if args.browser:
            webbrowser.open(origin)
            while thread.is_alive():
                thread.join(0.5)
        else:
            import webview
            webview.settings["ALLOW_DOWNLOADS"] = True
            webview.create_window("DevelopAid", origin, width=1440, height=960,
                                  min_size=(1050, 700), background_color="#f2f2ef")
            webview.start(private_mode=True)
    except KeyboardInterrupt:
        pass
    finally:
        server.should_exit = True
        thread.join(10)
        listener.close()


if __name__ == "__main__":
    main()
