"""Optional scientific consistency and memory-repair profile; no extra agents.

Numeric checks certify fields of a declared estimand, never arbitrary prose or
the complete causal interpretation. Dependency flags cover explicit citations.
"""
from copy import deepcopy
import json
import math
from pathlib import Path
from .common import Pending, digest, encoded, sha
from .memory import MemoryWorkspace
from .robust_contracts import TOOLS, schemas
from .statistics import CheckedEnvironment

# A tested claim is not an assumption of the measurement which tests it.
# Inspiration, target links and receipt acknowledgements retain provenance but
# do not make independently calculated evidence depend on a claim being true.
DEPENDENCY_FIELDS=('evidence_refs','result_refs','data_refs','assessment_refs','plan_ref')


class RobustWorkspace(MemoryWorkspace):
    tools=TOOLS
    environment_class=CheckedEnvironment
    def tool_schemas(self): return schemas()

    def __init__(self,root,question,world,settings,*,reopen=False):
        settings=deepcopy(settings)
        settings['consistency_profile']='checked_memory_v1'
        settings['robust_sources']={name:sha(Path(__file__).parent/name) for name in
            ('robust.py','robust_contracts.py','statistics.py','runtime_robust.py','composed_world.py','repair_fixture.py')}
        settings['private_scene_switches']=list(getattr(world,'mechanisms',[]))
        self.review_ready=False
        super().__init__(root,question,world,settings,reopen=reopen)
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS dependencies(child TEXT,parent TEXT,PRIMARY KEY(child,parent));
            CREATE INDEX IF NOT EXISTS dependency_parent ON dependencies(parent,child);
            CREATE TABLE IF NOT EXISTS memory_validity(ref TEXT PRIMARY KEY,status TEXT,reason TEXT,state_ref TEXT);
            CREATE TABLE IF NOT EXISTS affected(ref TEXT,target TEXT,PRIMARY KEY(ref,target));
            CREATE TABLE IF NOT EXISTS loop_counter(id INTEGER PRIMARY KEY CHECK(id=1),signature TEXT,outcome TEXT,count INTEGER,blocked INTEGER);
        ''')
        self.review_ready=True
        self._rebuild_reviews()

    def rebuild_index(self):
        super().rebuild_index()
        if self.review_ready: self._rebuild_reviews()

    def _rebuild_reviews(self):
        with self.db:
            for table in ('dependencies','memory_validity','affected'): self.db.execute('DELETE FROM '+table)
            for body, in self.db.execute('SELECT body FROM records ORDER BY rowid'):
                self._index_review(json.loads(body))

    def _flag(self,target,status,reason,state_ref,*,acknowledge_dependencies=False):
        self.db.execute('INSERT OR REPLACE INTO memory_validity VALUES (?,?,?,?)',(target,status,reason,state_ref))
        # Restoration acknowledges this record only. Descendants retain their
        # review flags until individually reviewed; new knowledge is not an ack.
        if acknowledge_dependencies: self.db.execute('DELETE FROM affected WHERE ref=?',(target,))
        if status!='active':
            self.db.execute('''INSERT OR IGNORE INTO affected
                WITH RECURSIVE descendants(ref) AS (
                  SELECT child FROM dependencies WHERE parent=? UNION
                  SELECT d.child FROM dependencies d JOIN descendants x ON d.parent=x.ref)
                SELECT ref,? FROM descendants''',(target,target))

    def _index_review(self,item):
        if item['record_type']=='state':
            for review in item.get('memory_reviews',[]):
                self._flag(review['target_ref'],'active' if review['decision']=='restore' else review['decision'],review['reason'],item['ref'],
                           acknowledge_dependencies=review['decision']=='restore')
        refs=[]
        for field in DEPENDENCY_FIELDS:
            values=item.get(field,[])
            refs.extend(values if isinstance(values,list) else [values] if isinstance(values,str) else [])
        for parent in set(refs):
            if parent.startswith('card:'): parent=parent[5:]
            self.db.execute('INSERT OR IGNORE INTO dependencies VALUES (?,?)',(item['ref'],parent))
            for target, in self.db.execute('SELECT target FROM affected WHERE ref=?',(parent,)).fetchall():
                self.db.execute('INSERT OR IGNORE INTO affected VALUES (?,?)',(item['ref'],target))
            invalid=self.db.execute("SELECT status FROM memory_validity WHERE ref=? AND status!='active'",(parent,)).fetchone()
            if invalid: self.db.execute('INSERT OR IGNORE INTO affected VALUES (?,?)',(item['ref'],parent))
        if item['record_type']=='knowledge':
            self._flag(item['ref'],'quarantine' if item['status']=='needs_review' else 'active',
                       'researcher marked needs_review' if item['status']=='needs_review' else '',item['ref'])
            if item.get('supersedes_ref'): self._flag(item['supersedes_ref'],'superseded','replaced by '+item['ref'],item['ref'])

    def add(self,kind,body):
        item=super().add(kind,body)
        if self.review_ready: self._index_review(item)
        return item

    def event(self,key,name,args,result):
        if not getattr(self,'defer_events',False): return super().event(key,name,args,result)

    def review(self,ref):
        row=self.db.execute('SELECT status,reason,state_ref FROM memory_validity WHERE ref=?',(ref,)).fetchone()
        affected=[r[0] for r in self.db.execute('SELECT target FROM affected WHERE ref=? LIMIT 12',(ref,))]
        return {'status':row[0] if row else 'active','reason':row[1] if row else '',
                'review_record':row[2] if row else None,'explicit_dependency_reviews':affected,
                'certification':'review state and explicit citations only; not a truth certificate'}

    def knowledge_filter(self):
        return "(d.kind!='knowledge' OR (NOT EXISTS(SELECT 1 FROM memory_validity v WHERE v.ref=d.ref AND v.status!='active') AND NOT EXISTS(SELECT 1 FROM affected z WHERE z.ref=d.ref)))"

    def knowledge_view(self,ref):
        item=super().knowledge_view(ref); item['review']=self.review(ref)
        row=self.db.execute('SELECT superseded_by FROM knowledge_current WHERE ref=?',(ref,)).fetchone()
        item['replacement_ref']=row[0] if row else None
        item['measurement_verification']='checked fields only' if item.get('measurements') else 'free text not numerically certified'
        try: item['bound_measurements']=[self.check_measurement(x) for x in item.get('measurements',[])]
        except (ValueError,Pending) as error:
            item['bound_measurements']=[]; item['measurement_verification']='needs_review'; item['measurement_error']=str(error)
            item['review']['status']='quarantine'
        return item

    def card(self,ref):
        return {**super().card(ref),'review':self.review(ref)}

    def context(self):
        context=super().context()
        context['research_knowledge']=[x for x in context['research_knowledge'] if x['source_state']=='current' and x['review']['status']=='active' and not x['review']['explicit_dependency_reviews']]
        context['memory_selection']['selected_refs']=[x['ref'] for x in context['research_knowledge']]
        context['memory_review_queue']=[{'ref':ref,'status':status,'reason':reason,'review_record':state}
            for ref,status,reason,state in self.db.execute("SELECT ref,status,reason,state_ref FROM memory_validity WHERE status!='active' ORDER BY rowid DESC LIMIT 6")]
        context['dependent_review_queue']=[{'ref':ref,'affected_by':target} for ref,target in
            self.db.execute('SELECT ref,target FROM affected ORDER BY rowid DESC LIMIT 6')]
        context['state_review']=self.review(context['state']['ref']) if context['state'] else None
        context['analysis_policy']='Use result.statistics for outcome set, aggregation, confidence and calendar. Free text is interpretation. Multiple hypotheses may remain active; no unique-mechanism assumption.'
        context['observed_history_facts']=json.loads((self.public/'observed_facts.json').read_text())
        if (self.private/'repair_fixture.json').exists():
            context['initialization_notice']='This is a registered memory-repair task. Initial notes and hypothesis were seeded by the test harness, not discovered by you. Review them against lawful sources; some may be correct. No hidden generator or audit answer is provided.'
        return context

    def check_measurement(self,claim):
        if claim['source_ref'].startswith('file:'):
            path,_=self.file(claim['source_ref'])
            if path!=self.public/'observed_facts.json': raise ValueError('only received observed_facts.json supports a history dimension claim')
            facts=json.loads(path.read_text()); actual=facts.get(claim['field'])
            if not isinstance(actual,(int,float)): raise ValueError('received numeric history field required')
            if claim['value'] is not None and not math.isclose(claim['value'],actual,rel_tol=1e-7,abs_tol=1e-7): raise ValueError('history dimension mismatch: expected '+str(actual))
            return {**claim,'value':actual,'verification':'exact observed dimension only'}
        result=self.record(claim['source_ref'],'result')
        if result['evidence_nature']=='record_reconciliation' and claim['field'] in ('mismatched_rows','recorded_total','verified_total','difference_units'):
            summary=result['actual_execution']['summary']; field=claim['field']
            actual=summary['verified_total']-summary['recorded_total'] if field=='difference_units' else summary[field]
            if claim['value'] is not None and not math.isclose(claim['value'],actual,rel_tol=1e-7,abs_tol=1e-7):
                raise ValueError('reconciliation field mismatch: '+encoded({'field':field,'expected':actual,'provided':claim['value']}))
            return {**claim,'value':actual,'unit':'rows' if field=='mismatched_rows' else 'items',
                    'verification':'received record arithmetic only; stock outflow is not independently measured sales or demand'}
        stats=result['actual_execution'].get('statistics')
        if not stats:
            facts_ref=self.file_ref(self.public/'observed_facts.json')['ref']
            raise ValueError('This result has no structured statistics. For history dimensions use '+
                encoded({'source_ref':facts_ref,'field':'business_days'})+
                ' (observed_facts.json; omit value to bind it). Other history fields: row_count, sites, skus, hours, calendar_window_days. '+
                'Exploratory outputs can be cited in evidence_refs without measurements; a code printout is not a structured estimator.')
        key=claim['estimate_key']
        stat=stats['primary'] if key=='primary' else stats['secondary'].get(key.removeprefix('secondary:')) if key.startswith('secondary:') else None
        if stat is None: raise ValueError('received primary or registered secondary estimate required')
        field=claim['field']
        if field not in ('estimate','confidence','lower','upper','clusters','site_day_units','business_days_observed'): raise ValueError('field does not belong to a statistical result')
        actual=stats['calendar'][field] if field=='business_days_observed' else stat['interval'][0 if field=='lower' else 1] if field in ('lower','upper') else stat[field]
        if claim['value'] is not None and not math.isclose(claim['value'],actual,rel_tol=1e-7,abs_tol=1e-7):
            raise ValueError('measurement mismatch: '+encoded({'field':field,'expected':actual,'provided':claim['value'],'result_ref':result['ref'],'estimate_key':key}))
        return {**claim,'value':actual,'product_ids':stat['product_ids'],'site_ids':stat['site_ids'],'unit':stat['unit'],'verification':'exact field of declared estimator only'}

    def update_state(self,a):
        a=deepcopy(a)
        missing={r[0] for r in self.db.execute("SELECT ref FROM hypothesis_status WHERE status IN ('active','new')")}-set(a['active_hypothesis_refs'])-set(a['inactive_hypotheses'])
        if missing:
            raise ValueError(encoded({'error':'hypothesis dispositions missing','hypothesis_refs':sorted(missing),
                'repair':'Keep these in active_hypothesis_refs, or put each in inactive_hypotheses with a concrete reason; original records are retained.'}))
        for review in a['memory_reviews']:
            self.record(review['target_ref']); self.references(review['evidence_refs'])
            row=self.db.execute('SELECT superseded_by FROM knowledge_current WHERE ref=?',(review['target_ref'],)).fetchone()
            if review['decision']=='restore' and row and row[0]: raise ValueError('superseded original cannot be restored; review its received replacement')
        restored={r['target_ref'] for r in a['memory_reviews'] if r['decision']=='restore'}
        for ref in a['evidence_refs']:
            if ref.startswith('K') and ref not in restored and (self.review(ref)['status']!='active' or self.review(ref)['explicit_dependency_reviews']):
                raise ValueError('factual memory premise '+ref+' needs review; restore it with evidence in this batch, or cite it as counterevidence. used_memory_refs tracks inspiration, not truth.')
        self.knowledge_rejections=[]; self.knowledge_entry_index=0
        result=super().update_state(a)
        result['memory_reviews_applied']=len(a['memory_reviews'])
        result['knowledge_rejections']=self.knowledge_rejections
        return result

    def save_knowledge(self,entry):
        """Reject an optional claim without discarding a valid research checkpoint."""
        index=self.knowledge_entry_index; self.knowledge_entry_index+=1
        self.db.execute('SAVEPOINT optional_knowledge')
        try:
            entry=deepcopy(entry)
            for claim in entry['measurements']:
                self.check_measurement(claim)
                if claim['source_ref'] not in entry['evidence_refs']: entry['evidence_refs'].append(claim['source_ref'])
            return super().save_knowledge(entry)
        except (ValueError,TypeError) as error:
            self.db.execute('ROLLBACK TO optional_knowledge')
            self.knowledge_rejections.append({'input_index':index,'error':str(error),
                'action':'This claim was not saved. Repair this entry separately; the valid state checkpoint and accepted entries are retained.'})
            return None
        finally: self.db.execute('RELEASE optional_knowledge')

    def result_view(self,item):
        return {**super().result_view(item),'statistics':item['actual_execution'].get('statistics'),'review':self.review(item['ref'])}

    def _checked_dispatch(self,name,a,key):
        if name in ('read_memory','read_artifact') and a['ref'].startswith('K'):
            view=self.knowledge_view(a['ref']); text=encoded(view); end=a['offset']+a['limit']
            result={'ref':a['ref'],'sha256':digest(view),'original_sha256':digest(self.record(a['ref'])),
                    'review':view['review'],'replacement_ref':view['replacement_ref'],
                    'text':text[a['offset']:end],'next_offset':end if end<len(text) else None}
            self.event(key,name,a,result); return result
        if name=='save_hypothesis' and a.get('effect_prediction'):
            prediction=a['effect_prediction']; self._validate_ids(prediction['outcome_product_ids'],prediction['site_ids'])
        if name=='register_test':
            h=self.record(a['hypothesis_ref'],'hypothesis'); prediction=h.get('effect_prediction')
            for products in a['outcome_groups'].values(): self._validate_ids(products,[])
            if prediction and a['mode']=='protocol':
                if set(a['outcome_product_ids'])!=set(prediction['outcome_product_ids']): raise ValueError('primary outcome must match the original effect_prediction; controls belong in outcome_groups')
                a={**a,'effect_prediction':prediction}
        if name=='record_assessment':
            for ref in a['result_refs']:
                result=self.record(ref,'result'); check=result['actual_execution'].get('statistics',{}).get('prediction_check')
                if a['status']!='unresolved':
                    if self.review(ref)['explicit_dependency_reviews']: raise ValueError('review affected evidence before a firm verdict')
                    if result['evidence_nature']=='intervention' and not check: raise ValueError('a firm quantitative intervention verdict needs a predeclared effect_prediction; unresolved remains available')
                    if check and a['status']!=check['compatible_verdict']: raise ValueError('numeric prediction compatibility is '+check['compatible_verdict']+'; failed significance is not refutation. See result.statistics.')
        if name=='finish_research':
            if any(self.review(ref)['explicit_dependency_reviews'] for ref in a['assessment_refs']): raise ValueError('affected judgments require review before final use')
        result=super().dispatch(name,a,key)
        if name=='run_test' and result.get('record_type')=='result':
            return {**self.result_view(result),'attachments':result['attachments'],
                    'receipt_scope':'Result fields and evidence links; full immutable execution/protocol via full_record.'}
        return result

    def dispatch(self,name,a,key):
        """Persist exact repeats independently of context capacity and op replay."""
        tracked=name in ('read_artifact','read_memory','query_data','run_python','update_research_state')
        args={k:v for k,v in a.items() if k!='purpose'}
        version=self.identity['public_inputs']
        if name in ('read_artifact','read_memory'):
            ref=a['ref']
            if ref.startswith('file:'):
                row=self.db.execute('SELECT hash FROM files WHERE ref=?',(ref,)).fetchone(); version=row[0] if row else None
            elif ref.startswith('K'): version=self.review(ref)
        signature=digest([name,args,version])
        previous=self.db.execute('SELECT signature,outcome,count,blocked FROM loop_counter WHERE id=1').fetchone()
        if tracked and name!='run_python' and previous and previous[0]==signature and previous[2]>=3:
            self.db.execute('UPDATE loop_counter SET blocked=blocked+1 WHERE id=1')
            result={'ok':False,'loop_guard':'blocked','error':'same action and unchanged input repeated after 3 identical outcomes; inspect existing evidence or change the actual check'}
            self.event(key,name,a,result); return result
        self.db.execute('SAVEPOINT consistency_action')
        self.defer_events=True
        try:
            result=self._checked_dispatch(name,a,key)
        except (ValueError,TypeError) as error:
            self.db.execute('ROLLBACK TO consistency_action')
            result={'ok':False,'error':str(error)}
        finally:
            self.db.execute('RELEASE consistency_action')
            self.defer_events=False
        failed=result.get('ok') is False
        if tracked or failed:
            if failed: outcome={'error':result.get('error')}
            elif name=='query_data': outcome={k:result.get(k) for k in ('columns','row_count','preview')} | {'data_hash':result.get('file',{}).get('sha256')}
            elif name=='run_python':
                execution=result.get('execution',{}); outcome={k:execution.get(k) for k in ('ok','stdout')}
                outcome['error_tail']=execution.get('stderr','').splitlines()[-1:]
            elif name=='update_research_state': outcome=a
            else: outcome={k:result.get(k) for k in ('sha256','text','preview','next_offset','review','replacement_ref')}
            outcome_hash=digest(outcome)
            count=previous[2]+1 if previous and previous[:2]==(signature,outcome_hash) else 1
            blocked=(previous[3]+1 if previous else 1) if count>3 else 0
            self.db.execute('INSERT OR REPLACE INTO loop_counter VALUES (1,?,?,?,?)',(signature,outcome_hash,count,blocked))
            if count==3: result={**result,'loop_notice':'3 identical outcomes with unchanged inputs; identify a specific unresolved check or use the existing artifact'}
            elif count>3: result={**result,'loop_guard':'blocked','loop_notice':'unchanged computation repeated; branch will pause if repeated again'}
        elif name not in ('read_context','search_memory','update_research_state'):
            self.db.execute('DELETE FROM loop_counter')
        self.event(key,name,a,result)
        return result

    def _validate_ids(self,products,sites):
        import pandas as pd
        valid=set(pd.read_csv(self.public/'products.csv').sku); valid_sites=set(pd.read_csv(self.public/'sites.csv').site)
        if not products or len(products)!=len(set(products)) or not set(products)<=valid: raise ValueError('distinct received outcome product IDs required')
        if len(sites)!=len(set(sites)) or not set(sites)<=valid_sites: raise ValueError('distinct received site IDs required')
        if len(sites)==1: raise ValueError('the declared site-cluster estimator requires at least two sites; leave site_ids empty for all sites, or use an observational method appropriate to one site')
