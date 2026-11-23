import argparse
import asyncio
import socket
import webbrowser
import uvicorn
from .config import SETTINGS
from .server import Runtime, create_app


async def run(demo=False, no_browser=False):
    runtime = Runtime(demo=demo)
    app = create_app(runtime)
    server = uvicorn.Server(uvicorn.Config(app, host=SETTINGS.host, port=SETTINGS.port, log_level="warning", access_log=False, ws_max_size=65536, workers=1))
    task = asyncio.create_task(server.serve())
    while not server.started and not task.done():
        await asyncio.sleep(0.1)
    if server.started:
        url = f"http://{SETTINGS.host}:{SETTINGS.port}/#token={runtime.token}"
        print("Jarvis Voice açıldı. Kapatmak için bu pencerede Ctrl+C kullan.", flush=True)
        if not no_browser:
            webbrowser.open(url)
        else:
            # Development-only local URL; this flag is not used by the Windows launcher.
            print(url, flush=True)
    await task


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--demo", action="store_true", help="UI/protocol test; no speech models")
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    try:
        asyncio.run(run(args.demo, args.no_browser))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
