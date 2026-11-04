"""Actual macOS file/network sandbox for Agent-authored Python."""
from __future__ import annotations
import json
import os
import subprocess
import sys
import hashlib
import shutil
from pathlib import Path


def quoted(path):
    # SBPL strings accept UTF-8, not JSON's ASCII-only \uXXXX escapes. Keep
    # quoted control characters/backslashes while binding the actual path.
    return json.dumps(str(Path(path).resolve()), ensure_ascii=False)


def last_number(directory, prefix, suffix):
    """Recover arbitrarily long counters without mistaking support files for runs."""
    return max([0] + [int(p.stem[len(prefix):]) for p in Path(directory).rglob(prefix+'*'+suffix)
                      if 'prior_outputs' not in p.parts and p.stem[len(prefix):].isdigit()])


class PythonWorkspace:
    def __init__(self, directory, public, shared, per_execution=False):
        self.directory = Path(directory).resolve()
        self.public, self.shared = Path(public).resolve(), Path(shared).resolve()
        self.per_execution=per_execution
        self.readonly_input_roots=()
        for name in ("tmp", ".matplotlib"):
            (self.directory / name).mkdir(parents=True, exist_ok=True)
        # Retain the venv entry point; resolving its symlink would bypass
        # pyvenv.cfg and silently use the base interpreter's dependencies.
        self.python = Path(sys.executable).absolute()
        self.count = last_number(self.directory, 'analysis_', '.py')

    def profile(self,write_root=None):
        roots = [self.public, self.shared, self.directory, self.python.parent.parent,
                 Path(sys.base_prefix).resolve(), self.python.resolve().parent.parent,
                 Path("/System"), Path("/usr"), Path("/Library"), Path("/private/preboot"), Path("/private/var/db/dyld")]
        roots += list(self.readonly_input_roots)
        # Restrict data access/write/network while retaining macOS interpreter
        # startup services. Conda itself is not the isolation boundary.
        reads = " ".join(f"(require-not (subpath {quoted(p)}))" for p in roots)
        parents = {p for root in roots[:6] for p in root.parents}
        reads += " " + " ".join(f"(require-not (literal {quoted(p)}))" for p in sorted(parents))
        return "\n".join(["(version 1)", "(allow default)", "(deny network*)",
                          "(deny process-info* (target others))", "(deny signal (target others))",
                          '(deny file-read-data (require-all ' + reads +
                          ' (require-not (subpath "/dev")) (require-not (subpath "/private/etc"))))',
                          f'(deny file-write* (require-all (require-not (subpath {quoted(write_root or self.directory)})) (require-not (subpath "/dev"))))'])

    def require_isolation(self):
        if not Path("/usr/bin/sandbox-exec").exists():
            raise RuntimeError("macOS sandbox unavailable; refuse unsandboxed model code")

    def sandbox_command(self, profile, launcher, run_dir):
        return ["/usr/bin/sandbox-exec", "-f", str(profile), str(self.python), "-I", "-c", launcher]

    def run(self, code, timeout=45):
        self.require_isolation()
        self.count += 1
        run_dir=self.directory/'executions'/f'run_{self.count:03d}' if self.per_execution else self.directory
        if self.per_execution:run_dir.mkdir(parents=True,exist_ok=False)
        for name in ('tmp','.matplotlib'):(run_dir/name).mkdir(parents=True,exist_ok=True)
        filename = run_dir / f"analysis_{self.count:03d}.py"
        with filename.open('x') as script:script.write(code)
        profile = run_dir / "execution.sb"
        profile.write_text(self.profile(run_dir))
        env = {"PATH": str(self.python.parent) + ":/usr/bin:/bin", "PYTHONNOUSERSITE": "1", "PYTHONDONTWRITEBYTECODE": "1",
               "TMPDIR": str(run_dir / "tmp"), "MPLCONFIGDIR": str(run_dir / ".matplotlib"),
               "MPLBACKEND": "Agg", "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1",
               "PUBLIC_DIR": str(self.public), "ARTIFACT_DIR": str(self.shared), "WORK_DIR": str(run_dir)}
        source_trace=run_dir/f"execution_{self.count:03d}_source_reads.jsonl"
        env['SOURCE_TRACE_FILE']=str(source_trace)
        def output_files():
            return {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in run_dir.rglob("*") if p.is_file()
                    and not any(part in ("tmp", ".matplotlib", "prior_outputs") for part in p.relative_to(run_dir).parts)
                    and not p.name.endswith((".sb", ".pyc", ".meta.json"))}
        before = output_files()
        before_modified = {p:p.stat().st_mtime_ns for p in before}
        # Keep original bytes when a model overwrites an earlier CSV/report.
        prior = run_dir / "prior_outputs" / f"before_{self.count:03d}"
        for p in before:
            target = prior / p.relative_to(self.directory)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(p, target)
            sidecar = Path(str(p)+".meta.json")
            if sidecar.exists(): shutil.copyfile(sidecar,Path(str(target)+".meta.json"))
        try:
            instrumentation='import source_access;source_access.install();' if (self.public/'source_access.py').exists() else ''
            launcher=f"import sys,runpy;sys.path.insert(0,{str(self.public)!r});{instrumentation}runpy.run_path({str(filename)!r},run_name='__main__')"
            result = subprocess.run(self.sandbox_command(profile, launcher, run_dir),
                                    cwd=run_dir, env=env, capture_output=True, text=True, timeout=timeout)
            response = {"ok": result.returncode == 0, "exit_code": result.returncode,
                        "stdout": result.stdout[:12000], "stderr": result.stderr[:6000], "code_file": str(filename)}
            response.update(stdout_truncated=len(result.stdout)>12000,stderr_truncated=len(result.stderr)>6000)
            (run_dir/f"execution_{self.count:03d}_stdout.txt").write_text(result.stdout)
            (run_dir/f"execution_{self.count:03d}_stderr.txt").write_text(result.stderr)
        except subprocess.TimeoutExpired:
            response = {"ok": False, "error": "Python time limit reached", "code_file": str(filename)}
        after = output_files()
        # A new execution may intentionally reproduce identical data bytes.
        # Its code/meaning/lineage still belongs to this execution, so a rewrite
        # must refresh the execution binding even when the content hash is equal.
        changed = [p for p, digest in after.items() if before.get(p) != digest or before_modified.get(p)!=p.stat().st_mtime_ns]
        for p in before:
            if p not in changed:
                (prior/p.relative_to(self.directory)).unlink(missing_ok=True)
                Path(str(prior/p.relative_to(self.directory))+".meta.json").unlink(missing_ok=True)
        response["generated_files"] = sorted(str(p) for p in changed)
        owned={filename,profile,source_trace,run_dir/f"execution_{self.count:03d}_stdout.txt",run_dir/f"execution_{self.count:03d}_stderr.txt"}
        response['data_outputs']=sorted(str(p) for p in changed if p not in owned and not p.name.endswith('.lineage.json'))
        response["replaced_versions"] = {str(p): str(prior / p.relative_to(self.directory)) for p in changed if p in before}
        receipt = run_dir / f"execution_{self.count:03d}.json"
        response["execution_receipt"] = str(receipt)
        response['source_reads']=[json.loads(line) for line in source_trace.read_text().splitlines()] if source_trace.exists() else []
        response['execution_directory']=str(run_dir)
        receipt.write_text(json.dumps(response, ensure_ascii=False, indent=2))
        return response

    def forecast(self, code_path, history_path, future_frame, output_name):
        code_path, history_path = Path(code_path).resolve(), Path(history_path).resolve()
        future = self.directory / f"{output_name}_inputs.csv"
        future_frame.to_csv(future, index=False)
        output = self.directory / f"{output_name}_predictions.json"
        code = f'''import importlib.util, json, numpy as np, pandas as pd
spec=importlib.util.spec_from_file_location("candidate", {str(code_path)!r})
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
history=pd.read_csv({str(history_path)!r})
future=pd.read_csv({str(future)!r})
pred=np.asarray(module.predict(history,future),dtype=float)
if pred.shape!=(len(future),) or not np.isfinite(pred).all() or (pred<0).any() or (pred>100).any():
    raise ValueError("predict must return one finite value in [0,100] per input row")
json.dump(pred.tolist(),open({str(output)!r},"w"))
print(json.dumps({{"rows":len(pred),"mean":float(pred.mean())}}))
'''
        receipt = self.run(code)
        if not receipt["ok"]:
            raise ValueError("forecast execution failed: " + receipt.get("stderr", receipt.get("error", "")))
        return json.loads(output.read_text()), receipt
