"""Windows process-tree helpers (toolhelp snapshot via ctypes, no deps)."""

import ctypes
import ctypes.wintypes as wt

TH32CS_SNAPPROCESS = 0x00000002


class _PROCESSENTRY32(ctypes.Structure):
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


def _snapshot() -> list[tuple[int, int, str]]:
    """Return (pid, ppid, exe_name_lower) for every running process."""
    out: list[tuple[int, int, str]] = []
    kernel32 = ctypes.windll.kernel32
    snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snap == -1:
        return out
    entry = _PROCESSENTRY32()
    entry.dwSize = ctypes.sizeof(_PROCESSENTRY32)
    if kernel32.Process32First(snap, ctypes.byref(entry)):
        while True:
            name = entry.szExeFile.decode("utf-8", errors="ignore").lower()
            out.append((entry.th32ProcessID, entry.th32ParentProcessID, name))
            if not kernel32.Process32Next(snap, ctypes.byref(entry)):
                break
    kernel32.CloseHandle(snap)
    return out


def has_descendant_named(root_pid: int, name_substrings: tuple[str, ...]) -> bool:
    """True if any descendant process of root_pid has a matching exe name."""
    procs = _snapshot()
    children: dict[int, list[tuple[int, str]]] = {}
    for pid, ppid, name in procs:
        children.setdefault(ppid, []).append((pid, name))

    stack = [root_pid]
    seen = set()
    while stack:
        cur = stack.pop()
        for pid, name in children.get(cur, []):
            if pid in seen:
                continue
            seen.add(pid)
            if any(sub in name for sub in name_substrings):
                return True
            stack.append(pid)
    return False
