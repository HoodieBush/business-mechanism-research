from pathlib import Path
from ..common import sha
from ..prompt_runtime_v05.prompts import compose as previous_compose


def source_identity():
    here = Path(__file__).parent
    return {p.name: sha(p) for p in sorted(here.glob('*'))
            if p.is_file() and p.suffix in ('.py', '.md', '.txt')}


def compose(role):
    return previous_compose(role) + '\n\n' + (Path(__file__).parent/'operation_contract.md').read_text()
