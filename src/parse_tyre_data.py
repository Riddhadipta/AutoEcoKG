"""Normalize ADAC tyre datasets without silently merging ambiguous variants."""
import argparse, csv, hashlib, re, unicodedata, math
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
def norm(s):
    return ''.join(c for c in unicodedata.normalize('NFKD', s.casefold()) if c.isalnum() and not unicodedata.combining(c))
def key(r):
    m = re.fullmatch(r'(\d{3})\s*/\s*(\d{2})\s*Z?R\s*(\d{2})', r['tyre_size'].strip(), re.I)
    if not m: raise ValueError('Invalid size: '+r['tyre_size'])
    k = (norm(r['tyre_name']), f'{m[1]}/{m[2]} R{m[3]}', r['category'].strip().lower())
    if not k[0] or k[2] not in {'summer','winter','all_season'}: raise ValueError('Invalid identity: '+str(k))
    return k
def tid(k): return 'TYRE-'+hashlib.sha256('|'.join(k).encode()).hexdigest()[:16]
def read(p):
    with p.open(encoding='utf-8-sig',newline='') as f: return list(csv.DictReader(f))
def write(p, rows, fields):
    with p.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); w.writerows(rows)
def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--input-dir',type=Path,default=ROOT/'data/intermediate/tyres')
    ap.add_argument('--output-dir',type=Path,default=ROOT/'data/processed')
    args=ap.parse_args()
    a=read(args.input_dir/'tyre_abrasion_raw.csv'); g=read(args.input_dir/'tyre_test_grades_raw.csv')
    if not a or not g: raise ValueError('Empty input table')
    entities={}; provenance=[]; candidates=[]
    for rows,kind,idcol in [(a,'abrasion','abrasion_id'),(g,'grades','tyre_test_id')]:
        ids=set(); keys=set()
        for r in rows:
            if any(v is None or not v.strip() for v in r.values()): raise ValueError('Missing field: '+str(r.get(idcol)))
            k=key(r)
            if r[idcol] in ids or k in keys: raise ValueError('Duplicate: '+r[idcol])
            ids.add(r[idcol]); keys.add(k)
            if int(r['source_page'])<1: raise ValueError('Invalid page')
            if kind=='abrasion':
                for f in ['abrasion_mg_km_t','estimated_unece_index']:
                    n=float(r[f]);
                    if not math.isfinite(n) or n<=0: raise ValueError('Invalid '+f+': '+r[idcol])
                if k[1]!=f"{int(r['width_mm'])}/{int(r['aspect_ratio'])} R{int(r['rim_inches'])}": raise ValueError('Size mismatch: '+r[idcol])
            else:
                for f,v in r.items():
                    if f.endswith('_grade') and not 0.6<=float(v)<=5.5: raise ValueError('Invalid grade: '+r[idcol]+' '+f)
            e=entities.setdefault(k,{'tyre_id':tid(k),'tyre_name':r['tyre_name'],'tyre_size':k[1],'category':k[2],'abrasion_id':'','tyre_test_id':''})
            e[idcol]=r[idcol]
            provenance.append({'tyre_id':tid(k),'source_kind':kind,'source_record_id':r[idcol],'source_file':r['source_file'],'source_page':r['source_page']})
    aliases={'syrontyrespremiumperformance':'syronpremiumperformance','doublecoindc100speedindexw':'doublecoindc100'}
    for k,e in entities.items():
        target=(aliases.get(k[0],''),k[1],k[2])
        if e['tyre_test_id'] and not e['abrasion_id'] and target in entities and entities[target]['abrasion_id']:
            other=entities[target]
            candidates.append(dict(grade_tyre_id=e['tyre_id'],abrasion_tyre_id=other['tyre_id'],tyre_test_id=e['tyre_test_id'],abrasion_id=other['abrasion_id'],grade_name=e['tyre_name'],abrasion_name=other['tyre_name'],tyre_size=k[1],status='manual_review'))
    out=args.output_dir; out.mkdir(parents=True,exist_ok=True)
    write(out/'tyres.csv',list(entities.values()),list(next(iter(entities.values()))))
    for rows,filename in [(a,'tyre_abrasion.csv'),(g,'tyre_test_grades.csv')]:
        write(out/filename,[{'tyre_id':tid(key(r)),**r} for r in rows],['tyre_id',*rows[0].keys()])
    write(out/'tyre_provenance.csv',provenance,list(provenance[0]))
    write(out/'tyre_match_candidates.csv',candidates,['grade_tyre_id','abrasion_tyre_id','tyre_test_id','abrasion_id','grade_name','abrasion_name','tyre_size','status'])
    summary=dict(abrasion_records=len(a),grade_records=len(g),normalized_tyre_keys=len(entities),exact_overlap=sum(bool(e['abrasion_id'] and e['tyre_test_id']) for e in entities.values()),alias_candidates=len(candidates),status='PASS_WITH_REVIEW' if candidates else 'PASS')
    write(out/'tyre_normalization_summary.csv',[summary],list(summary))
    for k,v in summary.items(): print(f'{k}: {v}')
if __name__=='__main__': main()
