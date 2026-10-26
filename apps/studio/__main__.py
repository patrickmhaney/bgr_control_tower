"""python -m apps.studio [--port 8800] [--project SLUG]: serve the Studio on localhost."""
import argparse
import os

import uvicorn

p = argparse.ArgumentParser(prog="python -m apps.studio")
p.add_argument("--port", type=int, default=8800)
p.add_argument("--project", help="the project pack to open with (switchable in the header)")
a = p.parse_args()
if a.project:
    os.environ["CT_PROJECT"] = a.project
print(f"Control Tower Studio on http://localhost:{a.port}")
uvicorn.run("apps.studio.app:app", host="127.0.0.1", port=a.port, log_level="warning")
