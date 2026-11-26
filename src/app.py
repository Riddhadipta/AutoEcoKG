"""AutoEcoKG dashboard. Save as src/app.py; run python -m streamlit run src/app.py."""
from pathlib import Path
from threading import RLock
import json
import pandas as pd
import plotly.express as px
from rdflib import RDF, RDFS, Namespace, URIRef
from engine import QueryEngine, QUERIES, PREFIX
from recommendation import recommend, FIELDS

ROOT = Path(__file__).resolve().parent.parent
AEK = Namespace('https://w3id.org/autoecokg/ontology#')
SOSA = Namespace('http://www.w3.org/ns/sosa/')
PROV = Namespace('http://www.w3.org/ns/prov#')
CLASSES = ['VehicleVariant', 'TyreVariant', 'VehicleObservation', 'TyreObservation',
           'TyreSourceRecord', 'AlignmentCandidate', 'TyreAliasCandidate', 'SourceDocument', 'TestProtocol']
TITLES = {'vehicles':'Vehicle catalogue', 'vehicle_co2':'WLTP CO₂ ranking', 'fuel_gap':'Fuel consumption gap',
          'low_abrasion':'Tyre abrasion ranking', 'safe_low_abrasion':'Safety-filtered abrasion',
          'alignment':'All vehicle–tyre candidates', 'matched_tyre_observations':'Model-and-size matches',
          'provenance':'Abrasion provenance'}
NUMERIC = ['co2','wltp','adac','gap','abrasion','safety','page','score','rank']

def frame(columns, rows):
    df = pd.DataFrame(rows, columns=columns)
    for c in NUMERIC:
        if c in df: df[c] = pd.to_numeric(df[c], errors='coerce')
    return df

def counts(g):
    return {c: len(set(g.subjects(RDF.type, AEK[c]))) for c in CLASSES}

def label(g, node):
    if node is None: return ''
    val = g.value(node,RDFS.label)
    return str(val) if val is not None else str(node).split('#')[-1].split('/')[-1]

def value(g, node, prop):
    v=g.value(node,prop)
    return '' if v is None else str(v)

def observations(g, feature):
    """Preserve context, source pages and inputs of derived observations."""
    out=[]
    for o in set(g.subjects(SOSA.hasFeatureOfInterest, URIRef(feature))):
        if not ((o,RDF.type,AEK.VehicleObservation) in g or (o,RDF.type,AEK.TyreObservation) in g): continue
        p=g.value(o,AEK.measurementProperty)
        if p is None: continue
        docs=[]; inputs=[]
        for s in g.objects(o,PROV.wasDerivedFrom):
            if (s,RDF.type,AEK.SourceDocument) in g: docs.append(value(g,s,AEK.sourceFilename))
            elif (s,RDF.type,AEK.VehicleObservation) in g: inputs.append(label(g,g.value(s,AEK.measurementProperty)))
        out.append({'property':str(p).split('#')[-1], 'value':value(g,o,AEK.numericValue) or value(g,o,AEK.textValue),
                    'unit':label(g,g.value(o,AEK.measurementUnit)), 'context':value(g,o,AEK.measurementContext),
                    'protocol':label(g,g.value(o,AEK.testProtocol)), 'year':value(g,o,AEK.testYear),
                    'period':value(g,o,AEK.testPeriod), 'source':'; '.join(sorted(docs)), 'page':value(g,o,AEK.sourcePage),
                    'derived inputs':'; '.join(sorted(inputs)), 'evidence':value(g,o,AEK.sourceEvidence), 'observation URI':str(o)})
    return pd.DataFrame(sorted(out,key=lambda r:(r['property'],r['observation URI'])))

def candidates(g, vehicle):
    out=[]
    for a in set(g.subjects(AEK.candidateVehicle,URIRef(vehicle))):
        t=g.value(a,AEK.candidateTyre)
        if t is None: continue
        out.append({'candidate':str(a),'tyre':str(t),'name':label(g,t),'size':value(g,t,AEK.tyreSize),
                    'match':value(g,a,AEK.matchType),'identity':value(g,a,AEK.identityVerified),'fitment':value(g,a,AEK.fitmentVerified)})
    order={'model_size_match':0,'model_only':1,'dimension_only':2}
    return pd.DataFrame(sorted(out,key=lambda r:(order.get(r['match'],9),r['name'],r['size'],r['tyre'])),
                        columns=['candidate','tyre','name','size','match','identity','fitment'])

