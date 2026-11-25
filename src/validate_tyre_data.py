"""Validate normalized ADAC tyre tables. Run from AutoEcoKG root."""
import csv
from pathlib import Path
from collections import Counter
import argparse, re, math

def read(path):
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))

def write(path, rows, fields):
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w=csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--data", type=Path, default=Path("data/processed"))
    args=ap.parse_args()
    d=args.data
    t,a,g,p,c=[read(d / n) for n in ("tyres.csv","tyre_abrasion.csv","tyre_test_grades.csv","tyre_provenance.csv","tyre_match_candidates.csv")]
    issues=[]
    def issue(level, record, field, msg):
        issues.append(dict(severity=level,record_id=record,field=field,message=msg))
    def unique(rows, field):
        for k,n in Counter(r.get(field,"") for r in rows).items():
            if not k or n>1: issue("ERROR",k,field,"Missing or duplicate ID")
    for rows,field in [(t,"tyre_id"),(a,"abrasion_id"),(g,"tyre_test_id")]:
        unique(rows,field)
    tm={r["tyre_id"]:r for r in t}
    am={r["abrasion_id"]:r for r in a}
    gm={r["tyre_test_id"]:r for r in g}
    def numeric(row,field,lo,hi,rid):
        try:
            x=float(row[field])
            if not math.isfinite(x) or not lo<=x<=hi: raise ValueError()
        except (KeyError,ValueError,TypeError):
            issue("ERROR",rid,field,f"Missing or outside [{lo}, {hi}]")
    for r in t:
        rid=r["tyre_id"]
        if not r["tyre_name"].strip(): issue("ERROR",rid,"tyre_name","Empty name")
        if not re.fullmatch(r"\d{3}/\d{2} R\d{2}",r["tyre_size"]): issue("ERROR",rid,"tyre_size","Unexpected dimension")
        if r["category"] not in ("summer","winter","all_season"): issue("ERROR",rid,"category","Unknown category")
        for f,idx in [("abrasion_id",am),("tyre_test_id",gm)]:
            k=r[f]
            if k and (k not in idx or idx[k]["tyre_id"]!=rid): issue("ERROR",rid,f,"Broken observation link")
        if not r["abrasion_id"] and not r["tyre_test_id"]: issue("ERROR",rid,"observations","No observations")
    for rows,field in [(a,"abrasion_id"),(g,"tyre_test_id")]:
        for r in rows:
            rid=r[field]; parent=tm.get(r["tyre_id"])
            if not parent or parent[field]!=rid: issue("ERROR",rid,"tyre_id","Broken reverse link")
            elif any(parent[k]!=r[k] for k in ("tyre_size","category")): issue("ERROR",rid,"identity","Size/category mismatch")
            numeric(r,"source_page",1,10000,rid)
            if not r["source_file"]: issue("ERROR",rid,"source_file","Missing source")
            if field=="abrasion_id":
                numeric(r,"abrasion_mg_km_t",0.000001,10000,rid)
                numeric(r,"estimated_unece_index",0.000001,100,rid)
            else:
                for k in r:
                    if k.endswith("_grade"): numeric(r,k,0.6,5.5,rid)
    expected={(r["tyre_id"],r[f]) for rows,f in [(a,"abrasion_id"),(g,"tyre_test_id")] for r in rows}
    actual=Counter((r["tyre_id"],r["source_record_id"]) for r in p)
    for k in expected|set(actual):
        if k not in expected or actual[k]!=1: issue("ERROR",k[1],"provenance","Missing, duplicate or orphan provenance")
    for r in p:
        obs=am.get(r["source_record_id"]) or gm.get(r["source_record_id"])
        if obs and any(r[k]!=obs[k] for k in ("source_file","source_page")):
            issue("ERROR",r["source_record_id"],"provenance","Source mismatch")
    for r in c:
        x=tm.get(r["grade_tyre_id"]); y=tm.get(r["abrasion_tyre_id"])
        if not x or not y or x["tyre_test_id"]!=r["tyre_test_id"] or y["abrasion_id"]!=r["abrasion_id"] or x["tyre_size"]!=y["tyre_size"]:
            issue("ERROR",r["tyre_test_id"],"candidate","Invalid candidate reference")
        else: issue("WARNING",r["tyre_test_id"],"candidate","Unresolved alias: "+r["grade_name"]+" / "+r["abrasion_name"])
    errors=sum(r["severity"]=="ERROR" for r in issues)
    warnings=len(issues)-errors
    summary=dict(tyres=len(t),abrasion_records=len(a),grade_records=len(g),provenance_records=len(p),errors=errors,warnings=warnings,status="FAIL" if errors else "PASS_WITH_REVIEW" if warnings else "PASS")
    write(d/"tyre_validation_issues.csv",issues,["severity","record_id","field","message"])
    write(d/"tyre_validation_summary.csv",[summary],list(summary))
    for k,v in summary.items(): print(f"{k}: {v}")
    return int(errors>0)

if __name__=="__main__":
    raise SystemExit(main())
