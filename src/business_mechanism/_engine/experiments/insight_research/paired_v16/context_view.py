"""Bounded navigation to exact science, not a generated memory summary."""
import json
import re
from ..common import Pending, digest, encoded
from ..critic_v01.shared import lifecycle
from ..paired_v12.journal_memory import own_context

KINDS = ('hypothesis','plan','result','assessment','knowledge','state','review','review_response','report_draft','report')


def job_brief(job):
    return {**{k:job[k] for k in ('ref','target_ref','target_version','round','status','parent_review_ref','review_http_limit')},
            'reason_preview':job['reason'][:240],'full_packet_ref':'job:'+job['ref']}


def brief(ws, item, cap=1800):
    result = {'ref':item['ref'],'record_type':item['record_type'],'original_version':digest(item),
              'read_ref':'original:'+item['ref'],'lifecycle':lifecycle(ws.db,item['ref'])}
    for key in ('hypothesis_ref','parent_ref','supersedes_assessment_ref','supersedes_ref','status','stage_status'):
        if key in item:
            result[key] = item[key]
    if len(encoded(item).encode()) <= cap:
        result['original'] = item
    else:
        result['preview_only'] = True
        result['preview'] = {k:str(item[k])[:320] for k in ('statement','question','prediction','falsification','scope','rationale') if k in item}
        result['instruction'] = 'Preview is incomplete. Read exact original before adjudicating scope, predictions or counterevidence.'
    return result


def index(ws, section, offset=0, page=8):
    if section in KINDS:
        values = [brief(ws,x) for x in ws.records(section)]
    elif section == 'jobs':
        values = [job_brief(j) for j in ws.jobs()]
    elif section == 'public_files':
        values = [{'ref':r,'path':str(ws.root/p),'nature':n} for r,p,n in ws.db.execute("SELECT ref,path,nature FROM files WHERE nature='public_seen' ORDER BY path")]
    elif section == 'unincorporated':
        values = [brief(ws,x) for x in ws.unincorporated()]
    elif section == 'open_issues':
        values = [{'review_ref':r,'issue_id':i,'affected_ref':a,'basis':b,'blocking':bool(k),
                   'original_review_read_ref':'original:'+r} for r,i,a,b,k in ws.db.execute('SELECT review_ref,issue_id,target,basis,blocking FROM review_issues WHERE open=1 ORDER BY rowid')]
    elif section == 'dependencies':
        values = [{'ref':r,'affected_by':t,'read_ref':'original:'+r} for r,t in ws.db.execute('SELECT ref,target FROM affected ORDER BY rowid')]
    elif section == 'counterevidence':
        values = [{'ref':r,'read_ref':r if r.startswith('file:') else 'original:'+r} for r in (ws.state() or {}).get('counterevidence_refs',[])]
    else:
        raise ValueError('known research_index section required')
    return {'section':section,'offset':offset,'total':len(values),'entries':values[offset:offset+page],
            'next_ref':f'research_index:{section}:{offset+page}' if offset+page<len(values) else None,
            'state_version':digest(values),'not_scientific_certification':True,
            'coverage':'Full paged registry including historical/retracted/untested objects. Read exact originals; order is not truth.'}


def read_index(ws, ref, offset=0, limit=12000):
    match = re.fullmatch(r'research_index:([a-z_]+):(\d+)',ref)
    if not match:
        raise ValueError('research_index:<section>:<nonnegative offset> required')
    value = index(ws,match[1],int(match[2])); text = encoded(value); end = offset+limit
    return {'ref':ref,'text':text[offset:end],'sha256':digest(value),'next_offset':end if end<len(text) else None}


