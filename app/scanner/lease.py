"""Scanner lease owner identity."""

from __future__ import annotations

import os
import socket
import uuid

OWNER = f"{socket.gethostname()}-{os.getpid()}-{uuid.uuid4().hex[:6]}"
