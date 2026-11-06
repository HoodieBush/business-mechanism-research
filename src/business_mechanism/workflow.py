"""Review readiness, bounded stage exits and evidence-based liveness."""
import json
from pathlib import Path
import sqlite3
from experiments.insight_research.common import Pending, digest, encoded, now, write_json, sha
from experiments.insight_research.paired_v16.guard import ProgressGuard as BaseGuard
from .method_coverage import coverage_report,computation_output


METHOD_COMPONENTS = ('data_scope', 'sampling', 'grouping', 'transformation', 'estimator', 'numeric_claim')


def assert_review_work_drained(ws):
    """Closing a task cannot silently drop paid critic work or active compute."""
    roots = [ws.private, *ws.root.parent.glob('reviews/*/critic/private')]
    for private in roots:
        for name in ('checkpoint.json', 'transport.json'):
            path = private/name
            value = json.loads(path.read_text()) if path.exists() else {}
            if (private != ws.private and value.get('pending')) or value.get('inflight') or value.get('delivery'):
                raise ValueError('task_close_requires_drained_paid_work')
        data_db = private/'data_jobs.sqlite'
        if data_db.exists():
            with sqlite3.connect(data_db.as_uri()+'?mode=ro', uri=True) as db:
                if any(json.loads(b).get('status') in ('queued', 'running') for b, in db.execute('SELECT body FROM jobs')):
                    raise ValueError('task_close_requires_finished_or_cancelled_compute')


def spec_components(spec):
    if 'claim_level' not in spec:
        return set(METHOD_COMPONENTS)
    required = {'data_scope', 'numeric_claim', *spec['required_components']}
    if spec['claim_level'] in ('association','causal'): required.add('estimator')
    if spec.get('sampling_mode', 'sampled') == 'sampled': required.add('sampling')
    if spec['grouping']: required.add('grouping')
    if spec['transformations']: required.add('transformation')
    return required


def review_contract(ws, target_ref):
    target = ws.record(target_ref)
    # A report only asserts the assessments explicitly presented as findings.
    # Inactive/unresolved hypotheses are disclosure, never cleared premises.
    targets = [target_ref]
    if target['record_type'] == 'report_draft':
        for ref in target.get('assessment_refs', []):
            targets.extend([ref, *ws.target_hypotheses(ref)])
    else:
        targets.extend(ws.target_hypotheses(target_ref))
    targets = list(dict.fromkeys(targets))
    required = {'claim_evidence'}; specs = []; missing = []
    business = [t for t in targets if ws.record(t).get('kind') == 'business']
    for ref in targets:
        row = ws.db.execute('SELECT version,spec_ref,body FROM release_analysis_specs WHERE target=?', (ref,)).fetchone()
        if row:
            if row[0] != digest(ws.record(ref)):
                raise ValueError('analysis_spec_target_version_changed')
            spec = json.loads(row[2]); required.update(spec_components(spec))
            specs.append({'target_ref': ref, 'analysis_spec_ref': row[1], 'spec': spec})
    if business:
        for ref in business:
            if not any(s['target_ref'] == ref or ref in ws.target_hypotheses(s['target_ref']) for s in specs):
                missing.append(ref)
    if business and not specs: required.update(METHOD_COMPONENTS)
    disclosure=target['record_type']=='report_draft' and not target.get('assessment_refs')
    if disclosure:required={'record_fidelity'}
    return {'target_ref': target_ref, 'target_version': digest(target),
            'review_kind':'disclosure' if disclosure else 'findings',
            'required_components': sorted(required), 'analysis_specs': specs,
            'missing_spec_targets': missing, 'ready': not missing,
            'acceptance_policy': 'Check the frozen claim, dataset and applicable methods. Observational association does not require causal identification; it cannot be accepted as a causal mechanism. Out-of-scope suggestions are advisory. Negative/inconclusive findings can be correct and deliverable.',
            'repair': 'Register an exact analysis spec before request_review. Use a new scientific version when a consumed snapshot/lineage cannot be changed. close_research_stage preserves honest unresolved work without granting clearance.'}


