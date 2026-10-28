"""
Run the domestic cups pipeline (EFL Cup, Coppa Italia, DFB Pokal, Copa del
Rey, Coupe de France) end to end: Opta -> WhoScored -> FotMob -> identity.

Only the two scrapers are cup-specific copies (scripts/cups/opta,
scripts/cups/whoscored). Everything else is the domestic script, run
unchanged, because those are already competition-agnostic:
  - scripts/opta/opta_json_to_csv.py
  - scripts/whoscored/parse_whoscored_jsons.py
  - scripts/fotmob/*.py
  - scripts/identity/{match_players_to_master,reconcile_new_players,build_player_legend}.py

Identity uses reference_data/player_id_map.csv READ-ONLY: cup players are
looked up in the map (so top-flight players are recognised by ID), but
update_player_id_map.py is never run for cups, so the map's league/team
labels are not touched. Lower-division players come through as new; that's
expected.

If a cup is missing a source (e.g. theanalyst.com has no page for it, or its
WhoScored stages aren't filled in yet), identity still runs on the sources
that exist: the missing one is replaced by an empty, header-only CSV, saved in
data/cups_missing_sources/<DATE>/ and listed in the output.

Run from the repo root:
    python scripts/cups/run_cups_pipeline.py --dry-run
    python scripts/cups/run_cups_pipeline.py
    python scripts/cups/run_cups_pipeline.py --steps fotmob,identity
    python scripts/cups/run_cups_pipeline.py --cups EFLCup,DFBPokal
    python scripts/cups/run_cups_pipeline.py --steps identity --date 2026-10-30

Steps: opta, whoscored, fotmob, identity (default: all four, in that order).
"""

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from cups_config import CUPS, SEASON, season_slug  # noqa: E402

PY = sys.executable
ALL_STEPS = ["opta", "whoscored", "fotmob", "identity"]
MASTER = "reference_data/master_player_table.csv"
ID_MAP = "reference_data/player_id_map.csv"


def run(cmd: list[str], dry: bool) -> bool:
    print("  $ " + " ".join(f'"{c}"' if " " in c else c for c in cmd))
    if dry:
        return True
    r = subprocess.run(cmd)
    if r.returncode != 0:
        print(f"  ✗ exited with code {r.returncode}")
        return False
    return True


def paths(date: str) -> dict:
    return {
        "opta_parsed": Path(f"data/opta/parsed/opta_parsed_cups_{date}"),
        "ws_raw": Path(f"data/whoscored/raw/whoscored_raw_json_cups_{date}"),
        "ws_parsed": Path(f"data/whoscored/parsed/parsed_whoscored_cups_{date}"),
        "fm_parsed": Path(f"data/fotmob/parsed/{date}"),
        "missing": Path(f"data/cups_missing_sources/{date}"),
    }


# ---------------------------------------------------------------- steps

