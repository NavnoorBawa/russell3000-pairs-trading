#!/usr/bin/env python3
"""
AUTOPILOT — Autonomous backtest monitor + improvement loop.
Waits for v9 to finish, analyzes results, auto-patches trading_system.py,
runs v10, analyzes, optionally runs v11. Writes full summary to overnight_results.txt.
No user input needed at any point.
"""

import subprocess
import time
import re
import os
import shutil
from datetime import datetime

BASE = "/Users/navnoorbawa/Downloads/Transformet Notion"
SYSTEM_PY = f"{BASE}/pairs_trading/trading_system.py"
SUMMARY_FILE = f"{BASE}/overnight_results.txt"
V9_PID = 29523
MAX_VERSIONS = 3   # run at most v9, v10, v11


def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    with open(SUMMARY_FILE, "a") as f:
        f.write(line + "\n")


def is_running(pid):
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def wait_for_completion(pid, log_file, version_label):
    """Wait for a PID to die, logging progress every 30 min."""
    log(f"Waiting for {version_label} (PID {pid}) to finish...")
    check_num = 0
    while is_running(pid):
        time.sleep(1800)   # 30 minutes
        check_num += 1
        if not is_running(pid):
            break
        # Progress snapshot — last meaningful log line
        try:
            result = subprocess.run(
                ["grep", "-v", "pair/s\|Backtesting:\|it/s\|▏\|▎\|▍\|▋\|▊\|▉\|█\|FIXED pair",
                 log_file],
                capture_output=True, text=True
            )
            lines = [l for l in result.stdout.strip().split("\n") if l.strip()]
            last = lines[-1] if lines else "(no output)"
            log(f"  [{version_label} check #{check_num}] {last}")
        except Exception:
            pass
    log(f"{version_label} process finished.")


# ─────────────────────────────────────────────────────────────────────────────
#  RESULT PARSER
# ─────────────────────────────────────────────────────────────────────────────

def parse_results(log_file):
    """Extract key metrics from a backtest log file."""
    try:
        with open(log_file, "r") as f:
            content = f.read()
    except FileNotFoundError:
        return {}

    res = {}

    # Main backtest
    m = re.search(r"Total Return[:\s]+([+-]?\d+\.?\d*)%", content)
    res["total_return"] = float(m.group(1)) if m else None

    m = re.search(r"Sharpe Ratio[:\s]+([+-]?\d+\.?\d*)", content)
    res["sharpe"] = float(m.group(1)) if m else None

    m = re.search(r"Max Drawdown[:\s]+([+-]?\d+\.?\d*)%", content)
    res["max_drawdown"] = float(m.group(1)) if m else None

    m = re.search(r"Total Trades[:\s]+(\d+)", content)
    res["total_trades"] = int(m.group(1)) if m else None

    m = re.search(r"Win Rate[:\s]+([+-]?\d+\.?\d*)%", content)
    res["win_rate"] = float(m.group(1)) if m else None

    m = re.search(r"Profit Factor[:\s]+([+-]?\d+\.?\d*)", content)
    res["profit_factor"] = float(m.group(1)) if m else None

    # Walk-forward summary
    m = re.search(r"Profitable windows[:\s]+(\d+)/(\d+)", content)
    if m:
        res["wf_profitable"] = int(m.group(1))
        res["wf_total"] = int(m.group(2))

    m = re.search(r"Avg Return[:\s]+([+-]?\d+\.?\d*)%", content)
    res["wf_avg_return"] = float(m.group(1)) if m else None

    m = re.search(r"Stitched[:\s]+([+-]?\d+\.?\d*)%", content)
    res["wf_stitched"] = float(m.group(1)) if m else None

    # Era split
    m = re.search(r"IS.*?avg\s+([+-]?\d+\.?\d*)%", content)
    res["is_avg"] = float(m.group(1)) if m else None

    m = re.search(r"OOS.*?avg\s+([+-]?\d+\.?\d*)%", content)
    res["oos_avg"] = float(m.group(1)) if m else None

    m = re.search(r"degradation[:\s]+([+-]?\d+\.?\d*)%", content)
    res["is_oos_degradation"] = float(m.group(1)) if m else None

    # Regime gate breakdown
    m = re.search(r"Regime gate summary[:\s]+(.+)", content)
    res["regime_gate"] = m.group(1) if m else None

    # Walk-forward window detail: extract last 10 windows (W10-W19 are OOS)
    window_pattern = re.compile(
        r"Window\s+(\d+).*?Return[:\s]+([+-]?\d+\.?\d*)%.*?WoI days[:\s]+(\d+)",
        re.DOTALL
    )
    windows = {}
    for m in window_pattern.finditer(content):
        windows[int(m.group(1))] = {
            "return": float(m.group(2)),
            "woi_days": int(m.group(3))
        }
    res["windows"] = windows

    # Also try simpler window pattern
    if not windows:
        simple = re.compile(r"Window\s+(\d+)[^:]*:\s+Return\s+([+-]?\d+\.?\d*)%")
        for m in simple.finditer(content):
            wn = int(m.group(1))
            if wn not in windows:
                windows[wn] = {"return": float(m.group(2)), "woi_days": 0}
        res["windows"] = windows

    # Errors
    res["has_error"] = "ERROR" in content or "Traceback" in content

    return res


