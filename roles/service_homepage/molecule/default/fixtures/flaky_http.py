# SPDX-License-Identifier: GPL-3.0-or-later
"""A local HTTP endpoint that resets its first N connections, then answers 200.

Stands in for a just-restarted Homepage container, whose first connections are reset while the
server starts. Usage: flaky_http.py <portfile> <resets>. Binds a free port and writes it to <portfile> once
listening, so each run gets its own endpoint and nothing has to connect to learn it is up.
Exits after one 200, or after 60 seconds.
"""

import os
import socket
import struct
import sys
import time

portfile, resets = sys.argv[1], int(sys.argv[2])
srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
srv.bind(("127.0.0.1", 0))
srv.listen(8)
with open(portfile + ".tmp", "w") as f:
    f.write(str(srv.getsockname()[1]))
os.replace(portfile + ".tmp", portfile)
srv.settimeout(1)
deadline = time.monotonic() + 60
seen = 0
while time.monotonic() < deadline:
    try:
        conn, _ = srv.accept()
    except socket.timeout:
        continue
    seen += 1
    if seen <= resets:
        # SO_LINGER 0: close() sends RST, which the client sees as "connection reset by peer".
        conn.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
        conn.close()
        continue
    conn.settimeout(5)
    try:
        conn.recv(4096)
        conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nok")
    except socket.timeout:
        continue  # a client that connects and sends nothing does not end the fixture
    finally:
        conn.close()
    break
srv.close()
