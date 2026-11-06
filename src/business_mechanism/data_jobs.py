"""Durable full-SQL jobs; SQLite owns global semantics, the sandbox owns compute."""
import base64
import hashlib
import json
from pathlib import Path
import sqlite3
import time
from experiments.insight_research.common import digest, encoded, now
from .sandbox import RestrictedPythonWorkspace


PROFILES = {
    'interactive': {'seconds': 30, 'memory_bytes': 536870912, 'disk_bytes': 67108864},
    'batch': {'seconds': 600, 'memory_bytes': 1073741824, 'disk_bytes': 536870912},
}


def file_hash(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''):
            h.update(block)
    return h.hexdigest()


# This is staged as inspected source by RestrictedPythonWorkspace, not imported
# from the hidden engine. No arbitrary SQL is interpolated into Python code.
WORKER = r'''
import base64,fcntl,json,os,pathlib,resource,sqlite3,stat,time
cfg=json.loads(base64.b64decode(CONFIG))
root=pathlib.Path(os.environ['WORK_DIR'])
resource.setrlimit(resource.RLIMIT_AS,(cfg['memory_bytes'],cfg['memory_bytes']))
resource.setrlimit(resource.RLIMIT_FSIZE,(cfg['disk_bytes'],cfg['disk_bytes']))
resource.setrlimit(resource.RLIMIT_CPU,(cfg['seconds']+1,cfg['seconds']+2))
started=time.monotonic();rows=0;columns=[];ticks=0;limit_hit=None
out=sqlite3.connect(root/'result.sqlite')
out.execute('PRAGMA journal_mode=OFF')
out.execute('PRAGMA max_page_count='+str(cfg['disk_bytes']//4096))
out.execute('CREATE TABLE result_rows(n INTEGER PRIMARY KEY,payload TEXT NOT NULL)')
db=sqlite3.connect(pathlib.Path(cfg['input']).as_uri()+'?mode=ro',uri=True)
db.execute('PRAGMA cache_size=-8192')
db.execute('PRAGMA temp_store=FILE')
allowed={sqlite3.SQLITE_SELECT,sqlite3.SQLITE_READ,sqlite3.SQLITE_FUNCTION,sqlite3.SQLITE_RECURSIVE}
db.set_authorizer(lambda act,p1,p2,*_:sqlite3.SQLITE_OK if act in allowed and str(p2).lower()!='load_extension' else sqlite3.SQLITE_DENY)
def stop(check_disk=False):
    global limit_hit
    if time.monotonic()-started>cfg['seconds']:limit_hit='time_limit'
    if pathlib.Path(cfg['cancel_path']).exists():limit_hit='cancelled'
    if check_disk:
        files={}
        # Include SQLite's unlinked temporary files. Read-only input descriptors
        # do not consume the output quota. The worker opens fewer than 256 fds.
        for fd in range(256):
            try:
                info=os.fstat(fd)
                if stat.S_ISREG(info.st_mode) and fcntl.fcntl(fd,fcntl.F_GETFL)&os.O_ACCMODE:
                    files[(info.st_dev,info.st_ino)]=info.st_size
            except OSError:pass
        if sum(files.values())>cfg['disk_bytes']:limit_hit='disk_limit'
    return limit_hit is not None
def progress():
    global ticks
    ticks+=1
    return stop(ticks%1000==0)
db.set_progress_handler(progress,1000)
status='failed';error=None
try:
    cur=db.execute(cfg['sql'],cfg['parameters'])
    if cur.description is None:raise ValueError('read-only SELECT with result columns required')
    columns=[c[0] for c in cur.description]
    while True:
        if stop(True):raise TimeoutError(limit_hit)
        batch=cur.fetchmany(512)
        if not batch:break
        def pack(row):
            return json.dumps([{'sqlite_blob_base64':base64.b64encode(x).decode()} if isinstance(x,bytes) else x for x in row],ensure_ascii=False)
        out.executemany('INSERT INTO result_rows VALUES (?,?)',[(rows+i+1,pack(row)) for i,row in enumerate(batch)])
        out.commit();rows+=len(batch)
    status='completed'
except Exception as exc:
    out.rollback()
    text=str(exc)
    code=(limit_hit or ('cancelled' if pathlib.Path(cfg['cancel_path']).exists() else
          'time_limit' if time.monotonic()-started>=cfg['seconds'] else
          'disk_limit' if 'full' in text or 'too large' in text else
          'memory_limit' if isinstance(exc,MemoryError) or 'memory' in text else
          'sql_error'))
    status='cancelled' if code=='cancelled' else 'partial' if rows else 'failed'
    error={'error_code':code,'message':text,'retryable':code in ('time_limit','memory_limit','disk_limit'),
           'limit_kind':code,'observed_units':{'elapsed_seconds':time.monotonic()-started,'output_rows':rows},
           'limit_units':{k:cfg[k] for k in ('seconds','memory_bytes','disk_bytes')}}
finally:
    db.close();out.close()
receipt={'status':status,'columns':columns,'output_rows':rows,'error':error,
         'vm_steps_approx':ticks*1000,'elapsed_seconds':time.monotonic()-started,
         'query_hash':cfg['query_hash'],'input_version':cfg['input_version'],
         'coverage':'complete_for_declared_query' if status=='completed' else 'incomplete'}
(root/'metrics.json').write_text(json.dumps(receipt))
print(json.dumps(receipt))
'''


