"""Command-line entry points.

    python -m app.cli seed
    python -m app.cli generate --month 2026-12 [--save]
    python -m app.cli validate --version 3
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter

from app.db import SessionLocal
from app.scheduling import generate, validate
from app.scheduling.types import Category, Severity
from app.services.engine_adapter import load_problem, load_roster, persist_outcome


def _print_report(problem, outcome_status, report, stats=None, lock_conflicts=()):
    names = {e.id: e.name for e in problem.employees}
    print(f"\nStatus: {outcome_status.value}")
    if stats:
        print(f"Solver: {stats.get('solve_status', '')} {stats.get('cp_sat_status', '')} "
              f"in {stats.get('wall_time_s', '?')}s  candidates={stats.get('num_candidates')}")
    for lc in lock_conflicts:
        print(f"  LOCK CONFLICT {names.get(lc.employee_id)} {lc.date}: {lc.reason}")
    if report is None:
        return
    print(f"Coverage: {report.coverage_pct}%  gaps={len(report.gaps)}  "
          f"hard rule violations={report.hard_rule_violations}")
    by_cat = Counter((i.category.value, i.type) for i in report.issues)
    for (cat, typ), n in sorted(by_cat.items()):
        print(f"  {cat:<14} {typ:<28} {n}")
    print("\nCoverage gaps:")
    for i in report.issues:
        if i.category == Category.COVERAGE:
            print(f"  [{i.details.get('gap_kind')}] {i.message}")
            for p in i.details.get("people", []):
                print(f"      - {p['name']} ({p['role'].lower()}): {p['reason']}")
    print("\nWarnings:")
    for i in report.issues:
        if i.severity == Severity.SOFT and i.category == Category.CONFIG:
            print(f"  {i.type}: {i.message}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="app.cli")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sd = sub.add_parser("seed", help="reset and load the sample dataset (destroys existing data)")
    sd.add_argument("--if-empty", action="store_true",
                    help="only seed an empty database; never modifies existing data (use in deployments)")
    g = sub.add_parser("generate", help="generate a roster for a month")
    g.add_argument("--month", required=True, help="YYYY-MM")
    g.add_argument("--save", action="store_true", help="store as a new draft version")
    v = sub.add_parser("validate", help="re-validate a stored version")
    v.add_argument("--version", type=int, required=True)
    args = ap.parse_args(argv)

    with SessionLocal() as s:
        if args.cmd == "seed":
            from app.seed.seed import seed, seed_if_empty
            if args.if_empty:
                result = seed_if_empty(s)
                print(result if result else "Database already contains data; seeding skipped.")
            else:
                print(seed(s))
            return 0
        if args.cmd == "generate":
            year, month = map(int, args.month.split("-"))
            problem = load_problem(s, year, month)
            out = generate(problem)
            _print_report(problem, out.status, out.report,
                          {"solve_status": out.solve.status.value, **out.solve.stats}, out.solve.lock_conflicts)
            if args.save:
                ver = persist_outcome(s, problem, out, created_by="cli")
                s.commit()
                print(f"\nSaved as version #{ver.version_no} (id={ver.id}) for {args.month}")
            return 0
        if args.cmd == "validate":
            from app import models as m
            ver = s.get(m.RosterVersion, args.version)
            if ver is None:
                print("version not found", file=sys.stderr)
                return 1
            problem = load_problem(s, ver.plan.year, ver.plan.month)
            rep = validate(problem, load_roster(s, ver.id))
            _print_report(problem, rep.status, rep)
            return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
