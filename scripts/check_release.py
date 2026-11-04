"""Check source integrity, metadata and local documentation links, without a model."""
import ast
import hashlib
import json
from pathlib import Path
import re
import tomllib

ROOT=Path(__file__).resolve().parents[1]


def main():
    package=ROOT/'src/business_mechanism'
    meta=tomllib.loads((ROOT/'pyproject.toml').read_text())['project']
    tree=ast.parse((package/'__init__.py').read_text())
    version=next(n.value.value for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='__version__' for t in n.targets))
    assert meta['version']==version
    manifest=json.loads((package/'engine_manifest.json').read_text())['files']
    engine=package/'_engine';bad=[]
    for relative,expected in manifest.items():
        path=(engine/relative).resolve()
        if not path.is_relative_to(engine) or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=expected:bad.append(relative)
    assert not bad,{'engine_integrity_mismatches':bad}
    required=['README.md','README.zh-CN.md','LICENSE','CITATION.cff','CONTRIBUTING.md','SECURITY.md','DEPLOYMENT_VERIFICATION.md','RELEASE_STATUS.json']
    for name in required:assert (ROOT/name).is_file(),name
    missing=[];links=0
    documents=[ROOT/'README.md',ROOT/'README.zh-CN.md',*ROOT.glob('docs/*.md'),*ROOT.glob('examples/*.md'),ROOT/'CONTRIBUTING.md',ROOT/'SECURITY.md']
    for document in documents:
        for raw in re.findall(r'\]\(([^)]+)\)',document.read_text()):
            if '://' in raw or raw.startswith('#'):continue
            links+=1;target=raw.split('#',1)[0]
            if not (document.parent/target).exists():missing.append({'document':str(document.relative_to(ROOT)),'link':target})
    assert not missing,{'broken_local_links':missing}
    assert not list(engine.rglob('interface*probe*.json'))
    print(json.dumps({'passed':True,'version':version,'engine_files':len(manifest),'local_links':links,'provider_calls':0}))


if __name__=='__main__':main()
