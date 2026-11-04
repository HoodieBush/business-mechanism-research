"""Local native-wire fixtures: real graph/SQLite/sandbox, zero external calls."""
from copy import deepcopy
import http.server
import json
from pathlib import Path
import sqlite3
import threading
import tempfile
from business_mechanism import create_project, run_project, project_status
from business_mechanism.service import open_project, request_pause
from business_mechanism.transport import ExecutionJournal, call_model
from experiments.insight_research.common import write_json, digest
from experiments.insight_research.prompt_runtime_v05.examples import examples


def recs(root, kind):
    with sqlite3.connect(root/'researcher/private/records.sqlite') as db:
        return [json.loads(b) for b, in db.execute('SELECT body FROM records WHERE kind=? ORDER BY rowid', (kind,))]


def template(role, label):
    return deepcopy(next(a for l,n,a in examples(role) if l == label))


class NativeFixture:
    def __init__(self):
        self.root = None; self.calls = []; self.bad_submitted=set()

    def response(self, payload):
        root = self.root
        critic = any(t['function']['name']=='record_review' for t in payload['tools'])
        self.calls.append({'role':'critic' if critic else 'researcher','max_tokens':payload['max_tokens'],
                           'thinking':payload.get('thinking')})
        with sqlite3.connect(root/'researcher/private/records.sqlite') as db:
            marker = db.execute("SELECT value FROM meta WHERE key='release_stage_marker'").fetchone()
            marker = int(marker[0]) if marker else 0
            stage_h = [json.loads(b) for b, in db.execute("SELECT body FROM records WHERE kind='hypothesis' AND rowid>?", (marker,))]
            pending = db.execute("SELECT ref,target FROM review_jobs WHERE status IN ('pending','running') ORDER BY rowid LIMIT 1").fetchone()
        hs, plans, results, assessments = [recs(root,k) for k in ('hypothesis','plan','result','assessment')]
        if critic:
            job,target = pending
            peer = root/'reviews'/job/'critic/private/critic.sqlite'
            with sqlite3.connect(peer) as db:
                actions = [json.loads(b) for b, in db.execute('SELECT body FROM actions ORDER BY rowid')]
            read = [a for a in actions if a['tool']=='read_memory']
            query = [a for a in actions if a['tool']=='query_data']
            if not read:
                name,args='read_memory',{'ref':target,'offset':0,'limit':12000}
            elif not query:
                name,args='query_data',{'sql':'SELECT count(*) AS n,sum(value) AS total FROM observations','purpose':'Independent fixture recomputation'}
            else:
                action = query[-1]
                # Read the exact actual action reference from its durable row.
                with sqlite3.connect(peer) as db:
                    ref = db.execute("SELECT ref FROM actions WHERE json_extract(body,'$.tool')='query_data' ORDER BY rowid DESC LIMIT 1").fetchone()[0]
                args=template('critic','review_clean')
                args.update(source_refs=[target],checks_performed=[{'action_ref':ref,'finding':'Actual SQL returned eight rows and positive total; only this finite observational fixture is checked.','artifact_refs':[]}],
                            checked_scope=['Original target and independent SQL count/sum'],unchecked_scope=['No causal identification or external generalization'])
                if (str(root),job) not in self.bad_submitted:
                    args['prior_issue_updates']={'UNKNOWN_ANCESTOR_ISSUE':'resolved'}
                    self.bad_submitted.add((str(root),job))
                name='record_review'
        elif not stage_h:
            name,args='save_hypothesis',{'kind':'data_quality','statement':'The received table has positive total value.',
                'scope':'Only the eight supplied rows; engineering fixture.', 'prediction':'The sum of value in the supplied table is greater than zero.',
                'falsification':'A total at or below zero refutes this sample-level prediction.',
                'alternatives':['The total is positive.','The total is nonpositive.'],'evidence_refs':[]}
        else:
            h=stage_h[-1]
            plan=next((p for p in reversed(plans) if p['hypothesis_ref']==h['ref']),None)
            result=next((r for r in reversed(results) if r['hypothesis_ref']==h['ref']),None)
            assessment=next((a for a in reversed(assessments) if a['hypothesis_ref']==h['ref']),None)
            if not plan:
                with sqlite3.connect(root/'researcher/private/records.sqlite') as db:
                    data=db.execute("SELECT ref FROM files WHERE path='public/business.sqlite'").fetchone()[0]
                name,args='register_test',{'hypothesis_ref':h['ref'],'prediction':h['prediction'], 'contrast':'Compare the exact observed total to zero.',
                    'observation_unit':'supplied row','allocation_unit':'none','analysis':'Exact SQL sum, observational sample-level check.',
                    'purpose':'Test original finite prediction.','data_refs':[data],'mode':'observational',
                    'code':"import sqlite3,json,os\nfrom pathlib import Path\ndb=sqlite3.connect('file:'+str(Path(os.environ['PUBLIC_DIR'])/'business.sqlite')+'?mode=ro',uri=True)\nn,total=db.execute('SELECT count(*),sum(value) FROM observations').fetchone()\nprint(json.dumps({'n':n,'total':total}))"}
            elif not result:
                name,args='run_test',{'plan_ref':plan['ref']}
            elif not assessment:
                name='record_assessment';args=template('researcher','assessment')
                args.update(hypothesis_ref=h['ref'],result_refs=[result['ref']],status='supported',
                            prediction_coverage='Exact supplied-row sum was checked.',rationale='Actual sandbox returned n=8,total=36, satisfying the registered finite prediction.',
                            limitations=['A sample-level engineering check; no business mechanism or causal effect is established.'])
            elif pending:
                name,args='request_review',{'job_ref':pending[0],'reason':'Independently verify this candidate against original data.'}
            else:
                with sqlite3.connect(root/'researcher/private/records.sqlite') as db:
                    states=[json.loads(b) for b, in db.execute("SELECT body FROM records WHERE kind='state' AND rowid>?",(marker,))]
                if not states:
                    name='update_research_state';args=template('researcher','state')
                    args.update(question='Engineering-only finite research fixture.',why='Incorporate actual independent check.',understanding='The sample total is36 for8rows; no causal or general claim.',
                        active_hypothesis_refs=[item['ref'] for item in hs],focus_hypothesis_refs=[h['ref']],evidence_refs=[result['ref']],
                        incorporated_result_refs=[r['ref'] for r in results],next_action='Deliver the finite result and limits.',next_reason='The registered sample-level question has been checked.')
                else:
                    name='finish_research';args=template('researcher','finish')
                    args.update(assessment_refs=[a['ref'] for a in assessments],other_hypotheses={},
                        limitations=['Engineering fixture only; sample descriptions do not establish a commercial mechanism.'],
                        open_questions=['Further business research would need a substantive question.'])
        return {'choices':[{'finish_reason':'tool_calls','message':{'role':'assistant','content':'',
            'reasoning_content':'Deterministic engineering fixture, not model research.',
            'tool_calls':[{'id':'fixture-'+str(len(self.calls)),'type':'function','function':{'name':name,'arguments':json.dumps(args)}}]}}],
            'usage':{'prompt_tokens':20,'completion_tokens':5,'total_tokens':25}}


