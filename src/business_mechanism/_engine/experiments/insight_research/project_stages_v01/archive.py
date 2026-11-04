"""Paged old scientific originals; never copy another role's private thoughts.

Full sources materialize only on explicit read. Context size does not grow
with the entire archive, and one stage never imports old claims as current K.
"""
import json,re,shutil,sqlite3
from pathlib import Path
from ..common import digest,encoded,sha,Pending,write_json
from ..paired_v01.evidence import EvidenceView
from ..memory import terms

def search_archive(view,args):
    clauses=['1'];params=[];query=args.get('query','');words=terms(query)
    if query.strip() and not words:return {'hits':[],'total':0,'next_offset':None,'query_notice':'No searchable terms'}
    if words:
        parts=[];long=[w for w in words if len(w)>=3];short=[w for w in words if len(w)<3]
        if long:
            parts.append('d.ref IN (SELECT ref FROM fts WHERE fts MATCH ?)');params.append(' OR '.join('"'+w.replace('"','""')+'"' for w in long))
        for w in short:parts.append('instr(lower(d.text),?)>0');params.append(w)
        parts.append('d.ref IN (SELECT ref FROM tags WHERE tag IN ('+','.join('?' for _ in words)+'))');params.extend(words)
        clauses.append('('+' OR '.join(parts)+')')
    kind=args.get('kind','all')
    if kind!='all':clauses.append('d.kind=?');params.append('hypothesis' if kind=='card' else kind)
    if args.get('hypothesis_ref'):
        ref=args['hypothesis_ref'];view.record(ref);clauses.append('d.ref IN (SELECT ref FROM links WHERE hypothesis=?)');params.append(ref)
    for field,column in (('status','status'),('lifecycle_status','lifecycle')):
        if args.get(field) is not None:clauses.append('d.'+column+'=?');params.append(args[field])
    for tag in args.get('tags',[]):clauses.append('d.ref IN (SELECT ref FROM tags WHERE tag=?)');params.append(tag.casefold())
    where=' FROM docs d WHERE '+' AND '.join(clauses);total=view.db.execute('SELECT count(*)'+where,params).fetchone()[0]
    limit=args.get('limit',8);offset=args.get('offset',0)
    rows=view.db.execute('SELECT ref,kind,status,text'+where+' ORDER BY seq DESC,ref LIMIT ? OFFSET ?',[*params,limit,offset])
    return {'hits':[{'ref':r,'kind':k,'recorded_status':s,'preview':t[:800],'lifecycle':view.review(r)} for r,k,s,t in rows],
        'total':total,'next_offset':offset+limit if total>offset+limit else None,'method':'SQL paged FTS/tag/short-term substring lookup; no private process or automatic truth filter.'}

class ArchiveAccess:
    def archive_descriptors(self):return self.settings.get('project_archives',[])
    def archive_view(self,stage):
        d=next((d for d in self.archive_descriptors() if d['stage_id']==stage),None)
        if d is None:raise ValueError('stage archive not received in this registered workspace')
        root=Path(d['path']).resolve()
        if sha(root/'manifest.json')!=d['manifest_sha256']:raise Pending('registered project archive manifest changed')
        # The sealed manifest authenticates the catalog. Scientific source
        # bytes are checked on actual file access, not reread in full on every
        # search. This avoids O(all historical data bytes) per memory query.
        manifest=json.loads((root/'manifest.json').read_text())
        catalog=root/'catalog.sqlite'
        if catalog.is_symlink() or sha(catalog)!=manifest['files_sha256']['catalog.sqlite']:raise Pending('registered archive catalog changed')
        view=object.__new__(EvidenceView);view.root=root;view.manifest=manifest
        view.db=sqlite3.connect(catalog.as_uri()+'?mode=ro',uri=True);return view
    def archive_context(self):
        ds=self.archive_descriptors()
        return {'stage_count':len(ds),'index_ref':'archive_index:0','search':'search_memory archive_stage=<received stage id>, query/kind/status/offset/limit',
            'read':'read_memory ref=archive:<stage id>:<exact old record/file ref>',
            'scope':'Earlier scoped observations/counterevidence/revisions are available, including unlinked, withdrawn and superseded records. These are already seen, not newly verified knowledge. Read originals and test applicability before reusing. Historical sources are copied on demand only; no other role private thought is accessible.'}
    def archive_search(self,args):
        stage=args['archive_stage'];view=self.archive_view(stage)
        try:
            selected={k:v for k,v in args.items() if k in ('query','kind','hypothesis_ref','status','lifecycle_status','offset','limit','tags')}
            if selected.get('hypothesis_ref','') and selected['hypothesis_ref'].startswith('archive:'+stage+':'):selected['hypothesis_ref']=selected['hypothesis_ref'].split(':',2)[2]
            if selected.get('kind')=='card':selected['kind']='hypothesis'
            if selected.get('kind')=='process':raise ValueError('other-stage private process is not exposed; scientific originals and attributed operations remain searchable')
            if args.get('include_history') is False:selected['lifecycle_status']='active'
            out=search_archive(view,selected)
            for hit in out['hits']:hit['ref']='archive:'+stage+':'+hit['ref']
            return {**out,'archive_stage':stage,'evidence_nature':'historical_scoped_source_not_new_validation'}
        finally:view.close()
    def archive_read(self,args):
        ref=args['ref']
        if ref.startswith('archive_index:'):
            m=re.fullmatch(r'archive_index:(\d+)',ref)
            if not m:raise ValueError('archive_index:<nonnegative offset> required')
            n=int(m[1]);ds=self.archive_descriptors();body={'items':[{'stage_id':d['stage_id'],'manifest_sha256':d['manifest_sha256'],'read_prefix':'archive:'+d['stage_id']+':'} for d in ds[n:n+8]],'total':len(ds),'next_ref':'archive_index:'+str(n+8) if n+8<len(ds) else None}
            text=encoded(body);end=args['offset']+args['limit'];return {'ref':ref,'text':text[args['offset']:end],'sha256':digest(body),'next_offset':end if end<len(text) else None}
        m=re.fullmatch(r'archive:([A-Za-z0-9_-]{1,80}):(.+)',ref)
        if not m:raise ValueError('exact received archive stage and reference required')
        stage,old=m.groups();view=self.archive_view(stage)
        try:
            if old.startswith('file:'):
                source,nature=view.file(old);version=sha(source)
                target=self.science/'project_history'/stage/'sources'/version/source.name
                body={'ref':ref,'original_file_ref':old,'original_sha256':version,'historical_source_nature':nature,'already_seen':True}
            else:
                original=view.record(old);body={'ref':ref,'original':original,'original_version':digest(original),'lifecycle':view.review(old),'already_seen':True,'scientific_certification':False}
                version=digest(body);source=None;target=self.science/'project_history'/stage/'records'/(version+'.json')
            if target.exists():
                if target.is_symlink() or (source is not None and sha(target)!=version) or (source is None and json.loads(target.read_text())!=body):raise Pending('materialized historical original changed; never overwrite')
            else:
                target.parent.mkdir(parents=True,exist_ok=True)
                if source is None:write_json(target,body)
                else:shutil.copyfile(source,target)
            f=self.file_ref(target,nature='historical_source_already_seen')
            text=encoded(body);end=args['offset']+args['limit']
            return {**{'ref':ref,'text':text[args['offset']:end],'sha256':digest(body),'next_offset':end if end<len(text) else None},'materialized_original':f,'compute_path':str(target),'evidence_nature':'historical_source_not_new_trial_or_current_certified_memory'}
        finally:view.close()
