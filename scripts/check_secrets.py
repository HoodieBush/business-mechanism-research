"""Scan files or the exact Git index/HEAD. Report paths only, never matches."""
import argparse
import json
from pathlib import Path
import re
import subprocess

ROOT=Path(__file__).resolve().parents[1]
PATTERNS=[re.compile(rb'\bsk-[A-Za-z0-9_-]{20,}'),
          re.compile(rb'\bgh[pousr]_[A-Za-z0-9_]{20,}'),
          re.compile(rb'\bgithub_pat_[A-Za-z0-9_]{20,}'),
          re.compile(rb'-----BEGIN [A-Z ]*PRIVATE KEY-----')]
EXCLUDED={'.git','.venv','venv','__pycache__','build','dist','work','runs','inputs','example-inputs'}


def git(*args):
    return subprocess.check_output(['git','-C',str(ROOT),*args])


def entries(mode):
    if mode=='all-files':
        for path in ROOT.rglob('*'):
            rel=path.relative_to(ROOT)
            if any(x in EXCLUDED or x.endswith('.egg-info') or x.startswith('acceptance-') for x in rel.parts):continue
            if path.is_file() and not path.is_symlink():yield str(rel),path.read_bytes()
    elif mode=='staged':
        for raw in git('ls-files','-s','-z').split(b'\0'):
            if not raw:continue
            fields,path=raw.split(b'\t',1);permissions,oid,stage=fields.decode().split()
            if stage!='0':raise RuntimeError('Unmerged Git index.')
            if permissions!='160000':yield path.decode(),git('cat-file','blob',oid)
    else:
        for raw in git('ls-tree','-r','-z','HEAD').split(b'\0'):
            if not raw:continue
            fields,path=raw.split(b'\t',1);_,kind,oid=fields.decode().split()
            if kind=='blob':yield path.decode(),git('cat-file','blob',oid)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    group=parser.add_mutually_exclusive_group()
    group.add_argument('--all-files',action='store_true');group.add_argument('--staged',action='store_true');group.add_argument('--tracked',action='store_true')
    args=parser.parse_args();mode='all-files' if args.all_files else 'staged' if args.staged else 'tracked'
    findings=[];count=0
    for path,data in entries(mode):
        count+=1
        if any(p.search(data) for p in PATTERNS):findings.append(path)
    print(json.dumps({'passed':not findings,'scope':mode,'files':count,'matching_paths_only':findings,'contents_redacted':True}))
    return 1 if findings else 0


if __name__=='__main__':raise SystemExit(main())
