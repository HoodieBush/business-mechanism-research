"""Observe registered SQLite/CSV reads in ordinary Python; not a semantic oracle.

Installed by the isolated launcher, no network, credentials or private source.
SQLite authorizer records actual columns requested, not domain-specific metrics.
This is cooperative research provenance, not tamper-proof adversarial auditing.
"""
import hashlib
import json
import os
import sqlite3
from pathlib import Path


def install():
    public=Path(os.environ['PUBLIC_DIR']);trace=Path(os.environ['SOURCE_TRACE_FILE'])
    contract_path=public/'data_dictionary.json';contract=json.loads(contract_path.read_text())
    database=(public/Path(contract['database_file']).name).resolve();seen=set();hashes={}
    def record(path,table,columns):
        path=Path(path).resolve();key=(str(path),table,tuple(columns))
        if key in seen:return
        seen.add(key)
        if path not in hashes:hashes[path]=hashlib.sha256(path.read_bytes()).hexdigest()
        with trace.open('a') as f:f.write(json.dumps({'path':str(path),'sha256':hashes[path],'table':table,'columns':list(columns),'observer':'registered_read_observer_v1'})+'\n')
    connect=sqlite3.connect
    def observed_connect(filename,*args,**kwargs):
        con=connect(filename,*args,**kwargs)
        text=str(filename);text=text[5:].split('?',1)[0] if text.startswith('file:') else text
        try:registered=Path(text).resolve()==database
        except (TypeError,ValueError):registered=False
        if registered:
            def authorize(action,table,column,*rest):
                if action==sqlite3.SQLITE_READ and table in contract['tables']:
                    columns=[column] if column in contract['tables'][table]['columns'] else []
                    record(database,table,columns);record(contract_path,'source_contract',columns)
                return sqlite3.SQLITE_OK
            con.set_authorizer(authorize)
        return con
    sqlite3.connect=observed_connect
    import pandas as pd
    reader=pd.read_csv
    def observed_csv(filename,*args,**kwargs):
        result=reader(filename,*args,**kwargs)
        try:path=Path(filename).resolve()
        except (TypeError,ValueError):return result
        if path.parent==public and path.suffix=='.csv' and hasattr(result,'columns'):
            record(path,'registered_csv',list(result.columns));record(contract_path,'source_contract',list(result.columns))
        return result
    pd.read_csv=observed_csv
