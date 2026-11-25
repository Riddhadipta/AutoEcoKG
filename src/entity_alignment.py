"""Generate conservative vehicle-to-tyre candidate links, not fitment approvals."""
import csv, re, unicodedata, argparse
from pathlib import Path
from collections import Counter

def read(path):
    with path.open(encoding="utf-8-sig",newline="") as f: return list(csv.DictReader(f))
def write(path, rows, fields):
    with path.open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); w.writerows(rows)
def name_key(s):
    # Retain plus signs and model numbers: Primacy 4 != Primacy 4+.
    return re.sub(r"[\s\-]+","",unicodedata.normalize("NFKC",s).casefold())
def sizes(s):
    return list(dict.fromkeys(f"{w}/{a} R{r}" for w,a,r in re.findall(r"(\d{3})\s*/\s*(\d{2})\s*Z?\s*R\s*(\d{2})",s,re.I)))
def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--data",type=Path,default=Path("data/processed")); d=ap.parse_args().data
    v=read(d/"adac_vehicles.csv"); t=read(d/"tyres.csv")
    checks=read(d/"tyre_validation_summary.csv")
    if len(checks)!=1 or checks[0]["status"] not in ("PASS","PASS_WITH_REVIEW"): raise SystemExit("Run tyre validation successfully first.")
    links=[]; summary=[]
    for car in v:
        dim=sizes(car["tested_tyre_size"]); key=name_key(car["tested_tyre_model"])
        counts=Counter()
        for tyre in t:
            same_size=tyre["tyre_size"] in dim
            same_model=bool(key) and key==name_key(tyre["tyre_name"])
            if same_model and same_size: kind="model_size_match"
            elif same_model: kind="model_only"
            elif same_size: kind="dimension_only"
            else: continue
            counts[kind]+=1
            links.append(dict(vehicle_id=car["vehicle_id"],vehicle_name=car["vehicle_name"],vehicle_tested_tyre_model=car["tested_tyre_model"],vehicle_tested_tyre_size=car["tested_tyre_size"],tyre_id=tyre["tyre_id"],tyre_name=tyre["tyre_name"],tyre_size=tyre["tyre_size"],category=tyre["category"],match_type=kind,identity_verified="false",fitment_verified="false"))
        summary.append(dict(vehicle_id=car["vehicle_id"],vehicle_name=car["vehicle_name"],model_size_matches=counts["model_size_match"],model_only_matches=counts["model_only"],dimension_only_matches=counts["dimension_only"],status="model_size_candidate" if counts["model_size_match"] else "review_candidates" if counts else "no_candidate"))
    write(d/"vehicle_tyre_matches.csv",links,["vehicle_id","vehicle_name","vehicle_tested_tyre_model","vehicle_tested_tyre_size","tyre_id","tyre_name","tyre_size","category","match_type","identity_verified","fitment_verified"])
    write(d/"vehicle_tyre_alignment_summary.csv",summary,["vehicle_id","vehicle_name","model_size_matches","model_only_matches","dimension_only_matches","status"])
    print("Vehicles:",len(v))
    print("Candidate links:",dict(Counter(r["match_type"] for r in links)))
    print("Vehicle statuses:",dict(Counter(r["status"] for r in summary)))
if __name__=="__main__": main()
