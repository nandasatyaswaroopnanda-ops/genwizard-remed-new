#!/usr/bin/env python3
"""Unified service runner for Nexus ITSM & Identity Management."""
import subprocess
import sys
import time
import signal

def main():
    procs = []
    
    # 1. Start Backend on port 8000
    p_backend = subprocess.Popen([
        sys.executable, "-m", "uvicorn", "backend.main:app",
        "--host", "0.0.0.0", "--port", "8000"
    ])
    procs.append(p_backend)

    # 2. Start Identity Service on port 8080
    p_identity = subprocess.Popen([
        sys.executable, "-m", "uvicorn", "identity_service.main:app",
        "--host", "0.0.0.0", "--port", "8080"
    ])
    procs.append(p_identity)

    def shutdown(sig, frame):
        for p in procs:
            try:
                p.terminate()
            except Exception:
                pass
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    # Wait for both
    try:
        while True:
            for p in procs:
                ret = p.poll()
                if ret is not None:
                    print(f"Process {p.pid} exited with code {ret}")
            time.sleep(1)
    except KeyboardInterrupt:
        shutdown(None, None)

if __name__ == "__main__":
    main()
