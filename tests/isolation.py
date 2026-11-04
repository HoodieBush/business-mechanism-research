"""Exercise real OS boundaries and venv scientific imports, zero model calls."""
import argparse
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
import time
from business_mechanism.sandbox import RestrictedPythonWorkspace, probe_runtime
import business_mechanism.sandbox as sandbox_module


def main(output):
    output=output.resolve();output.mkdir(parents=True,exist_ok=False)
    public=output/'public';public.mkdir();shared=output/'shared';shared.mkdir()
    data=public/'input.txt';data.write_text('original input')
    worker=RestrictedPythonWorkspace(output/'compute',public,shared,per_execution=True)
    private_source=Path(sandbox_module.__file__).resolve()
    # The source must be inside an otherwise readable interpreter environment,
    # making the exclusion test substantive rather than a missing mount.
    assert private_source.is_relative_to(Path(sys.prefix).resolve()),'Use a non-editable installed package to test the source boundary.'
    assert private_source.read_text()
    link=public/'source-link';link.symlink_to(private_source)
    listener=socket.socket();listener.bind(('127.0.0.1',0));listener.listen();port=listener.getsockname()[1]
    name='BUSINESS_RESEARCH_ISOLATION_SENTINEL';previous=os.environ.get(name);os.environ[name]='synthetic-controller-env-only'
    try:
        first=worker.run('import os,pathlib;pathlib.Path(os.environ["WORK_DIR"],"prior.txt").write_text("prior output")')
        assert first['ok'],first
        prior=Path(first['execution_directory'])/'prior.txt'
        code=f'''import json,os,pathlib,socket,sys
import numpy,pandas,scipy,statsmodels.api,matplotlib
def denied(path,write=False):
    try:
        pathlib.Path(path).write_text('changed') if write else pathlib.Path(path).read_text()
        return False
    except OSError:return True
try:
    connection=socket.create_connection(('127.0.0.1',{port}),timeout=.7);connection.close();network_denied=False
except OSError:network_denied=True
pathlib.Path(os.environ['WORK_DIR'],'allowed.txt').write_text('new output')
print(json.dumps({{
    'scientific_imports':True,
    'same_venv':str(pathlib.Path(sys.prefix).resolve())=={str(Path(sys.prefix).resolve())!r},
    'private_source_denied':denied({str(private_source)!r}),
    'source_symlink_denied':denied({str(link)!r}),
    'public_write_denied':denied({str(data)!r},True),
    'prior_write_denied':denied({str(prior)!r},True),
    'host_loopback_denied':network_denied,
    'controller_environment_absent':{name!r} not in os.environ
}}))
'''
        result=worker.run(code,timeout=60);assert result['ok'],result
        checks=json.loads(result['stdout']);assert all(checks.values()),checks
        assert data.read_text()=='original input' and prior.read_text()=='prior output'
        checks['current_work_output_created']=(Path(result['execution_directory'])/'allowed.txt').is_file()
        if sys.platform=='linux':
            host_pid_ns=os.readlink('/proc/self/ns/pid');host_net_ns=os.readlink('/proc/self/ns/net')
            namespaces=worker.run('import os,json;print(json.dumps({"pid":os.readlink("/proc/self/ns/pid"),"net":os.readlink("/proc/self/ns/net")}))')
            assert namespaces['ok'],namespaces
            values=json.loads(namespaces['stdout'])
            checks['pid_namespace_changed']=values['pid']!=host_pid_ns
            checks['network_namespace_changed']=values['net']!=host_net_ns
            child=worker.run('import subprocess,sys,os,pathlib;subprocess.run([sys.executable,"-c","import pathlib;pathlib.Path(\'child.txt\').write_text(\'allowed\')"],check=True)')
            checks['subprocess_allowed_in_current_work']=child['ok'] and (Path(child['execution_directory'])/'child.txt').is_file()
            timeout=worker.run('import subprocess,sys,time;subprocess.Popen([sys.executable,"-c","import pathlib,time;time.sleep(2);pathlib.Path(\'escaped-timeout.txt\').write_text(\'late\')"]);time.sleep(30)',timeout=1)
            time.sleep(2.5)
            checks['timeout_kills_descendants']=not timeout['ok'] and not (Path(timeout['execution_directory'])/'escaped-timeout.txt').exists()
        probe=probe_runtime();checks['preflight_actual_boundary']=probe['passed']
        assert all(checks.values()),checks
        receipt={'passed':all(checks.values()),'platform':sys.platform,'backend':probe['backend'],'checks':checks,'external_provider_calls':0}
        (output/'result.json').write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps(receipt));return receipt
    finally:
        listener.close()
        if previous is None:os.environ.pop(name,None)
        else:os.environ[name]=previous


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True)
    main(parser.parse_args().output)