def format_results(res, version):
    lines = [f"\n{'='*60}", f"  {version} RESULTS", f"{'='*60}"]
    if res.get("has_error"):
        lines.append("  *** ERRORS DETECTED IN LOG ***")
    lines.append(f"  Total Return:    {res.get('total_return', 'N/A')}%")
    lines.append(f"  Sharpe Ratio:    {res.get('sharpe', 'N/A')}")
    lines.append(f"  Max Drawdown:    {res.get('max_drawdown', 'N/A')}%")
    lines.append(f"  Total Trades:    {res.get('total_trades', 'N/A')}")
    lines.append(f"  Win Rate:        {res.get('win_rate', 'N/A')}%")
    lines.append(f"  Profit Factor:   {res.get('profit_factor', 'N/A')}")
    lines.append(f"  WF Profitable:   {res.get('wf_profitable', 'N/A')}/{res.get('wf_total', 'N/A')}")
    lines.append(f"  WF Avg Return:   {res.get('wf_avg_return', 'N/A')}%/qtr")
    lines.append(f"  WF Stitched:     {res.get('wf_stitched', 'N/A')}%")
    lines.append(f"  IS avg:          {res.get('is_avg', 'N/A')}%/qtr")
    lines.append(f"  OOS avg:         {res.get('oos_avg', 'N/A')}%/qtr")
    lines.append(f"  IS→OOS degrad:   {res.get('is_oos_degradation', 'N/A')}%")
    if res.get("regime_gate"):
        lines.append(f"  Regime gate:     {res['regime_gate']}")
    if res.get("windows"):
        lines.append("  Windows (OOS W10-W19):")
        for wn in sorted(res["windows"].keys()):
            if wn >= 10:
                w = res["windows"][wn]
                lines.append(f"    W{wn:02d}: {w['return']:+.2f}%   WoI={w.get('woi_days',0)}d")
    lines.append(f"{'='*60}\n")
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
#  DECISION ENGINE — what to change for next version
# ─────────────────────────────────────────────────────────────────────────────

def decide_improvements(res, current_version):
    """
    Returns list of (description, patch_fn) tuples.
    patch_fn takes the file content string and returns modified string.
    """
    changes = []

    if res.get("has_error") or res.get("total_return") is None:
        log("  Results incomplete or errored — skipping auto-improvement.")
        return []

    # Rule 1: Walking on Ice scale too weak
    # If ≥3 OOS windows (W10-W19) have WoI days AND are losing, tighten scale 0.60→0.40
    woi_losing_windows = [
        wn for wn, w in res.get("windows", {}).items()
        if wn >= 10 and w.get("woi_days", 0) >= 5 and w.get("return", 0) < 0
    ]
    current_woi_scale = _read_current_woi_scale()
    if len(woi_losing_windows) >= 2 and current_woi_scale > 0.35:
        new_scale = max(0.35, current_woi_scale - 0.20)
        changes.append((
            f"Reduce WoI scale {current_woi_scale:.2f}× → {new_scale:.2f}× "
            f"(WoI-and-losing windows: {woi_losing_windows})",
            lambda content, ns=new_scale, cs=current_woi_scale:
                content.replace(
                    f"_disp_scale = {cs:.2f}",
                    f"_disp_scale = {ns:.2f}"
                )
        ))

    # Rule 2: WoI threshold too permissive — if many windows fire with modest dispersion
    # Check if changing 1.2 → 1.0 would help (more windows caught)
    # Only apply if OOS avg is below 0%
    oos_avg = res.get("oos_avg", 0) or 0
    if oos_avg < 0.0 and current_version == "v10":
        changes.append((
            f"Tighten WoI cum_disp_z trigger 1.2 → 1.0σ (OOS avg {oos_avg:.2f}% < 0)",
            lambda content: content.replace(
                "_cur_dispz > 1.2",
                "_cur_dispz > 1.0"
            )
        ))

    # Rule 3: If OOS barely positive and IS very high — consider more aggressive 6m filter
    is_avg = res.get("is_avg", 0) or 0
    if is_avg > 10 and oos_avg < 1.0 and current_version == "v10":
        changes.append((
            f"Tighten 6m ADF p-threshold 0.15 → 0.10 (IS={is_avg:.1f}% but OOS={oos_avg:.2f}%)",
            lambda content: content.replace(
                "if p6 > 0.15:",
                "if p6 > 0.10:"
            ).replace(
                "p<0.15 is still",
                "p<0.10 is still"
            )
        ))

    return changes