def step_opta(cups, date, dry):
    print("\n=== Opta ===")
    have = [k for k in cups if CUPS[k].get("opta_tmcl") and CUPS[k].get("opta_url")]
    for k in cups:
        if k not in have:
            print(f"  – {k}: no tmcl in cups_config.py yet, skipped")
    if not have:
        return
    raw = Path(f"data/opta/raw/opta_raw_cups_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
    p = paths(date)
    ok = run([PY, str(HERE / "opta/grab_data_from_opta_api_cups.py"), str(raw), "--cups", ",".join(have)], dry)
    if not ok:
        return
    ok = run([PY, "scripts/opta/opta_json_to_csv.py", str(raw), str(p["opta_parsed"])], dry)
    if ok and not dry:
        record_opta_files(raw, p["opta_parsed"])


def record_opta_files(raw_dir: Path, parsed_dir: Path):
    """
    The Opta parser names its CSV after the competition name inside the JSON
    (which we don't know in advance for cups). Record which CSV belongs to
    which cup key, so the identity step can find it.
    """
    mapping_path = parsed_dir / "cup_files.json"
    mapping = json.loads(mapping_path.read_text()) if mapping_path.exists() else {}
    for f in raw_dir.glob("*_stats.json"):
        key = f.name[: -len("_stats.json")]
        data = json.loads(f.read_text())
        if "player" not in data:
            continue
        name = f"{data['player']['league']}_{data['player']['lastUpdated']}_merged_df_clean.csv"
        if (parsed_dir / name).exists():
            mapping[key] = name
    mapping_path.write_text(json.dumps(mapping, indent=2))
    print(f"  Recorded cup → Opta file mapping in {mapping_path}")


def step_whoscored(cups, date, dry):
    print("\n=== WhoScored ===")
    have = [k for k in cups if CUPS[k].get("whoscored_stages") and CUPS[k].get("whoscored_page_url")]
    for k in cups:
        if k not in have:
            print(f"  – {k}: no stages in cups_config.py yet, skipped")
    if not have:
        return
    p = paths(date)
    ok = run([PY, str(HERE / "whoscored/whoscored_scrape_cups.py"), str(p["ws_raw"]), "--cups", ",".join(have)], dry)
    if ok:
        run([PY, "scripts/whoscored/parse_whoscored_jsons.py", str(p["ws_raw"]), str(p["ws_parsed"])], dry)


def step_fotmob(cups, date, dry):
    print("\n=== FotMob ===")
    slug = season_slug()
    for k in cups:
        cup = CUPS[k]
        key = f"{cup['fotmob_key']}_{slug}"
        print(f"\n-- {k} ({cup['fotmob_name']}, {key})")
        if not run([PY, "scripts/fotmob/fotmob_fetch_fixtures.py", cup["fotmob_name"], SEASON], dry):
            continue
        if not run([PY, "scripts/fotmob/fotmob_scrape_match_details.py", f"{key}_fixtures.json",
                    f"data/fotmob/raw/{key}", cup["fotmob_name"]], dry):
            continue
        run([PY, "scripts/fotmob/fotmob_json_to_csv.py", f"data/fotmob/raw/{key}"], dry)


# ---------------------------------------------------------------- identity

def _latest(pattern: str, exclude: str = "cups") -> Path | None:
    hits = sorted((p for p in Path(".").glob(pattern) if exclude not in str(p)), key=lambda p: p.stat().st_mtime)
    return hits[-1] if hits else None


def empty_like(source: str, cup_key: str, date: str) -> Path | None:
    """Header-only CSV for a missing source, copied from the latest domestic file of that source."""
    template = {
        "opta": _latest("data/opta/parsed/opta_parsed_*/*_merged_df_clean.csv"),
        "whoscored": _latest("data/whoscored/parsed/parsed_whoscored_*/*_player_meta.csv"),
        "fotmob": _latest("data/fotmob/parsed/*/*/player_stats.csv"),
    }[source]
    if template is None:
        return None
    out = paths(date)["missing"] / f"{cup_key}_{source}_EMPTY.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(template, encoding="utf-8") as f:
        header = f.readline()
    out.write_text(header, encoding="utf-8")
    return out


def find_sources(cup_key: str, date: str) -> dict:
    p = paths(date)
    cup = CUPS[cup_key]
    found = {}

    mapping_path = p["opta_parsed"] / "cup_files.json"
    if mapping_path.exists():
        name = json.loads(mapping_path.read_text()).get(cup_key)
        if name and (p["opta_parsed"] / name).exists():
            found["opta"] = p["opta_parsed"] / name

    ws = sorted(p["ws_parsed"].glob(f"{cup_key}_*_player_meta.csv"))
    if ws:
        found["whoscored"] = ws[-1]

    fm = p["fm_parsed"] / f"{cup['fotmob_key']}_{season_slug()}" / "player_stats.csv"
    if fm.exists():
        found["fotmob"] = fm
    return found


def step_identity(cups, date, dry):
    print("\n=== Identity (player_id_map.csv read-only) ===")
    summary = {}
    for k in cups:
        cup = CUPS[k]
        print(f"\n-- {k}")
        found = find_sources(k, date)
        if not found and not dry:
            print("  ✗ no source data found for this date, skipped")
            summary[k] = "skipped (no data)"
            continue

        files, missing = {}, []
        for source in ("opta", "whoscored", "fotmob"):
            if source in found:
                files[source] = found[source]
            elif dry:
                files[source] = Path(f"<{source} file for {k}>")
            else:
                placeholder = empty_like(source, k, date)
                if placeholder is None:
                    print(f"  ✗ no {source} data and no domestic file to copy headers from; skipped")
                    break
                files[source] = placeholder
                missing.append(source)
        else:
            if missing:
                print(f"  ⚠️  no {', '.join(missing)} data: running on the other source(s) with an empty placeholder")
            other = f"reference_data/other_league_teams_for_{cup['domestic_league']}.csv"
            id_map_args = ["--id-map", ID_MAP] if Path(ID_MAP).exists() or dry else []
            if not id_map_args:
                print(f"  ⚠️  {ID_MAP} not found; running without the ID map")
            crosswalk, reconciled, legend = (f"crosswalk_{k}_{date}.csv", f"reconciled_{k}_{date}.csv",
                                             f"legend_{k}_{date}.csv")
            src = [str(files["opta"]), str(files["whoscored"]), str(files["fotmob"])]
            ok = (run([PY, "scripts/identity/match_players_to_master.py", MASTER, *src, crosswalk, other,
                       *id_map_args], dry)
                  and run([PY, "scripts/identity/reconcile_new_players.py", MASTER, *src, reconciled, other,
                           *id_map_args], dry)
                  and run([PY, "scripts/identity/build_player_legend.py", crosswalk, reconciled, legend, MASTER],
                          dry))
            status = "planned (dry run)" if dry else ("ok" if ok else "failed")
            summary[k] = status + (f" (no {', '.join(missing)})" if missing else "")

    if summary:
        print("\nIdentity summary:")
        for k, s in summary.items():
            print(f"  {k}: {s}")


# ---------------------------------------------------------------- main

def main(argv=None):
    ap = argparse.ArgumentParser(description="Domestic cups pipeline")
    ap.add_argument("--steps", default=",".join(ALL_STEPS), help="comma list of: " + ",".join(ALL_STEPS))
    ap.add_argument("--cups", default=",".join(CUPS), help="comma list of: " + ",".join(CUPS))
    ap.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"),
                    help="date folder to read/write (default: today)")
    ap.add_argument("--dry-run", action="store_true", help="print the plan and commands without running anything")
    a = ap.parse_args(argv)

    steps = [s.strip() for s in a.steps.split(",") if s.strip()]
    cups = [c.strip() for c in a.cups.split(",") if c.strip()]
    bad = [s for s in steps if s not in ALL_STEPS] + [c for c in cups if c not in CUPS]
    if bad:
        ap.error(f"unknown step/cup: {', '.join(bad)}")

    print(f"Cups pipeline — date {a.date}, season {SEASON}")
    print(f"  steps: {', '.join(steps)}")
    print(f"  cups:  {', '.join(cups)}")
    if a.dry_run:
        print("  (dry run: nothing will be executed)")
        print("\nConfig status:")
        for k in cups:
            c = CUPS[k]
            print(f"  {k:14} FotMob {c['fotmob_key']:8} | Opta {'✓' if c['opta_tmcl'] else '— not set'} | "
                  f"WhoScored {str(len(c['whoscored_stages'])) + ' stage(s)' if c['whoscored_stages'] else '— not set'}")

    for step in ALL_STEPS:
        if step in steps:
            {"opta": step_opta, "whoscored": step_whoscored, "fotmob": step_fotmob,
             "identity": step_identity}[step](cups, a.date, a.dry_run)

    print("\nDone. Cups never write to player_id_map.csv (read-only by design).")


if __name__ == "__main__":
    main()
