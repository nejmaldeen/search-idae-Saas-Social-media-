#!/usr/bin/env python3
"""CLI for the AI SaaS Opportunity Discovery Agent."""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from oda import db, orchestrator, report, review, store          # noqa: E402
from oda.connectors import capability_table, get                  # noqa: E402


def _conn(args):
    return db.open_db(args.database)


def cmd_audit(args):
    rows = capability_table(probe=not args.no_probe)
    w = (14, 46, 10, 34)
    print(f"{'PLATFORM':{w[0]}} {'ACCESS MECHANISM':{w[1]}} {'USABLE':{w[2]}} CREDENTIALS / BLOCKER")
    print("-" * 120)
    for r in rows:
        blocker = r["blocked_reason"] or "-"
        print(f"{r['platform']:{w[0]}} {r['access_mechanism'][:w[1]]:{w[1]}} "
              f"{str(r['usable_now']):{w[2]}} {blocker[:60]}")
    print()
    for r in rows:
        print(f"[{r['platform']}]")
        print(f"  data available : {r['data_available']}")
        print(f"  limits         : {r['limits']}")
        print(f"  ToS notes      : {r['tos_notes']}")
        print(f"  needs human    : {r['needs_human'] or '-'}")
    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))


def cmd_verify(args):
    """Live end-to-end check of one or more connectors: probe, then a real search."""
    names = ([p.strip() for p in args.platform.split(",") if p.strip()]
             if args.platform else list(__import__("oda.connectors", fromlist=["x"]).REGISTRY))
    from oda.connectors import REGISTRY
    rc = 0
    for name in names:
        c = REGISTRY.get(name)
        if c is None:
            print(f"[{name}] UNKNOWN connector")
            rc = 1
            continue
        ok, why = c.available()
        print(f"\n=== {name} ===")
        print(f"  credentials : {'OK' if ok else 'MISSING -> ' + why}")
        if not ok:
            print(f"  needs       : {c.capability.needs_human or '-'}")
            rc = 1
            continue
        if getattr(c, "probe_url", None):
            reach, preason = c.probe()
            print(f"  reachability: {'OK' if reach else 'BLOCKED -> ' + preason[:90]}")
            if not reach:
                print("  fix         : allow this host under Network access for the environment")
                rc = 1
                continue
        if name == "manual":
            print("  search      : n/a (manual import path)")
            continue
        res = c.search(args.query, limit=args.limit)
        print(f"  live search : status={res.access_status} http={res.http_code} "
              f"items={len(res.items)}")
        if res.reason:
            print(f"  reason      : {str(res.reason)[:120]}")
        if res.items:
            it = res.items[0]
            print(f"  sample      : {(it.title or it.text)[:88]!r}")
            print(f"  sample url  : {it.url}")
            print(f"  RESULT      : WORKING - real data retrieved")
        elif res.ok:
            print("  RESULT      : reachable but 0 items for this query (try another query)")
        else:
            print(f"  RESULT      : NOT WORKING - {res.access_status}")
            rc = 1
    sys.exit(rc)


def cmd_verify_integration(args):
    """Run the 11-criteria integration verification across platforms."""
    from oda import verify as V
    names = ([p.strip() for p in args.platform.split(",") if p.strip()]
             if args.platform else list(V and __import__(
                 "oda.connectors", fromlist=["x"]).SAUDI_PRIORITY))
    usernames = [u.strip().lstrip("@") for u in (args.usernames or "").split(",") if u.strip()]

    before = V.provider_spend()
    reports, total_items = [], 0
    for name in names:
        print(f"→ verifying {name} ...", flush=True)
        rep = V.verify_platform(name, limit=args.limit, usernames=usernames or None,
                                comments_per_post=args.comments,
                                probe_query=args.query)
        reports.append(rep)
        total_items += rep.sample_items
        print(f"  {name}: {rep.score()} ({rep.sample_items} items)", flush=True)
    after = V.provider_spend()
    cost = V.measure_cost(before, after, total_items)

    md = V.to_markdown(reports)
    if cost:
        md += (f"\n## التكلفة المقاسة فعلياً (C10)\n\n"
               f"- أُنفق خلال هذا التحقق: **${cost['spent_usd']}**\n"
               f"- عناصر مجلوبة: **{cost['items']}**\n"
               f"- **التكلفة لكل ١٠٠٠ عنصر: ${cost['usd_per_1000']}**\n")
    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(md)
    jp = os.path.splitext(args.out)[0] + ".json"
    with open(jp, "w", encoding="utf-8") as f:
        f.write(V.to_json(reports))
    print(f"\nwrote {args.out} and {jp}")
    if cost:
        print(f"measured cost: ${cost['spent_usd']} for {cost['items']} items "
              f"= ${cost['usd_per_1000']}/1000")


