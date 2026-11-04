"""Persistent researcher/critic service. No network or model call on import."""
from pathlib import Path
import sys
import hashlib
import json

__version__ = '0.1.4'


def _bootstrap():
    here = Path(__file__).resolve().parent
    candidates = [here/'_engine', *here.parents]
    for root in candidates:
        if (root/'experiments/insight_research/reuse_manifest.json').is_file():
            manifest = here/'engine_manifest.json'
            if root == here/'_engine' and manifest.exists():
                for relative, version in json.loads(manifest.read_text())['files'].items():
                    file = (root/relative).resolve()
                    if not file.is_relative_to(root) or not file.is_file() or hashlib.sha256(file.read_bytes()).hexdigest() != version:
                        raise RuntimeError('Installed engine source integrity failed: '+relative)
            for directory in (root/'experiments/capability_lab', root/'experiments/business_team', root):
                if str(directory) not in sys.path:
                    sys.path.insert(0, str(directory))
            return root
    raise RuntimeError('Engine source bundle missing; install the built distribution or use the project source tree.')


ENGINE_ROOT = _bootstrap()


def create_project(*args, **kwargs):
    from .service import create_project as create
    return create(*args, **kwargs)


def run_project(*args, **kwargs):
    from .service import run_project as run
    return run(*args, **kwargs)


def project_status(*args, **kwargs):
    from .service import project_status as status
    return status(*args, **kwargs)
