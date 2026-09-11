"""Bounded local readiness check for make demo."""
import sys
import time
from urllib.error import URLError
from urllib.request import urlopen

for attempt in range(50):
    try:
        with urlopen(sys.argv[1], timeout=1) as response:
            if response.status == 200:
                break
    except (URLError, TimeoutError):
        time.sleep(.1)
else:
    raise SystemExit("API did not become ready; inspect /tmp/uc1-demo-server.log")