def build(ws):
    state = ws.state(); outstanding = ws.unincorporated()
    focus = list((state or {}).get('focus_hypothesis_refs',[]))
    candidates = list(dict.fromkeys(focus+[r['hypothesis_ref'] for r in outstanding]))
    if not candidates:
        h = ws.records('hypothesis'); candidates = [h[-1]['ref']] if h else []
    # Exact original predictions for one focus; complete additional originals
    # stay in typed paged registries, never silently discarded or certified.
    selected = [brief(ws,ws.record(r,'hypothesis'),cap=14000) for r in candidates[:1]]
    knowledge = ws.search(kind='knowledge',limit=3,include_history=False)['hits']
    files = [{'ref':r,'path':str(ws.root/p),'nature':n} for r,p,n in ws.db.execute("SELECT ref,path,nature FROM files WHERE nature='public_seen' ORDER BY path")]
    jobs = ws.jobs('pending')+ws.jobs('running')+ws.jobs('exhausted')
    delegated = ws.delegated_jobs()
    recent_feedback = ws.records('review')[-1:]
    unanswered = ws.unanswered()
    usage = ws.study_budget.snapshot() if hasattr(ws,'study_budget') else None
    counts = {kind:ws.db.execute('SELECT count(*) FROM records WHERE kind=?',(kind,)).fetchone()[0] for kind in KINDS}
    ctx = {'research_profile':'paired_research_v1','verification_mode':ws.settings['verification_mode'],
        'original_question':ws.question,'state':brief(ws,state,cap=9000) if state else None,
        'active_original_hypotheses':selected,'additional_focus_count':max(0,len(candidates)-len(selected)),
        'unincorporated_results':[{'ref':r['ref'],'hypothesis_ref':r['hypothesis_ref'],'read_ref':'original:'+r['ref']} for r in outstanding[:8]],
        'unincorporated_total':len(outstanding),
        'research_knowledge':[brief(ws,ws.record(x['ref']),cap=1200) for x in knowledge],
        'memory_selection':{'selected_refs':[x['ref'] for x in knowledge],'method':'Existing bounded indexed retrieval; selection is not truth. Search include_history for older/retracted/no-H memories.'},
        'review_jobs':[job_brief(j) for j in jobs[:8]],'review_jobs_total':len(jobs),'delegated_review_jobs':[job_brief(j) for j in delegated],
        'review_feedback':[brief(ws,q,cap=2500) for q in recent_feedback],
        'unanswered_review_opinions':unanswered[:8],'unanswered_total':len(unanswered),
        'open_review_issues':index(ws,'open_issues')['entries'],
        'critical_counterevidence':index(ws,'counterevidence')['entries'],
        'dependent_review_queue':index(ws,'dependencies')['entries'],
        'archive_counts':counts,'public_files':files[:16],'public_files_total':len(files),'common_study_usage':usage,
        'archive_navigation':{name:f'research_index:{name}:0' for name in (*KINDS,'jobs','unincorporated','open_issues','dependencies','counterevidence','public_files')},
        'original_record_reading':'read_memory(original:<ref>,offset,limit) returns exact immutable record plus version; job:<J> returns prepared review packet; search_memory includes history.',
        'archive_path_policy':'Originals may retain ancestor absolute paths. Use current PUBLIC_DIR/ARTIFACT_DIR or returned compute_path. Registered code is never silently rewritten; if an old absolute path fails after relocation, retain that failed result and register a clearly revised observational plan with current paths. This is not new independent evidence.',
        'own_journal_memory':own_context(ws),'uncheckpointed_work':ws.checkpoint_work(),
        'resources':{'limits':ws.settings['limits'],'new_trials_remaining':max(0,2-ws.trials_started())},
        'permissions':{'read_only':[str(ws.public),str(ws.science)],'python_write':'current WORK_DIR only','private_process':'own memory only'},
        'initialization_notice':ws.settings.get('initialization_notice','No seeded scientific claims.'),
        'stage_closeout':ws.closeout(),
        'workflow':'You choose research and explicitly request_review(job_ref,reason) for ordinary A/K candidates; their receipts give exact jobs. finish_research explicitly submits the stage D and requests its publication review in the same action. Self then uses review_claim; independent peer returns feedback. Respond with original evidence. Strong memories/report still require current clearance. Submission is not scientific approval; opinions are not facts.',
        'assessment_policy':'Keep exact original prediction, scope, unit and falsifier. Record literal trigger separately from whether the rule is scientifically adequate. Posthoc new criteria create a new exploratory H; old evidence is not fresh validation.',
        'interpretation':'This is bounded navigation, not a scientific summary or automatic incorporation. Unloaded/history/contrary evidence remains in full paged indexes and exact originals; no object is cleared by leaving the active view.'}
    # Counts/cursors remain present even when a long natural-language issue
    # cannot be repeated in the fixed view. All original fields stay readable.
    if len(encoded(ctx).encode()) > ws.settings['execution_policy'].get('active_context_bytes',65536):
        ctx['state'] = brief(ws,state,cap=0) if state else None
        ctx['research_knowledge'] = []
        ctx['review_feedback'] = [{'ref':q['ref'],'read_ref':'original:'+q['ref'],'original_version':digest(q)} for q in recent_feedback]
        ctx['unanswered_review_opinions'] = [{'review_ref':x['review_ref'],'issue_id':x['issue_id'],'affected_refs':x['affected_refs']} for x in unanswered[:8]]
        ctx['navigation_reduction'] = 'Long optional text moved to exact originals; counts, original predictions and all archive cursors preserved.'
    if len(encoded(ctx).encode()) > ws.settings['execution_policy'].get('active_context_bytes',65536):
        raise Pending('critical bounded navigation still exceeds registered size; originals retained, no request sent or scientific verdict inferred')
    return ctx
