"""Translate every cited lawful operation, keeping reviews attributed feedback."""
import json,re,shutil,sqlite3
from pathlib import Path
from ..common import Pending,digest,sha
from ..paired_v01.contracts import Review
from ..paired_v01.evidence import filtered_action
from ..paired_v01.orchestrator import replace_refs as previous_replace
from ..paired_v03.orchestrator import ResearchRun as PreviousRun,ResearchRuntime


def source_actions(value):
    if isinstance(value,str):return set(re.findall(r'\baction:[0-9]+\b',value))
    if isinstance(value,list):return set().union(*(source_actions(v) for v in value)) if value else set()
    if isinstance(value,dict):return source_actions(list(value.values()))
    return set()


def translate(value,mapping):
    value=previous_replace(value,mapping)
    if isinstance(value,str):return re.sub(r'\baction:[0-9]+\b',lambda m:mapping.get(m[0],m[0]),value)
    if isinstance(value,list):return [translate(v,mapping) for v in value]
    if isinstance(value,dict):return {k:translate(v,mapping) for k,v in value.items()}
    return value


class ResearchRun(PreviousRun):
    def review_job(self,job):
        if self.ws.job(job['ref'])['status']=='completed':return
        return super().review_job(job)

    def import_feedback(self,job,reviewer):
        if self.ws.job(job['ref'])['status']=='completed':return
        original=reviewer.report()
        if not original:raise Pending('critic has no complete review; retain its paid checkpoint')
        mapping={'directory:'+name:'job:'+job['ref']+'/directory:'+name for name in ('all','related','results')}
        imported=self.ws.science/'review_runs'/job['ref']
        try:
            for path in reviewer.science.rglob('*'):
                if not path.is_file() or any(p in ('tmp','.matplotlib') for p in path.relative_to(reviewer.science).parts):continue
                target=imported/path.relative_to(reviewer.science);target.parent.mkdir(parents=True,exist_ok=True)
                if target.exists():
                    if sha(target)!=sha(path):raise Pending('imported critic artifact changed')
                else:shutil.copyfile(path,target)
            actions=[(ref,json.loads(body)) for ref,body in reviewer.db.execute('SELECT ref,body FROM actions ORDER BY rowid')]
            notes=[json.loads(b) for b, in reviewer.db.execute("SELECT body FROM records WHERE kind='checkpoint' ORDER BY rowid")]
            for ref,_ in actions:mapping[ref]='C'+digest([job['ref'],ref])[:16]
            for note in notes:mapping[note['ref']]='N'+digest([job['ref'],note['ref']])[:16]
            cited=[]
            for ref in sorted(source_actions(original)):
                try:item=reviewer.view.record(ref)
                except ValueError:
                    if ref in original['source_refs']:raise
                    continue # Free-text historical labels remain visible, not certified citations.
                number=int(ref[7:]);row=self.ws.db.execute('SELECT body FROM events WHERE id=?',(number,)).fetchone()
                if not row or digest(filtered_action(number,json.loads(row[0])))!=digest(item):
                    raise Pending('lawful operation projection no longer matches owner event '+ref)
                mapping[ref]='C'+digest([job['ref'],'source',ref])[:16];cited.append((ref,item))
            new_ref='Q'+digest([job['ref'],original['ref']])[:16];mapping[original['ref']]=new_ref
            with self.ws.db:
                for old_ref,relative in reviewer.db.execute('SELECT ref,path FROM files'):
                    path=imported/Path(relative).relative_to('artifacts')
                    mapping[old_ref]=self.ws.file_ref(path,'review_computation_seen')['ref']
                for ref,item in cited:
                    self.ws.add('review_action',{'_record_ref':mapping[ref],'author':'lawful_operation_projection',
                        'job_ref':job['ref'],'origin_action_ref':ref,'source_event_ref':'event:'+ref[7:],
                        'source_version':digest(item),'operation':item,'hypothesis_refs':self.ws.target_hypotheses(job['target_ref'])})
                for ref,action in actions:
                    self.ws.add('review_action',{'_record_ref':mapping[ref],'author':'critic_tool','job_ref':job['ref'],
                        'origin_action_ref':ref,'operation':translate(action,mapping),'hypothesis_refs':self.ws.target_hypotheses(job['target_ref'])})
                for note in notes:
                    self.ws.add('review_note',{'_record_ref':mapping[note['ref']],'author':'critic','job_ref':job['ref'],
                        'original_ref':note['ref'],'note':translate(note,mapping)})
                body=translate({k:original[k] for k in Review.model_fields},mapping)
                body['source_ref_translation']={ref:mapping[ref] for ref,_ in cited}
                self.ws.apply_review(job['ref'],body,author='independent_critic',original_ref=original['ref'],record_ref=new_ref)
            self.ws._publish()
        except (ValueError,TypeError,sqlite3.Error) as error:
            raise Pending('completed critic review retained; import needs repair for '+job['ref']+': '+str(error)) from error