def main(output):
    output.mkdir(parents=True,exist_ok=False)
    data=output/'input';data.mkdir()
    with sqlite3.connect(data/'business.sqlite') as db:
        db.execute('CREATE TABLE observations(value INTEGER)');db.executemany('INSERT INTO observations VALUES (?)',[(n,) for n in range(1,9)])
    (data/'business_brief.md').write_text('Engineering fixture: eight supplied values. No real business claim.')
    write_json(data/'data_dictionary.json',{'tables':{'observations':{'value':'observed fixture number'}}})
    fixture=NativeFixture()
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            payload=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            if payload['model']=='fixture-redaction':
                self.send_response(500);self.end_headers()
                self.wfile.write(('Server echoed '+self.headers.get('Authorization','')).encode());return
            raw=json.dumps(fixture.response(payload)).encode()
            self.send_response(200);self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(raw)
        def log_message(self,*args):pass
    server=http.server.ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    model={'model':'local-native-fixture','base_url':f'http://127.0.0.1:{server.server_port}/v1',
        'request_timeout_seconds':10,'generation_options':{'max_tokens':65536,'thinking':{'type':'enabled'},'reasoning_effort':'high'}}
    checks={}
    try:
        root=output/'project';fixture.root=root
        create_project(root,'Engineering-only native research loop.',model,data=data,max_stages=2)
        result=run_project(root,stages=2)
        checks['two_actual_graph_research_stages']=result['status']=='completed' and len(recs(root,'report'))==2
        checks['two_native_hypothesis_test_assessment_cycles']=len(recs(root,'hypothesis'))==2 and len(recs(root,'result'))==2 and len(recs(root,'assessment'))==2
        checks['actual_sandbox_values_and_source_reads']=all(r['ok'] and json.loads(r['actual_execution']['stdout'])=={'n':8,'total':36} and r['actual_execution']['source_reads'] for r in recs(root,'result'))
        checks['both_roles_used_independent_tools']=sum(c['role']=='critic' for c in fixture.calls)>=6
        checks['formal_reports_readable_and_archived']=len(list((root/'deliveries').glob('F*.md')))==2
        checks['no_experiment_billing_required']='token_budget_pointer' not in model
        before=project_status(root)['execution_usage']
        run_project(root,stages=1)
        checks['completed_stage_limit_does_not_repay']=project_status(root)['execution_usage']==before
        _,project,ws,backend=open_project(root)
        try:
            checks['original_prediction_and_history_retained']=len(ws.records('hypothesis'))==2 and ws.stage_marker()>0
        finally:ws.close()
        pause_root=output/'pause_project';fixture.root=pause_root
        create_project(pause_root,'Cooperative pause/reopen fixture.',model,data=data,max_stages=1)
        _,_,ws,_=open_project(pause_root)
        try:
            denied=ws.call('query_data',{'sql':'DELETE FROM observations','purpose':'must deny write'},'fixture-denied-write')
            checks['sql_read_only']=denied.get('ok') is False
            denied=ws.call('collect_evidence',{'operation':'flow_audit','windows':1,'purpose':'must not invent measurement'},'fixture-denied-measurement')
            checks['missing_measurement_service_is_explicit']=denied.get('ok') is False
        finally:ws.close()
        request_pause(pause_root)
        paused=run_project(pause_root)
        checks['operator_pause_has_durable_handoff']=paused['status']=='pending' and (pause_root/'deliveries/阶段交接.md').is_file()
        resumed=run_project(pause_root,resume=True)
        checks['native_process_reopen_resumes_to_report']=resumed['status']=='completed'
        checks['full_model_capacity_and_thinking_kept']=all(c['max_tokens']==65536 and c['thinking']=={'type':'enabled'} for c in fixture.calls)
        rejected=[]
        for peer in root.glob('reviews/*/critic/private/critic.sqlite'):
            with sqlite3.connect(peer) as db:
                rejected.extend(json.loads(b) for b, in db.execute("SELECT result FROM operations WHERE json_extract(result,'$.ok')=0"))
        checks['producer_rejects_foreign_parent_ids_then_recovers']=len(rejected)>=4 and all('prior issue bindings' in a.get('error','') for a in rejected)
        import os
        variable='BUSINESS_RESEARCH_FIXTURE_CREDENTIAL';fake='sk-'+'SyntheticGuardCredentialOnly'+'123456'
        os.environ[variable]=fake
        try:
            redacted=call_model({**model,'model':'fixture-redaction','api_key_env':variable},
                {'model':'fixture-redaction','messages':[{'role':'user','content':'local redaction test'}]})
            checks['transport_never_serializes_echoed_credential']=fake not in json.dumps(redacted) and '[REDACTED]' in redacted.get('response_body','')
        finally:os.environ.pop(variable,None)
        lost_root=output/'lost_response_project'
        create_project(lost_root,'Interrupted local transport fixture.',model,data=data,max_stages=1)
        _,_,ws,b=open_project(lost_root)
        try:
            runtime=b.runtime;runtime.cp['messages']=runtime.initial();runtime.save()
            payload=runtime.payload();journal=b.journal;key=digest(['researcher',1])
            bound=b.budget.reserve(key,'researcher',payload)
            journal.state.update(attempts=1,inflight={'attempt':1,'study_key':key,'request_hash':digest(payload),'reservation':bound})
            journal.save();journal.persist_request(1,payload)
            n=len(fixture.calls);runtime.run(1)
            snap=b.budget.snapshot()
            checks['lost_response_keeps_reservation_and_no_implicit_resend']=len(fixture.calls)==n and snap['unknown_reserve']==bound and snap['http_attempts']==1 and journal.state['delivery'] is None
        finally:ws.close()
        ack_root=output/'error_delivery_project'
        create_project(ack_root,'Durable error delivery recovery fixture.',model,data=data,max_stages=1)
        _,_,ws,b=open_project(ack_root)
        try:
            rt=b.runtime;rt.cp['messages']=rt.initial();rt.save();payload=rt.payload()
            journal=b.journal;key=digest(['researcher',1]);bound=b.budget.reserve(key,'researcher',payload)
            journal.persist_request(1,payload);journal.persist_response(1,{'error_type':'http','http_status':502})
            b.budget.settle(key,digest(payload),None)
            item={'attempt':1,'study_key':key,'request_hash':digest(payload),'reservation':bound}
            journal.state.update(attempts=1,accounted_tokens=bound,inflight=None,delivery=item);journal.save()
            n=len(fixture.calls);rt.run(0);rt.run(0)
            checks['durable_error_ack_recovers_once_without_repay']=len(fixture.calls)==n and journal.state['delivery'] is None and rt.cp['transport_failures']==1 and b.budget.snapshot()['unknown_reserve']==bound
        finally:ws.close()
        assert all(checks.values()),checks
        report={'status':'passed','checks':checks,'external_provider_calls':0,'local_fixture_http':len(fixture.calls),
                'not_scientific_evidence':True,'fixture_only':True}
        write_json(output/'result.json',report);print(json.dumps(report))
        return report
    finally:server.shutdown();server.server_close()


if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);main(p.parse_args().output.resolve())
