"""Start the News Scraper Platform.

    python run.py              start and open the dashboard in the browser
    python run.py --no-browser start without opening a browser
"""

import sys
import threading
import webbrowser

import uvicorn

from backend import config


def main() -> None:
    url = f"http://{config.HOST}:{config.PORT}"
    print(f"\n  News Scraper Platform is running at {url}\n  Press Ctrl+C to stop.\n")
    if "--no-browser" not in sys.argv:
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    uvicorn.run("backend.main:app", host=config.HOST, port=config.PORT, log_level="warning")


if __name__ == "__main__":
    main()
