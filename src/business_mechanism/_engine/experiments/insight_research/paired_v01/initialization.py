"""Whitelisted common initial scientific state for a matched repair task."""
import json
from pathlib import Path
import shutil

from ..common import Pending, sha, write_json
from execution import last_number


def export_initial(owner, destination):
    destination = Path(destination).resolve(); destination.mkdir(parents=True, exist_ok=False)
    manifest = {'format':'provided_research_state_v1', 'public_inputs':owner.identity['public_inputs'],
        'records':[json.loads(x[0]) for x in owner.db.execute('SELECT body FROM records ORDER BY rowid')],
        'events':[{'id':n,'operation':op,'body':json.loads(b)} for n,op,b in owner.db.execute('SELECT id,operation,body FROM events ORDER BY id')],
        'completed_tests':[{'key':k,'signature':s,'result':json.loads(b)} for k,s,b in owner.db.execute("SELECT key,signature,result FROM operations WHERE key LIKE 'test:%' AND status='completed'")],
        'files':[], 'notice':'All inherited scientific records and notes are script-provided, not discoveries of this run. Their assertions need checking against lawful evidence.'}
    for ref,path,version,nature in owner.db.execute('SELECT ref,path,hash,nature FROM files'):
        source,_ = owner.file(ref); relative = source.relative_to(owner.root)
        target=destination/'files'/relative;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,target)
        if sha(target)!=version:raise Pending('provided source changed during export')
        manifest['files'].append({'ref':ref,'path':str(relative),'hash':version,'nature':nature})
    write_json(destination/'manifest.json',manifest)
    return manifest


def import_initial(owner, manifest_path):
    manifest_path=Path(manifest_path).resolve();manifest=json.loads(manifest_path.read_text())
    if manifest['public_inputs']!=owner.identity['public_inputs']:raise ValueError('paired initial observations differ')
    marker=owner.db.execute("SELECT value FROM meta WHERE key='provided_initial_sha'").fetchone()
    if marker:
        if marker[0]!=sha(manifest_path):raise ValueError('provided initial state changed')
        return
    if owner.db.execute('SELECT 1 FROM records LIMIT 1').fetchone():raise ValueError('initial state import cannot overwrite research')
    for file in manifest['files']:
        relative=Path(file['path'])
        if relative.is_absolute() or '..' in relative.parts or relative.parts[0] not in ('public','science'):
            raise ValueError('provided files must stay in public/science')
        source=manifest_path.parent/'files'/relative;target=owner.root/relative
        if source.is_symlink() or sha(source)!=file['hash']:raise ValueError('provided source changed')
        target.parent.mkdir(parents=True,exist_ok=True)
        if target.exists():
            if sha(target)!=file['hash']:raise ValueError('provided/current file collision')
        else:shutil.copyfile(source,target)
    with owner.db:
        for file in manifest['files']:
            owner.db.execute('INSERT OR IGNORE INTO files VALUES (?,?,?,?)',(file['ref'],file['path'],file['hash'],file['nature']))
        for body in manifest['records']:
            if body['record_type'] not in ('hypothesis','plan','result','assessment','knowledge','state'):
                raise ValueError('only scientific initial records may be imported')
            owner.db.execute('INSERT INTO records VALUES (?,?,?)',(body['ref'],body['record_type'],json.dumps(body,ensure_ascii=False,sort_keys=True)))
        for event in manifest['events']:
            owner.db.execute('INSERT INTO events VALUES (?,?,?)',(event['id'],event['operation'],json.dumps(event['body'],ensure_ascii=False,sort_keys=True)))
        for op in manifest['completed_tests']:
            owner.db.execute('INSERT INTO operations VALUES (?,?,?,?)',(op['key'],op['signature'],'completed',json.dumps(op['result'],ensure_ascii=False,sort_keys=True)))
        owner.db.execute("INSERT INTO meta VALUES ('provided_initial_sha',?)",(sha(manifest_path),))
    owner.rebuild_index();owner._rebuild_reviews();owner._publish()
    owner.worker.count=last_number(owner.worker.directory,'analysis_','.py')
    with owner.db:
        for a in owner.records('assessment'):owner.enqueue(a['ref'])
