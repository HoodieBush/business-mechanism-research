"""Installed engine code stays private even inside the Python environment."""
from pathlib import Path
from execution import PythonWorkspace, quoted


class RestrictedPythonWorkspace(PythonWorkspace):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.private_code_roots = (Path(__file__).resolve().parent,)

    def profile(self, write_root=None):
        profile = super().profile(write_root)
        return profile+'\n'+'\n'.join('(deny file-read* (subpath '+quoted(p)+'))' for p in self.private_code_roots)


def restrict_worker(workspace):
    previous = workspace.worker
    worker = RestrictedPythonWorkspace(previous.directory, previous.public, previous.shared,
                                       per_execution=previous.per_execution)
    worker.readonly_input_roots = previous.readonly_input_roots
    workspace.worker = worker
