"""Lawful scientific-stage archive, including before any A/D exists.

Unlike a critic job, an early research stage needs no invented review target.
The stopped-source/paid-work guards are owned by Project.close_stage.
"""
import json,shutil,sqlite3
from pathlib import Path
from ..common import digest,encoded,sha,now,write_json,Pending
from ..critic_v01.shared import lifecycle
from ..paired_v01.evidence import SEARCH_FIELDS,filtered_action
def export_stage(owner,destination):
    destination=Path(destination).resolve();destination.mkdir(parents=True,exist_ok=False)
    if destination.is_relative_to(owner.root):raise ValueError('project archive must be outside the live owner')
    files={};originals={}
    db=sqlite3.connect(destination/'catalog.sqlite')
    db.executescript('''CREATE TABLE docs(ref TEXT PRIMARY KEY,kind TEXT,body TEXT,text TEXT,status TEXT,lifecycle TEXT,seq INTEGER);
        CREATE INDEX docs_kind_status ON docs(kind,status,seq); CREATE INDEX docs_lifecycle ON docs(lifecycle,seq);
        CREATE TABLE lifecycle(ref TEXT PRIMARY KEY,body TEXT); CREATE TABLE files(ref TEXT PRIMARY KEY,path TEXT,hash TEXT,nature TEXT);
        CREATE TABLE links(ref TEXT,hypothesis TEXT,PRIMARY KEY(ref,hypothesis)); CREATE INDEX links_hypothesis ON links(hypothesis,ref);
        CREATE TABLE tags(ref TEXT,tag TEXT,PRIMARY KEY(ref,tag)); CREATE INDEX tags_tag ON tags(tag,ref);
        CREATE VIRTUAL TABLE fts USING fts5(ref UNINDEXED,text,tokenize='trigram');''')
    def add(item,seq,life):
        ref=item['ref'];kind=item['record_type'];text=encoded({k:item[k] for k in SEARCH_FIELDS if k in item})
        if kind=='result':text+=item['actual_execution'].get('stdout','')[:2048]
        if kind in ('review','review_response','review_note','review_action','action'):
            life={**life,'eligible_as_current_premise':False,'certification':'Attributed opinion/operation, not factual truth.'}
        db.execute('INSERT INTO docs VALUES (?,?,?,?,?,?,?)',(ref,kind,encoded(item),text,item.get('status',''),life['status'],seq));db.execute('INSERT INTO lifecycle VALUES (?,?)',(ref,encoded(life)));db.execute('INSERT INTO fts VALUES (?,?)',(ref,text))
        hs=[ref] if kind=='hypothesis' else [item['hypothesis_ref']] if item.get('hypothesis_ref') else item.get('hypothesis_refs',[])
        db.executemany('INSERT OR IGNORE INTO links VALUES (?,?)',[(ref,h) for h in hs]);db.executemany('INSERT OR IGNORE INTO tags VALUES (?,?)',[(ref,t.casefold()) for t in item.get('tags',[])])
    try:
        with db:
            for ref,name,h,nature in owner.db.execute('SELECT ref,path,hash,nature FROM files'):
                source,_=owner.file(ref);relative=source.relative_to(owner.root)
                if relative.parts[0] not in ('public','science') or source.is_symlink():raise ValueError('only actual received scientific files may be archived')
                target=destination/relative;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,target)
                if sha(target)!=h:raise Pending('stage source changed while archiving')
                files[str(relative)]=h;db.execute('INSERT INTO files VALUES (?,?,?,?)',(ref,str(relative),h,nature))
            for name,h in owner.identity['public_inputs'].items():
                if files.get('public/'+name)!=h:raise Pending('received public source missing from stage archive')
            for seq,ref,body in owner.db.execute('SELECT rowid,ref,body FROM records ORDER BY rowid'):
                item=json.loads(body);add(item,seq,lifecycle(owner.db,ref));originals[ref]=digest(item)
            for seq,body in owner.db.execute('SELECT id,body FROM events ORDER BY id'):
                add(filtered_action(seq,json.loads(body)),seq,{'status':'active','eligible_as_current_premise':False})
    finally:db.close()
    files['catalog.sqlite']=sha(destination/'catalog.sqlite')
    write_json(destination/'manifest.json',{'format':'lawful_project_stage_archive_v1','created_at':now(),'files_sha256':files,'record_original_versions':originals,
        'excluded':['private model thoughts/messages','transport credentials','root audit/scoring','unregistered files'],'scope':'Already seen scientific originals and attributed operations; not a new sample or automatically current knowledge.'})
