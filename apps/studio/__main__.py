"""python -m apps.studio [--port 8800]: serve the Studio on localhost."""
import argparse

import uvicorn

p = argparse.ArgumentParser(prog="python -m apps.studio")
p.add_argument("--port", type=int, default=8800)
a = p.parse_args()
print(f"Control Tower Studio on http://localhost:{a.port}")
uvicorn.run("apps.studio.app:app", host="127.0.0.1", port=a.port, log_level="warning")
