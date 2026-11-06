"""Native HTTP/graph business coverage and unresolved-stage end-to-end fixtures."""
from copy import deepcopy
import argparse
import http.server
import json
from pathlib import Path
import sqlite3
import threading
from business_mechanism import create_project, run_project, project_status
from acceptance import NativeFixture, recs, template


class BusinessFixture(NativeFixture):
    def __init__(self, unresolved=False):
        super().__init__(); self.unresolved = unresolved; self.close_before_review = False; self.refuted = False; self.source_method=False; self.repair=False; self.disclosure=False; self.plain_output=False

    def response(self, payload):
        raw = super().response(payload)
        stage=json.loads((self.root/'project.json').read_text())['active_stage']
        function = raw['choices'][0]['message']['tool_calls'][0]['function']
        name = function['name']; args = json.loads(function['arguments'])
        critic=any(t['function']['name']=='record_review' for t in payload['tools'])
        if self.repair and not critic:
            with sqlite3.connect(self.root/'researcher/private/records.sqlite') as db:
                candidate=db.execute("SELECT a.ref,h.ref FROM records a JOIN records h ON h.ref=json_extract(a.body,'$.hypothesis_ref') WHERE a.kind='assessment' ORDER BY a.rowid DESC LIMIT 1").fetchone()
                if candidate:
                    reviewed=db.execute("SELECT review_ref FROM review_jobs WHERE target=? AND status='completed' ORDER BY rowid DESC LIMIT 1",(candidate[0],)).fetchone()
                    cleared=db.execute('SELECT 1 FROM clearances WHERE target=?',(candidate[0],)).fetchone()
                    state=db.execute('SELECT body FROM release_hypotheses WHERE ref=?',(candidate[1],)).fetchone()
                    if reviewed and not cleared:
                        if json.loads(state[0])['status']=='active':
                            name='close_hypothesis';args={'hypothesis_ref':candidate[1],'outcome':'inconclusive','reason':'Fixture closes the first incomplete verification; a later bounded directed check must retain this endpoint.','evidence_refs':[]}
                        else:
                            name='request_revalidation';args={'target_ref':candidate[0],'expected_review_ref':reviewed[0],'reason':'Complete the missing data-scope method check without changing the original target, prediction or evidence.'}
        if name == 'save_hypothesis':
            args['kind'] = 'business'
            if self.unresolved:
                args.update(statement='The unobserved future operational total remains positive.',
                    scope='A future window absent from the supplied eight historical rows.',
                    prediction='The total in an unsupplied future window is positive.',
                    falsification='A nonpositive total in that future window would reject the prediction.')
            if self.refuted:
                args.update(statement='The supplied finite sum is nonpositive.',prediction='The exact supplied sum is at or below zero.',
                            falsification='A positive exact supplied sum refutes this prediction.')
        if name == 'record_assessment' and self.refuted:
            args.update(status='refuted',rationale='The independently reproducible exact sum is positive; the original nonpositive prediction is refuted in this supplied dataset.')
        if name=='record_assessment' and self.unresolved:
            args.update(status='unresolved',rationale='The historical aggregate does not supply the requested future window.',
                        prediction_coverage='Only the historical proxy was computed; the future prediction is unobserved.')
        if name == 'record_assessment':
            h = args['hypothesis_ref']
            with sqlite3.connect(self.root/'researcher/private/records.sqlite') as db:
                spec = db.execute('SELECT 1 FROM release_analysis_specs WHERE target=?', (h,)).fetchone()
                source = db.execute("SELECT ref FROM files WHERE path='public/business.sqlite'").fetchone()[0]
                code = db.execute("SELECT ref FROM files WHERE path LIKE 'science/%.py' ORDER BY rowid DESC LIMIT 1").fetchone()
            if not spec:
                assert code, 'Actual executed scientific code ref required'
                name = 'register_analysis_spec'
                args = {'target_ref': h, 'spec': {'dataset_ref': source, 'filter': 'all eight supplied fixture rows',
                    'sampling': 'full supplied table', 'entity': [], 'grouping': {}, 'transformations': [],
                    'estimator': 'exact SQLite sample sum', 'uncertainty': 'descriptive engineering fixture only',
                    'required_components': ['data_scope', 'numeric_claim'], 'claim_level': 'descriptive', 'sampling_mode': 'census',
                    'code_ref': code[0]}}
                if self.source_method and stage==2: args['spec']['transformations']=['Square each raw supplied value before aggregation.']
        if name == 'record_review':
            ref = args['checks_performed'][0]['action_ref']
            args['coverage_checks'] = [{'component': component, 'action_ref': ref,
                'output_pointer': '/preview/0/0' if component=='data_scope' else '/preview/0/1',
                'relation': 'eq', 'expected': 8 if component=='data_scope' else 36 if stage==1 else 204}
                for component in ('claim_evidence', 'data_scope', 'numeric_claim')]
            if self.plain_output:
                with sqlite3.connect(self.root/'researcher/private/records.sqlite') as db:
                    job=db.execute("SELECT ref FROM review_jobs WHERE status='running' ORDER BY rowid DESC LIMIT 1").fetchone()[0]
                with sqlite3.connect(self.root/'reviews'/job/'critic/private/critic.sqlite') as db:
                    rendered=db.execute("SELECT ref FROM actions WHERE json_extract(body,'$.tool')='run_python' ORDER BY rowid DESC LIMIT 1").fetchone()
                if not rendered:
                    expression='value' if stage==1 else 'value*value'
                    name='run_python';args={'code':"import sqlite3,os\ndb=sqlite3.connect('file:'+os.path.join(os.environ['PUBLIC_DIR'],'business.sqlite')+'?mode=ro',uri=True)\nn,total=db.execute('SELECT count(*),sum("+expression+") FROM observations').fetchone()\nprint('rows='+str(n))\nprint('total='+str(total))",'purpose':'Independent exact plain-output fixture.'}
                else:
                    args['checks_performed'].append({'action_ref':rendered[0],'finding':'Actual computation emitted exact row and total lines; no numerical extraction or new data is inferred.','artifact_refs':[]})
                    args['coverage_checks']=[{'component':component,'basis':'recomputed','action_ref':rendered[0],
                        'output_pointer':'/stdout_lines/0' if component=='data_scope' else '/stdout_lines/1',
                        'relation':'eq','expected':'rows=8' if component=='data_scope' else 'total='+str(36 if stage==1 else 204)}
                        for component in ('claim_evidence','data_scope','numeric_claim')]
            if self.unresolved:
                target=args['source_refs'][0]
                args.update(target_conclusion='insufficient_evidence',prior_issue_updates={},
                    unchecked_scope=['The required future observation is not supplied.'],
                    issues=[{'issue_id':'FUTURE_WINDOW_UNAVAILABLE','type':'missing_evidence','basis':'observed','blocking':True,
                        'affected_refs':[target],'description':'The prediction concerns a future input window absent from the supplied historical fixture.',
                        'evidence_locations':[target],'action_refs':[ref],'check_artifact_refs':[],
                        'claim_impact':'Historical positive totals do not verify an unobserved future outcome.',
                        'minimal_next_step':'Obtain the actual future observation or leave the original prediction unresolved.'}],
                    open_issue_ids=['FUTURE_WINDOW_UNAVAILABLE'])
            if self.repair:
                with sqlite3.connect(self.root/'researcher/private/records.sqlite') as db:
                    job=db.execute("SELECT target,round FROM review_jobs WHERE status='running' ORDER BY rowid DESC LIMIT 1").fetchone()
                    kind=db.execute('SELECT kind FROM records WHERE ref=?',(job[0],)).fetchone()[0]
                if kind=='assessment' and job[1]==1:
                    args.update(target_conclusion='insufficient_evidence',prior_issue_updates={},unchecked_scope=['Data scope was not covered in this initial finite verification slice.'])
                    args['coverage_checks']=[c for c in args['coverage_checks'] if c['component']!='data_scope']
            if self.source_method and stage==2:
                with sqlite3.connect(self.root/'researcher/private/records.sqlite') as db:
                    job=db.execute("SELECT ref FROM review_jobs WHERE status IN ('pending','running') ORDER BY rowid DESC LIMIT 1").fetchone()[0]
                packet=json.loads((self.root/'reviews'/job/'inputs/packet.json').read_text())
                specs=packet['release_review_contract']['analysis_specs']
                code_ref=next(s['spec']['code_ref'] for s in specs if s['spec']['transformations'])
                with sqlite3.connect(self.root/'reviews'/job/'critic/private/critic.sqlite') as db:
                    read=db.execute("SELECT ref FROM actions WHERE json_extract(body,'$.tool')='read_artifact' AND json_extract(body,'$.arguments.ref')=? ORDER BY rowid DESC LIMIT 1",(code_ref,)).fetchone()
                if not read:
                    name='read_artifact';args={'ref':code_ref,'offset':0,'limit':12000}
                else:
                    args['coverage_checks'].append({'component':'transformation','basis':'source_inspected','action_ref':read[0],
                        'output_pointer':'/text','relation':'contains','expected':'value*value',
                        'justification':'The exact declared SQL inside this received source squares each raw value before SUM; the separate independent SQL reproduced its numeric result.'})
        if self.disclosure and not critic:
            if name=='request_review':
                name='close_hypothesis';args={'hypothesis_ref':recs(self.root,'hypothesis')[-1]['ref'],'outcome':'inconclusive',
                    'reason':'Fixture discloses that the finite candidate remains unreviewed; no scientific acceptance is asserted.','evidence_refs':[]}
            elif name=='finish_research':
                args.update(assessment_refs=[],other_hypotheses={h['ref']:'Unreviewed candidate, explicitly inconclusive; no scientific acceptance.' for h in recs(self.root,'hypothesis')})
        if self.disclosure and critic and name=='query_data':
            with sqlite3.connect(self.root/'researcher/private/records.sqlite') as db:
                job=db.execute("SELECT ref,target FROM review_jobs WHERE status='running' ORDER BY rowid DESC LIMIT 1").fetchone()
            with sqlite3.connect(self.root/'reviews'/job[0]/'critic/private/critic.sqlite') as db:
                audit=db.execute("SELECT ref FROM actions WHERE json_extract(body,'$.tool')='inspect_report_disclosure' ORDER BY rowid DESC LIMIT 1").fetchone()
            if not audit:name='inspect_report_disclosure';args={}
            else:
                name='record_review';args=template('critic','review_clean')
                args.update(source_refs=[job[1]],checked_scope=['Original records and disclosure of unreviewed candidates.'],
                    unchecked_scope=['No numerical or scientific hypothesis approval is asserted.'],
                    checks_performed=[{'action_ref':audit[0],'finding':'All received hypotheses are disclosed and there are no certified findings.','artifact_refs':[]}],
                    coverage_checks=[{'component':'record_fidelity','basis':'record_checked','action_ref':audit[0],
                        'output_pointer':'/checks/'+key,'relation':'eq','expected':True} for key in ['all_hypotheses_disclosed','no_certified_findings_asserted']])
        if name == 'finish_research' and self.close_before_review:
            with sqlite3.connect(self.root/'researcher/private/records.sqlite') as db:
                eligible={r[0] for r in db.execute('SELECT target FROM clearances')}
            args['assessment_refs']=[a['ref'] for a in recs(self.root,'assessment') if a['ref'] in eligible]
            supported_h={a['hypothesis_ref'] for a in recs(self.root,'assessment') if a['ref'] in eligible}
            args['other_hypotheses']={h['ref']:'Prior stage remains unresolved; no supported claim.' for h in recs(self.root,'hypothesis') if h['ref'] not in supported_h}
        if name == 'request_review' and self.close_before_review and stage==1:
            name='close_research_stage'
            args={'outcome':'blocked','reason':'Fixture closes a prior claim without review; later independent work must remain possible.',
                  'unresolved_refs':[a['ref'] for a in recs(self.root,'assessment')],'evidence_refs':[]}
        if name == 'finish_research' and self.unresolved:
            name = 'close_research_stage'
            args = {'outcome': 'unresolved', 'reason': 'This engineering fixture has no external mechanism validation.',
                    'unresolved_refs': [h['ref'] for h in recs(self.root, 'hypothesis')], 'evidence_refs': []}
        if name=='update_research_state' and self.unresolved:
            args.update(understanding='The historical aggregate is available; the actual future prediction remains unresolved.',
                        pending_claim_refs=[a['ref'] for a in recs(self.root,'assessment')],
                        next_action='Disclose the missing future observation without claiming verification.',
                        next_reason='No independent future measurement exists in the supplied snapshot.')
        function.update(name=name, arguments=json.dumps(args))
        return raw