def cmd_new(args):
    conn = _conn(args)
    pid = store.create_project(conn, name=args.name, domain=args.domain, market=args.market,
                               languages=args.languages, period_days=args.period_days,
                               notes=args.sector)
    print(f"project_id={pid}")
    return pid


def cmd_projects(args):
    conn = _conn(args)
    for p in store.list_projects(conn, include_synthetic=args.include_synthetic):
        c = store.counts(conn, p["id"])
        print(f"{p['id']}  {p['name'][:34]:34s} domain={p['domain'][:26]:26s} "
              f"contents={c['contents']:4d} signals={c['signals']:4d} "
              f"clusters={c['clusters']:3d} opps={c['opportunities']:3d} "
              f"open_tasks={c['open_tasks']:2d}")


def cmd_run(args):
    conn = _conn(args)
    # None = auto-detect usable platforms; "" = explicitly collect from none
    plats = (None if args.platforms is None
             else [p.strip() for p in args.platforms.split(",") if p.strip()])
    rep = orchestrator.run_pipeline(
        conn, args.project, platforms=plats, resume=not args.no_resume,
        sector=args.sector, known_tools=[t.strip() for t in (args.tools or "").split(",") if t.strip()],
        per_query_limit=args.limit, max_queries_per_platform=args.max_queries,
        sleep_between=args.sleep, only_steps=(args.steps.split(",") if args.steps else None),
        data_origin=(db.SYNTHETIC if args.synthetic else db.REAL),
        comments_per_post=args.comments, max_comment_posts=args.comment_posts)
    print(json.dumps(rep, ensure_ascii=False, indent=2, default=str))


def cmd_import(args):
    conn = _conn(args)
    payload = sys.stdin.read() if args.file == "-" else open(args.file, encoding="utf-8").read()
    res = get("manual").parse(payload, default_platform=args.platform, default_kind=args.kind)
    st = store.ingest_result(conn, args.project, args.platform, res,
                             data_origin=db.SYNTHETIC if args.synthetic else db.REAL)
    print(json.dumps(st, ensure_ascii=False, indent=2))


def cmd_tasks(args):
    conn = _conn(args)
    for t in review.list_tasks(conn, args.project, status=args.status):
        print(f"[{t['status']:9s}] {t['id']}  ({t['kind']})  {t['title']}")
        if args.verbose:
            print(f"   what : {t['what_is_needed']}")
            print(f"   why  : {t['why_needed']}")
            print(f"   steps: {t['steps']}")
            print(f"   return: {t['expected_return']}")
            print(f"   next : {t['after_completion']}\n")


def cmd_answer(args):
    conn = _conn(args)
    ok, msg = review.complete_task(conn, args.task, args.response)
    print(("OK: " if ok else "FAILED: ") + msg)
    sys.exit(0 if ok else 1)


def cmd_report(args):
    conn = _conn(args)
    origin = db.SYNTHETIC if args.synthetic else db.REAL
    if args.stdout:
        print(report.to_markdown(report.build_report(conn, args.project, data_origin=origin)))
    else:
        res = report.export(conn, args.project, args.out, data_origin=origin)
        print(json.dumps(res, ensure_ascii=False, indent=2))


