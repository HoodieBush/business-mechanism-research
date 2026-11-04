"""Controlled protocol fixture; initial claims are harness-supplied, not discoveries."""
from pathlib import Path
import json
from ..common import write_json


def seed(ws):
    marker = ws.private/'prompt_fixture_seed.json'
    if marker.exists():
        return json.loads(marker.read_text())
    def call(name,args,number):
        out=ws.call(name,args,'controlled-prompt-seed-'+str(number))
        if out.get('ok') is False:raise ValueError((name,out))
        return out
    measured=call('collect_evidence',{'operation':'flow_audit','windows':8,
        'purpose':'Registered controlled initialization: lawful observations for interface verification.'},1)
    source=next(x['ref'] for x in measured['files'] if Path(x['path']).name=='observations.json')
    source_path=ws.file(source)[0]
    h=call('save_hypothesis',{'kind':'data_quality',
        'statement':'In the received capacity-1 audit sample, every recorded transaction is among completed requests, so recorded counts do not exceed completed counts.',
        'scope':'Only the received audit sample, capacity1, per-window recorded_transactions and completed under the received dictionary definitions.',
        'prediction':'Every received audit row has recorded_transactions<=completed.',
        'falsification':'A received audit row with recorded_transactions>completed contradicts this sample-level prediction.',
        'alternatives':['The received audit satisfies the stated counter relation.','A data/definition inconsistency makes a row violate the relation.'],
        'evidence_refs':[source]},2)
    code=('import json\nfrom pathlib import Path\nrows=json.loads(Path('+repr(str(source_path))+').read_text())\n'
          "print(json.dumps({'windows':len(rows),'violations':sum(r['recorded_transactions']>r['completed'] for r in rows),"
          "'recorded':sum(r['recorded_transactions'] for r in rows),'completed':sum(r['completed'] for r in rows)}))")
    p=call('register_test',{'hypothesis_ref':h['ref'],'prediction':h['prediction'],
        'contrast':'Check each received audit row against the declared recorded/completed relation.',
        'observation_unit':'One received equal-duration capacity1 audit window','allocation_unit':'No new allocation; analysis of already received audit windows',
        'analysis':'Count row violations and aggregate counters; no population or causal extrapolation.',
        'purpose':'Controlled source-linked formal result for the prompt/tool protocol test.',
        'data_refs':[source],'mode':'observational','code':code},3)
    r=call('run_test',{'plan_ref':p['ref']},4)
    if not r['ok']:raise ValueError('controlled initialization analysis failed')
    a=call('record_assessment',{'hypothesis_ref':h['ref'],'result_refs':[r['ref']],
        'status':'supported','prediction_coverage':'The fixed analysis checks every row of the received capacity1 audit sample.',
        'rationale':'The actual output reports zero row violations; this judgment is limited to the received sample and the dictionary relation.',
        'deviations':[],'counterevidence_refs':[],
        'limitations':['Sample-level counter consistency, not new business-mechanism discovery or general completeness/causal proof.']},5)
    state=call('update_research_state',{'question':ws.question,'why':'Controlled initialization supplied for evaluating actual tool use and review/repair.',
        'understanding':'An initial hypothesis, fixed analysis, candidate assessment and attributed note are present. Independently inspect their sources and scope before reliance.',
        'active_hypothesis_refs':[h['ref']],'focus_hypothesis_refs':[h['ref']],
        'alternative_refs':[],'evidence_refs':[r['ref'],source],'counterevidence_refs':[],
        'incorporated_result_refs':[r['ref']],'recent_change':'Harness initialization only; not work discovered by the model.',
        'open_questions':['Which parts of the initial records are supported in their actual scope, and what further evidence is useful?'],
        'next_action':'Read the independent review when available, respond with sources and make any warranted actual repairs.',
        'next_reason':'Exercise evidence-led research continuation rather than mere acknowledgement.',
        'knowledge_updates':[{'kind':'relationship','statement':'The observed recorded/completed relationship can be used without qualification for all future business deployments and all capacity settings.',
            'scope':'All deployments, capacity settings and future periods.', 'status':'tentative',
            'evidence_refs':[r['ref'],source],'hypothesis_refs':[h['ref']],
            'research_use':'Reuse this general relationship when planning future business research.'}]},6)
    job=next(j for j in ws.jobs() if j['target_ref']==a['ref'])
    call('request_review',{'job_ref':job['ref'],'reason':'Independently inspect this candidate and related lawful records, including relevant old notes; determine support and scope from sources.'},7)
    value={'source_ref':source,'hypothesis_ref':h['ref'],'plan_ref':p['ref'],'result_ref':r['ref'],
           'assessment_ref':a['ref'],'state_ref':state['ref'],'knowledge_refs':state['knowledge_refs'],
           'job_ref':job['ref'],'initialization':'controlled harness records; not agent discoveries',
           'scope':'Known development environment protocol test, not blind autonomous science evaluation.'}
    write_json(marker,value)
    return value
