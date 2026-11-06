"""File-backed capture and finite worker resources; no controller-size stdout."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import time


def file_hash(path):
    h=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''): h.update(block)
    return h.hexdigest()


def run(worker, code, timeout):
    worker.require_isolation(); worker.count+=1
    run_dir=worker.directory/'executions'/f'run_{worker.count:03d}' if worker.per_execution else worker.directory
    if worker.per_execution: run_dir.mkdir(parents=True,exist_ok=False)
    for name in ('tmp','.matplotlib'): (run_dir/name).mkdir(parents=True,exist_ok=True)
    filename=run_dir/f'analysis_{worker.count:03d}.py'
    with filename.open('x') as script: script.write(code)
    profile=run_dir/'execution.sb'; profile.write_text(worker.profile(run_dir))
    env={'PATH':str(worker.python.parent)+':/usr/bin:/bin','PYTHONNOUSERSITE':'1','PYTHONDONTWRITEBYTECODE':'1',
         'TMPDIR':str(run_dir/'tmp'),'MPLCONFIGDIR':str(run_dir/'.matplotlib'),'MPLBACKEND':'Agg',
         'OPENBLAS_NUM_THREADS':'1','OMP_NUM_THREADS':'1','PUBLIC_DIR':str(worker.public),
         'ARTIFACT_DIR':str(worker.shared),'WORK_DIR':str(run_dir)}
    trace=run_dir/f'execution_{worker.count:03d}_source_reads.jsonl'; env['SOURCE_TRACE_FILE']=str(trace)
    def files():
        return {p:file_hash(p) for p in run_dir.rglob('*') if p.is_file()
                and not any(x in ('tmp','.matplotlib','prior_outputs') for x in p.relative_to(run_dir).parts)
                and not p.name.endswith(('.sb','.pyc','.meta.json'))}
    before=files(); modified={p:p.stat().st_mtime_ns for p in before}
    prior=run_dir/'prior_outputs'/f'before_{worker.count:03d}'
    for p in before:
        target=prior/p.relative_to(worker.directory); target.parent.mkdir(parents=True,exist_ok=True); shutil.copyfile(p,target)
        sidecar=Path(str(p)+'.meta.json')
        if sidecar.exists(): shutil.copyfile(sidecar,Path(str(target)+'.meta.json'))
    instrumentation='import source_access;source_access.install();' if (worker.public/'source_access.py').exists() else ''
    # Limits execute inside the existing sandbox. Original model code is kept
    # byte-for-byte in filename; no unsandboxed fallback or controller preexec.
    limits=f'import resource;resource.setrlimit(resource.RLIMIT_FSIZE,(536870912,536870912));resource.setrlimit(resource.RLIMIT_CPU,({int(timeout)+1},{int(timeout)+2}));'
    if os.uname().sysname=='Linux': limits+='resource.setrlimit(resource.RLIMIT_AS,(4294967296,4294967296));'
    launcher=f'import sys,runpy;{limits}sys.path.insert(0,{str(worker.public)!r});{instrumentation}runpy.run_path({str(filename)!r},run_name="__main__")'
    out=run_dir/f'execution_{worker.count:03d}_stdout.txt'; err=run_dir/f'execution_{worker.count:03d}_stderr.txt'
    limit=2*1024*1024; failure=None; started=time.monotonic()
    rss_limit=getattr(worker,'rss_limit_bytes',None); next_rss_check=started; peak_rss=0
    with out.open('wb') as stdout, err.open('wb') as stderr:
        child=subprocess.Popen(worker.sandbox_command(profile,launcher,run_dir),cwd=run_dir,env=env,
                               stdout=stdout,stderr=stderr,start_new_session=True)
        while child.poll() is None:
            if time.monotonic()-started>=timeout: failure='worker_time_limit'
            elif out.stat().st_size+err.stat().st_size>limit: failure='worker_output_limit'
            if rss_limit and time.monotonic()>=next_rss_check:
                # sandbox-exec execs the SQL interpreter in this PID. Probe from
                # the controller so the isolated query cannot disable the guard.
                try:
                    probe=subprocess.run(['/bin/ps','-o','rss=','-p',str(child.pid)],
                                         capture_output=True,text=True,timeout=1)
                    rss=int(probe.stdout.strip())*1024
                    if probe.returncode: raise ValueError('RSS probe failed')
                    peak_rss=max(peak_rss,rss)
                    if rss>rss_limit: failure='worker_memory_limit'
                except (OSError,ValueError,subprocess.TimeoutExpired):
                    if child.poll() is None: failure='worker_resource_monitor_failed'
                next_rss_check=time.monotonic()+.1
            if failure:
                try: os.killpg(child.pid,signal.SIGKILL)
                except ProcessLookupError: pass
                child.wait(); break
            time.sleep(.02)
    if out.stat().st_size+err.stat().st_size>limit: failure=failure or 'worker_output_limit'
    with out.open('rb') as stream: stdout=stream.read(12000).decode('utf-8','replace')
    with err.open('rb') as stream: stderr=stream.read(6000).decode('utf-8','replace')
    response={'ok':child.returncode==0 and failure is None,'exit_code':child.returncode,'stdout':stdout,'stderr':stderr,
              'stdout_truncated':out.stat().st_size>12000,'stderr_truncated':err.stat().st_size>6000,'code_file':str(filename)}
    if rss_limit: response['memory_guard']={'kind':'sampled_process_rss','limit_bytes':rss_limit,'peak_observed_bytes':peak_rss,'interval_seconds':.1}
    if failure: response.update(error=failure,error_code=failure,coverage='incomplete')
    after=files(); changed=[p for p,h in after.items() if before.get(p)!=h or modified.get(p)!=p.stat().st_mtime_ns]
    for p in before:
        if p not in changed:
            (prior/p.relative_to(worker.directory)).unlink(missing_ok=True)
            Path(str(prior/p.relative_to(worker.directory))+'.meta.json').unlink(missing_ok=True)
    owned={filename,profile,trace,out,err}
    response.update(generated_files=sorted(map(str,changed)),
        data_outputs=sorted(str(p) for p in changed if p not in owned and not p.name.endswith('.lineage.json')),
        replaced_versions={str(p):str(prior/p.relative_to(worker.directory)) for p in changed if p in before},
        execution_directory=str(run_dir),source_reads=[])
    if trace.exists():
        with trace.open() as stream:
            for line in stream:
                if len(response['source_reads'])>=10000:
                    response['source_reads_truncated']=True; break
                try: response['source_reads'].append(json.loads(line))
                except ValueError:
                    response.update(source_trace_incomplete=True,ok=False,error='source_trace_incomplete')
                    break
    receipt=run_dir/f'execution_{worker.count:03d}.json'; response['execution_receipt']=str(receipt)
    receipt.write_text(json.dumps(response,ensure_ascii=False,indent=2)); return response
