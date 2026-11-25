"""AutoEcoKG structural and semantic CSV validation (Python standard library)."""
import argparse, csv, math
from pathlib import Path
from collections import Counter

def read(path):
    with path.open(encoding='utf-8-sig', newline='') as f: return list(csv.DictReader(f))
def write(path, fields, rows):
    with path.open('w', encoding='utf-8-sig', newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); w.writerows(rows)
def num(x):
    try:
        n=float(x); return n if math.isfinite(n) else None
    except (TypeError,ValueError): return None

def main():
    ap=argparse.ArgumentParser(description=__doc__); ap.add_argument('--input-dir',type=Path,default=Path(__file__).resolve().parent.parent/'data'/'processed'); ap.add_argument('--output-dir',type=Path); a=ap.parse_args(); d=a.input_dir; out=a.output_dir or d; out.mkdir(parents=True,exist_ok=True)
    v=read(d/'adac_vehicles.csv'); p=read(d/'provenance.csv'); s=read(d/'parsing_summary.csv'); issues=[]
    def issue(r,field,severity,message): issues.append(dict(vehicle_id=r.get('vehicle_id',''),vehicle_name=r.get('vehicle_name',''),field=field,severity=severity,message=message))
    if not v: issue({},'dataset','ERROR','No vehicle records')
    ids={r['vehicle_id']:r for r in v}; obs=Counter((r['vehicle_id'],r['parameter']) for r in p)
    for field in ['vehicle_id','source_file','text_sha256']:
        counts=Counter(r[field] for r in v)
        for r in v:
            if not r[field] or counts[r[field]]>1: issue(r,field,'ERROR','Blank or duplicate identifier')
    bounds={'power_kw':(1,2000),'power_ps':(1,3000),'torque_nm':(1,5000),'tested_weight_kg':(300,5000),'manufacturer_weight_kg':(300,5000),'braking_distance_m':(10,100),'suspension_comfort_grade':(.6,5.5),'max_speed_kmh':(1,500),'acceleration_0_100_s':(.1,100),'range_km':(1,3000),'wltp_co2_g_km':(0,1000),'adac_reported_co2_g_km':(0,1000),'adac_wtw_co2_g_km':(0,1500),'interior_noise_db':(20,120)}
    types={'electric','diesel','petrol','petrol_mild_hybrid','diesel_mild_hybrid','full_hybrid','plug_in_hybrid'}
    required=['power_kw','power_ps','tested_weight_kg','braking_distance_m','wltp_co2_g_km','tested_tyre_model','tested_tyre_size','suspension_comfort_grade','range_km']
    applicability=[]
    for r in v:
        t=r['powertrain']; fields=required+['torque_nm','adac_reported_co2_g_km','adac_wtw_co2_g_km']
        if t not in types: issue(r,'powertrain','ERROR','Unrecognized powertrain')
        if t!='electric': fields+=['wltp_fuel_l_100km','adac_fuel_l_100km','city_fuel_l_100km','rural_fuel_l_100km','autobahn_fuel_l_100km']
        if t in {'electric','plug_in_hybrid'}: fields+=['wltp_electric_kwh_100km','adac_electric_kwh_100km']
        for f in fields:
            present=bool(r.get(f,'')); applicability.append((f,present))
            if not present: issue(r,f,'ERROR' if f in required else 'WARNING','Applicable measurement absent; verify source availability')
        for f,(lo,hi) in bounds.items():
            if r.get(f,'') and (num(r[f]) is None or not lo<=num(r[f])<=hi): issue(r,f,'ERROR','Outside broad plausibility bounds or not numeric')
        for f in r:
            if f.endswith(('_l_100km','_kwh_100km')) and r[f] and (num(r[f]) is None or num(r[f])<0): issue(r,f,'ERROR','Invalid consumption')
        kw,ps=num(r['power_kw']),num(r['power_ps'])
        if kw is not None and ps is not None and abs(ps-kw*1.35962)>2: issue(r,'power_ps','ERROR','kW/PS mismatch')
        if t=='electric' and (num(r['wltp_co2_g_km']) not in (None,0) or any(r.get(f) for f in ['wltp_fuel_l_100km','adac_fuel_l_100km'])): issue(r,'powertrain','ERROR','BEV has fuel or nonzero WLTP tailpipe CO2')
        for kind,unit in [('fuel','l_100km'),('electric','kwh_100km')]:
            f=f'{kind}_{unit}_gap_pct'; x=num(r.get(f'wltp_{kind}_{unit}')); y=num(r.get(f'adac_{kind}_{unit}')); g=num(r.get(f))
            if g is not None and (t=='plug_in_hybrid' or x is None or x<=0 or y is None or abs(g-(y-x)/x*100)>.03): issue(r,f,'ERROR','Invalid or incompatible consumption gap')
        x,y=num(r['adac_reported_co2_g_km']),num(r['adac_wtw_co2_g_km'])
        if x is not None and y is not None and y<x: issue(r,'adac_wtw_co2_g_km','WARNING','WTW below reported CO2; verify measurement boundaries')
        if r['protocol_date'] not in {'01.02.2019','01.02.2026'}: issue(r,'protocol_date','WARNING','Unrecognized protocol')
    for o in p:
        r=ids.get(o['vehicle_id']); f=o['parameter']
        if r is None: issue(o,f,'ERROR','Orphan observation'); continue
        if obs[(o['vehicle_id'],f)]>1: issue(r,f,'ERROR','Duplicate observation')
        if o['source_file']!=r['source_file'] or o['protocol_date']!=r['protocol_date']: issue(r,f,'ERROR','Provenance source/protocol mismatch')
        if not o['evidence'] or any(num(o[k]) is None or num(o[k])<1 for k in ['source_line','source_page']): issue(r,f,'ERROR','Missing/invalid source reference')
        x,y=num(r.get(f)),num(o['value'])
        if f not in r or (abs(x-y)>1e-8 if x is not None and y is not None else r.get(f)!=o['value']): issue(r,f,'ERROR','Observation value differs from vehicle table')
    for r in v:
        for f in bounds.keys() | {k for k in r if k.endswith(('_l_100km','_kwh_100km'))} | {'drive_type','gearbox','tested_tyre_size','tested_tyre_model','standard_tyre_size','engine_capacity_cc'}:
            if r.get(f) and not obs[(r['vehicle_id'],f)]: issue(r,f,'ERROR','Missing observation provenance')
    for r in s:
        if r['status']!='parsed': issue({'vehicle_name':r['filename']},'status','WARNING','Parser flagged report')
    if Counter(r['filename'] for r in s)!=Counter(r['source_file'] for r in v): issue({},'source_file','ERROR','Summary and vehicle filenames differ')
    if len({r['protocol_date'] for r in v})>1: issue({},'protocol_date','WARNING','Mixed protocols: stratify protocol-sensitive comparisons')
    counts=Counter(i['severity'] for i in issues); summary=[{'metric':k,'value':val} for k,val in [('vehicles',len(v)),('observations',len(p)),('errors',counts['ERROR']),('warnings',counts['WARNING']),('status','FAIL' if counts['ERROR'] else 'PASS_WITH_WARNINGS' if issues else 'PASS')]]
    comp=[]
    for f in sorted({f for f,_ in applicability}):
        vals=[x for k,x in applicability if k==f]; comp.append(dict(parameter=f,applicable=len(vals),present=sum(vals),missing=len(vals)-sum(vals),completeness_pct=round(100*sum(vals)/len(vals),2)))
    write(out/'validation_issues.csv',['vehicle_id','vehicle_name','field','severity','message'],issues); write(out/'validation_summary.csv',['metric','value'],summary); write(out/'data_completeness.csv',['parameter','applicable','present','missing','completeness_pct'],comp)
    for r in summary: print(f"{r['metric']}: {r['value']}")
    return int(bool(counts['ERROR']))
if __name__=='__main__': raise SystemExit(main())
