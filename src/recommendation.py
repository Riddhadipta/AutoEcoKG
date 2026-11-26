"""Research-only tyre ranking from AutoEcoKG RDF queries (not fitment advice)."""
import argparse
import csv
import re
from pathlib import Path
from math import isfinite
from engine import QueryEngine

FIELDS = ['rank','tyre','name','size','category','abrasion','safety','score','pareto_optimal','fitment_status']

def normalize_size(value):
    match = re.fullmatch(r'\s*(\d{3})\s*[/ ]\s*(\d{2})\s*Z?R\s*(\d{2})\s*', value, re.I)
    if not match:
        raise ValueError('Use a tyre size such as 225/40 R18')
    return f'{match[1]}/{match[2]} R{match[3]}'

def recommend(engine, size, category='summer', max_safety=2.5, abrasion_weight=0.5, max_abrasion=None):
    """Lower score is better; min-max normalization within eligible candidates."""
    size = normalize_size(size)
    if category not in ('summer','winter','all_season'):
        raise ValueError('Invalid tyre category')
    if not 0.6 <= max_safety <= 5.5 or not 0 <= abrasion_weight <= 1:
        raise ValueError('Invalid safety threshold or abrasion weight')
    if max_abrasion is not None and (not isfinite(max_abrasion) or max_abrasion <= 0):
        raise ValueError('Maximum abrasion must be positive and finite')
    _, abrasion_rows = engine.run('low_abrasion')
    season_by_id = {r['tyre']: r['category'] for r in abrasion_rows}
    _, rows = engine.run('safe_low_abrasion', max_safety=max_safety)
    candidates = {}
    for r in rows:
        if r['size'] != size or season_by_id.get(r['tyre']) != category:
            continue
        a, s = float(r['abrasion']), float(r['safety'])
        if not (isfinite(a) and a > 0 and isfinite(s) and 0.6 <= s <= max_safety):
            continue
        if max_abrasion is not None and a > max_abrasion:
            continue
        item = dict(r, abrasion=a, safety=s, category=category, fitment_status='not_verified')
        if r['tyre'] in candidates and candidates[r['tyre']] != item:
            raise ValueError('Multiple conflicting observations for tyre '+r['tyre'])
        candidates[r['tyre']] = item
    rows = list(candidates.values())
    if not rows:
        return []
    bounds = {k: (min(r[k] for r in rows), max(r[k] for r in rows)) for k in ('abrasion','safety')}
    def norm(r,k):
        lo, hi = bounds[k]
        return (r[k]-lo)/(hi-lo) if hi != lo else 0.0
    for r in rows:
        r['score'] = abrasion_weight*norm(r,'abrasion') + (1-abrasion_weight)*norm(r,'safety')
        r['pareto_optimal'] = not any(q['abrasion'] <= r['abrasion'] and q['safety'] <= r['safety'] and (q['abrasion'] < r['abrasion'] or q['safety'] < r['safety']) for q in rows)
    rows.sort(key=lambda r:(r['score'],r['safety'],r['abrasion'],r['tyre']))
    for i,r in enumerate(rows,1):
        r['rank'] = i
        r['score'] = round(r['score'],6)
    return rows

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--graph',type=Path,default=Path(__file__).resolve().parent.parent/'data/autoecokg_triples.ttl')
    parser.add_argument('--size',required=True)
    parser.add_argument('--category',choices=['summer','winter','all_season'],default='summer')
    parser.add_argument('--max-safety',type=float,default=2.5)
    parser.add_argument('--max-abrasion',type=float)
    parser.add_argument('--abrasion-weight',type=float,default=0.5)
    parser.add_argument('--limit',type=int,default=10,help='Display limit; 0 shows all')
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    if args.limit < 0: parser.error('Limit must be nonnegative')
    try:
        rows=recommend(QueryEngine(args.graph),args.size,args.category,args.max_safety,args.abrasion_weight,args.max_abrasion)
    except ValueError as exc:
        parser.error(str(exc))
    print(f'Eligible tyres: {len(rows)} | Abrasion weight: {args.abrasion_weight:g} | Safety weight: {1-args.abrasion_weight:g}')
    print('Research ranking only: fitment is not verified; missing grades are excluded.')
    if not rows: print('No eligible records; no recommendation can be made from this dataset.')
    for r in rows[:args.limit] if args.limit else rows:
        print(f"{r['rank']}. {r['name']} | {r['size']} | abrasion={r['abrasion']:g} mg/km/t | safety={r['safety']:g} | score={r['score']:.4f} | Pareto={r['pareto_optimal']}")
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True)
        with args.output.open('w',encoding='utf-8-sig',newline='') as f:
            writer=csv.DictWriter(f,fieldnames=FIELDS)
            writer.writeheader(); writer.writerows(rows)
        print(f'Saved: {args.output}')

if __name__=='__main__':
    main()
