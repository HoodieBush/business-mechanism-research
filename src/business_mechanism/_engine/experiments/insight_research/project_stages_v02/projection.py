"""Archive actual job/clearance/response state without altering old science."""
import json,sqlite3
from ..common import sha,digest,encoded,write_json
from ..project_stages_v01.projection import export_stage as previous
def export_stage(owner,destination):
    previous(owner,destination)
    from pathlib import Path
    destination=Path(destination);jobs=owner.jobs()
    with sqlite3.connect(destination/'catalog.sqlite') as db:
        db.execute('CREATE TABLE stage_review_status(ref TEXT PRIMARY KEY,body TEXT)')
        for ref,body in owner.db.execute("SELECT ref,body FROM records WHERE kind IN ('assessment','knowledge','report_draft')"):
            item=json.loads(body);clear=owner.db.execute('SELECT version,review_ref FROM clearances WHERE target=?',(ref,)).fetchone()
            status={'source_ref':ref,'source_version':digest(item),'record_type':'archived_operational_review_status',
                'source_review_jobs':[j for j in jobs if j['target_ref']==ref],
                'stored_clearance_ref':clear[1] if clear else None,'stored_clearance_version_matches_original':bool(clear and clear[0]==digest(item)),
                'source_unanswered_opinions':owner.unanswered({ref}),
                'scientific_certification':False,'meaning':'Actual archived task/clearance/response bookkeeping only, separate from the immutable scientific original. A supported label or active lifecycle is not evidence that its separate review finished. Old clearance does not validate applicability to a new question.'}
            db.execute('INSERT INTO stage_review_status VALUES (?,?)',(ref,encoded(status)))
    manifest=json.loads((destination/'manifest.json').read_text());manifest['files_sha256']['catalog.sqlite']=sha(destination/'catalog.sqlite');manifest['stage_review_status']='Separate indexed operational metadata; no original scientific body rewritten';write_json(destination/'manifest.json',manifest)