def review_coverage(peer, body):
    contract = peer.packet.get('release_review_contract')
    if contract is None:
        candidate = peer.packet.get('candidate_record', {})
        contract = {'required_components': ['claim_evidence'], 'ready': False,
                    'missing_spec_targets': [candidate.get('ref')], 'legacy_snapshot': True}
    declared_sources={s['spec']['code_ref'] for s in contract.get('analysis_specs',[])}
    def method_source(ref):
        path=peer.file(ref)[0]
        if ref not in declared_sources and not path.is_relative_to(peer.science/'compute'):
            raise ValueError('method source must be the declared analysis code or reviewer execution source, not unrelated public utilities')
        return path
    report = coverage_report(body.get('coverage_checks', []), peer.action,
                             required=contract['required_components'], source_file=method_source,
                             record_target=contract['target_ref'] if contract.get('review_kind')=='disclosure' else None,
                             record_packet_digest=peer.identity['packet_digest'])
    report['review_contract'] = contract
    if not contract.get('ready'):
        report.update(clearance_eligible=False, analysis_spec_missing=True)
    return report


def coverage_errors(peer, body):
    if body.get('phase') != 'complete' or body.get('target_conclusion') != 'consistent_in_checked_scope':
        return []
    report = review_coverage(peer, body)
    if report['clearance_eligible']:
        return []
    return [{'path': '/coverage_checks', 'error_code': 'coverage_incomplete', 'coverage': report,
             'repair': 'Use get_review_contract for actual computation and Python/SQL source-read receipts. Numeric claims need independent computation; methods may use explicit source_inspected /text contains checks with justification, or explained shared computations linked to exact executed code fragments. Do not invent distinct numeric fields for each method. If evidence is still inadequate, complete insufficient_evidence and state the actual unchecked scope.'}]


def recheck_saved_coverage(ws,review,contract):
    """Replay exact archived assertions under today's gate; no model or compute."""
    job=review['job_ref']; declared={s['spec']['code_ref'] for s in contract.get('analysis_specs',[])}
    operations={}
    for ref,body in ws.db.execute("SELECT ref,body FROM records WHERE kind='review_action'"):
        item=json.loads(body);operations[ref]=item['operation']
        if item['job_ref']==job:operations[item['origin_action_ref']]=item['operation']
    executed={op['result']['execution']['code_file'] for op in operations.values()
              if op.get('tool')=='run_python' and op.get('result',{}).get('execution',{}).get('code_file')}
    def source(ref):
        path=ws.file(ref)[0]
        if ref not in declared and str(path) not in executed:
            raise ValueError('saved method source is not declared or an archived reviewer execution')
        return path
    identity=json.loads((ws.root.parent/'reviews'/job/'critic/private/identity.json').read_text())
    return coverage_report(review['method_coverage']['checks'],lambda ref:operations[ref],
        required=contract['required_components'],source_file=source,
        record_target=contract['target_ref'] if contract.get('review_kind')=='disclosure' else None,
        record_packet_digest=identity['packet_digest'])


