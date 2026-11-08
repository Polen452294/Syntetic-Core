"""Explicit real-browser regression on a local fixture, without external site visits."""

import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from syntetic_core import CoreSettings, SynteticCore

pytestmark = [
    pytest.mark.browser,
    pytest.mark.skipif(
        os.getenv("SYNTETIC_CORE_RUN_BROWSER") != "1",
        reason="Set SYNTETIC_CORE_RUN_BROWSER=1 for real browser tests",
    ),
]


async def test_real_discovery_persistent_profile_and_document_worker_coherence(tmp_path):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(
                b'<meta name="viewport" content="width=device-width, initial-scale=1">'
                b"<title>Core fixture</title><h1>Example</h1>"
            )

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        core = SynteticCore(
            tmp_path,
            settings=CoreSettings(
                allowed_target_hosts=["127.0.0.1"],
                trusted_local_target_hosts=["127.0.0.1"],
                browser_start_timeout=120,
            ),
        )
        caps = await core.capabilities()
        chromium = next(r for r in caps["runtimes"] if r["engine"] == "chromium")
        assert chromium["smoke_test"] == "passed", chromium
        persona = await core.create_profile("persistent", family="android")
        url = f"http://127.0.0.1:{server.server_port}/"
        async with core.session(persona.id) as session:
            await session.goto(url)
            assert await session.page.title() == "Core fixture"
            await session.page.evaluate("localStorage.setItem('state', 'saved')")
            document = await session.page.evaluate(
                "[navigator.hardwareConcurrency, navigator.deviceMemory, "
                "navigator.maxTouchPoints, navigator.webdriver]"
            )
            worker = await session.page.evaluate("""() => new Promise((resolve, reject) => {
                const source = 'postMessage([' +
                    'navigator.hardwareConcurrency,navigator.deviceMemory])';
                const url = URL.createObjectURL(new Blob([source], {type:'text/javascript'}));
                const worker = new Worker(url);
                const timeout = setTimeout(() => {
                    worker.terminate(); reject(Error('Worker timeout'));
                }, 10000);
                worker.onmessage = e => {
                    clearTimeout(timeout); worker.terminate();
                    URL.revokeObjectURL(url); resolve(e.data);
                };
            })""")
            assert document[:2] == worker
            assert document[2:] == [5, False]
        async with core.session(persona.id) as session:
            await session.goto(url)
            assert await session.page.evaluate("localStorage.getItem('state')") == "saved"
            assert session.persona.config_hash == persona.config_hash
    finally:
        await __import__("asyncio").to_thread(server.shutdown)
        server.server_close()
