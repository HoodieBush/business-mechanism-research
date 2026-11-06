"""No-network deployment preflight. Never prints or stores a credential."""
import argparse
import importlib
import importlib.metadata
import json
from pathlib import Path
import platform
import sqlite3
import subprocess
import sys
import tempfile
import tomllib
from urllib.parse import urlparse


def main(model_path=None,data_path=None):
    checks=[]
    def add(name,passed,detail):
        checks.append({'check':name,'passed':bool(passed),'detail':detail})
    add('python',sys.version_info[:2]==(3,12),'Requires Python 3.12.')
    add('platform',(sys.platform=='darwin' and platform.machine()=='arm64') or sys.platform=='linux','macOS arm64 or Linux with actual isolation required; see support matrix.')
    modules=('business_mechanism','langgraph.graph','langgraph.checkpoint.sqlite','pydantic','numpy','pandas','scipy.stats','sklearn','statsmodels.api','matplotlib')
    for name in modules:
        try:importlib.import_module(name)
        except Exception as error:add('import:'+name,False,type(error).__name__+'; reinstall tested dependencies in a new venv.')
        else:add('import:'+name,True,'Import succeeded.')
    try:version=importlib.metadata.version('business-mechanism-research')
    except importlib.metadata.PackageNotFoundError:version='not-installed'
    expected=tomllib.loads((Path(__file__).resolve().parents[1]/'pyproject.toml').read_text())['project']['version']
    from business_mechanism import __version__ as code_version
    add('release_version',version==code_version==expected,
        'Expected: '+expected+'; installed metadata: '+version+'; imported package: '+code_version)
    try:
        from business_mechanism.sandbox import probe_runtime
        probe=probe_runtime()
        add('sandbox',probe['passed'],'Actual read/write boundary probe passed: '+probe['backend'])
    except (ImportError,RuntimeError,OSError,subprocess.TimeoutExpired) as error:
        add('sandbox',False,str(error))
    try:
        with sqlite3.connect(':memory:') as probe_db:
            heap = probe_db.execute('PRAGMA hard_heap_limit').fetchone()
        add('sqlite_query_heap_limit', heap is not None, 'SQLite must expose hard_heap_limit; each isolated SQL worker verifies activation.')
    except sqlite3.Error:
        add('sqlite_query_heap_limit', False, 'SQLite hard heap limit probe failed.')
    if model_path:
        try:
            config=json.loads(model_path.expanduser().read_text())
            if not isinstance(config,dict):raise ValueError('config must be an object')
            from business_mechanism.service import validate_model
            validate_model(config,(Path.cwd()/'work/preflight-placeholder').resolve())
            url=urlparse(config['base_url']);name=config['model']
            placeholder='YOUR_' in name or not name.strip() or (url.hostname or '').endswith(('.example','.invalid'))
            local=url.hostname in ('127.0.0.1','localhost','::1')
            add('model_target',not placeholder and bool(url.hostname) and (url.scheme=='https' or (local and url.scheme=='http')) and not url.username and not url.password and not url.path.rstrip('/').endswith('/chat/completions'),'Configure actual model and API prefix; placeholders and URL credentials are rejected. No network request was made.')
            generation=config.get('generation_options',{})
            add('model_capacity',generation.get('thinking')=={'type':'enabled'} and generation.get('reasoning_effort')=='high' and generation.get('max_tokens')==65536,'This release expects thinking/high/max_tokens65536.')
            from model_credentials import load_api_key
            try:key=load_api_key({**config,'requires_api_key':True})
            except (RuntimeError,OSError):add('credential',False,'Set the declared environment variable or an external nonempty api_key_file; value is never printed.')
            else:
                add('credential',bool(key),'Credential loaded without network request or serialization.')
                del key
            if config.get('api_key_file'):
                location=Path(config['api_key_file']).expanduser().resolve()
                add('external_credential_path',not location.is_relative_to(Path(__file__).resolve().parents[1]) and not location.is_relative_to((Path.cwd()/'work').resolve()),'Credential file must be outside the delivered package and research workspaces.')
            if config.get('token_budget_pointer'):
                add('external_experiment_ledger',False,'Remove original experiment ledger pointer for ordinary local deployment.')
        except (ValueError,KeyError,TypeError,OSError,ImportError) as error:
            add('model_config',False,type(error).__name__+'; see docs/CONFIGURATION.md. No config contents printed.')
    if data_path:
        try:
            data=data_path.expanduser().resolve()
            for name in ('business.sqlite','business_brief.md','data_dictionary.json'):
                item=data/name
                if not item.is_file() or item.is_symlink():raise ValueError('required regular input missing')
            dictionary=json.loads((data/'data_dictionary.json').read_text())
            if not isinstance(dictionary,dict) or not isinstance(dictionary.get('tables'),dict):raise ValueError('dictionary tables object required')
            with sqlite3.connect((data/'business.sqlite').as_uri()+'?mode=ro',uri=True) as db:
                integrity=db.execute('PRAGMA quick_check').fetchone()[0]
                tables=db.execute("SELECT name FROM sqlite_master WHERE type IN ('table','view') AND name NOT LIKE 'sqlite_%'").fetchall()
            add('input_data',integrity=='ok' and bool(tables) and bool((data/'business_brief.md').read_text().strip()),'SQLite integrity, received schema, JSON dictionary and nonempty brief checked; no business rows sent anywhere.')
        except (ValueError,TypeError,KeyError,OSError,sqlite3.Error):
            add('input_data',False,'Expected readable business.sqlite, nonempty business_brief.md and data_dictionary.json with tables object.')
    passed=all(c['passed'] for c in checks)
    result={'status':'passed' if passed else 'failed','checks':checks,'external_model_calls':0,'network_requests':0,'model_connectivity_tested':False,
            'meaning':'Local installation/configuration preflight only; not provider compatibility or scientific acceptance.'}
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return 0 if passed else 2


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model-config',type=Path)
    parser.add_argument('--data',type=Path)
    args=parser.parse_args()
    raise SystemExit(main(args.model_config,args.data))
