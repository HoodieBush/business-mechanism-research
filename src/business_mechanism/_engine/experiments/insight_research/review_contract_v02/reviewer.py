import re
from ..common import digest,sha
from ..review_contract_v01.reviewer import Reviewer as Previous

PRIOR_ACTION=re.compile(r'\bC[0-9a-f]{16}\b')


class Reviewer(Previous):
    def prior_action(self, ref):
        parent=self.packet.get('previous_feedback') or {}
        allowed={c['action_ref'] for c in parent.get('checks_performed',[])}
        if ref not in allowed:
            raise ValueError('Prior action must be explicitly listed in this directed parent review.')
        item=self.view.record(ref)
        if item.get('record_type')!='review_action' or self.view.review(ref)['status']!='active':
            raise ValueError('Active attributed prior review action required; withdrawn work cannot be reused.')
        if not re.fullmatch(r'J[0-9a-f]{16}',item.get('job_ref','')):
            raise ValueError('Valid origin review job identity required.')
        operation=item['operation']
        if operation.get('result',{}).get('ok') is False or operation.get('result',{}).get('execution',{}).get('ok') is False:
            raise ValueError('A failed prior tool is not reusable computation.')
        # Read only lawful public snapshot metadata, never a role's private
        # reasoning. Exact public inputs must match; reuse is not new sampling.
        prior=self.root.parents[2]/'reviews'/item['job_ref']/'inputs/public'
        if not prior.is_dir():
            raise ValueError('Original public input snapshot unavailable; recompute instead.')
        old={str(p.relative_to(prior)):sha(p) for p in prior.rglob('*') if p.is_file()}
        current={str(p.relative_to(self.public)):sha(p) for p in self.public.rglob('*') if p.is_file()}
        if old!=current:
            raise ValueError('Public inputs changed since prior computation; recompute instead.')
        return item,{'source_action_ref':ref,'source_action_version':digest(item),
            'origin_job_ref':item['job_ref'],'origin_tool':operation['tool'],
            'kind':'reused_prior_tool_output','new_computation_in_this_review':False,
            'public_input_versions':current,'scientific_certification':False}

    def action(self, ref):
        try:return super().action(ref)
        except ValueError:
            if not PRIOR_ACTION.fullmatch(ref):raise
            item,_=self.prior_action(ref)
            return item['operation']

    def normalize_submission(self,name,args):
        corrected,changes=super().normalize_submission(name,args)
        self._output_ref_reconstruction=[]
        if name=='record_review':
            for check in corrected.get('checks_performed',[]):
                unknown=[]
                for ref in check.get('artifact_refs',[]):
                    try:self.references([ref])
                    except ValueError:unknown.append(ref)
                if unknown:
                    operation=self.action(check['action_ref']);outputs=[]
                    def collect(value):
                        if isinstance(value,dict):
                            ref=value.get('ref')
                            if isinstance(ref,str) and ref.startswith('file:'):
                                try:self.references([ref])
                                except ValueError:pass
                                else:
                                    if ref not in outputs:outputs.append(ref)
                            for v in value.values():collect(v)
                        elif isinstance(value,list):
                            for v in value:collect(v)
                    collect(operation.get('result',{}))
                    if outputs:
                        # The explicit, validated operation is authoritative.
                        # Derive its real outputs; never guess an opaque ID by
                        # edit distance or affirm that an unknown ref was valid.
                        check['artifact_refs']=[r for r in check['artifact_refs'] if r not in unknown]
                        check['artifact_refs']=list(dict.fromkeys([*check['artifact_refs'],*outputs]))
                        proof={'action_ref':check['action_ref'],'unresolved_requested_refs':unknown,
                               'derived_actual_output_refs':outputs,'authority':'Exact validated action output; no fuzzy ID matching or scientific text change'}
                        self._output_ref_reconstruction.append(proof)
                        changes.setdefault('actual_output_reference_reconstruction',[]).append(proof)
            for issue in corrected.get('issues',[]):
                if issue.get('basis')!='recomputed' or issue.get('action_refs'):continue
                refs=[]
                for location in issue.get('evidence_locations',[]):
                    for ref in PRIOR_ACTION.findall(location):
                        try:self.prior_action(ref)
                        except ValueError:continue
                        if ref not in refs:refs.append(ref)
                if refs:
                    issue['action_refs']=refs
                    changes.setdefault('explicit_prior_action_links',{})[issue['issue_id']]=refs
        return corrected,changes

    def dispatch(self,name,args,key):
        body=args
        if name=='record_review':
            refs={c['action_ref'] for c in body.get('checks_performed',[])}
            refs.update(r for i in body.get('issues',[]) for r in i.get('action_refs',[]))
            provenance=[]
            for ref in sorted(refs):
                if PRIOR_ACTION.fullmatch(ref):
                    _,proof=self.prior_action(ref);provenance.append(proof)
            if provenance:body={**body,'reused_check_provenance':provenance}
            reconstruction=getattr(self,'_output_ref_reconstruction',[])
            if reconstruction:body={**body,'output_reference_reconstruction':reconstruction}
        return super().dispatch(name,body,key)
