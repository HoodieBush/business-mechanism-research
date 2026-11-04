import json,re
from ..common import digest,write_json,sha,Pending
class ReviewStatusMixin:
    def source_status(self,stage,ref):
        view=self.archive_view(stage)
        try:
            if not view.db.execute("SELECT 1 FROM sqlite_master WHERE name='stage_review_status'").fetchone():return {'metadata_available':False,'meaning':'Old archive lacks review-job metadata; do not infer review completion from a strong label.'}
            row=view.db.execute('SELECT body FROM stage_review_status WHERE ref=?',(ref,)).fetchone()
            return json.loads(row[0]) if row else None
        finally:view.close()
    def archive_search(self,args):
        out=super().archive_search(args)
        for hit in out['hits']:
            stage,ref=hit['ref'].split(':',2)[1:];status=self.source_status(stage,ref)
            if status is not None:hit['source_review_status']=status
        return out
    def archive_read(self,args):
        out=super().archive_read(args)
        m=re.fullmatch(r'archive:([A-Za-z0-9_-]{1,80}):(.+)',args['ref'])
        if not m or m[2].startswith('file:'):return out
        stage,ref=m.groups();status=self.source_status(stage,ref)
        if status is None:return out
        path=self.science/'project_history'/stage/'review_status'/(digest(status)+'.json')
        if path.exists():
            if path.is_symlink() or json.loads(path.read_text())!=status:raise Pending('separate archived review-status receipt changed; never overwrite')
        else:write_json(path,status)
        receipt=self.file_ref(path,nature='archived_operational_review_status')
        return {**out,'separate_source_review_status':status,'source_review_status_file':receipt,
            'status_scope':'The separate status receipt is NOT embedded in the old scientific original or materialized_original. It reports actual old jobs and version matching, not scientific truth or newly inherited clearance.'}
