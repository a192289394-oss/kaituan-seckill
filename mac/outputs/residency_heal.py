"""Whitelist self-heal for 7x24 residency. Never logs in, never business-submits."""
from __future__ import annotations
import os
import re
import shlex
import subprocess
import time

import android_runtime

BUSINESS_PACKAGE = "com.bytedance.ls.merchant"
NATIVE_HELPER = "kaituan-frida-server"
HELPER_BIN = "/data/local/tmp/kaituan-frida-server"
HELPER_LISTEN = "127.0.0.1:27042"
PLAYER = "/Applications/BlueStacks.app/Contents/MacOS/BlueStacks"

# Soft dismiss labels only; never "同意"/login/update-now.
_DISMISS_LABELS = ("稍后", "以后再说", "取消", "关闭", "暂不", "Not Now", "Later", "Cancel", "Close")


def _run(args, timeout=15):
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return None
    except OSError:
        return None


def _su(adb, serial, cmd, timeout=15):
    """Run su -c <cmd> via one adb shell string so arguments stay intact."""
    return _run([adb, "-s", serial, "shell", "su -c " + shlex.quote(cmd)], timeout=timeout)


def _shell(adb, serial, cmd, timeout=15):
    return _run([adb, "-s", serial, "shell", cmd], timeout=timeout)


def dismiss_bluestacks_blockers():
    """Click whitelist Close/Later on BlueStacks windows; never Update/Agree."""
    labels = ", ".join('"' + x + '"' for x in _DISMISS_LABELS)
    script = f'''
    set dismissLabels to {{{labels}}}
    tell application "System Events"
      set procs to (every process whose name contains "BlueStacks")
      if procs is {{}} then return "no_process"
      repeat with p in procs
        try
          set frontmost of p to true
          repeat with w in windows of p
            repeat with label in dismissLabels
              try
                click (first button of w whose name is label)
                return "clicked:" & label
              end try
              try
                click (first button of w whose description is label)
                return "clicked_desc:" & label
              end try
            end repeat
          end repeat
        end try
      end repeat
    end tell
    return "no_match"
    '''
    result = _run(["osascript", "-e", script], timeout=20)
    if result is None:
        return {"ok": False, "detail": "osascript_timeout"}
    text = (result.stdout or "").strip() or (result.stderr or "").strip()
    if result.returncode != 0:
        return {"ok": False, "detail": "osascript_failed:" + text[:120]}
    if text.startswith("clicked"):
        return {"ok": True, "detail": text}
    return {"ok": False, "detail": text or "no_match"}


def ensure_bluestacks_adb(cfg, adb):
    """Reconnect + optional autostart via existing android_runtime.probe."""
    try:
        result = android_runtime.probe(cfg, adb, allow_launch=True)
    except (subprocess.TimeoutExpired, OSError, ValueError) as exc:
        return {"ok": False, "detail": type(exc).__name__}
    state = (getattr(result, "stdout", "") or "").strip()
    if getattr(result, "returncode", 1) == 0 and state == "device":
        return {"ok": True, "detail": "adb_device"}
    # One dismiss pass then reconnect once.
    dismiss_bluestacks_blockers()
    time.sleep(2)
    try:
        result = android_runtime.probe(cfg, adb, allow_launch=True)
    except (subprocess.TimeoutExpired, OSError, ValueError) as exc:
        return {"ok": False, "detail": type(exc).__name__}
    state = (getattr(result, "stdout", "") or "").strip()
    if getattr(result, "returncode", 1) == 0 and state == "device":
        return {"ok": True, "detail": "adb_device_after_dismiss"}
    return {"ok": False, "detail": "adb_not_device"}


def wait_boot(adb, serial, seconds=45):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        r = _run([adb, "-s", serial, "shell", "getprop", "sys.boot_completed"], timeout=5)
        if r and r.returncode == 0 and (r.stdout or "").strip() == "1":
            return True
        time.sleep(2)
    return False


def ensure_frida(adb, serial):
    """Start installed kaituan-frida-server only; never push/replace binary."""
    check = _su(adb, serial, "pidof " + NATIVE_HELPER, timeout=8)
    pids = (check.stdout or "").split() if check and check.returncode == 0 else []
    if len(pids) == 1 and pids[0].isdigit():
        return {"ok": True, "detail": "already_running"}
    if len(pids) > 1:
        return {"ok": False, "detail": "helper_not_unique"}
    # Daemonize; ADB may time out while process stays up.
    _su(adb, serial, HELPER_BIN + " -D -l " + HELPER_LISTEN, timeout=8)
    time.sleep(1)
    check = _su(adb, serial, "pidof " + NATIVE_HELPER, timeout=8)
    pids = (check.stdout or "").split() if check and check.returncode == 0 else []
    if len(pids) == 1 and pids[0].isdigit():
        return {"ok": True, "detail": "started:" + pids[0]}
    return {"ok": False, "detail": "helper_start_failed"}


