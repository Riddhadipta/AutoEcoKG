"""AutoEcoKG: build an RDF graph from validated CSVs. Run from any directory."""
import argparse
import csv
from decimal import Decimal
from pathlib import Path
from urllib.parse import quote
from collections import Counter
from rdflib import Graph, Namespace, Literal, RDF, RDFS, OWL, XSD

AEK = Namespace('https://w3id.org/autoecokg/ontology#')
RES = Namespace('https://w3id.org/autoecokg/resource/')
SOSA = Namespace('http://www.w3.org/ns/sosa/')
PROV = Namespace('http://www.w3.org/ns/prov#')
UNITS = {'kW':'kw','PS':'ps','Nm':'nm','cm3':'cubicCentimetre','g/km':'gramsPerKm',
         'L/100 km':'litresPer100Km','kWh/100 km':'kwhPer100Km','kg':'kg','km':'km',
         'km/h':'kmPerHour','s':'second','m':'metre','dB(A)':'decibel','dB':'decibel',
         'grade':'adacGrade','mg/km/t':'mgPerKmPerTonne','1':'dimensionless','%':'percent'}

def uri(kind, key):
    return RES[kind+'/'+quote(str(key), safe='')]

def rows(folder, filename):
    with (folder/filename).open(encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))

def build(folder, ontology):
    g = Graph().parse(ontology, format='turtle')
    for prefix, ns in [('aek',AEK),('res',RES),('sosa',SOSA),('prov',PROV)]: g.bind(prefix,ns)
    counts = Counter()
    def add(s,p,o): g.add((s,p,o))
    def text(s,p,v):
        if v is not None and str(v).strip(): add(s,p,Literal(v,datatype=XSD.string))
    def entity(kind,key,cls,label=None):
        if not key: raise ValueError(f'Missing ID for {kind}')
        s=uri(kind,key); add(s,RDF.type,cls); text(s,AEK.recordId,key)
        if label: add(s,RDFS.label,Literal(label))
        return s
    def source(name):
        s=entity('source',name,AEK.SourceDocument,name); text(s,AEK.sourceFilename,name); return s
    def protocol(name): return entity('protocol',name,AEK.TestProtocol,name)
    def prop(name):
        p=AEK[name]; add(p,RDF.type,AEK.MeasurementProperty); add(p,RDFS.label,Literal(name.replace('_',' '))); return p
    def observation(kind,key,feature,param,value,unit,context,doc=None,page=None,line=None,evidence=None,proto=None,year=None,period=None,record=None):
        s=entity('observation',key,AEK.VehicleObservation if kind in ('vehicle','derived_vehicle') else AEK.TyreObservation)
        add(s,SOSA.hasFeatureOfInterest,feature); add(s,AEK.measurementProperty,prop(param)); add(s,SOSA.observedProperty,prop(param))
        if unit:
            if unit not in UNITS: raise ValueError(f'Unknown unit: {unit}')
            val=Decimal(str(value))
            if not val.is_finite(): raise ValueError(f'Invalid value: {value}')
            add(s,AEK.numericValue,Literal(val,datatype=XSD.decimal)); add(s,AEK.measurementUnit,AEK[UNITS[unit]])
        else: text(s,AEK.textValue,value)
        text(s,AEK.measurementContext,context); text(s,AEK.sourceEvidence,evidence)
        if doc: add(s,PROV.wasDerivedFrom,source(doc))
        if page: add(s,AEK.sourcePage,Literal(int(page),datatype=XSD.integer))
        if line: add(s,AEK.sourceLine,Literal(int(line),datatype=XSD.integer))
        if proto: add(s,AEK.testProtocol,proto)
        if year: add(s,AEK.testYear,Literal(str(year),datatype=XSD.gYear))
        text(s,AEK.testPeriod,period)
        if record: add(s,PROV.wasDerivedFrom,record)
        counts[kind+'_observations']+=1
        return s
    # Source-record entities keep 194 original tyre rows distinct from individual measurements.
    for name,datatype in [('sourceTableColumn',XSD.integer),('sourceTextSha256',XSD.string),('reportDate',XSD.string)]:
        add(AEK[name],RDF.type,OWL.DatatypeProperty); add(AEK[name],RDFS.range,datatype)
    add(AEK.TyreSourceRecord,RDF.type,OWL.Class); add(AEK.TyreSourceRecord,RDFS.subClassOf,PROV.Entity)
    vehicles={}; tyres={}; vehicle_rows={}; observed={}; tyre_records={}
    for r in rows(folder,'adac_vehicles.csv'):
        k=r['vehicle_id']; assert k not in vehicles,k
        s=vehicles[k]=entity('vehicle',k,AEK.VehicleVariant,r['vehicle_name']); vehicle_rows[k]=r
        for field,p in [('powertrain','powertrain'),('tested_tyre_model','testedTyreName'),('tested_tyre_size','testedTyreSize'),('report_date','reportDate'),('text_sha256','sourceTextSha256')]: text(s,AEK[p],r[field])
        add(s,PROV.wasDerivedFrom,source(r['source_file'])); counts['vehicles']+=1
    for i,r in enumerate(rows(folder,'provenance.csv'),1):
        k=r['vehicle_id']; p=r['parameter']; key=(k,p)
        if key in observed: raise ValueError(f'Duplicate vehicle observation {key}')
        same = Decimal(r['value']) == Decimal(vehicle_rows[k][p]) if r['unit'] else r['value'] == vehicle_rows[k][p]
        if not same: raise ValueError(f'Conflicting CSV value {key}')
        observed[key]=observation('vehicle',f'{k}/{p}',vehicles[k],p,r['value'],r['unit'],r['measurement_kind'],r['source_file'],r['source_page'],r['source_line'],r['evidence'],protocol('ADAC vehicle protocol '+r['protocol_date']) if r['measurement_kind']=='ADAC_test' else None)
    for k,r in vehicle_rows.items():
        for p,base in [('fuel_l_100km_gap_pct','fuel_l_100km'),('electric_kwh_100km_gap_pct','electric_kwh_100km')]:
            if not r[p]: continue
            # A derived value is linked to both input observations, not attributed to a PDF page.
            s=observation('derived_vehicle',f'{k}/{p}',vehicles[k],p,r[p],'%','derived: (ADAC - WLTP) / WLTP * 100')
            for prefix in ('adac_','wltp_'): add(s,PROV.wasDerivedFrom,observed[k,prefix+base])
    for r in rows(folder,'tyres.csv'):
        k=r['tyre_id']; assert k not in tyres,k
        s=tyres[k]=entity('tyre',k,AEK.TyreVariant,r['tyre_name']); text(s,AEK.tyreSize,r['tyre_size']); text(s,AEK.seasonCategory,r['category']); counts['tyres']+=1
    for r in rows(folder,'tyre_provenance.csv'):
        k=r['source_record_id']; assert k not in tyre_records,k
        s=tyre_records[k]=entity('tyre-record',k,AEK.TyreSourceRecord); add(s,SOSA.hasFeatureOfInterest,tyres[r['tyre_id']]); text(s,AEK.measurementContext,r['source_kind']); add(s,PROV.wasDerivedFrom,source(r['source_file'])); add(s,AEK.sourcePage,Literal(int(r['source_page']),datatype=XSD.integer)); counts['tyre_source_records']+=1
    for r in rows(folder,'tyre_abrasion.csv'):
        k=r['abrasion_id']; rec=tyre_records[k]; proto=protocol('ADAC tyre abrasion 2023-2025')
        for p,u,c in [('abrasion_mg_km_t','mg/km/t','ADAC measured abrasion'),('estimated_unece_index','1','ADAC estimate; not UNECE certification')]:
            observation('tyre',f'{k}/{p}',tyres[r['tyre_id']],p,r[p],u,c,r['source_file'],r['source_page'],evidence=r['source_evidence'],proto=proto,period=r['test_period'],record=rec)
        counts['abrasion_records']+=1
    for r in rows(folder,'tyre_test_grades.csv'):
        k=r['tyre_test_id']; rec=tyre_records[k]; year=r['test_year']; proto=protocol('ADAC tyre grading since 2023')
        add(rec,AEK.sourceTableColumn,Literal(int(r['source_table_column']),datatype=XSD.integer))
        for p,v in r.items():
            if not v or not (p.endswith('_grade') or p in ('eu_external_noise_db','eu_fuel_efficiency_class','eu_wet_grip_class')): continue
            u='grade' if p.endswith('_grade') else 'dB' if p=='eu_external_noise_db' else ''
            observation('tyre',f'{k}/{p}',tyres[r['tyre_id']],p,v,u,'ADAC grade' if u=='grade' else 'EU label reported by ADAC',r['source_file'],r['source_page'],proto=proto if u=='grade' else None,year=year,record=rec)
        counts['grade_records']+=1
    for r in rows(folder,'vehicle_tyre_matches.csv'):
        k=r['vehicle_id']+'/'+r['tyre_id']; s=entity('alignment',k,AEK.AlignmentCandidate)
        add(s,AEK.candidateVehicle,vehicles[r['vehicle_id']]); add(s,AEK.candidateTyre,tyres[r['tyre_id']]); text(s,AEK.matchType,r['match_type'])
        for f,p in [('identity_verified',AEK.identityVerified),('fitment_verified',AEK.fitmentVerified)]:
            if r[f].lower() not in ('true','false'): raise ValueError(f'Invalid flag {r[f]}')
            add(s,p,Literal(r[f].lower()=='true',datatype=XSD.boolean))
        counts['alignment_candidates']+=1
    for r in rows(folder,'tyre_match_candidates.csv'):
        k=r['tyre_test_id']+'/'+r['abrasion_id']; s=entity('alias',k,AEK.TyreAliasCandidate)
        add(s,AEK.aliasSourceTyre,tyres[r['grade_tyre_id']]); add(s,AEK.aliasTargetTyre,tyres[r['abrasion_tyre_id']]); text(s,AEK.reviewStatus,r['status'])
        for key in ('tyre_test_id','abrasion_id'): add(s,PROV.wasDerivedFrom,tyre_records[r[key]])
        counts['alias_candidates']+=1
    return g,counts

def main():
    root=Path(__file__).resolve().parent.parent
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input',type=Path,default=root/'data/processed'); p.add_argument('--ontology',type=Path,default=root/'ontology/autoecokg_ontology.ttl'); p.add_argument('--output',type=Path,default=root/'data/autoecokg_triples.ttl')
    a=p.parse_args(); g,counts=build(a.input,a.ontology); a.output.parent.mkdir(parents=True,exist_ok=True)
    g.serialize(a.output,format='turtle'); check=Graph().parse(a.output,format='turtle'); assert len(check)==len(g)
    for k,v in counts.items(): print(f'{k}: {v}')
    print(f'RDF triples: {len(g)}\nTurtle round-trip: PASS\nOutput: {a.output}')
if __name__=='__main__': main()
