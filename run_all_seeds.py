"""
Runs every seed script in the correct dependency order, with progress output
and a final pass/fail summary — designed to kick off from a phone terminal
(Render shell, Termux, Colab, etc.) and walk away from.

Does NOT stop on the first failure. Rationale: `seed_vulgate.py` might fail
because you haven't picked a mirror yet, but that shouldn't block `seed_strongs.py`
from running — they're independent. Steps that genuinely depend on an earlier
step (Hebrew/Greek/Vulgate/TSK all need `verses` populated by KJV first) will
naturally fail with a clear "table is empty" error if their dependency didn't
run — that's real information, not something to hide by aborting early.

Usage:
  python run_all_seeds.py                # run everything, in order
  python run_all_seeds.py --only kjv bdb  # run just these steps
  python run_all_seeds.py --skip vulgate  # run everything except these
  python run_all_seeds.py --list          # show step names and exit

Requires the same environment as the individual scripts: SUPABASE_URL and
SUPABASE_SERVICE_ROLE_KEY (via env vars or .env).
"""
import argparse
import importlib
import sys
import time
import traceback

# (step_id, module_name, human description) — order is the real run order.
STEPS = [
    ("books", "seed_books", "66-book canon"),
    ("kjv", "seed_kjv", "KJV text + canonical verses"),
    ("hebrew", "seed_hebrew_leningrad", "Hebrew Leningrad Codex (OSHB)"),
    ("greek", "seed_greek_sblgnt", "Greek SBLGNT"),
    ("vulgate", "seed_vulgate", "Latin Vulgate"),
    ("strongs", "seed_strongs", "Strong's Hebrew + Greek"),
    ("bdb", "seed_bdb", "Brown-Driver-Briggs (linked to Strong's)"),
    ("tsk", "seed_tsk_crossrefs", "Treasury of Scripture Knowledge cross-refs"),
    ("commentaries", "seed_commentaries", "Public-domain commentaries + overview context cards"),
    ("map_locations", "seed_map_locations", "Biblical place coordinates (Pleiades)"),
    ("journeys", "seed_journeys", "Paul's missionary journeys + stops"),
]


def run_step(step_id, module_name, description):
    print(f"\n{'=' * 60}")
    print(f"▶ {step_id}: {description}")
    print(f"{'=' * 60}")
    start = time.time()
    try:
        module = importlib.import_module(module_name)
        module.run()
        elapsed = time.time() - start
        print(f"✅ {step_id} completed in {elapsed:.1f}s")
        return {"step": step_id, "status": "ok", "elapsed": elapsed, "error": None}
    except Exception as e:
        elapsed = time.time() - start
        print(f"❌ {step_id} FAILED after {elapsed:.1f}s: {e}")
        traceback.print_exc()
        return {"step": step_id, "status": "failed", "elapsed": elapsed, "error": str(e)}


def main():
    parser = argparse.ArgumentParser(description="Run Exegia seed scripts in order.")
    parser.add_argument("--only", nargs="+", help="Run only these step ids")
    parser.add_argument("--skip", nargs="+", help="Skip these step ids")
    parser.add_argument("--list", action="store_true", help="List step ids and exit")
    args = parser.parse_args()

    if args.list:
        for step_id, _, description in STEPS:
            print(f"  {step_id:10s} — {description}")
        return

    steps_to_run = STEPS
    if args.only:
        wanted = set(args.only)
        steps_to_run = [s for s in STEPS if s[0] in wanted]
        unknown = wanted - {s[0] for s in STEPS}
        if unknown:
            print(f"WARN unknown step ids ignored: {unknown}")
    if args.skip:
        skip_set = set(args.skip)
        steps_to_run = [s for s in steps_to_run if s[0] not in skip_set]

    if not steps_to_run:
        print("Nothing to run.")
        return

    print(f"Running {len(steps_to_run)} step(s): {[s[0] for s in steps_to_run]}")
    overall_start = time.time()
    results = [run_step(*step) for step in steps_to_run]
    overall_elapsed = time.time() - overall_start

    print(f"\n{'=' * 60}")
    print("SUMMARY")
    print(f"{'=' * 60}")
    for r in results:
        icon = "✅" if r["status"] == "ok" else "❌"
        print(f"  {icon} {r['step']:10s} {r['elapsed']:6.1f}s  {r['error'] or ''}")

    ok_count = sum(1 for r in results if r["status"] == "ok")
    fail_count = len(results) - ok_count
    print(f"\n{ok_count}/{len(results)} steps succeeded, {fail_count} failed. "
          f"Total time: {overall_elapsed:.1f}s")

    if fail_count:
        print("\nRe-run just the failed steps once fixed, e.g.:")
        failed_ids = [r["step"] for r in results if r["status"] == "failed"]
        print(f"  python run_all_seeds.py --only {' '.join(failed_ids)}")
        sys.exit(1)


if __name__ == "__main__":
    main()
