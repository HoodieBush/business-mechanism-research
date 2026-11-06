"""Explicit bounded verification work and honest disclosure-only delivery."""
from experiments.insight_research.common import digest, encoded, now, write_json
from .workflow import review_contract


def followup(ws, target_ref):
    target=ws.record(target_ref); jobs=[j for j in ws.jobs() if j['target_ref']==target_ref]
    result={'target_ref':target_ref,'eligible':False,'tool':'request_revalidation'}
    if target['record_type'] not in ('assessment','knowledge') or ws.clearance(target_ref) or not jobs:return result
    latest=jobs[-1]
    if latest['status'] in ('pending','running'):
        return {**result,'existing_job_ref':latest['ref'],'reason':'An existing review must complete or receive an explicit allocation; do not duplicate it.'}
    if latest['status']!='completed' or not latest['review_ref']:return result
    review=ws.record(latest['review_ref'],'review');cov=review.get('method_coverage',{})
    count=ws.db.execute('SELECT count(*) FROM review_jobs WHERE episode=?',(latest['episode'],)).fetchone()[0]
    eligible=(review['target_conclusion'] in ('insufficient_evidence','consistent_in_checked_scope')
              and bool(cov.get('missing_components') or cov.get('analysis_spec_missing'))
              and not ws.blocked(target_ref) and review_contract(ws,target_ref)['ready']
              and count<ws.workflow.get('max_lineage_reviews',4))
    return {**result,'eligible':eligible,'expected_review_ref':review['ref'],
            'missing_components':cov.get('missing_components',[]),'remaining_lineage_reviews':max(0,ws.workflow.get('max_lineage_reviews',4)-count),
            'reason':'The previous review completed without method coverage; request a bounded directed revalidation of the unchanged target. This is not a new sample or automatic approval.'}


def repair_tasks(ws):
    tasks=[task for a in reversed(ws.records('assessment')[-16:]) if (task:=followup(ws,a['ref']))['eligible']]
    return sorted(tasks,key=lambda task:len(task['missing_components']))[:4]


def unpublished_findings(ws, *, include_deferred=False):
    published={ref for r in ws.records('report') for ref in r.get('assessment_refs',[])}
    values=[]
    for a in ws.records('assessment'):
        if a['ref'] in published or not ws.clearance(a['ref']):continue
        if not include_deferred and ws.db.execute('SELECT 1 FROM meta WHERE key=?',('release_publication_handoff:'+a['ref'],)).fetchone():continue
        try:ws.premise(a['ref'])
        except ValueError:continue
        handoff=ws.db.execute('SELECT value FROM meta WHERE key=?',('release_publication_handoff:'+a['ref'],)).fetchone()
        values.append({'assessment_ref':a['ref'],'hypothesis_ref':a['hypothesis_ref'],'status':a['status'],
                       'publication_handoff':__import__('json').loads(handoff[0]) if handoff else None})
    return values


def undisclosed_endpoints(ws):
    from . import convergence
    return [h for h in convergence.items(ws) if h.get('endpoint') and not ws.db.execute(
        'SELECT 1 FROM release_reported_endpoints WHERE hypothesis=? AND operation=?',
        (h['hypothesis_ref'],h['endpoint']['operation'])).fetchone()]