def action_catalog(peer):
    values = []
    rows=[(ref,json.loads(body),'current') for ref,body in peer.db.execute('SELECT ref,body FROM actions ORDER BY rowid DESC LIMIT 24')]
    known={ref for ref,_,_ in rows}
    for check in (peer.packet.get('previous_feedback') or {}).get('checks_performed',[])[:16]:
        ref=check['action_ref']
        if ref in known:continue
        try:rows.append((ref,peer.action(ref),'prior_directed_review'));known.add(ref)
        except ValueError:pass
    for ref,item,origin in rows:
        tool = item['tool']; result = item.get('result', {})
        if tool=='inspect_report_disclosure' and result.get('target_ref')==peer.packet['target_ref']:
            values.append({'action_ref':ref,'tool':tool,'origin':origin,'basis':'record_checked',
                           'actual_output_paths':[{'output_pointer':'/checks/'+key,'observed':value} for key,value in result['checks'].items()]})
        if tool in ('read_memory','read_artifact') and result.get('ok') is not False:
            source=item.get('arguments',{}).get('ref','')
            try:
                if source.startswith('file:') and peer.file(source)[0].suffix.lower() in ('.py','.sql'):
                    text=result.get('text','')
                    fragments=[line.strip() for line in text.splitlines() if 8<=len(line.strip())<=160][:6]
                    values.append({'action_ref':ref,'tool':tool,'source_ref':source,'output_pointer':'/text',
                                   'basis':'source_inspected','exact_fragment_examples':fragments,
                                   'origin':origin,'new_computation_in_this_review':False,
                                   'actual_output_paths':[],
                                   'policy':'Explain the checked method component; source inspection cannot cover numeric_claim or claim_evidence.'})
            except ValueError: pass
        if tool not in ('query_data', 'read_data_result', 'run_python', 'inspect_evidence') or result.get('ok') is False:
            continue
        if tool == 'run_python':
            try: result = computation_output(result['execution'])
            except (ValueError, KeyError, TypeError): continue
        roots = {k: v for k, v in result.items() if k in ('preview', 'rows', 'parsed_stdout', 'statistics','stdout_lines')}
        pointers = []
        def walk(value, path, depth=0):
            if len(pointers) >= 12 or depth > 5: return
            if isinstance(value, dict):
                for key, child in value.items(): walk(child, path+'/'+str(key).replace('~', '~0').replace('/', '~1'), depth+1)
            elif isinstance(value, list):
                for i, child in enumerate(value[:12] if path=='/stdout_lines' else value[:3]): walk(child, path+'/'+str(i), depth+1)
            elif isinstance(value, (int, float, bool)) or value is None or isinstance(value, str) and len(value) < 100:
                pointers.append({'output_pointer': path, 'observed': value})
        for key, value in roots.items(): walk(value, '/'+key)
        values.append({'action_ref': ref, 'tool': tool,'origin':origin,'new_computation_in_this_review':origin=='current', 'actual_output_paths': pointers,
                       'pointer_inventory_is_partial':True,'pointer_limit':12,'instruction':'Only listed paths/values are shown here. Read the exact original computation for further fields; never infer complete coverage from this bounded inventory.'})
    return values


def stage_number(ws):
    return ws.db.execute('SELECT max(stage) FROM release_stages').fetchone()[0]


def archive_stage_window(runtime):
    messages = runtime.cp['messages']; archive_id = digest(messages)
    directory = runtime.ws.private/'context_archives'
    path = directory/(archive_id+'.json')
    if path.exists() and json.loads(path.read_text()) != messages:
        raise Pending('owned context archive changed')
    if not path.exists(): write_json(path, messages)
    write_json(directory/'latest.json', {'archive_id': archive_id, 'read_ref': 'own_context:'+archive_id,
        'last_model_response': runtime.cp.get('responses', 0), 'no_scientific_summary_generated': True,
        'no_results_marked_incorporated': True, 'reason': 'stage transition; exact old window retained'})
    return archive_id


def stage_outcome(ws):
    row = ws.db.execute('SELECT body FROM release_stage_outcomes WHERE stage=?', (stage_number(ws),)).fetchone()
    return json.loads(row[0]) if row else None


