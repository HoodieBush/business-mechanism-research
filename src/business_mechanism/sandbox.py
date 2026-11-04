"""Installed engine code stays private even inside the Python environment."""
from pathlib import Path
import json
import os
import shutil
import subprocess
import sys
import tempfile
from execution import PythonWorkspace, quoted


def backend_name():
    if sys.platform=='darwin':
        if not Path('/usr/bin/sandbox-exec').is_file():
            raise RuntimeError('macOS sandbox-exec unavailable; refuse unsandboxed analysis.')
        return 'macos-seatbelt'
    if sys.platform=='linux':
        executable=shutil.which('bwrap')
        if not executable:
            raise RuntimeError('Linux requires bubblewrap: install the maintained distro package, then run tools/check_install.py.')
        result=subprocess.run([executable,'--help'],capture_output=True,text=True,timeout=10)
        if result.returncode or '--disable-userns' not in result.stdout:
            raise RuntimeError('bubblewrap must support --disable-userns; install a supported maintained package.')
        return 'linux-bubblewrap'
    raise RuntimeError('Supported runtimes are macOS or Linux with verified isolation; native Windows is not supported.')


class RestrictedPythonWorkspace(PythonWorkspace):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.private_code_roots = (Path(__file__).resolve().parent,)

    def profile(self, write_root=None):
        if sys.platform=='linux':
            return json.dumps({'backend':'linux-bubblewrap','readonly':[str(p) for p in self.read_roots()],
                'writable':str(write_root or self.directory),'private_source_hidden':[str(p) for p in self.private_code_roots],
                'network':'isolated namespace','processes':'private pid namespace','nested_user_namespaces':False},indent=2)
        profile = super().profile(write_root)
        return profile+'\n'+'\n'.join('(deny file-read* (subpath '+quoted(p)+'))' for p in self.private_code_roots)

    def require_isolation(self):
        backend_name()

    def read_roots(self):
        return [self.public,self.shared,self.directory,Path(sys.prefix).resolve(),
                Path(sys.base_prefix).resolve(),self.python.resolve().parent.parent,*map(Path,self.readonly_input_roots)]

    def sandbox_command(self, profile, launcher, run_dir):
        if sys.platform!='linux':
            return super().sandbox_command(profile,launcher,run_dir)
        command=[shutil.which('bwrap'),'--unshare-user','--unshare-pid','--unshare-net','--unshare-ipc','--unshare-uts',
                 '--disable-userns','--die-with-parent','--new-session','--cap-drop','ALL']
        mounted=[]
        for name in ('/usr','/bin','/sbin','/lib','/lib64'):
            path=Path(name)
            if path.is_symlink():
                command+=['--symlink',os.readlink(path),name]
            elif path.is_dir():
                command+=['--ro-bind',name,name];mounted.append(path.resolve())
        command+=['--proc','/proc','--dev','/dev','--size','67108864','--tmpfs','/tmp']
        # Construct an empty filesystem, exposing only runtime/input roots.
        # Never bind the host root, home, /run, or private research databases.
        for root in sorted({p.resolve() for p in self.read_roots()},key=lambda p:len(p.parts)):
            if not root.exists() or any(root.is_relative_to(p) for p in mounted):continue
            command+=['--ro-bind',str(root),str(root)];mounted.append(root)
        for name in ('/etc/ld.so.cache','/etc/localtime','/etc/nsswitch.conf','/etc/passwd','/etc/group','/etc/fonts'):
            path=Path(name)
            if path.exists():command+=['--ro-bind',str(path.resolve()),name]
        command+=['--bind',str(run_dir),str(run_dir)]
        # Runtime packages may share a venv with the engine; mask source last
        # so a broad interpreter mount cannot expose it to either role.
        for root in self.private_code_roots:
            if any(root.is_relative_to(p) for p in mounted):
                command+=['--tmpfs',str(root),'--remount-ro',str(root)]
        command+=['--chdir',str(run_dir),'--',str(self.python),'-I','-c',launcher]
        return command


def probe_runtime():
    """Exercise the actual worker, not just binary presence. No provider call."""
    name=backend_name()
    with tempfile.TemporaryDirectory(prefix='business-research-isolation-') as td:
        root=Path(td).resolve();public=root/'public';public.mkdir();shared=root/'shared';shared.mkdir()
        (public/'input.txt').write_text('read-only input')
        private=root/'not-exposed.txt';private.write_text('unexposed canary')
        worker=RestrictedPythonWorkspace(root/'compute',public,shared,per_execution=True)
        code=f'''import os,json,pathlib
data=pathlib.Path({str(public/'input.txt')!r}).read_text()
try:pathlib.Path({str(private)!r}).read_text();hidden=False
except OSError:hidden=True
try:pathlib.Path({str(public/'input.txt')!r}).write_text('overwrite');readonly=False
except OSError:readonly=True
pathlib.Path(os.environ['WORK_DIR'],'output.txt').write_text('allowed')
print(json.dumps({{'read':data=='read-only input','private_hidden':hidden,'input_readonly':readonly}}))
'''
        result=worker.run(code,timeout=20)
        if not result.get('ok'):
            raise RuntimeError('Isolation probe failed for '+name+': '+result.get('stderr',result.get('error',''))[:700]+
                ' Linux also requires permitted unprivileged user namespaces; consult docs/LINUX.md.')
        values=json.loads(result['stdout'])
        if not all(values.values()):raise RuntimeError('Isolation boundary probe failed: '+name)
        return {'backend':name,'passed':True,'checks':values,'model_calls':0}


def restrict_worker(workspace):
    previous = workspace.worker
    worker = RestrictedPythonWorkspace(previous.directory, previous.public, previous.shared,
                                       per_execution=previous.per_execution)
    worker.readonly_input_roots = previous.readonly_input_roots
    workspace.worker = worker
