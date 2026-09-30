#!/usr/bin/env python3
import json, sys
from collections import defaultdict

def agg(rs):
    d = defaultdict(int)
    for r in rs:
        for k in ("total","code","comment","doc","blank","bytes"):
            d[k] += r[k]
        d["files"] += 1
    return d

def table(title, groups, key=lambda d: -d["total"]):
    print(f"\n### {title}")
    print("| group | files | total lines | code | comment | docstring | blank |")
    print("|---|---:|---:|---:|---:|---:|---:|")
    tot = defaultdict(int)
    for name, d in sorted(groups.items(), key=lambda kv: key(kv[1])):
        print(f"| {name} | {d['files']:,} | {d['total']:,} | {d['code']:,} | {d['comment']:,} | {d['doc']:,} | {d['blank']:,} |")
        for k,v in d.items(): tot[k]+=v
    print(f"| **TOTAL** | **{tot['files']:,}** | **{tot['total']:,}** | **{tot['code']:,}** | **{tot['comment']:,}** | **{tot['doc']:,}** | **{tot['blank']:,}** |")


def main( argv=None ):
    """
    Render the markdown report for the rows JSON named by `argv[1]`.

    THIS USED TO BE MODULE-LEVEL CODE, and line 5 was `rows = json.load(open(sys.argv[1]))`
    — so merely IMPORTING this file read argv and parsed a file, which means it could
    not be imported at all: bare, it raised IndexError; under pytest, whose argv[1] is
    a test path, FileNotFoundError. Same shape as its sibling loc_rollup.py but one
    notch worse, since that one at least imported successfully before doing its damage.
    Wrapping changes nothing about running the script; it only makes importing it free.

    Requires:
        - argv[1] names a JSON file of row dicts as written by count.py

    Ensures:
        - prints the whole report to stdout and returns the parsed rows
        - reads argv exactly once, from the argument when given
    """
    argv = sys.argv if argv is None else argv
    rows = json.load( open( argv[ 1 ] ) )
    incl = [r for r in rows if not r["excluded"]]
    excl = [r for r in rows if r["excluded"]]

    print("## ALL TRACKED")
    a = agg(rows); print(f"files={a['files']:,} lines={a['total']:,} bytes={a['bytes']:,}")

    # buckets
    g = defaultdict(lambda: defaultdict(int))
    for r in rows:
        d = g[r["bucket"]]
        for k in ("total","code","comment","doc","blank","bytes"): d[k]+=r[k]
        d["files"]+=1
    table("Buckets (all)", g, key=lambda d: d.get("_",0))

    # tiers
    A = [r for r in incl if r["bucket"].startswith("A")]
    B = [r for r in incl if r["bucket"].startswith("B")]
    C = [r for r in incl if r["bucket"].startswith("C")]
    for nm, rs in (("Tier A (code+tests+config)", A),
                   ("Tier B (A + docs)", A+B),
                   ("Tier C (B + R&D/history)", A+B+C)):
        d = agg(rs)
        print(f"\n{nm}: files={d['files']:,} total={d['total']:,} code={d['code']:,} comment={d['comment']:,} doc={d['doc']:,} blank={d['blank']:,}")

    # language breakdown per tier
    for nm, rs in (("Tier A by language", A), ("Tier B-only docs by language", B), ("Tier C-only R&D by language", C)):
        g = defaultdict(lambda: defaultdict(int))
        for r in rs:
            d = g[r["lang"]]
            for k in ("total","code","comment","doc","blank"): d[k]+=r[k]
            d["files"]+=1
        table(nm, g)

    # A split into code vs tests
    for nm, rs in (("A1 app code+config by language", [r for r in A if r["bucket"].startswith("A1")]),
                   ("A2 tests by language", [r for r in A if r["bucket"].startswith("A2")])):
        g = defaultdict(lambda: defaultdict(int))
        for r in rs:
            d = g[r["lang"]]
            for k in ("total","code","comment","doc","blank"): d[k]+=r[k]
            d["files"]+=1
        table(nm, g)

    # exclusions
    g = defaultdict(lambda: defaultdict(int))
    for r in excl:
        d = g[r["bucket"]]
        for k in ("total","code","comment","doc","blank","bytes"): d[k]+=r[k]
        d["files"]+=1
    table("Excluded buckets", g)

    # top-dir breakdown of tier A
    g = defaultdict(lambda: defaultdict(int))
    for r in A:
        p = r["path"].split("/")
        key = "/".join(p[:2]) if len(p)>1 else "(root)"
        d = g[key]
        for k in ("total","code","comment","doc","blank"): d[k]+=r[k]
        d["files"]+=1
    table("Tier A by directory", g)

    return rows


if __name__ == "__main__":
    main()