def close_stage(ws, *, outcome, reason, unresolved_refs, evidence_refs, key, actor='researcher'):
    previous = stage_outcome(ws)
    if previous: return previous
    if ws.report():
        raise ValueError('formal_stage_already_completed: advance without replacing its outcome')
    ws.references([*unresolved_refs, *evidence_refs])
    # Only private checkpoints of the live project; never archived copies.
    private_roots = [ws.private, *ws.root.parent.glob('reviews/*/critic/private')]
    for private in private_roots:
        data_db = private/'data_jobs.sqlite'
        if data_db.exists():
            with sqlite3.connect(data_db.as_uri()+'?mode=ro', uri=True) as db:
                if any(json.loads(b).get('status') in ('queued', 'running') for b, in db.execute('SELECT body FROM jobs')):
                    raise ValueError('stage_close_requires_finished_or_cancelled_compute')
        for name in ('checkpoint.json', 'transport.json'):
            path = private/name
            value = json.loads(path.read_text()) if path.exists() else {}
            pending = value.get('pending')
            # close_research_stage is itself a paid single-call tool batch.
            if pending and not (private == ws.private and len(pending.get('calls', [])) == 1
                                and pending['calls'][0]['name'] == 'close_research_stage'):
                raise ValueError('stage_close_requires_drained_paid_tools')
            if value.get('inflight') or value.get('delivery'):
                raise ValueError('stage_close_requires_acknowledged_transport')
    jobs = ws.jobs('pending')+ws.jobs('running')
    for job in jobs:
        ws.db.execute('INSERT OR REPLACE INTO release_task_state VALUES (?,?,?)',
                      (job['ref'], 'blocked_execution', 'Stage closed unresolved; review not completed or cleared'))
    item = {'ref': 'stage:'+digest([stage_number(ws), key])[:24], 'stage': stage_number(ws),
            'outcome': outcome, 'reason': reason, 'unresolved_refs': unresolved_refs,
            'evidence_refs': evidence_refs, 'created_at': now(), 'actor': actor,
            'formal_report_ref': None, 'scientific_certification': False,
            'recorded_unverified_claim_refs': [a['ref'] for a in ws.records('assessment') if not ws.clearance(a['ref'])],
            'evidence_fingerprint': EvidenceProgressGuard(ws.root.parent, ws, ws.study_budget).fingerprint()}
    ws.db.execute('INSERT INTO release_stage_outcomes VALUES (?,?)', (item['stage'], encoded(item)))
    from .verification_tasks import record_execution_handoff
    record_execution_handoff(ws,item)
    directory = ws.root.parent/'deliveries'; directory.mkdir(exist_ok=True)
    write_json(directory/('stage-'+str(item['stage'])+'-unresolved.json'), item)
    return item


def stage_health(ws):
    stage = stage_number(ws)
    row = ws.db.execute('SELECT count(*) FROM release_delivery_attempts WHERE stage=?', (stage,)).fetchone()
    return {'stage': stage, 'outcome': stage_outcome(ws), 'delivery_attempts': row[0],
            'clearances': ws.db.execute('SELECT count(*) FROM clearances').fetchone()[0],
            'policy': 'A closed unresolved stage is a handoff, not a formal scientific report.'}


def delivery_preflight(ws, args, key):
    previous = stage_outcome(ws)
    if previous: return {'ok': False, 'error_code': 'stage_already_closed', 'stage_outcome': previous}
    prior_reports=ws.records('report')
    published={ref for r in prior_reports for ref in r.get('assessment_refs',[])}
    selected=args.get('assessment_refs',[])
    from .verification_tasks import undisclosed_endpoints,followup
    if prior_reports and ((selected and set(selected)<=published) or (not selected and not undisclosed_endpoints(ws))):
        return {'ok':False,'error_code':'no_new_report_scope',
                'next_action':'This verified finding/disposition was already delivered. Continue an existing active goal or choose a new worthwhile hypothesis; old report prose is not new research. Keep the prior report archived.'}
    fingerprint = EvidenceProgressGuard(ws.root.parent, ws, ws.study_budget).fingerprint()
    stage = stage_number(ws)
    ws.db.execute('INSERT OR IGNORE INTO release_delivery_attempts VALUES (?,?,?)', (key, stage, fingerprint))
    count = ws.db.execute('SELECT count(*) FROM release_delivery_attempts WHERE stage=? AND fingerprint=?', (stage, fingerprint)).fetchone()[0]
    invalid = [ref for ref in args.get('assessment_refs', []) if not ws.clearance(ref)]
    latest = ws.records('report_draft')
    live = latest[-1] if latest and ws.after_marker(latest[-1]['ref']) else None
    if live:
        jobs = [j for status in ('pending', 'running', 'completed', 'exhausted') for j in ws.jobs(status) if j['target_ref'] == live['ref']]
        if (args.get('supersedes_draft_ref') == live['ref'] and not invalid and not ws.unanswered()
                and any(j['status'] == 'completed' and j['round'] < ws.workflow.get('max_lineage_reviews', 4) for j in jobs)):
            return None  # Explicit, bounded revision after attributed feedback.
        contracts = [review_contract(ws, r) for r in invalid]
        return {'ok': False, 'error_code': 'existing_stage_draft', 'draft_ref': live['ref'],
                'review_jobs': jobs, 'unverified_assessments': invalid, 'repair_contracts': contracts,
                'next_action': 'Read exact review/coverage feedback; revise a scientific claim with new evidence, or close_research_stage as unresolved. Repeated finish does not create a new draft.', 'delivery_attempts_without_new_evidence': count}
    if invalid:
        return {'ok': False, 'error_code': 'report_claims_unverified', 'unverified_assessments': invalid,
                'repair_contracts': [review_contract(ws, ref) for ref in invalid],
                'verification_followups':[followup(ws,ref) for ref in invalid],
                'next_action': 'Use request_revalidation for a completed opinion with a repairable coverage gap. If no scientific finding can be verified, finish_research with assessment_refs=[] discloses recorded unresolved endpoints without granting science clearance. Do not resubmit unverified findings.',
                'delivery_attempts_without_new_evidence': count}
    return None


