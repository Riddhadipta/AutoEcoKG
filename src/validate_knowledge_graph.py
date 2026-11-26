"""AutoEcoKG stage 9: SHACL and project-specific graph validation."""
import argparse
import csv
from collections import Counter
from decimal import Decimal
from pathlib import Path
from rdflib import Graph, Namespace, RDF, OWL, Literal

A = Namespace('https://w3id.org/autoecokg/ontology#')
S = Namespace('http://www.w3.org/ns/sosa/')
P = Namespace('http://www.w3.org/ns/prov#')
SH = Namespace('http://www.w3.org/ns/shacl#')
CLASSES = ['VehicleVariant','TyreVariant','VehicleObservation','TyreObservation',
           'TyreSourceRecord','AlignmentCandidate','TyreAliasCandidate','SourceDocument','TestProtocol']

def audit(g):
    issues = []
    def issue(level, code, node, message):
        issues.append(dict(severity=level,check=code,focus_node=str(node),message=message))
    for cls in CLASSES:
        nodes = set(g.subjects(RDF.type,A[cls]))
        if not nodes: issue('ERROR','empty_class',A[cls],'Expected populated class')
        ids = Counter(str(v) for n in nodes for v in g.objects(n,A.recordId))
        for k,n in ids.items():
            if n > 1: issue('ERROR','duplicate_id',A[cls],k)
    observations = set(g.subjects(RDF.type,A.VehicleObservation)) | set(g.subjects(RDF.type,A.TyreObservation))
    for n in observations:
        prop = g.value(n,A.measurementProperty)
        unit = g.value(n,A.measurementUnit)
        value = g.value(n,A.numericValue)
        ctx = str(g.value(n,A.measurementContext) or '')
        sources = set(g.objects(n,P.wasDerivedFrom))
        if ctx.startswith('derived:'):
            if len(sources)!=2 or any((s,RDF.type,A.VehicleObservation) not in g for s in sources):
                issue('ERROR','derived_inputs',n,'Expected two vehicle observation inputs')
            if g.value(n,A.sourcePage) is not None: issue('ERROR','derived_page',n,'Derived value must not claim a direct PDF page')
            if unit != A.percent: issue('ERROR','derived_unit',n,'Expected percent')
            try:
                adac = next(s for s in sources if str(g.value(s,A.measurementProperty)).split('#')[-1].startswith('adac_'))
                wltp = next(s for s in sources if str(g.value(s,A.measurementProperty)).split('#')[-1].startswith('wltp_'))
                a,b = [Decimal(str(g.value(s,A.numericValue))) for s in (adac,wltp)]
                if abs(Decimal(str(value)) - (a-b)/b*100) > Decimal('0.11'): issue('ERROR','derived_formula',n,'Gap differs from inputs by more than 0.11 percentage points')
                if any(g.value(s,S.hasFeatureOfInterest)!=g.value(n,S.hasFeatureOfInterest) for s in sources): issue('ERROR','derived_feature',n,'Inputs must refer to same vehicle')
            except (StopIteration,ArithmeticError,ValueError,TypeError): issue('ERROR','derived_formula',n,'Cannot recompute gap')
        else:
            if not any((s,RDF.type,A.SourceDocument) in g for s in sources) or g.value(n,A.sourcePage) is None:
                issue('ERROR','source_provenance',n,'Expected document and source page')
        if value is not None:
            try:
                v=Decimal(str(value))
                if not v.is_finite(): raise ValueError('non-finite')
                if unit==A.adacGrade and not Decimal('0.6')<=v<=Decimal('5.5'): issue('ERROR','grade_range',n,'ADAC grade outside 0.6–5.5')
                if unit!=A.percent and v<0: issue('ERROR','negative_measurement',n,'Negative physical measurement')
                expected={A.abrasion_mg_km_t:A.mgPerKmPerTonne,A.estimated_unece_index:A.dimensionless}.get(prop)
                if expected is not None and (unit!=expected or v<=0): issue('ERROR','abrasion_unit_range',n,'Invalid abrasion/index unit or nonpositive value')
            except (ArithmeticError,ValueError): issue('ERROR','invalid_number',n,'Not a finite decimal')
        elif prop in (A.abrasion_mg_km_t,A.estimated_unece_index) or str(prop).endswith('_grade'):
            issue('ERROR','missing_numeric',n,'Expected numerical measurement')
        if str(prop).endswith('_grade') and unit!=A.adacGrade: issue('ERROR','grade_unit',n,'Expected ADAC grade unit')
    for n in g.subjects(RDF.type,A.TyreAliasCandidate):
        issue('WARNING','unresolved_alias',n,'Retained for manual review; no automatic merge')
    for s,o in g.subject_objects(OWL.sameAs):
        if any((n,RDF.type,c) in g for n in (s,o) for c in (A.VehicleVariant,A.TyreVariant)):
            issue('ERROR','unsupported_identity',s,'Vehicle/tyre owl:sameAs requires verified evidence')
    pairs=Counter((g.value(n,A.candidateVehicle),g.value(n,A.candidateTyre)) for n in g.subjects(RDF.type,A.AlignmentCandidate))
    for pair,count in pairs.items():
        if count>1: issue('ERROR','duplicate_alignment',pair[0],str(pair[1]))
    return issues

def main():
    root=Path(__file__).resolve().parent.parent
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--graph',type=Path,default=root/'data/autoecokg_triples.ttl')
    p.add_argument('--shapes',type=Path,default=root/'ontology/shacl_shapes.ttl')
    p.add_argument('--output',type=Path,default=root/'data/processed')
    args=p.parse_args()
    g=Graph().parse(args.graph,format='turtle'); shapes=Graph().parse(args.shapes,format='turtle')
    args.output.mkdir(parents=True,exist_ok=True)
    issues=audit(g)
    try:
        from pyshacl import validate
    except ImportError:
        print('PySHACL missing. Run: python -m pip install pyshacl')
        return 2
    conforms,report,report_text=validate(g,shacl_graph=shapes,inference='none',abort_on_first=False,meta_shacl=True)
    report.serialize(args.output/'kg_shacl_report.ttl',format='turtle')
    (args.output/'kg_shacl_report.txt').write_text(report_text,encoding='utf-8')
    for r in report.subjects(RDF.type,SH.ValidationResult):
        issues.append(dict(severity='ERROR',check='SHACL',focus_node=str(report.value(r,SH.focusNode)),message='; '.join(str(m) for m in report.objects(r,SH.resultMessage))))
    errors=sum(i['severity']=='ERROR' for i in issues); warnings=sum(i['severity']=='WARNING' for i in issues)
    status='FAIL' if errors or not conforms else 'PASS_WITH_REVIEW' if warnings else 'PASS'
    summary={'rdf_triples':len(g),**{c:len(set(g.subjects(RDF.type,A[c]))) for c in CLASSES},'shacl_conforms':conforms,'errors':errors,'warnings':warnings,'status':status}
    for name,data,fields in [('kg_validation_summary.csv',[summary],list(summary)),('kg_validation_issues.csv',issues,['severity','check','focus_node','message'])]:
        with (args.output/name).open('w',encoding='utf-8-sig',newline='') as f:
            w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); w.writerows(data)
    for k,v in summary.items(): print(f'{k}: {v}')
    return 1 if status=='FAIL' else 0

if __name__=='__main__': raise SystemExit(main())
