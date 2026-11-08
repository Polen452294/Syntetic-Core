"""Native Gecko AddonsActor handshake; content requests never cross this IPC channel."""

import asyncio
import json
import socket
from pathlib import Path

from syntetic_core._engine.errors import ProfileValidationError


def debugger_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


async def install_extensions(port: int, profile: Path) -> None:
    async with asyncio.timeout(15):
        while True:
            try:
                reader, writer = await asyncio.open_connection("127.0.0.1", port)
                break
            except OSError:
                await asyncio.sleep(0.05)
        try:

            async def receive() -> dict:
                size = await reader.readuntil(b":")
                if len(size) > 9 or not size[:-1].isdigit():
                    raise ProfileValidationError("Invalid Gecko addon IPC frame")
                length = int(size[:-1])
                if length > 1024**2:
                    raise ProfileValidationError("Gecko addon IPC response exceeds limit")
                return json.loads(await reader.readexactly(length))

            async def request(actor: str, method: str, **params: object) -> dict:
                body = json.dumps({"to": actor, "type": method, **params}).encode()
                writer.write(str(len(body)).encode() + b":" + body)
                await writer.drain()
                while True:
                    response = await receive()
                    if response.get("from") != actor:
                        continue
                    if response.get("error"):
                        raise ProfileValidationError("Gecko rejected the local content extension")
                    return response

            await receive()  # Root actor greeting.
            root = await request("root", "getRoot")
            actor = root.get("addonsActor")
            if not isinstance(actor, str):
                raise ProfileValidationError("Gecko runtime has no native AddonsActor")
            for path in sorted((profile.parent / ".gecko-addons").glob("*.xpi")):
                await request(
                    actor,
                    "installTemporaryAddon",
                    addonPath=str(path.resolve()),
                    openDevTools=False,
                )
        finally:
            writer.close()
            await writer.wait_closed()
