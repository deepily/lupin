#!/usr/bin/env python3
import json, sys
from collections import defaultdict

rows = json.load(open(sys.argv[1]))

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
