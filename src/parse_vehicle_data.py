"""AutoEcoKG: parse ADAC Autotest text tables; retain evidence and missing values."""
import argparse
import csv
import hashlib
import re
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NUM = r'(?:\d{1,3}(?:\.\d{3})+|\d+)(?:,\d+)?'

def number(s):
    return float(s.replace('.', '').replace(',', '.'))

def normalize(text):
    return unicodedata.normalize('NFKC', text).replace('–', '-').replace('−', '-').replace('\u00ad', '')

def parse(path):
    text = normalize(path.read_text(encoding='utf-8-sig'))
    lines = [line.strip() for line in text.splitlines()]
    def section(label):
        return next((i for i,l in enumerate(lines) if re.fullmatch(label,l,re.I)), None)
    h, a = section('Herstellerangaben'), section('ADAC Messwerte')
    if h is None or a is None or a <= h or not any(re.fullmatch('Autotest', l, re.I) for l in lines[:12]):
        raise ValueError('Missing vehicle report headings or unsupported layout')
    # Some reports place test metadata before the measurement rows.
    a = next((i for i in range(a+1,len(lines)) if re.match(r'^Überholvorgang 60-100 km/h',lines[i],re.I)),a)
    end = next((i for i in range(a+1,len(lines)) if re.match(r'^(Informationen zum Testfahrzeug|Kosten\b)',lines[i],re.I)),len(lines))
    protocol = re.search(r'seit\s+(\d{2}\.\d{2}\.\d{4})\s+gültigen\s+Testprotokoll',text,re.I)
    protocol = protocol.group(1) if protocol else ''
    title_idx = next(i for i,l in enumerate(lines[:12]) if re.fullmatch('Autotest',l,re.I))
    if protocol == '01.02.2026' or any(re.search(r'\d+ von \d+',l) for l in lines[:8]):
        title = next((re.sub(r'\s*·\s*1 von \d+\s*$', '', l) for l in lines[:12] if re.search(r'·\s*1 von \d+\s*$',l)), '')
        if not title:
            title = ' '.join(l for l in lines[title_idx+1:next((i for i in range(title_idx+1,min(12,len(lines))) if re.match(r'^(Fünf|Vier|Drei|Zwei)türig',lines[i],re.I)),title_idx+1)] if l and not l.startswith('©'))
    else:
        title_parts=[]
        for l in lines[title_idx+1:title_idx+9]:
            if re.match(r'^(Fünf|Vier|Drei|Zwei)türig',l,re.I): break
            if l: title_parts.append(l)
        title=' '.join(title_parts)
    if not title: raise ValueError('Vehicle title not recognized')
    vid = 'adac_' + hashlib.sha256(title.casefold().encode()).hexdigest()[:16]
    row={'vehicle_id':vid,'vehicle_name':title,'source_file':path.name,'protocol_date':protocol,'report_date':next((l.split(':',1)[1].strip() for l in lines if l.startswith('Stand:')), ''),'text_sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
    obs=[]
    def record(key,value,unit,kind,idx,raw):
        if value is None or value=='': return
        row[key]=value
        page=''
        for j in range(idx,-1,-1):
            m=re.fullmatch(r'--- PAGE (\d+) ---',lines[j]) or re.search(r'© ADAC e\.V\.\s*\|\s*Seite (\d+)',lines[j]) or re.search(r'(?:^|·)\s*(\d+) von \d+\s*$',lines[j])
            if m: page=m.group(1); break
        if not page and j == 0: page='1'
        obs.append(dict(vehicle_id=vid,parameter=key,value=value,unit=unit,measurement_kind=kind,protocol_date=protocol,source_file=path.name,source_line=idx+1,source_page=page,evidence=raw))
    def field(label,start,stop):
        for i in range(start,stop):
            if re.fullmatch(label,lines[i],re.I):
                j=i+1
                while j<stop and not lines[j]: j+=1
                if j<stop: return j,lines[j]
        return None,''
    def extract(key,label,pattern,unit,kind,start,stop,group=1):
        i,s=field(label,start,stop)
        m=re.search(pattern,s,re.I)
        if m: record(key,number(m.group(group)) if unit else m.group(group),unit,kind,i,s)
    M='manufacturer'; A='ADAC_test'
    for key,label,pattern,unit in [
        ('power_kw','(?:System)?leistung',rf'({NUM})\s*kW','kW'),('power_ps','(?:System)?leistung',rf'({NUM})\s*PS','PS'),
        ('torque_nm',r'(?:Maximales Drehmoment|Max\. Systemdrehmoment)',rf'({NUM})\s*Nm','Nm'),('engine_capacity_cc','Hubraum',rf'({NUM})\s*(?:ccm|cm3)','cm3'),
        ('max_speed_kmh','Höchstgeschwindigkeit',rf'({NUM})\s*km/h','km/h'),('acceleration_0_100_s','Beschleunigung 0-100 km/h',rf'({NUM})\s*s','s'),
        ('wltp_fuel_l_100km',r'Verbrauch pro 100 km \(WLTP\)',rf'({NUM})\s*l\b','L/100 km'),('wltp_electric_kwh_100km',r'Verbrauch pro 100 km \(WLTP\)',rf'({NUM})\s*kWh','kWh/100 km'),
        ('wltp_co2_g_km',r'CO2-Ausstoß(?: \(WLTP\))?',rf'({NUM})\s*g/km','g/km'),('manufacturer_weight_kg','Leergewicht/Zuladung',rf'^({NUM})\s*/','kg'),
        ('standard_tyre_size',r'Reifengröße \(Serie[^)]*\)',r'(.+)',''),('drive_type','Kraftübertragung',r'(.+)',''),('gearbox','Getriebe(?:art)?',r'(.+)','')]:
        extract(key,label,pattern,unit,M,h,a)
    for key,label,pattern,unit in [
        ('adac_fuel_l_100km',r'(?:Eco|Auto)test-Verbrauch(?: pro 100 km)?',rf'({NUM})\s*l\b','L/100 km'),('adac_electric_kwh_100km',r'(?:Eco|Auto)test-Verbrauch(?: pro 100 km)?',rf'({NUM})\s*kWh','kWh/100 km'),
        ('adac_wtw_co2_g_km','CO2-Ausstoß Ecotest',rf'WTW\s*\*?\s*({NUM})\s*g/km','g/km'),
        ('adac_reported_co2_g_km','CO2-Ausstoß Ecotest',rf'^({NUM})\s*g/km','g/km'),
        ('tested_weight_kg','Leergewicht/Zuladung',rf'^({NUM})\s*/','kg'),('braking_distance_m','Bremsweg aus 100 km/h',rf'({NUM})\s*m\b','m'),
        ('range_km','Reichweite',rf'({NUM})\s*km','km'),('interior_noise_db','Innengeräusch 130 km/h',rf'({NUM})\s*dB','dB(A)'),
        ('tested_tyre_size',r'Reifengröße(?: Testwagen(?: \([^)]*\))?)?',r'(.+)',''),('tested_tyre_model',r'Reifen(?:marke Testwagen)?',r'(.+)','')]:
        extract(key,label,pattern,unit,A,a,end)
    i,s=field(r'Stadt/Land/BAB(?: \([^)]*\))?',a,end)
    m=re.fullmatch(rf'({NUM})\s*/\s*({NUM})\s*/\s*({NUM})\s*(l|kWh)/100\s*km',s,re.I)
    if m:
        u='L/100 km' if m.group(4).lower()=='l' else 'kWh/100 km'
        mode=lines[i-1] if i else ''
        for j,key in enumerate(('city','rural','autobahn'),1): record(key+('_fuel_l_100km' if u.startswith('L') else '_electric_kwh_100km'),number(m.group(j)),u,A,i,mode+' | '+s)
    # Read the summary grade, not the narrative heading or contents page.
    for i in range(h,len(lines)-1):
        if lines[i].casefold()=='federung' and re.fullmatch(r'[0-5],\d',lines[i+1]):
            record('suspension_comfort_grade',number(lines[i+1]),'grade',A,i+1,lines[i+1]); break
    # Fuel/powertrain classification is conservative: use explicit cues only.
    intro=' '.join(lines[title_idx+1:title_idx+80]).lower()
    spec=' '.join(lines[h:a]).lower()
    # Only use description immediately before Hubraum/Leistung, not equipment list.
    first=next((i for i in range(h,a) if lines[i] in ('Hubraum','Leistung')),h)
    desc=' '.join(lines[max(h,first-3):first]).lower()
    if re.search(r'plugin.hybrid|plug.in.hybrid',desc+' '+intro): powertrain='plug_in_hybrid'
    elif 'mild-hybrid' in desc or 'mildhybrid' in desc or 'mild-hybrid' in intro: powertrain='diesel_mild_hybrid' if 'diesel' in desc else 'petrol_mild_hybrid' if 'benzin' in desc else 'mild_hybrid_unspecified'
    elif row.get('wltp_electric_kwh_100km') and not row.get('wltp_fuel_l_100km') and (re.search(r'elektro.?motor|synchronmotor|synchronmaschine',desc+' '+intro) or 'electric' in title.lower() or 'elektro' in title.lower()): powertrain='electric'
    elif re.search(r'voll.hybrid|full.hybrid|e:hev|e.power',desc+' '+title.lower()): powertrain='full_hybrid'
    elif 'hybrid' in desc: powertrain='hybrid_unspecified'
    elif 'diesel' in desc: powertrain='diesel'
    elif 'benzin' in desc: powertrain='petrol'
    else: powertrain='unknown'
    row['powertrain']=powertrain
    # Gap is a comparison of test results, not owner-reported real-world consumption.
    for carrier,unit in [('fuel_l_100km','L/100 km'),('electric_kwh_100km','kWh/100 km')]:
        x,y=row.get('wltp_'+carrier),row.get('adac_'+carrier)
        if x and y is not None and powertrain!='plug_in_hybrid':
            row[carrier+'_gap_pct']=round(100*(y-x)/x,2)
    return row,obs

GROUPS={
 'engine_specs.csv':['power_kw','power_ps','torque_nm','engine_capacity_cc','drive_type','gearbox'],
 'emissions.csv':['wltp_co2_g_km','adac_reported_co2_g_km','adac_wtw_co2_g_km'],
 'energy_consumption.csv':['wltp_fuel_l_100km','wltp_electric_kwh_100km','adac_fuel_l_100km','adac_electric_kwh_100km','city_fuel_l_100km','rural_fuel_l_100km','autobahn_fuel_l_100km','city_electric_kwh_100km','rural_electric_kwh_100km','autobahn_electric_kwh_100km','fuel_l_100km_gap_pct','electric_kwh_100km_gap_pct'],
 'vehicle_components.csv':['standard_tyre_size','tested_tyre_size','tested_tyre_model','suspension_comfort_grade'],
 'performance.csv':['max_speed_kmh','acceleration_0_100_s','manufacturer_weight_kg','tested_weight_kg','braking_distance_m','range_km','interior_noise_db']}

def write_csv(path,rows,columns):
    with path.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=columns,extrasaction='ignore'); w.writeheader(); w.writerows(rows)