def record_execution_handoff(ws, outcome):
    """A saved unresolved handoff ends an execution obligation, never science."""
    from . import convergence
    mentioned=set()
    for ref in outcome['unresolved_refs']:
        row=ws.db.execute("SELECT body FROM records WHERE ref=? AND kind='assessment'",(ref,)).fetchone()
        if not row or not ws.clearance(ref):continue
        review_ref=ws.db.execute('SELECT review_ref FROM clearances WHERE target=?',(ref,)).fetchone()[0]
        if ws.record(review_ref,'review')['created_at']>outcome['created_at']:continue
        ws.db.execute('INSERT OR IGNORE INTO meta VALUES (?,?)',('release_publication_handoff:'+ref,
            encoded({'assessment_ref':ref,'assessment_version':digest(__import__('json').loads(row[0])),
                'stage_outcome_ref':outcome['ref'],'reason':outcome['reason'],
                'scientific_clearance_revoked':False,'formal_report':False})))
    for ref in outcome['unresolved_refs']+outcome['evidence_refs']:
        if ws.db.execute('SELECT 1 FROM records WHERE ref=?',(ref,)).fetchone():
            mentioned.update(ws.target_hypotheses(ref))
        if ref.startswith('H'):mentioned.add(ref)
    for h in convergence.items(ws):
        endpoint=h.get('endpoint')
        if endpoint and endpoint['created_at']<=outcome['created_at'] and h['hypothesis_ref'] in mentioned:
            ws.db.execute('INSERT OR IGNORE INTO meta VALUES (?,?)',
                ('release_execution_handoff:'+endpoint['operation'],encoded({'hypothesis_ref':h['hypothesis_ref'],
                 'endpoint_operation':endpoint['operation'],'stage_outcome_ref':outcome['ref'],
                 'formal_report':False,'scientific_clearance':False})))


def initialize_handoffs(ws):
    # Backfill operational receipts from exact archived outcomes once after an
    # explicit upgrade. Original outcomes/records are never rewritten.
    marker='release_execution_handoffs_initialized_v2'
    if not ws.db.execute('SELECT 1 FROM meta WHERE key=?',(marker,)).fetchone():
        for body, in ws.db.execute('SELECT body FROM release_stage_outcomes ORDER BY stage'):
            record_execution_handoff(ws,__import__('json').loads(body))
        ws.db.execute('INSERT OR IGNORE INTO meta VALUES (?,?)',(marker,now()))


def pending_disclosures(ws):
    return [h for h in undisclosed_endpoints(ws) if not ws.db.execute('SELECT 1 FROM meta WHERE key=?',
            ('release_execution_handoff:'+h['endpoint']['operation'],)).fetchone()]


def closeout_scope(ws):
    return digest([sorted((h['hypothesis_ref'],h['endpoint']['operation']) for h in pending_disclosures(ws)),
                   sorted(a['assessment_ref'] for a in unpublished_findings(ws))])


def phase(ws):
    from . import convergence
    if repair_tasks(ws):return 'repair_verification'
    if unpublished_findings(ws):return 'deliver_verified_findings'
    if convergence.active_refs(ws):return 'finish_active_goal'
    if pending_disclosures(ws):return 'disclose_closed_goals'
    return 'choose_next_goal'


def record_delivery(ws,report):
    from . import convergence
    marker='release_delivery_recorded:'+report['ref']
    if ws.db.execute('SELECT 1 FROM meta WHERE key=?',(marker,)).fetchone():return
    # A genuinely verified delivery can open a fresh bounded work window; it
    # does not reset the separate scientific-evidence no-progress counter.
    if report.get('assessment_refs') and all(ws.clearance(r) for r in report['assessment_refs']):
        from .workflow import EvidenceProgressGuard
        fingerprint=EvidenceProgressGuard(ws.root.parent,ws,ws.study_budget).fingerprint()
        with ws.study_budget.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS release_delivery_epochs(report TEXT PRIMARY KEY,at_request INTEGER,fingerprint TEXT)')
            valid=[(ref,n,fp) for ref,n,fp in db.execute('SELECT report,at_request,fingerprint FROM release_delivery_epochs ORDER BY at_request,rowid')
                   if ws.db.execute("SELECT 1 FROM records WHERE ref=? AND kind='report'",(ref,)).fetchone()]
            if not valid or valid[-1][2]!=fingerprint:
                db.execute('INSERT OR IGNORE INTO release_delivery_epochs VALUES (?,?,?)',
                           (report['ref'],ws.study_budget.snapshot()['http_attempts'],fingerprint))
    mentioned=set(report.get('other_hypotheses',{}))
    mentioned.update(ws.record(ref,'assessment')['hypothesis_ref'] for ref in report.get('assessment_refs',[]))
    for h in convergence.items(ws):
        if h['hypothesis_ref'] in mentioned and h.get('endpoint'):
            ws.db.execute('INSERT OR IGNORE INTO release_reported_endpoints VALUES (?,?,?)',
                (h['hypothesis_ref'],h['endpoint']['operation'],report['ref']))
    ws.db.execute('INSERT OR IGNORE INTO meta VALUES (?,?)',(marker,now()))


