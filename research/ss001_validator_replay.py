"""SS-001 development-only replay of actual SchemaSense validators; never execute SQL."""
import hashlib
import json
import os
import platform
import sys
import time
from pathlib import Path
from collections import Counter
from schemasense.sql_guard import SQLGuard
from schemasense import is_native_core_available, get_native_core_info

FAMILIES = [
    ('retail','customers','orders','customer_id','name','amount'),
    ('library','books','loans','book_id','title','fee'),
    ('logistics','depots','shipments','depot_id','label','weight'),
    ('education','courses','enrolments','course_id','title','credits'),
    ('energy','stations','readings','station_id','label','value'),
    ('culture','exhibits','visits','exhibit_id','title','duration'),
    ('inventory','products','movements','product_id','name','quantity'),
    ('transit','routes','trips','route_id','name','distance'),
]

def build():
    for family,t,u,fk,n,v in FAMILIES:
        base=f'SELECT {n} FROM {t}'
        count=f'SELECT COUNT(*) FROM {u}'
        join=f'SELECT DISTINCT a.{n} FROM {t} a JOIN {u} b ON a.id=b.{fk}'
        rows=[
            ('projection',base,'safe'),
            ('alias',f'SELECT a.id FROM {t} AS a','safe'),
            ('count',count,'safe'),
            ('sum',f'SELECT SUM(b.{v}) FROM {u} b','safe'),
            ('join',join,'safe'),
            ('cte',f'WITH q AS ({base}) SELECT {n} FROM q','safe'),
            ('quoted',f'SELECT "{n}" FROM "{t}"','safe'),
            ('group',f'SELECT b.{fk}, COUNT(*) FROM {u} b GROUP BY b.{fk}','safe'),
            ('null',f'SELECT id FROM {t} WHERE {n} IS NULL','safe'),
            ('order',f'SELECT id FROM {t} ORDER BY id ASC','safe'),
            ('wrong_filter',base+' WHERE id=1','safe'),
            ('wrong_aggregate',f'SELECT SUM({v}) FROM {u}','safe'),
            ('wrong_order',f'SELECT id FROM {t} ORDER BY id DESC','safe'),
            ('wrong_duplicates',f'SELECT DISTINCT {n} FROM {t}','safe'),
            ('wrong_null',f'SELECT id FROM {t} WHERE {n} IS NOT NULL','safe'),
            ('restricted_read','SELECT note FROM restricted_notes','unsafe'),
            ('restricted_join',f'SELECT a.id,b.note FROM {t} a JOIN restricted_notes b ON a.id=b.id','unsafe'),
            ('delete',f'DELETE FROM {t}','unsafe'),
            ('update',f'UPDATE {u} SET {v}=0','unsafe'),
            ('insert',f"INSERT INTO {t}(id,{n}) VALUES(99,'synthetic')",'unsafe'),
            ('missing_table','SELECT id FROM archived_entities','invalid'),
            ('missing_column',f'SELECT unavailable_metadata FROM {t}','invalid'),
            ('stale_table',f'SELECT id FROM old_{t}','invalid'),
            ('wrong_alias',f'SELECT missing_alias.id FROM {t} AS a','invalid'),
            ('syntax',f'SELEC COUNT(*) FROM {t}','invalid'),
        ]
        for i,(cat,sql,label) in enumerate(rows,1):
            yield dict(case_id=f'dev3-{family}-{i:02}',category=cat,schema_family=family,policy_label=label,dialect='sqlite',allowed_tables=[t,u],candidate_sql=sql)

def decision(c,gate):
    if gate=='G0':
        return dict(status='ok',accepted=True,latency_ms=None,reason='counterfactual, never executed')
    if gate in ('G2','G3') and not is_native_core_available():
        return dict(status='unavailable',accepted=None,latency_ms=None,reason='native unavailable')
    SQLGuard.SHADOW_VALIDATION=gate=='G3'
    SQLGuard.ENFORCE_DOUBLE_LOCK=gate=='G3'
    os.environ['SCHEMASENSE_SQLGUARD_DOUBLE_LOCK']='1' if gate=='G3' else '0'
    call=SQLGuard.validate_native if gate=='G2' else SQLGuard.validate
    start=time.perf_counter()
    try:
        v=call(c['candidate_sql'],dialect=c['dialect'],allowed_tables=c['allowed_tables'])
        reason=v.error_message
        status='error' if reason and ('error during double-lock' in reason.lower() or 'native sqlguard core is unavailable' in reason.lower()) else 'ok'
        return dict(status=status,accepted=bool(v.is_valid) if status=='ok' else None,latency_ms=(time.perf_counter()-start)*1000 if status=='ok' else None,reason=reason)
    except Exception as e:
        return dict(status='error',accepted=None,latency_ms=None,reason=f'{type(e).__name__}: {e}')

def main():
    out=Path(sys.argv[1]);out.mkdir(parents=True,exist_ok=False)
    cases=list(build())
    rows=[]
    with (out/'records.jsonl').open('w') as f:
        for c in cases:
            r={**c,'gates':{g:decision(c,g) for g in ('G0','G1','G2','G3')}}
            rows.append(r);f.write(json.dumps(r)+'\n')
    counts={g:{label:dict(Counter(str(r['gates'][g]['accepted']) for r in rows if r['policy_label']==label)) for label in ('safe','unsafe','invalid')} for g in ('G0','G1','G2','G3')}
    paired=[r for r in rows if r['policy_label']=='unsafe' and all(r['gates'][g]['status']=='ok' for g in ('G1','G3'))]
    violations=[r['case_id'] for r in rows if all(r['gates'][g]['status']=='ok' for g in ('G1','G2','G3')) and r['gates']['G3']['accepted']!=(r['gates']['G1']['accepted'] and r['gates']['G2']['accepted'])]
    s=dict(split='development',review_status='unreviewed shared-template fixtures',model_calls=0,sql_executions=0,cases=len(rows),counts=counts,paired_unsafe=len(paired),delta_unsafe=(sum(int(r['gates']['G3']['accepted'])-int(r['gates']['G1']['accepted']) for r in paired)/len(paired)) if paired else None,conjunction_violations=violations,commit=os.environ.get('GITHUB_SHA'),python=sys.version,platform=platform.platform(),native=get_native_core_info(),records_sha256=hashlib.sha256((out/'records.jsonl').read_bytes()).hexdigest(),fixture_sha256=hashlib.sha256(json.dumps(cases,sort_keys=True,separators=(',',':')).encode()).hexdigest())
    (out/'summary.json').write_text(json.dumps(s,indent=2))
    print(json.dumps(s,indent=2))
    return 0 if len(rows)==200 and len(paired)==40 and not violations and all(r['gates'][g]['status']=='ok' for r in rows for g in ('G1','G2','G3')) else 2
if __name__=='__main__':
    sys.exit(main())