def main():
    p=argparse.ArgumentParser(); p.add_argument('--input',type=Path,default=ROOT/'data/intermediate'); p.add_argument('--output',type=Path,default=ROOT/'data/processed'); args=p.parse_args()
    if not args.input.is_dir(): p.error(f'Input directory missing: {args.input}')
    paths=sorted(args.input.glob('*.txt')); args.output.mkdir(parents=True,exist_ok=True)
    if not paths: p.error('No .txt reports found; run PDF extraction first.')
    manifest=args.input/'extraction_summary.csv'; allowed=None
    if manifest.exists():
        with manifest.open(encoding='utf-8-sig',newline='') as f: allowed={Path(r['filename']).stem for r in csv.DictReader(f) if r.get('status')=='success'}
    rows=[]; observations=[]; audit=[]; seen=set(); ids=set()
    for path in paths:
        try:
            if allowed is not None and path.stem not in allowed: raise ValueError('Not in successful extraction manifest (possibly stale)')
            digest=hashlib.sha256(path.read_bytes()).hexdigest()
            if digest in seen: raise ValueError('Duplicate text')
            seen.add(digest)
            row,obs=parse(path)
            if row['vehicle_id'] in ids: raise ValueError('Repeated vehicle title; review variant identity manually')
            ids.add(row['vehicle_id']); rows.append(row); observations.extend(obs)
            missing=[k for k in ['power_kw','tested_weight_kg','wltp_co2_g_km','protocol_date'] if row.get(k) in ('',None)]
            if not any(k in row for k in ('adac_fuel_l_100km','adac_electric_kwh_100km')): missing.append('ADAC consumption')
            if row['powertrain'] in ('unknown','hybrid_unspecified','mild_hybrid_unspecified'): missing.append('powertrain')
            if row['powertrain']=='electric' and not row.get('adac_electric_kwh_100km'): missing.append('electric consumption')
            status='review' if missing else 'parsed'
            audit.append({'filename':path.name,'status':status,'fields_extracted':len(obs),'details':'; '.join(missing)})
        except Exception as e: audit.append({'filename':path.name,'status':'skipped','fields_extracted':0,'details':str(e)})
        print(f"[{audit[-1]['status']}] {path.name}: {audit[-1]['details']}")
    identity=['vehicle_id','vehicle_name','powertrain','protocol_date','report_date','source_file','text_sha256']
    write_csv(args.output/'vehicles.csv',rows,identity)
    write_csv(args.output/'adac_vehicles.csv',rows,identity+[k for fields in GROUPS.values() for k in fields])
    for name,fields in GROUPS.items(): write_csv(args.output/name,rows,['vehicle_id']+fields)
    write_csv(args.output/'provenance.csv',observations,['vehicle_id','parameter','value','unit','measurement_kind','protocol_date','source_file','source_line','source_page','evidence'])
    write_csv(args.output/'parsing_summary.csv',audit,['filename','status','fields_extracted','details'])
    print(f'Parsed {len(rows)} of {len(paths)} text files; {len(observations)} observations. Review parsing_summary.csv.')

if __name__=='__main__': main()
