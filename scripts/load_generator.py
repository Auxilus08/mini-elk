#!/usr/bin/env python3
"""Demo / scenario controller.

Writes a ScenarioState JSON document to the shared scenario file. All running
services pick up the change within ~1 second through their ScenarioWatcher.

Examples
--------
    python scripts/load_generator.py --scenario spike
    python scripts/load_generator.py --scenario storm
    python scripts/load_generator.py --scenario silence
    python scripts/load_generator.py --scenario chaos --duration 120
    python scripts/load_generator.py --scenario normal
    python scripts/load_generator.py --list
    python scripts/load_generator.py --status
    python scripts/load_generator.py --watch
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

import yaml


# ----------------------------------------------------------------------
# Optional rich support — degrade gracefully when missing.
# ----------------------------------------------------------------------
try:
    from rich.console import Console
    from rich.table import Table
    _console = Console()
    _RICH = True
except Exception:  # noqa: BLE001
    _console = None
    _RICH = False


SCENARIO_COLOURS = {
    "normal":  "green",
    "spike":   "yellow",
    "storm":   "red",
    "silence": "blue",
    "chaos":   "magenta",
}


def _print(msg: str, *, style: Optional[str] = None) -> None:
    if _RICH and _console is not None:
        _console.print(msg, style=style or "")
    else:
        print(msg)


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + \
        f"{datetime.now(timezone.utc).microsecond // 1000:03d}Z"


# ----------------------------------------------------------------------
# Profile / scenario file resolution
# ----------------------------------------------------------------------
def _find_repo_root(start: Path) -> Path:
    """Walk upward looking for sim_profiles.yaml."""
    cur = start.resolve()
    for parent in (cur, *cur.parents):
        if (parent / "sim_profiles.yaml").exists():
            return parent
    return start.resolve()


def load_profiles(profiles_path: Path) -> Dict[str, Any]:
    with profiles_path.open("r") as fh:
        return yaml.safe_load(fh)


def resolve_scenario_file(profiles: Dict[str, Any], override: Optional[str]) -> Path:
    if override:
        return Path(override)
    runtime = profiles.get("runtime", {}) or {}
    declared = runtime.get("scenario_state_file")
    # Inside the container this is /shared/scenario.json. On the host the bind
    # mount lives under ./shared-state/. Map automatically when running locally.
    if declared and declared.startswith("/shared"):
        local = Path("shared-state") / Path(declared).name
        if local.parent.exists():
            return local
    if declared:
        return Path(declared)
    return Path("shared-state/scenario.json")


# ----------------------------------------------------------------------
# Scenario building
# ----------------------------------------------------------------------
def build_state(scenario_name: str, profiles: Dict[str, Any], *, duration: Optional[int]) -> Dict[str, Any]:
    scenarios = profiles.get("scenarios", {}) or {}
    if scenario_name not in scenarios:
        raise SystemExit(f"unknown scenario {scenario_name!r}; available: {sorted(scenarios)}")
    sc = scenarios[scenario_name] or {}

    target = sc.get("service") or sc.get("services")
    inject = sc.get("inject")
    rps_multiplier = float(sc.get("rps_multiplier", 1.0))
    declared_duration = sc.get("duration_s")

    state = {
        "name": scenario_name,
        "target_service": target,
        "inject": inject,
        "rps_multiplier": rps_multiplier,
        "started_at": _now_iso(),
        "duration_s": int(duration) if duration is not None else (
            int(declared_duration) if declared_duration is not None else None
        ),
    }
    return state


def _atomic_write(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2))
    os.replace(tmp, path)


# ----------------------------------------------------------------------
# Commands
# ----------------------------------------------------------------------
def cmd_set(args: argparse.Namespace, profiles: Dict[str, Any], scenario_file: Path) -> None:
    state = build_state(args.scenario, profiles, duration=args.duration)
    _atomic_write(scenario_file, state)
    colour = SCENARIO_COLOURS.get(args.scenario, "white")
    _print(f"→ scenario set to [{colour}]{args.scenario}[/{colour}] (file: {scenario_file})",
           style=None)
    if state["target_service"]:
        _print(f"  target: {state['target_service']}    inject: {state['inject']}")
    # Only countdown-and-revert when the *user* asked for a duration. A
    # YAML-declared duration is exposed to services via state.duration_s but the
    # CLI shouldn't block on it (chaos defaults to 300s — that would hang).
    if args.duration is not None:
        _print(f"  duration: {args.duration}s — will revert to 'normal' automatically")
        _countdown_revert(args.duration, profiles, scenario_file)
    elif state["duration_s"]:
        _print(f"  declared duration: {state['duration_s']}s (services will time out injection)")


def _countdown_revert(seconds: int, profiles: Dict[str, Any], scenario_file: Path) -> None:
    end = time.time() + seconds
    try:
        while True:
            remaining = int(end - time.time())
            if remaining <= 0:
                break
            sys.stdout.write(f"\r  reverting in {remaining:>4d}s ...")
            sys.stdout.flush()
            time.sleep(1)
    except KeyboardInterrupt:
        sys.stdout.write("\n  interrupted — leaving scenario active\n")
        return
    sys.stdout.write("\n")
    state = build_state("normal", profiles, duration=None)
    _atomic_write(scenario_file, state)
    _print("→ reverted to [green]normal[/green]")


def cmd_list(profiles: Dict[str, Any]) -> None:
    scenarios = profiles.get("scenarios", {}) or {}
    if _RICH and _console is not None:
        table = Table(title="Available scenarios", show_lines=False, header_style="bold")
        table.add_column("name")
        table.add_column("target")
        table.add_column("inject")
        table.add_column("notes")
        for name, sc in scenarios.items():
            colour = SCENARIO_COLOURS.get(name, "white")
            sc = sc or {}
            target = sc.get("service") or sc.get("services") or "—"
            inject = sc.get("inject") or "—"
            notes_parts = []
            if "rps_multiplier" in sc:
                notes_parts.append(f"rps×{sc['rps_multiplier']}")
            if "duration_s" in sc:
                notes_parts.append(f"{sc['duration_s']}s")
            notes = ", ".join(notes_parts) or "—"
            table.add_row(f"[{colour}]{name}[/{colour}]", str(target), str(inject), notes)
        _console.print(table)
    else:
        for name, sc in scenarios.items():
            sc = sc or {}
            target = sc.get("service") or sc.get("services") or "-"
            inject = sc.get("inject") or "-"
            print(f"{name:10s}  target={target:15s}  inject={inject}")


def cmd_status(scenario_file: Path) -> None:
    if not scenario_file.exists():
        _print(f"no scenario file at {scenario_file} — nothing active (default 'normal')",
               style="dim")
        return
    try:
        data = json.loads(scenario_file.read_text())
    except json.JSONDecodeError as exc:
        _print(f"scenario file unreadable: {exc}", style="red")
        return
    name = data.get("name", "unknown")
    colour = SCENARIO_COLOURS.get(name, "white")
    started = data.get("started_at", "?")
    age = _age_seconds(started)
    age_str = f"{age:.0f}s" if age is not None else "?"
    _print(f"active scenario: [{colour}]{name}[/{colour}]  started_at={started}  age={age_str}")
    if data.get("target_service"):
        _print(f"  target={data['target_service']} inject={data.get('inject')}")
    if data.get("duration_s"):
        _print(f"  declared duration: {data['duration_s']}s")


def _age_seconds(started_at: str) -> Optional[float]:
    try:
        s = started_at.replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    return (datetime.now(timezone.utc) - dt).total_seconds()


def cmd_watch(scenario_file: Path) -> None:
    _print(f"watching {scenario_file} — Ctrl-C to stop", style="dim")
    last_mtime: Optional[float] = None
    last_name: Optional[str] = None
    try:
        while True:
            try:
                mtime = scenario_file.stat().st_mtime
            except FileNotFoundError:
                if last_name is not None:
                    _print("scenario file removed", style="dim")
                    last_name = None
                time.sleep(0.5)
                continue
            if mtime != last_mtime:
                last_mtime = mtime
                try:
                    data = json.loads(scenario_file.read_text())
                except json.JSONDecodeError:
                    time.sleep(0.2)
                    continue
                name = data.get("name", "?")
                if name != last_name:
                    colour = SCENARIO_COLOURS.get(name, "white")
                    ts = datetime.now().strftime("%H:%M:%S")
                    _print(f"[dim]{ts}[/dim]  → [{colour}]{name}[/{colour}]"
                           f"  target={data.get('target_service') or '—'}"
                           f"  inject={data.get('inject') or '—'}")
                    last_name = name
            time.sleep(0.5)
    except KeyboardInterrupt:
        sys.stdout.write("\n")


# ----------------------------------------------------------------------
# Entry point
# ----------------------------------------------------------------------
def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="mini-elk demo scenario controller")
    p.add_argument("--scenario", help="scenario name from sim_profiles.yaml (e.g. spike, storm, silence, chaos, normal)")
    p.add_argument("--duration", type=int, default=None,
                   help="seconds to keep the scenario active before reverting to 'normal'")
    p.add_argument("--list", action="store_true", help="list available scenarios")
    p.add_argument("--status", action="store_true", help="print currently active scenario")
    p.add_argument("--watch", action="store_true", help="tail scenario file changes")
    p.add_argument("--profiles", default=None, help="path to sim_profiles.yaml (auto-detected by default)")
    p.add_argument("--scenario-file", default=None, help="override scenario state file path")
    return p.parse_args()


def main() -> None:
    args = parse_args()

    repo_root = _find_repo_root(Path.cwd())
    profiles_path = Path(args.profiles) if args.profiles else (repo_root / "sim_profiles.yaml")
    if not profiles_path.exists():
        raise SystemExit(f"sim_profiles.yaml not found at {profiles_path}")
    profiles = load_profiles(profiles_path)
    scenario_file = resolve_scenario_file(profiles, args.scenario_file)
    if not scenario_file.is_absolute():
        scenario_file = repo_root / scenario_file

    if args.list:
        cmd_list(profiles)
        return
    if args.status:
        cmd_status(scenario_file)
        return
    if args.watch:
        cmd_watch(scenario_file)
        return
    if args.scenario:
        cmd_set(args, profiles, scenario_file)
        return

    raise SystemExit("nothing to do — pass --scenario, --list, --status, or --watch")


if __name__ == "__main__":
    main()