def request(ws, args, key):
    task=followup(ws,args['target_ref'])
    if task.get('existing_job_ref'):
        return {'ok':False,'error_code':'review_already_active','followup':task}
    if task.get('expected_review_ref')!=args['expected_review_ref']:
        return {'ok':False,'error_code':'review_followup_version_conflict','followup':task}
    if not task['eligible']:
        return {'ok':False,'error_code':'review_followup_not_available','followup':task,
                'next_action':'Substantive changes need a new scientific version/evidence; exhausted lineages remain unresolved. A complete review is not automatically clearance.'}
    job=ws.enqueue(args['target_ref'],args['target_ref'],parent_review=args['expected_review_ref'],reason=args['reason'])
    scheduled=ws._checked_dispatch('request_review',{'job_ref':job,'reason':args['reason']},key+':delegate')
    return {**scheduled,'new_job_ref':job,'previous_review_ref':args['expected_review_ref'],
            'unchanged_target_version':digest(ws.record(args['target_ref'])),'scientific_status_changed':False,
            'meaning':'Only verification is scheduled. Previous opinions, original criteria and costs are retained.'}


def inspected_disclosure(peer):
    candidate=peer.packet['candidate_record']
    if candidate['record_type']!='report_draft' or candidate.get('assessment_refs'):
        raise ValueError('disclosure_audit_requires_report_without_certified_findings')
    received={r for r, in peer.view.db.execute("SELECT ref FROM docs WHERE kind='hypothesis'")}
    disclosed=set(candidate.get('other_hypotheses',{}))
    return {'target_ref':peer.packet['target_ref'],'packet_digest':peer.identity['packet_digest'],
            'checks':{'all_hypotheses_disclosed':received<=disclosed,
                      'no_certified_findings_asserted':not candidate.get('assessment_refs')},
            'hypothesis_count':len(received),'certified_finding_count':0,
            'scope':'Record/disposition disclosure only. Reviewer must inspect accuracy and misleading prose. No hypothesis or assessment receives scientific clearance from this audit.'}


def record_verified_endpoint(ws, job):
    target=ws.record(job['target_ref'])
    if target['record_type']!='assessment' or not ws.clearance(target['ref']):return
    from . import convergence
    h=convergence.get(ws,target['hypothesis_ref'])
    latest=next((a for a in reversed(ws.records('assessment')) if a['hypothesis_ref']==target['hypothesis_ref']),None)
    if not latest or latest['ref']!=target['ref']:return
    key='verified:'+ws.job(job['ref'])['review_ref']
    if ws.db.execute('SELECT 1 FROM release_hypothesis_events WHERE operation=?',(key,)).fetchone():return
    endpoint={'hypothesis_ref':target['hypothesis_ref'],
        'outcome':{'supported':'accepted_in_scope','refuted':'refuted'}.get(target['status'],'inconclusive'),
        'reason':'A new independently completed review verified this assessment under the unchanged original hypothesis criteria.',
        'assessment_ref':target['ref'],'evidence_refs':target['result_refs'],'successor_ref':None,
        'actor':'verification_controller','created_at':now(),'operation':key,'verified_assessment':True,
        'scientific_certification':False,'original_hypothesis_version':h['original_version']}
    if h.get('endpoint'):h.setdefault('endpoint_history',[]).append(h['endpoint'])
    h.update(status=endpoint['outcome'],endpoint=endpoint);convergence.save(ws,h)
    ws.db.execute('INSERT INTO release_hypothesis_events VALUES (?,?)',(key,encoded(endpoint)))
    write_json(ws.root.parent/'deliveries'/('hypothesis-'+h['hypothesis_ref']+'-'+key.replace(':','-')+'.json'),endpoint)
