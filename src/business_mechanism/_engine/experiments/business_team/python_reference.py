"""Small source-bound Python reference, without importing/executing received code."""
import ast
import csv
import hashlib
import json
from pathlib import Path
import sqlite3


def reference(public):
    public=Path(public).resolve();source=public/'research_data.py'
    tree=ast.parse(source.read_text())
    api={}
    for node in tree.body:
        if isinstance(node,ast.FunctionDef) and not node.name.startswith('_'):
            api[node.name]='('+ast.unparse(node.args)+')'
        elif isinstance(node,ast.ClassDef):
            api[node.name]={m.name:('property; access without ()' if any(isinstance(d,ast.Name) and d.id=='property' for d in m.decorator_list)
                                  else '('+ast.unparse(m.args)+')') for m in node.body
                            if isinstance(m,ast.FunctionDef)}
    dictionary=json.loads((public/'data_dictionary.json').read_text())
    database=public/Path(dictionary['database_file']).name
    with sqlite3.connect(database.as_uri()+'?mode=ro',uri=True) as con:
        actual={r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type IN ('table','view')")}
        tables={name:{'columns':[r[1] for r in con.execute('PRAGMA table_info("'+name.replace('"','""')+'")')]}
                for name in sorted(actual & dictionary['tables'].keys())}
    csv_files={}
    for path in sorted(public.glob('*.csv')):
        with path.open(newline='',encoding='utf-8-sig') as f:
            columns=next(csv.reader(f),[])
        csv_files[path.name]={'column_count':len(columns),'columns':columns}
    return {'version':'python-reference-v1','source_file':str(source),
            'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
            'api_signatures':api,'registered_sql_tables':tables,'csv_files':csv_files,
            'rules':[
                'read_table(name) accepts an exact registered SQL table name, not a CSV name, file path or base_dir keyword. CSV files use pandas.read_csv with PUBLIC_DIR.',
                'CSV research views may contain joined columns absent from a SQL table. Matching rows or selected measurements does not establish whole-schema equivalence.',
                'Frame is a limited provenance wrapper, not pandas.DataFrame. Only listed methods are implemented; to_pandas() returns a copy for arbitrary pandas work.',
                'Group.agg uses keyword output=(input_column,string_operation). Frame.to_csv interpretations are producer statements, not verified field meanings.',
                'Frame constructor columns is a mapping of column names to lineage records, not a list of column labels or source= keyword. Do not invent lineage just to wrap an ordinary pandas result.',
                'Ordinary pandas CSV export is allowed. Explain filters, units and untracked transformations in the actual code/delivery; independent review is still needed.',
                'Read received files under PUBLIC_DIR/ARTIFACT_DIR; write only the current WORK_DIR. A new run_python has a new process and WORK_DIR; prior paths are read-only.',
                'This reference documents software and file structure. It grants no tool permissions and supplies no research finding or scientific certification.'],
            'examples':{
                'registered_table_to_pandas':'from research_data import read_table\nf = read_table(table_name)\ndf = f.to_pandas()\n',
                'CSV_to_pandas':'import os, pandas as pd\ndf = pd.read_csv(os.path.join(os.environ["PUBLIC_DIR"], csv_name))\n',
                'tracked_aggregation':'out = f.groupby(group_keys).agg(total=(value_column, "sum"))\nout.to_csv(output_path, interpretations={"total": output_meaning})\n',
                'ordinary_pandas_export':'df.to_csv(output_path, index=False)\n# Describe actual transforms and units; do not pass Frame-only interpretations= to pandas.to_csv.\n'}}


def short_help(value):
    api=value['api_signatures']
    return ('Python接口：research_data.read_table'+api['read_table']+'只接收注册SQLite表名，不接收CSV路径或base_dir。'
            'CSV用pandas.read_csv；CSV联接视图不自动等于原SQL表。Frame不是完整DataFrame；'
            'Frame.to_pandas'+api['Frame']['to_pandas']+'后可用任意pandas。'
            '若使用Frame，to_csv'+api['Frame']['to_csv']+'；普通pandas直接to_csv，声明未追踪变换，不编造lineage。'
            '真实签名、表/CSV列结构与通用示例的精确文件路径见read_context.python_api_reference；将返回路径原样交read_artifact读取。')


def materialize(public,preserve_source_identity=False):
    value=reference(public)
    path=Path(public)/'python_api.json'
    if preserve_source_identity:
        if not path.is_file():raise ValueError('missing received Python reference during continuation')
        previous=json.loads(path.read_text())
        value['source_file']=previous['source_file']
        if value!=previous:raise ValueError('received Python API source/signatures/table contract changed')
        return previous
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
    return value