class EvidenceProgressGuard(BaseGuard):
    """Narrative state, report prose, IDs and repeated stage exits are not evidence."""
    def fingerprint(self):
        signatures = set(); components = set(); contracts = set()
        databases = [self.owner.db]
        opened = []
        for path in self.root.glob('reviews/*/critic/private/critic.sqlite'):
            db = sqlite3.connect(path.as_uri()+'?mode=ro', uri=True); databases.append(db); opened.append(db)
        try:
            for db in databases:
                for path, version in db.execute('SELECT path,hash FROM files'):
                    if path.endswith(('rows.csv', '_stdout.txt', 'result.sqlite')):
                        signatures.add(version)
            for body, in self.owner.db.execute("SELECT body FROM records WHERE kind='review'"):
                cov = json.loads(body).get('method_coverage', {})
                specs=cov.get('review_contract',{}).get('analysis_specs',[])
                # A check of a genuinely different data/code contract advances
                # that verification task, even when other targets already had
                # the same component names. Object IDs/prose do not suffice.
                material=[]
                for s in specs:
                    spec=s['spec']; versions=[]
                    for k in ('dataset_ref','code_ref'):
                        row=self.owner.db.execute('SELECT hash FROM files WHERE ref=?',(spec[k],)).fetchone()
                        versions.append(row[0] if row else spec[k])
                    material.append(versions)
                for c in cov.get('covered_components',[]):
                    proofs=[{k:x.get(k) for k in ('output_pointer','relation','expected','observed','observed_fragment','source_text_hash')}
                            for x in cov.get('checks',[]) if x.get('passed') and x['component']==c]
                    components.add(digest([sorted(set(map(tuple,material))),c,proofs]))
            # A newly bound input/code/method contract is concrete repair of
            # readiness. Rebinding identical specs to new IDs is deduplicated.
            for body, in self.owner.db.execute('SELECT body FROM release_analysis_specs'):
                spec=json.loads(body);versions=[]
                for key in ('dataset_ref','code_ref'):
                    row=self.owner.db.execute('SELECT hash FROM files WHERE ref=?',(spec[key],)).fetchone()
                    versions.append(row[0] if row else spec[key])
                contracts.add(digest([versions,sorted(spec['required_components']),spec.get('claim_level'),spec.get('sampling_mode')]))
        finally:
            for db in opened: db.close()
        return digest([sorted(signatures), sorted(components), sorted(contracts)])

    def inspect(self):
        value = super().inspect()
        from .recovery import recovery_baseline
        baseline = recovery_baseline(self.budget, self.fingerprint())
        count = self.budget.snapshot()['http_attempts']
        with self.budget.connect() as db:
            last=db.execute('SELECT last_progress_request FROM execution_control WHERE id=1').fetchone()[0]
            def researcher_since(index):
                return db.execute("SELECT count(*) FROM (SELECT role FROM attempts ORDER BY rowid LIMIT -1 OFFSET ?) WHERE role='researcher'",(index,)).fetchone()[0]
            researcher_stalled=researcher_since(last)
            rotation_stalled=researcher_since(baseline) if baseline else None
        value['researcher_requests_without_structural_progress']=researcher_stalled
        value['requests_since_last_task_rotation'] = count-baseline if baseline else None
        value['effective_requests_without_progress'] = min(researcher_stalled, rotation_stalled) if baseline else researcher_stalled
        with self.budget.connect() as db:
            deliveries=list(db.execute('SELECT report,at_request FROM release_delivery_epochs')) if db.execute("SELECT 1 FROM sqlite_master WHERE name='release_delivery_epochs'").fetchone() else []
        latest=max((n for ref,n in deliveries if self.owner.db.execute("SELECT 1 FROM records WHERE ref=? AND kind='report'",(ref,)).fetchone()),default=0)
        value['requests_since_last_verified_delivery']=count-latest if latest else None
        if latest:
            with self.budget.connect() as db:
                after_delivery=db.execute("SELECT count(*) FROM (SELECT role FROM attempts ORDER BY rowid LIMIT -1 OFFSET ?) WHERE role='researcher'",(latest,)).fetchone()[0]
            value['effective_requests_without_progress']=min(value['effective_requests_without_progress'],after_delivery)
        with self.budget.connect() as db:
            authorizations=[json.loads(b) for b, in db.execute('SELECT body FROM release_authorization_windows')] if db.execute("SELECT 1 FROM sqlite_master WHERE name='release_authorization_windows'").fetchone() else []
            active=[a for a in authorizations if a['started_unix']==value['started_at_unix'] and a['deadline_unix']==value['deadline_unix']]
            if active:
                authorization=max(active,key=lambda a:a['started_unix'])
                position=authorization['inherited_usage']['http_attempts']
                authorization_requests=db.execute("SELECT count(*) FROM (SELECT role FROM attempts ORDER BY rowid LIMIT -1 OFFSET ?) WHERE role='researcher'",(position,)).fetchone()[0]
                value['requests_since_explicit_authorization']=authorization_requests
                value['effective_requests_without_progress']=min(value['effective_requests_without_progress'],authorization_requests)
        value['progress_basis'] = 'Researcher no-progress admission excludes independently bounded critic requests. Raw all-role history, costs, output/code/method evidence and deadline remain unchanged. Operational handoff is not a scientific result.'
        write_json(self.root/'semantic_health.json', value)
        return value

    def admit(self, timeout, *, workflow_closeout=False, bounded_goal=False):
        value = self.inspect()
        if value['remaining_wall_seconds'] < timeout+45:
            raise Pending('persistent study wall deadline cannot admit a new request; paid work retained')
        if value['effective_requests_without_progress'] >= self.stop and not (workflow_closeout or bounded_goal):
            raise Pending('semantic_stagnation: no new computation content or method coverage within the registered request bound; preserve unresolved work')
        if workflow_closeout and value['effective_requests_without_progress'] >= self.stop:
            value['bounded_workflow_closeout_admitted']=True
            value['admission_reason']='A registered finite verification/publication slice or four-request terminal-task delivery closeout is admitted; scientific progress counter is not reset and shared deadline/costs remain authoritative.'
            write_json(self.root/'semantic_health.json',value)
        if bounded_goal:
            value['bounded_goal_work_admitted']=True
            write_json(self.root/'semantic_health.json',value)
        rows = self.owner.db.execute('SELECT body FROM release_stage_outcomes ORDER BY stage DESC LIMIT 3').fetchall()
        if (len(rows) == 3 and len({json.loads(r[0])['evidence_fingerprint'] for r in rows}) == 1
                and json.loads(rows[0][0])['evidence_fingerprint']==self.fingerprint()
                and value['requests_since_last_task_rotation'] is None and not (workflow_closeout or bounded_goal)):
            raise Pending('semantic_stagnation: three closed stages without new evidence or coverage; further stage churn is blocked')
        return value