class DataJobs:
    def __init__(self, workspace):
        self.ws = workspace
        self.path = workspace.private/'data_jobs.sqlite'
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS jobs(ref TEXT PRIMARY KEY,body TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS snapshots(path TEXT PRIMARY KEY,stat TEXT,hash TEXT)')
            db.execute('CREATE TABLE IF NOT EXISTS retries(key TEXT PRIMARY KEY,job TEXT)')

    def connect(self):
        return sqlite3.connect(self.path, timeout=10)

    def snapshot(self):
        path = self.ws.public/'business.sqlite'
        stat = path.stat()
        fingerprint = encoded([stat.st_size, stat.st_mtime_ns, stat.st_ino])
        with self.connect() as db:
            row = db.execute('SELECT stat,hash FROM snapshots WHERE path=?', (str(path),)).fetchone()
            if row and row[0] != fingerprint:
                raise ValueError('input_version_changed: frozen SQLite snapshot was modified')
            version = row[1] if row else file_hash(path)
            db.execute('INSERT OR IGNORE INTO snapshots VALUES (?,?,?)', (str(path), fingerprint, version))
        return {'snapshot_ref': 'snapshot:'+version, 'input_version': version, 'bytes': stat.st_size}

    def start(self, sql, parameters, resource_profile, snapshot_ref, *, key):
        source = self.snapshot()
        if snapshot_ref != source['snapshot_ref']:
            raise ValueError('snapshot_version_conflict: use get_data_profile')
        ref = 'datajob:'+digest([key, source, sql, parameters, resource_profile])[:24]
        item = {'job_ref': ref, 'status': 'queued', 'created_at': now(), **source,
                'query_hash': digest([sql, parameters]), 'sql': sql, 'parameters': parameters,
                'resource_profile': resource_profile, 'execution_mode': 'sqlite_full_query',
                'attempts': [], 'result_ref': None, 'coverage': 'incomplete',
                'recovery': 'A new attempt reruns the entire original SQL. Result paging resumes; SQLite internal execution does not.'}
        with self.connect() as db:
            db.execute('INSERT OR IGNORE INTO jobs VALUES (?,?)', (ref, encoded(item)))
        return self.get(ref)

    def get(self, ref):
        with self.connect() as db:
            row = db.execute('SELECT body FROM jobs WHERE ref=?', (ref,)).fetchone()
        if not row:
            raise ValueError('unknown_data_job: owned job_ref required')
        return json.loads(row[0])

    def save(self, item):
        with self.connect() as db:
            db.execute('UPDATE jobs SET body=? WHERE ref=?', (encoded(item), item['job_ref']))

    def jobs(self):
        with self.connect() as db:
            return [json.loads(row[0]) for row in db.execute('SELECT body FROM jobs ORDER BY rowid')]

    def cancel(self, ref):
        item = self.get(ref)
        if item['status'] in ('queued', 'running'):
            directory = self.ws.science/'data_jobs'/ref.split(':')[1]
            directory.mkdir(parents=True, exist_ok=True)
            (directory/'cancel').touch()
            if item['status'] == 'queued':
                item['status'] = 'cancelled'; self.save(item)
        return {'job_ref': ref, 'cancellation_requested': True, 'status': item['status']}

    def retry(self, ref, *, key):
        with self.connect() as db:
            prior = db.execute('SELECT job FROM retries WHERE key=?', (key,)).fetchone()
        if prior:
            if prior[0] != ref:
                raise ValueError('retry_operation_identity_conflict')
            return self.get(ref)
        item = self.get(ref)
        if item['status'] not in ('failed', 'partial', 'cancelled'):
            raise ValueError('retry_requires_terminal_incomplete_job')
        directory = self.ws.science/'data_jobs'/ref.split(':')[1]
        (directory/'cancel').unlink(missing_ok=True)
        item['status'] = 'queued'
        with self.connect() as db:
            db.execute('UPDATE jobs SET body=? WHERE ref=?', (encoded(item), ref))
            db.execute('INSERT INTO retries VALUES (?,?)', (key, ref))
        return item

    def run_next(self, *, remaining_seconds):
        queued = [x for x in self.jobs() if x['status'] in ('queued', 'running')]
        if not queued:
            return None
        item = queued[0]
        directory = self.ws.science/'data_jobs'/item['job_ref'].split(':')[1]
        directory.mkdir(parents=True, exist_ok=True)
        if item['status'] == 'running':
            # The runtime lock excludes a live owner. Reconcile durable output
            # before declaring interrupted; never append to a failed prefix.
            previous = item['attempts'][-1]
            self.finish(item, previous)
            return self.get(item['job_ref'])
        profile = PROFILES[item['resource_profile']]
        seconds = min(profile['seconds'], int(remaining_seconds)-2)
        if seconds < 1:
            return {'job_ref': item['job_ref'], 'status': 'waiting_for_authorized_time'}
        if self.snapshot()['input_version'] != item['input_version']:
            raise ValueError('input_version_changed')
        number = len(item['attempts'])+1
        worker = RestrictedPythonWorkspace(directory/str(number), self.ws.public,
                                            directory, per_execution=True)
        run_dir = worker.directory/'executions'/'run_001'
        attempt = {'attempt': number, 'status': 'running', 'started_at': now(),
                   'directory': str(run_dir), 'seconds': seconds}
        item['attempts'].append(attempt); item['status'] = 'running'; self.save(item)
        cfg = {**profile, 'seconds': seconds, 'input': str(self.ws.public/'business.sqlite'),
               'sql': item['sql'], 'parameters': item['parameters'], 'cancel_path': str(directory/'cancel'),
               'query_hash': item['query_hash'], 'input_version': item['input_version']}
        code = 'CONFIG='+repr(base64.b64encode(encoded(cfg).encode()).decode())+'\n'+WORKER
        try:
            execution = worker.run(code, timeout=seconds+1)
            attempt['execution'] = execution
        except Exception as error:
            attempt['execution'] = {'ok': False, 'error': type(error).__name__+': '+str(error)}
        self.finish(item, attempt)
        return self.get(item['job_ref'])

    def finish(self, item, attempt):
        root = Path(attempt['directory'])
        metrics = root/'metrics.json'
        if metrics.exists():
            values = json.loads(metrics.read_text())
            # Verify the immutable input stat again after execution.
            try:
                self.snapshot()
            except ValueError as error:
                values.update(status='failed', coverage='incomplete',
                              error={'error_code': 'input_version_changed', 'retryable': False, 'message': str(error)})
        else:
            execution = attempt.get('execution', {})
            text = execution.get('error', '')+' '+execution.get('stderr', '')
            code = ('time_limit' if 'time limit' in text else 'memory_limit' if 'MemoryError' in text else
                    'disk_limit' if execution.get('exit_code') in (-25, 153) or 'disk is full' in text or 'File too large' in text else 'worker_interrupted')
            values = {'status': 'failed', 'coverage': 'incomplete', 'output_rows': 0,
                      'error': {'error_code': code, 'retryable': True,
                                'message': 'No durable completion receipt; partial files retained. Retry starts a new full execution.'}}
        attempt.update(values, finished_at=now())
        attempt['artifacts'] = [self.ws.file_ref(p) for p in (root/'result.sqlite', metrics,
            root/'analysis_001.py', root/'execution_001.json') if p.exists()]
        if values['status'] == 'completed':
            attempt['result_ref'] = 'dataresult:'+digest([item['job_ref'], attempt['attempt'], file_hash(root/'result.sqlite')])[:24]
            item['result_ref'] = attempt['result_ref']
        item.update(status=values['status'], coverage=values['coverage'], error=values.get('error'))
        if item['error']:
            item['error'].update(input_version=item['input_version'], query_hash=item['query_hash'],
                                 artifact_refs=attempt['artifacts'])
        self.save(item)

    def describe(self, item):
        current = item['attempts'][-1] if item['attempts'] else {}
        return {k: item.get(k) for k in ('job_ref', 'status', 'snapshot_ref', 'input_version',
                    'query_hash', 'execution_mode', 'result_ref', 'coverage', 'error', 'recovery')} | {
            'current_attempt': len(item['attempts']), 'output_rows': current.get('output_rows'),
            'artifact_refs': current.get('artifacts', []),
            'progress': 'SQLite execution progress is unknown until rows are emitted; output_rows is not scanned input rows.'}

    def read(self, result_ref, cursor, limit):
        matches = [(j, a) for j in self.jobs() for a in j['attempts'] if a.get('result_ref') == result_ref]
        if not matches:
            raise ValueError('completed_owned_result_ref_required')
        job, attempt = matches[0]
        offset = 0
        if cursor:
            try:
                version, offset = json.loads(base64.urlsafe_b64decode(cursor.encode()))
            except (ValueError, TypeError):
                raise ValueError('invalid_result_cursor') from None
            if version != result_ref or type(offset) is not int or offset < 0:
                raise ValueError('result_cursor_version_conflict')
        artifact = next(a for a in attempt['artifacts'] if a['path'].endswith('result.sqlite'))
        path, _ = self.ws.file(artifact['ref'])
        with sqlite3.connect(Path(path).as_uri()+'?mode=ro', uri=True) as db:
            values = db.execute('SELECT n,payload FROM result_rows WHERE n>? ORDER BY n LIMIT ?', (offset, limit)).fetchall()
        rows = []; consumed = offset; total_bytes = 0
        for n, raw in values:
            if total_bytes+len(raw.encode()) > 16000:
                if not rows:
                    return {'ok': False, 'error_code': 'result_row_exceeds_preview',
                            'result_ref': result_ref, 'artifact': artifact, 'coverage': attempt['coverage'],
                            'action': 'Analyze this result.sqlite inside run_python; raw row is preserved.'}
                break
            rows.append(json.loads(raw)); total_bytes += len(raw.encode()); consumed = n
        next_cursor = base64.urlsafe_b64encode(encoded([result_ref, consumed]).encode()).decode() if consumed < attempt['output_rows'] else None
        return {'result_ref': result_ref, 'input_version': job['input_version'], 'query_hash': job['query_hash'],
                'columns': attempt['columns'], 'rows': rows, 'output_rows': attempt['output_rows'],
                'next_cursor': next_cursor, 'artifact_refs': attempt['artifacts'], 'coverage': attempt['coverage']}

    def profile(self):
        source = self.snapshot()
        with sqlite3.connect((self.ws.public/'business.sqlite').as_uri()+'?mode=ro', uri=True) as db:
            tables = []
            for name, kind in db.execute("SELECT name,type FROM sqlite_master WHERE type IN ('table','view') AND name NOT LIKE 'sqlite_%'"):
                quoted = '"'+name.replace('"', '""')+'"'
                tables.append({'name': name, 'kind': kind,
                    'columns': [list(r) for r in db.execute('PRAGMA table_info('+quoted+')')],
                    'indexes': [list(r) for r in db.execute('PRAGMA index_list('+quoted+')')]})
        return {**source, 'tables': tables, 'resource_profiles': PROFILES,
                'tool': 'start_data_job', 'semantics': 'Full original read-only SQL, streamed output, immutable paged results.',
                'row_counts': 'Run COUNT(*) as a batch job; views may expand their base tables.',
                'partition_plans': 'Not installed. No arbitrary SQL is split into partial aggregates.'}