def main():
    ap = argparse.ArgumentParser(prog="oda", description=__doc__)
    ap.add_argument("--database", default=db.DEFAULT_DB, help="SQLite path")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("audit", help="feasibility audit of every connector")
    s.add_argument("--no-probe", action="store_true", help="skip live reachability checks")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_audit)

    s = sub.add_parser("verify", help="live-test connectors end to end")
    s.add_argument("--platform", default=None, help="comma list; default = all")
    s.add_argument("--query", default="inventory management problems")
    s.add_argument("--limit", type=int, default=3)
    s.set_defaults(func=cmd_verify)

    s = sub.add_parser("verify-integration",
                       help="run the 11-criteria integration verification")
    s.add_argument("--platform", default=None,
                   help="comma list; default = the Saudi-priority platforms")
    s.add_argument("--usernames", default=None,
                   help="comma list of accounts (required for snapchat)")
    s.add_argument("--limit", type=int, default=5, help="sample size per platform")
    s.add_argument("--comments", type=int, default=15, help="comments per post")
    s.add_argument("--query", default=None, help="override the Arabic probe query")
    s.add_argument("--out", default="VERIFICATION.md")
    s.set_defaults(func=cmd_verify_integration)

    s = sub.add_parser("new", help="create a research project")
    s.add_argument("--name", required=True)
    s.add_argument("--domain", required=True)
    s.add_argument("--market", default=None, help="market code, e.g. sa / ae / eg")
    s.add_argument("--languages", default="ar,en")
    s.add_argument("--period-days", type=int, default=365)
    s.add_argument("--sector", default=None, help="synonym pack: ecommerce | saas")
    s.set_defaults(func=cmd_new)

    s = sub.add_parser("projects", help="list projects")
    s.add_argument("--include-synthetic", action="store_true")
    s.set_defaults(func=cmd_projects)

    s = sub.add_parser("run", help="run or resume the pipeline")
    s.add_argument("--project", required=True)
    s.add_argument("--platforms", default=None, help="comma list; default = auto-detected")
    s.add_argument("--sector", default=None)
    s.add_argument("--tools", default=None, help="comma list of known competitor names")
    s.add_argument("--limit", type=int, default=15, help="results per query")
    s.add_argument("--max-queries", type=int, default=6, help="queries per platform")
    s.add_argument("--sleep", type=float, default=6.5, help="seconds between queries")
    s.add_argument("--steps", default=None, help="comma list to run only some steps")
    s.add_argument("--comments", type=int, default=25, help="comments per post (cost control)")
    s.add_argument("--comment-posts", type=int, default=8, help="posts to fetch comments for")
    s.add_argument("--no-resume", action="store_true")
    s.add_argument("--synthetic", action="store_true",
                   help="process synthetic_fixture rows instead of real data (testing)")
    s.set_defaults(func=cmd_run)

    s = sub.add_parser("import", help="manual import of real user-supplied content")
    s.add_argument("--project", required=True)
    s.add_argument("--file", required=True, help="path or - for stdin")
    s.add_argument("--platform", default="manual", help="origin platform label")
    s.add_argument("--kind", default="post")
    s.add_argument("--synthetic", action="store_true",
                   help="mark as synthetic_fixture (testing only; excluded from real reports)")
    s.set_defaults(func=cmd_import)

    s = sub.add_parser("tasks", help="list human review tasks")
    s.add_argument("--project", required=True)
    s.add_argument("--status", default=None)
    s.add_argument("--verbose", action="store_true")
    s.set_defaults(func=cmd_tasks)

    s = sub.add_parser("answer", help="complete a human review task")
    s.add_argument("--task", required=True)
    s.add_argument("--response", required=True)
    s.set_defaults(func=cmd_answer)

    s = sub.add_parser("report", help="export a report")
    s.add_argument("--project", required=True)
    s.add_argument("--out", default="exports")
    s.add_argument("--stdout", action="store_true")
    s.add_argument("--synthetic", action="store_true", help="report on synthetic rows instead")
    s.set_defaults(func=cmd_report)

    args = ap.parse_args()
    try:
        args.func(args)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(2)
    except KeyboardInterrupt:
        print("\ninterrupted; progress is saved and the run can be resumed.", file=sys.stderr)
        sys.exit(130)


if __name__ == "__main__":
    main()