def main(output):
    output.mkdir(parents=True, exist_ok=False)
    data = output/'input'; data.mkdir()
    with sqlite3.connect(data/'business.sqlite') as db:
        db.execute('CREATE TABLE observations(value INTEGER)')
        db.executemany('INSERT INTO observations VALUES (?)', [(i,) for i in range(1, 9)])
    (data/'business_brief.md').write_text('Synthetic business contract fixture; not a scientific result.')
    (data/'data_dictionary.json').write_text('{}')
    fixture = BusinessFixture()
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            response = json.dumps(fixture.response(payload)).encode()
            self.send_response(200); self.end_headers(); self.wfile.write(response)
        def log_message(self, *args): pass
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    model = {'model': 'business-fixture', 'base_url': f'http://127.0.0.1:{server.server_port}/v1',
             'request_timeout_seconds': 10, 'generation_options': {'max_tokens': 65536}}
    checks = {}
    try:
        for scenario in ('supported', 'source_method', 'plain_output', 'repair', 'disclosure', 'refuted', 'unresolved', 'prior_blocked'):
            unresolved=scenario=='unresolved'
            fixture.unresolved = unresolved
            fixture.close_before_review=scenario=='prior_blocked'
            fixture.refuted=scenario=='refuted'
            fixture.source_method=scenario=='source_method'
            fixture.plain_output=scenario=='plain_output'
            fixture.repair=scenario=='repair';fixture.disclosure=scenario=='disclosure'
            project = output/scenario; fixture.root = project
            create_project(project, 'Synthetic business review contract.', model, data=data, max_stages=2)
            result = run_project(project, stages=2)
            if scenario=='plain_output':
                checks['plain_computation_output_reaches_two_formal_reports'] = result['status']=='completed' and len(recs(project,'report'))==2
                checks['plain_output_assertions_preserve_exact_text_provenance'] = all(any(c.get('evidence_kind')=='exact_computation_text_not_numeric_parsing_or_new_observation' for c in r['method_coverage']['checks']) for r in recs(project,'review'))
            elif scenario=='repair':
                checks['incomplete_review_can_revalidate_same_target_to_formal_report'] = result['status']=='completed' and len(recs(project,'report'))==2
                with sqlite3.connect(project/'researcher/private/records.sqlite') as db:
                    states=[json.loads(b) for b, in db.execute('SELECT body FROM release_hypotheses')]
                    checks['old_inconclusive_endpoint_preserved_after_verified_completion'] = all(h['status']=='accepted_in_scope' and h.get('endpoint_history') and h['endpoint_history'][0]['outcome']=='inconclusive' for h in states)
                    checks['revalidation_does_not_create_new_hypotheses_or_results'] = len(recs(project,'hypothesis'))==2 and len(recs(project,'result'))==2
            elif scenario=='disclosure':
                checks['inconclusive_disclosure_can_formally_finish_without_numeric_claims'] = result['status']=='completed' and len(recs(project,'report'))==2
                with sqlite3.connect(project/'researcher/private/records.sqlite') as db:
                    checks['disclosure_never_grants_assessment_clearance'] = db.execute("SELECT count(*) FROM clearances c JOIN records r ON c.target=r.ref WHERE r.kind='assessment'").fetchone()[0]==0
            elif scenario=='source_method':
                checks['source_method_plus_independent_numbers_can_reach_formal_report'] = result['status']=='completed' and len(recs(project,'report'))==2
                reviews=recs(project,'review')
                checks['method_source_is_attributed_separately_from_recomputation'] = any(c.get('basis')=='source_inspected' and c['passed'] for r in reviews for c in r['method_coverage']['checks'])
            elif scenario=='refuted':
                checks['refuted_predictions_are_valid_formal_results'] = result['status']=='completed' and len(recs(project,'report'))==2 and all(a['status']=='refuted' for a in recs(project,'assessment'))
                with sqlite3.connect(project/'researcher/private/records.sqlite') as db:
                    checks['verified_refutations_have_terminal_endpoints'] = db.execute("SELECT count(*) FROM release_hypotheses WHERE json_extract(body,'$.status')='refuted'").fetchone()[0]==2
            elif scenario=='prior_blocked':
                checks['prior_blocked_claim_does_not_block_independent_formal_report'] = result['status']=='completed' and len(recs(project,'report'))==1
                with sqlite3.connect(project/'researcher/private/records.sqlite') as db:
                    checks['prior_pending_job_is_retained_as_blocked'] = db.execute("SELECT count(*) FROM review_jobs j JOIN release_task_state b ON j.ref=b.job WHERE j.status='pending'").fetchone()[0]==1
            elif unresolved:
                checks['unresolved_stage_is_distinct_from_formal_completion'] = result['status'] == 'stage_closed' and not recs(project, 'report')
                handoff=json.loads((project/'deliveries/latest.json').read_text())
                checks['unresolved_handoff_is_readable_and_distinct'] = handoff.get('stage_outcome') is not None and handoff['formal_report'] is None
                with sqlite3.connect(project/'researcher/private/records.sqlite') as db:
                    checks['two_unresolved_stages_closed_without_clearance_forgery'] = db.execute('SELECT count(*) FROM release_stage_outcomes').fetchone()[0] == 2
                before = project_status(project)['execution_usage']
                run_project(project)
                checks['closed_stage_limit_does_not_repay'] = project_status(project)['execution_usage'] == before
            else:
                checks['two_business_stages_reach_formal_reports'] = result['status'] == 'completed' and len(recs(project, 'report')) == 2
                reviews = recs(project, 'review')
                checks['all_business_reviews_have_actual_output_coverage'] = all(r['method_coverage']['clearance_eligible'] for r in reviews)
                with sqlite3.connect(project/'researcher/private/records.sqlite') as db:
                    checks['spec_registered_before_each_business_review'] = db.execute('SELECT count(*) FROM release_analysis_specs').fetchone()[0] == 2
                checks['original_hypotheses_and_computations_preserved'] = len(recs(project, 'hypothesis')) == 2 and len(recs(project, 'result')) == 2
        assert all(checks.values()), checks
        result = {'passed': True, 'checks': checks, 'local_fixture_http': len(fixture.calls), 'external_provider_calls': 0,
                  'scope': 'Business contract plumbing and stage lifecycle, not scientific certification.'}
        (output/'result.json').write_text(json.dumps(result, indent=2)+'\n'); print(json.dumps(result))
    finally:
        server.shutdown(); server.server_close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('--output', required=True, type=Path)
    main(parser.parse_args().output.resolve())
