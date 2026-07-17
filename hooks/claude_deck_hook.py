"""Claude Code hook: forward session events to the claude-deck broker.

Stdlib only, fire-and-forget, never blocks or fails the session.
Adds the hook process's ancestor PIDs so the daemon can locate the exact
VS Code terminal hosting this session.
"""

import ctypes
import ctypes.wintypes as wt
import json
import os
import sys
import urllib.request

BROKER_URL = "http://127.0.0.1:8642/hook"

TH32CS_SNAPPROCESS = 0x00000002


class PROCESSENTRY32(ctypes.Structure):
    _fields_ = [
        ("dwSize", wt.DWORD),
        ("cntUsage", wt.DWORD),
        ("th32ProcessID", wt.DWORD),
        ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
        ("th32ModuleID", wt.DWORD),
        ("cntThreads", wt.DWORD),
        ("th32ParentProcessID", wt.DWORD),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", wt.DWORD),
        ("szExeFile", ctypes.c_char * 260),
    ]


def ancestor_chain(max_depth: int = 15) -> tuple:
    """Walk this process's parent chain via a toolhelp snapshot.

    Returns (pids, exe_names) so the broker can tell VS Code terminals
    apart from the Claude desktop app.
    """
    try:
        kernel32 = ctypes.windll.kernel32
        snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
        if snapshot == -1:
            return [], []
        parents = {}
        names = {}
        entry = PROCESSENTRY32()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32)
        if kernel32.Process32First(snapshot, ctypes.byref(entry)):
            while True:
                parents[entry.th32ProcessID] = entry.th32ParentProcessID
                names[entry.th32ProcessID] = entry.szExeFile.decode(
                    "utf-8", errors="ignore"
                ).lower()
                if not kernel32.Process32Next(snapshot, ctypes.byref(entry)):
                    break
        kernel32.CloseHandle(snapshot)

        pids = []
        exe_names = []
        pid = os.getpid()
        for _ in range(max_depth):
            pids.append(pid)
            exe_names.append(names.get(pid, ""))
            parent = parents.get(pid)
            if not parent or parent == pid:
                break
            pid = parent
        return pids, exe_names
    except Exception:
        return [], []


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return
    pids, exe_names = ancestor_chain()
    payload["ancestry"] = pids
    payload["ancestry_names"] = exe_names
    try:
        req = urllib.request.Request(
            BROKER_URL,
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=2)
    except Exception:
        pass


if __name__ == "__main__":
    main()