def candidate_dot(g, vehicle, rows):
    """Actual graph edge directions: candidate -> vehicle and candidate -> tyre."""
    q=lambda s:json.dumps(str(s),ensure_ascii=False)
    lines=['digraph G {','rankdir=LR; graph [bgcolor="transparent"]; node [shape=box,style="rounded,filled",fontname="Arial",fontsize=10]; edge [fontname="Arial",fontsize=9];',
           f'v [label={q(label(g,URIRef(vehicle)))},fillcolor="#dbeafe"];']
    for i,r in enumerate(rows):
        lines += [f'a{i} [label={q(r["match"]+"\nfitment: "+r["fitment"])},fillcolor="#ede9fe"];',
                  f't{i} [label={q(r["name"]+"\n"+r["size"])},fillcolor="#fef3c7"];',
                  f'a{i} -> v [label="candidateVehicle"];', f'a{i} -> t{i} [label="candidateTyre"];']
    lines.append('}')
    return '\n'.join(lines)

def main():
    import streamlit as st
    st.set_page_config(page_title='AutoEcoKG | Automotive Environmental Knowledge Graph',page_icon='🚘',layout='wide')
    st.title('AutoEcoKG')
    st.caption('Automotive Environmental Knowledge Graph · RDF / OWL · ADAC test data')
    graph_path=ROOT/'data/autoecokg_triples.ttl'
    if not graph_path.is_file():
        st.error(f'Graph missing: {graph_path}. Run python src/generate_knowledge_graph.py first.'); st.stop()
    stamp=graph_path.stat().st_mtime_ns
    @st.cache_resource
    def load_engine(path,mtime):
        return QueryEngine(path),RLock()
    @st.cache_data(show_spinner=False)
    def query(path,mtime,name,safety=2.5):
        eng,lock=load_engine(path,mtime)
        with lock: return frame(*eng.run(name,max_safety=safety))
    @st.cache_data(show_spinner=False)
    def ranking(path,mtime,size,season,safety,weight,maximum):
        eng,lock=load_engine(path,mtime)
        with lock: return frame(FIELDS,recommend(eng,size,season,safety,weight,maximum))
    @st.cache_data(show_spinner=False)
    def csv_report(path,mtime): return pd.read_csv(path,encoding='utf-8-sig')
    def run(name,safety=2.5): return query(str(graph_path),stamp,name,safety)
    def read_report(path):
        return csv_report(str(path),path.stat().st_mtime_ns) if path.is_file() else None
    def show(df,key,filename=None):
        st.dataframe(df,hide_index=True,use_container_width=True)
        st.download_button('Export CSV locally',df.to_csv(index=False).encode('utf-8-sig'),file_name=filename or f'{key}.csv',mime='text/csv',key=key)
    def metric_row(items):
        for col,(k,v) in zip(st.columns(len(items)),items): col.metric(k,v)
    try:
        engine,lock=load_engine(str(graph_path),stamp)
    except Exception as exc:
        st.error(f'Unable to load graph: {exc}'); st.stop()
    g=engine.graph
    c=counts(g)
    page=st.sidebar.radio('Explore AutoEcoKG',['Overview','Vehicle explorer','Tyre explorer','Tyre recommendations','Graph explorer','SPARQL queries','Validation & benchmarks'])
    st.sidebar.caption('Research prototype. EEA integration on hold. No certified vehicle fitment.')
    st.sidebar.caption('ADAC test protocols and sample coverage differ. Keep exported source data local until redistribution rights are established.')
    if page=='Overview':
        metric_row([('RDF triples',f'{len(g):,}'),('Vehicles',c['VehicleVariant']),('Tyre entities',c['TyreVariant']),('Candidate links',c['AlignmentCandidate'])])
        metric_row([('Vehicle observations',c['VehicleObservation']),('Tyre observations',c['TyreObservation']),('Source documents',c['SourceDocument']),('Unresolved aliases',c['TyreAliasCandidate'])])
        v=run('vehicles'); t=run('low_abrasion')
        left,right=st.columns(2)
        with left:
            d=v.groupby('powertrain').size().reset_index(name='count')
            st.plotly_chart(px.bar(d,x='count',y='powertrain',orientation='h',title='Vehicle powertrains'),use_container_width=True)
        with right:
            d=t.groupby('category').size().reset_index(name='count')
            st.plotly_chart(px.pie(d,names='category',values='count',title='Abrasion measurement coverage'),use_container_width=True)
        a=run('alignment'); d=a.groupby('matchType').size().reset_index(name='count')
        st.plotly_chart(px.bar(d,x='matchType',y='count',title='Alignment candidates (not certified fitments)'),use_container_width=True)
        st.info('Scope: independent ADAC vehicle and tyre observations; 2 unresolved tyre aliases; limited cross-source overlap. WLTP, ADAC and derived values are kept distinct.')
    elif page=='Vehicle explorer':
        v=run('vehicles'); powers=['All']+sorted(v.powertrain.unique().tolist()); p=st.selectbox('Powertrain',powers)
        f=v if p=='All' else v[v.powertrain==p]; show(f,'vehicles')
        selected=st.selectbox('Inspect vehicle',f.vehicle.tolist(),format_func=lambda u:label(g,URIRef(u)))
        if selected:
            st.subheader(label(g,URIRef(selected))); st.caption(f'Tested tyre: {value(g,URIRef(selected),AEK.testedTyreName)} · {value(g,URIRef(selected),AEK.testedTyreSize)}')
            show(observations(g,selected),'vehicle_observations')
        st.subheader('WLTP CO₂ comparison'); st.caption('Declared WLTP CO₂, not lifecycle emissions; electric tailpipe zero does not mean zero lifecycle CO₂.')
        co=run('vehicle_co2'); co=co[co.vehicle.isin(f.vehicle)]
        st.plotly_chart(px.bar(co.sort_values('co2',ascending=False),x='co2',y='name',orientation='h',labels={'co2':'WLTP CO₂ (g/km)','name':'Vehicle'},height=max(350,len(co)*27)),use_container_width=True)
        st.subheader('Fuel consumption gap'); gap=run('fuel_gap'); gap=gap[gap.name.isin(f.name)]
        st.caption('ADAC vs WLTP test conditions differ. Comparable records only; not everyday driving measurements.')
        if gap.empty: st.info('No comparable fuel gap records for this selection.')
        else:
            melt=gap.melt(id_vars='name',value_vars=['wltp','adac'],var_name='method',value_name='L/100 km')
            st.plotly_chart(px.bar(melt,x='L/100 km',y='name',color='method',barmode='group',orientation='h',height=max(350,len(gap)*42)),use_container_width=True); show(gap,'fuel_gap')
    elif page=='Tyre explorer':
        t=run('low_abrasion'); season=st.selectbox('Season',['All']+sorted(t.category.unique().tolist())); f=t if season=='All' else t[t.category==season]
        size=st.selectbox('Size',['All']+sorted(f['size'].unique().tolist())); f=f if size=='All' else f[f['size']==size]
        metric_row([('Abrasion records',len(f)),('Minimum mg/km/t',f'{f.abrasion.min():g}' if len(f) else '—')]); show(f,'abrasion')
        if not f.empty:
            top=f.head(15).copy(); top['tyre label']=top.name+' · '+top['size']; st.plotly_chart(px.bar(top.iloc[::-1],x='abrasion',y='tyre label',orientation='h',labels={'abrasion':'Abrasion (mg/km/t)'},title='Lowest measured abrasion'),use_container_width=True)
        # Include provisional grade-only entities as well, not only measured abrasion rows.
        entities=sorted(set(g.subjects(RDF.type,AEK.TyreVariant)),key=lambda u:(label(g,u),str(u)))
        entities=[str(u) for u in entities if (season=='All' or value(g,u,AEK.seasonCategory)==season) and (size=='All' or value(g,u,AEK.tyreSize)==size)]
        if entities:
            selected=st.selectbox('Inspect all matching tyre entities (including grade-only)',entities,format_func=lambda u:f'{label(g,URIRef(u))} · {value(g,URIRef(u),AEK.tyreSize)} · {value(g,URIRef(u),AEK.recordId)}')
            show(observations(g,selected),'tyre_observations')
        st.caption('Measured abrasion and ADAC abrasion grades are different properties; missing grades are not zero.')
    elif page=='Tyre recommendations':
        st.info('Research ranking only. Fitment, load/speed rating and OEM approval are not verified. Lower grades and scores are better.')
        t=run('low_abrasion'); seasons=['summer','winter','all_season']
        season=st.selectbox('Season',seasons); sizes=sorted(t[t.category==season]['size'].unique().tolist()); default=sizes.index('225/40 R18') if '225/40 R18' in sizes else 0
        size=st.selectbox('Dimension',sizes,index=default) if sizes else st.text_input('Dimension','225/40 R18')
        safety=st.slider('Maximum safety grade',0.6,5.5,2.5,0.1); weight=st.slider('Environmental weight (%)',0,100,50,5)
        cap=st.checkbox('Limit abrasion'); maximum=st.number_input('Maximum abrasion (mg/km/t)',min_value=1.0,value=70.0) if cap else None
        st.caption(f'Abrasion weight {weight}% · Safety weight {100-weight}% · Normalized within eligible candidates.')
        if not size: st.stop()
        try:
            with st.spinner('Ranking eligible tyres…'): r=ranking(str(graph_path),stamp,size,season,safety,weight/100,maximum)
        except ValueError as e: st.error(str(e)); st.stop()
        if r.empty: st.warning('No eligible tyres with both abrasion and safety observations. This is a data/constraint limitation, not a fitment assessment.')
        else:
            metric_row([('Eligible tyres',len(r)),('Pareto optimal',int(r.pareto_optimal.sum())),('Top score',f'{r.iloc[0].score:.4f}')]); st.subheader(f'Top candidate: {r.iloc[0]["name"]}')
            st.plotly_chart(px.scatter(r,x='abrasion',y='safety',color='pareto_optimal',hover_name='name',labels={'abrasion':'Abrasion (mg/km/t)','safety':'ADAC safety grade','pareto_optimal':'Pareto optimal'},title='Safety–abrasion trade-off'),use_container_width=True)
            show(r,'tyre_recommendations')
    elif page=='Graph explorer':
        v=run('vehicles'); selected=st.selectbox('Vehicle',v.vehicle.tolist(),format_func=lambda u:label(g,URIRef(u)))
        a=candidates(g,selected); st.caption('Alignment nodes connect vehicles to candidate tyres. False means not verified, not incompatible.')
        st.metric('Candidate links',len(a))
        if a.empty: st.info('No matching tyre candidates in the current graph.')
        else:
            kinds=st.multiselect('Match types',a['match'].unique().tolist(),default=a['match'].unique().tolist()); subset=a[a['match'].isin(kinds)]
            show(subset,'vehicle_tyre_candidates')
            if len(subset):
                limit=st.slider('Maximum links in diagram',1,12,min(6,len(subset))); st.graphviz_chart(candidate_dot(g,selected,subset.head(limit).to_dict('records')),use_container_width=True)
                st.caption(f'Diagram shows {min(limit,len(subset))} of {len(subset)} selected links; complete table above.')
                t=st.selectbox('Inspect candidate tyre evidence',subset.tyre.tolist(),format_func=lambda u:label(g,URIRef(u)))
                show(observations(g,t),'candidate_observations')
    elif page=='SPARQL queries':
        name=st.selectbox('Built-in query',list(QUERIES),format_func=lambda x:TITLES[x]); safety=st.slider('Maximum safety grade',0.6,5.5,2.5,0.1) if name=='safe_low_abrasion' else 2.5
        with st.expander('SPARQL source',expanded=True):
            st.code(PREFIX+QUERIES[name],language='sparql')
            if name=='safe_low_abrasion': st.caption(f'Parameter binding: maxSafety = {safety} (xsd:decimal)')
        with st.spinner('Executing RDF query…'): df=run(name,safety)
        st.metric('Results',len(df)); show(df,'query_results',name+'.csv')
        if name in ('alignment','matched_tyre_observations'): st.caption('All candidate relationships are unverified unless explicitly confirmed by source evidence.')
    else:
        st.subheader('SHACL validation'); validation=read_report(ROOT/'data/processed/kg_validation_summary.csv')
        if validation is None: st.info('Run python src/validate_knowledge_graph.py to generate the report.')
        else:
            show(validation,'kg_validation_summary')
            issues=read_report(ROOT/'data/processed/kg_validation_issues.csv')
            if issues is not None: show(issues,'kg_validation_issues')
        st.subheader('Benchmark results'); summary=read_report(ROOT/'evaluation/benchmark_summary.csv'); results=read_report(ROOT/'evaluation/benchmark_results.csv')
        if summary is None or results is None: st.info('Run python src/evaluate.py to generate benchmark reports.')
        else:
            show(summary,'benchmark_summary'); d=results.groupby(['group','status']).size().reset_index(name='tests')
            st.plotly_chart(px.bar(d,x='group',y='tests',color='status',title='Benchmark outcomes'),use_container_width=True)
            group=st.selectbox('Test category',['All']+sorted(results.group.unique().tolist())); show(results if group=='All' else results[results.group==group],'benchmark_results')
        for report in (validation,summary):
            if report is not None and 'rdf_triples' in report and int(report.iloc[0].rdf_triples)!=len(g): st.warning('A saved report has a different triple count from the current graph. Rerun validation and evaluation.')
        st.caption('Saved reports are snapshots, not live tests. Matching triple counts do not prove graph identity. Rerun after any data or ontology change. Benchmark reference: processed CSVs, not external ground truth.')
    st.divider(); st.caption('AutoEcoKG · Academic research prototype · Source: ADAC reports. No commercial or certified fitment advice.')

if __name__=='__main__':
    main()