def ensure_merchant_process(adb, serial, foreground=False):
    """Cold-start or bring 来客 to foreground. Never force-stop, clear data, or login."""
    check = _shell(adb, serial, "pidof " + BUSINESS_PACKAGE, timeout=8)
    pids = (check.stdout or "").split() if check and check.returncode == 0 else []
    if len(pids) > 1:
        return {"ok": False, "detail": "process_not_unique"}
    need_start = not pids or foreground
    if need_start:
        brief = _shell(
            adb, serial,
            "cmd package resolve-activity --brief " + BUSINESS_PACKAGE,
            timeout=10,
        )
        if not brief or brief.returncode != 0:
            return {"ok": False, "detail": "resolve_activity_failed"}
        lines = [ln.strip() for ln in (brief.stdout or "").splitlines() if ln.strip()]
        component = lines[-1] if lines else ""
        if "/" not in component:
            return {"ok": False, "detail": "no_launcher_component"}
        start = _shell(adb, serial, "am start -W -n " + component, timeout=25)
        if start is None:
            return {"ok": False, "detail": "am_start_timeout"}
        time.sleep(1)
    check = _shell(adb, serial, "pidof " + BUSINESS_PACKAGE, timeout=8)
    pids = (check.stdout or "").split() if check and check.returncode == 0 else []
    if len(pids) == 1 and pids[0].isdigit():
        return {"ok": True, "detail": ("foregrounded:" if foreground else "running:") + pids[0]}
    return {"ok": False, "detail": "process_absent_after_start"}


def plan_actions(blocking, warnings=None):
    """Ordered whitelist actions from residency blocking codes."""
    blocking = list(blocking or [])
    warnings = list(warnings or [])
    actions = []
    if any(c in blocking for c in ("adb_not_device", "adb_timeout", "boot_incomplete", "boot_probe_timeout")):
        actions.append("ensure_bluestacks_adb")
    if "helper_process_absent_or_ambiguous" in blocking or "helper_probe_timeout" in blocking:
        actions.append("ensure_frida")
    if any(c in blocking for c in ("process_absent", "app_not_running", "app_probe_timeout")):
        actions.append("ensure_merchant")
    if "app_not_foreground" in warnings:
        actions.append("foreground_merchant")
    # Dedupe preserve order
    seen = set()
    out = []
    for a in actions:
        if a not in seen:
            seen.add(a)
            out.append(a)
    return out


def run_heal(cfg, adb, actions):
    """Execute whitelist actions. Returns heal_last dict."""
    serial = cfg.get("serial") or (cfg.get("android_device") or {}).get("adb_endpoint")
    started = time.time()
    details = []
    ok_all = True
    if not actions:
        return {"at": started, "action": "none", "ok": True, "reason": "nothing_to_heal"}
    for action in actions:
        if action == "ensure_bluestacks_adb":
            r = ensure_bluestacks_adb(cfg, adb)
            details.append("bluestacks:" + r["detail"])
            if r["ok"]:
                wait_boot(adb, serial, seconds=40)
            else:
                ok_all = False
                break
        elif action == "ensure_frida":
            r = ensure_frida(adb, serial)
            details.append("frida:" + r["detail"])
            if not r["ok"]:
                ok_all = False
                break
        elif action == "ensure_merchant":
            r = ensure_merchant_process(adb, serial, foreground=False)
            details.append("merchant:" + r["detail"])
            if not r["ok"]:
                ok_all = False
                break
        elif action == "foreground_merchant":
            r = ensure_merchant_process(adb, serial, foreground=True)
            details.append("foreground:" + r["detail"])
            # Soft: failure does not force ok_all False for write_ready
            if not r["ok"]:
                details.append("foreground_soft_fail")
        else:
            details.append("skipped:" + action)
            ok_all = False
            break
    return {
        "at": started,
        "action": "+".join(actions),
        "ok": bool(ok_all),
        "reason": ";".join(details)[:240],
    }