def _read_current_woi_scale():
    """Read current Walking on Ice scale factor from trading_system.py."""
    try:
        with open(SYSTEM_PY, "r") as f:
            content = f.read()
        m = re.search(r"_disp_scale = (0\.\d+)\s*\n\s*else:\s*\n\s*_disp_scale = 1\.00", content)
        if m:
            return float(m.group(1))
        # fallback: find the WoI-specific line
        m = re.search(r"# Low VIX.*?Walking on Ice\s*\n\s*_disp_scale = (0\.\d+)", content)
        if m:
            return float(m.group(1))
    except Exception:
        pass
    return 0.60  # default


def apply_patches(patches, version_label):
    """Apply list of (description, patch_fn) to trading_system.py. Makes backup first."""
    if not patches:
        return False

    # Backup
    backup = f"{SYSTEM_PY}.backup_{version_label}"
    shutil.copy2(SYSTEM_PY, backup)
    log(f"  Backed up trading_system.py → {os.path.basename(backup)}")

    with open(SYSTEM_PY, "r") as f:
        content = f.read()

    for desc, patch_fn in patches:
        log(f"  Applying: {desc}")
        new_content = patch_fn(content)
        if new_content == content:
            log(f"    WARNING: patch had no effect (pattern not found) — {desc}")
        else:
            content = new_content
            log(f"    OK: patch applied")

    with open(SYSTEM_PY, "w") as f:
        f.write(content)

    return True


def launch_backtest(log_file):
    """Launch a new backtest in background, return PID."""
    cmd = f'cd "{BASE}" && nohup python -m pairs_trading.main > "{log_file}" 2>&1 &'
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    # PID is tricky to get from nohup — use pgrep
    time.sleep(3)
    result2 = subprocess.run(
        ["pgrep", "-f", "pairs_trading.main"],
        capture_output=True, text=True
    )
    pids = [int(p) for p in result2.stdout.strip().split("\n") if p.strip()]
    return max(pids) if pids else None


# ─────────────────────────────────────────────────────────────────────────────
#  MAIN LOOP
# ─────────────────────────────────────────────────────────────────────────────

def main():
    with open(SUMMARY_FILE, "w") as f:
        f.write(f"=== AUTOPILOT STARTED {datetime.now()} ===\n\n")

    log("AUTOPILOT STARTED — monitoring v9 then auto-improving")
    log(f"Watching PID {V9_PID}")

    results_history = {}
    versions = [
        ("v9", V9_PID, f"{BASE}/backtest_v9.log"),
    ]

    current_pid = V9_PID
    current_version = "v9"
    current_log = f"{BASE}/backtest_v9.log"

    for iteration in range(MAX_VERSIONS):
        # ── Step 1: Wait for current version to finish ───────────────────────
        wait_for_completion(current_pid, current_log, current_version)
        time.sleep(10)  # let file flush

        # ── Step 2: Parse results ─────────────────────────────────────────────
        log(f"Parsing {current_version} results from {os.path.basename(current_log)}...")
        res = parse_results(current_log)
        results_history[current_version] = res

        formatted = format_results(res, current_version)
        log(formatted)

        # ── Step 3: Check for errors ──────────────────────────────────────────
        if res.get("has_error"):
            log(f"ERROR detected in {current_version} log — checking if fatal...")
            # Check if results still exist (non-fatal error)
            if res.get("total_return") is None:
                log("Fatal: no Total Return found. Stopping autopilot.")
                break

        # ── Step 4: Decide if improvement is worthwhile ───────────────────────
        if iteration == MAX_VERSIONS - 1:
            log("Reached max versions — stopping.")
            break

        next_version = f"v{10 + iteration}"
        log(f"\nDeciding improvements for {next_version}...")
        patches = decide_improvements(res, current_version)

        if not patches:
            log("No further improvements identified — autopilot done.")
            break

        # ── Step 5: Apply patches ─────────────────────────────────────────────
        log(f"Applying {len(patches)} patch(es) for {next_version}:")
        applied = apply_patches(patches, current_version)
        if not applied:
            log("No patches applied — stopping.")
            break

        # ── Step 6: Launch next version ───────────────────────────────────────
        next_log = f"{BASE}/backtest_{next_version}.log"
        log(f"Launching {next_version}...")
        new_pid = launch_backtest(next_log)
        if not new_pid:
            log(f"Could not determine PID for {next_version} — stopping.")
            break

        log(f"{next_version} launched with PID {new_pid}")
        current_pid = new_pid
        current_version = next_version
        current_log = next_log
        time.sleep(5)

    # ── Final summary ──────────────────────────────────────────────────────────
    log("\n" + "="*60)
    log("AUTOPILOT COMPLETE — FINAL SUMMARY")
    log("="*60)
    for ver, res in results_history.items():
        ret = res.get("total_return", "N/A")
        sh = res.get("sharpe", "N/A")
        oos = res.get("oos_avg", "N/A")
        wfp = res.get("wf_profitable", "N/A")
        wft = res.get("wf_total", "N/A")
        log(f"  {ver}: Return={ret}%  Sharpe={sh}  OOS_avg={oos}%/qtr  WF={wfp}/{wft}")

    log(f"\nAll results saved to: {SUMMARY_FILE}")
    log("Wake up and say 'check now' — full analysis ready.")


if __name__ == "__main__":
    main()
