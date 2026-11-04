"""Task-independent column provenance for ordinary dataframe research.

Tracked operations preserve input definitions. Renaming is a label change,
not a change of entity or unit. Unsupported arbitrary Python remains usable
through to_pandas(), but its outputs require independent interpretation/review.
No business metric, SKU, expected outcome or scientific answer is encoded here.
"""
import hashlib
import json
import os
import sqlite3
from pathlib import Path
import pandas as pd


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def source_entry(path, table, name, definition):
    return {'source_id':digest(path)+':'+table+'.'+name,'source_path':str(Path(path).resolve()),
            'source_sha256':digest(path),'table':table,'original_column':name,'definition':definition}


def traced_column(source):
    return {'sources':[source], 'expression':{'operation':'source','id':source['source_id']},
            'meaning_status':'input_definition_preserved'}


def derived(columns, operation, **details):
    sources={s['source_id']:s for c in columns for s in c['sources']}
    return {'sources':list(sources.values()),'expression':{'operation':operation,'inputs':[c['expression'] for c in columns],**details},
            'meaning_status':'derived_interpretation_requires_review'}


class Series:
    def __init__(self, values, lineage, row_operations=()):
        self.values,self.lineage,self.row_operations=values,lineage,list(row_operations)

    def _op(self,other,name):
        right=other.values if isinstance(other,Series) else other
        value=getattr(self.values,name)(right)
        parents=[self.lineage]+([other.lineage] if isinstance(other,Series) else [])
        details={} if isinstance(other,Series) else {'literal':other}
        return Series(value,derived(parents,name,**details),self.row_operations)

    def __eq__(self,o):return self._op(o,'__eq__')
    def __ne__(self,o):return self._op(o,'__ne__')
    def __lt__(self,o):return self._op(o,'__lt__')
    def __le__(self,o):return self._op(o,'__le__')
    def __gt__(self,o):return self._op(o,'__gt__')
    def __ge__(self,o):return self._op(o,'__ge__')
    def __and__(self,o):return self._op(o,'__and__')
    def __or__(self,o):return self._op(o,'__or__')
    def __add__(self,o):return self._op(o,'__add__')
    def __sub__(self,o):return self._op(o,'__sub__')
    def __mul__(self,o):return self._op(o,'__mul__')
    def __truediv__(self,o):return self._op(o,'__truediv__')

    def rename(self,name):
        return Series(self.values.rename(name),self.lineage,self.row_operations+[{'operation':'rename_label','new_label':name}])

    def to_pandas(self):return self.values.copy()


class Frame:
    def __init__(self, values, columns, row_operations=()):
        """Wrap values with columns={name: lineage_record}; not a column-name list.

        This limited provenance wrapper is not a pandas DataFrame. Use
        to_pandas() for other methods. Ordinary pandas exports are allowed;
        do not fabricate lineage merely to construct a Frame.
        """
        self.values,self.lineage,self.row_operations=values,columns,list(row_operations)

    @property
    def shape(self):return self.values.shape

    @property
    def columns(self):return self.values.columns

    def __getitem__(self,key):
        if isinstance(key,Series):
            if not key.values.index.equals(self.values.index):raise ValueError('filter index does not match dataframe')
            frame=self.values.loc[key.values]
            return Frame(frame,self.lineage,self.row_operations+[{'operation':'filter_rows','predicate':key.lineage['expression'],'rows_before':len(self.values),'rows_after':len(frame)}])
        value=self.values[key]
        if isinstance(value,pd.Series):return Series(value,self.lineage[key],self.row_operations)
        return Frame(value,{c:self.lineage[c] for c in value.columns},self.row_operations+[{'operation':'select_columns','columns':list(value.columns)}])

    def __setitem__(self,key,value):
        self.values[key]=value.values if isinstance(value,Series) else value
        if isinstance(value,Series):self.lineage[key]=value.lineage
        else:self.lineage[key]={'sources':[],'expression':{'operation':'untracked_assignment'},'meaning_status':'untracked_requires_independent_review'}

    def rename(self,columns):
        frame=self.values.rename(columns=columns)
        # Origin identity/definition survives every rename, even a misleading one.
        return Frame(frame,{columns.get(k,k):v for k,v in self.lineage.items()},self.row_operations+[{'operation':'rename_labels','mapping':columns}])

    def set_index(self,keys):
        frame=self.values.set_index(keys)
        return Frame(frame,{c:self.lineage[c] for c in frame.columns},self.row_operations+[{'operation':'set_index','keys':list(keys),'index_is_unique':bool(frame.index.is_unique)}])

    def sort_values(self,keys):return Frame(self.values.sort_values(keys),self.lineage,self.row_operations+[{'operation':'sort','keys':keys}])

    def groupby(self,keys):return Group(self,keys)

    def merge(self,other,on,how='inner',suffixes=('_x','_y')):
        if not isinstance(other,Frame):raise TypeError('merge requires tracked Frame; otherwise use to_pandas() and review untracked output')
        keys=[on] if isinstance(on,str) else list(on)
        common=(set(self.columns)&set(other.columns))-set(keys)
        lineage={}
        for name in self.columns:lineage[name+suffixes[0] if name in common else name]=self.lineage[name]
        for name in other.columns:
            if name not in keys:lineage[name+suffixes[1] if name in common else name]=other.lineage[name]
            else:lineage[name]=derived([self.lineage[name],other.lineage[name]],'join_key')
        result=self.values.merge(other.values,on=keys,how=how,suffixes=suffixes)
        operation={'operation':'join','on':keys,'how':how,'left_rows':len(self.values),'right_rows':len(other.values),'output_rows':len(result),
                   'review_obligation':'Check join multiplicity and whether downstream quantities are duplicated.'}
        return Frame(result,lineage,self.row_operations+other.row_operations+[operation])

    def to_pandas(self):
        """Return an ordinary pandas copy; further operations are not auto-tracked."""
        return self.values.copy()

    def to_csv(self,path,index=False,interpretations=None):
        """Write CSV and draft lineage; interpretations is a column->meaning map.

        The declarations are not verified semantics. This keyword belongs to
        Frame.to_csv, not pandas.DataFrame.to_csv.
        """
        self.values.to_csv(path,index=index)
        columns=dict(self.lineage)
        if index:
            for name in self.values.index.names:
                if name:columns.setdefault(name,{'sources':[],'expression':{'operation':'index_export'},'meaning_status':'index_definition_requires_review'})
        manifest={'version':'generic-provenance-v1','artifact_sha256':digest(path),'columns':columns,'row_operations':self.row_operations,
                  'producer_column_interpretations':interpretations or {},
                  'actual_rows':len(self.values),'verification_status':'draft_not_semantically_verified',
                  'limits':'Runtime lineage for supported operations; input definitions do not certify derived interpretation. Untracked code/output requires independent review.'}
        Path(str(path)+'.lineage.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2,default=str)+'\n')


class Group:
    def __init__(self,frame,keys):self.frame,self.keys=frame,([keys] if isinstance(keys,str) else list(keys))

    def agg(self,**named):
        """Use output_name=(input_column, string_operation); keys stay as columns."""
        result=self.frame.values.groupby(self.keys).agg(**named).reset_index()
        columns={k:self.frame.lineage[k] for k in self.keys}
        for output,(source,operation) in named.items():
            if not isinstance(operation,str):raise TypeError('tracked aggregation uses named string operation; custom callable needs independent review')
            columns[output]=derived([self.frame.lineage[source]],'aggregate',function=operation,group_keys=self.keys)
        return Frame(result,columns,self.frame.row_operations+[{'operation':'groupby_aggregate','keys':self.keys,'rows_before':len(self.frame.values),'rows_after':len(result),
                     'review_obligation':'Reconcile output grain and units with aggregation and the original quantity definition.'}])


def concat(items,axis=1):
    if axis!=1 or not all(isinstance(x,(Frame,Series)) for x in items):raise TypeError('tracked concat supports columns; arbitrary concat can use pandas and needs review')
    result=pd.concat([x.values for x in items],axis=1)
    lineages={};operations=[]
    for item in items:
        pairs=item.lineage.items() if isinstance(item,Frame) else [(item.values.name,item.lineage)]
        for name,lineage in pairs:
            if name in lineages:raise ValueError('ambiguous duplicate column label')
            lineages[name]=lineage
        operations.extend(item.row_operations)
    return Frame(result,lineages,operations+[{'operation':'concat_columns','axis':axis,'review_obligation':'Check index alignment and missing values.'}])


def _access(path,table,columns):
    trace=os.environ.get('SOURCE_TRACE_FILE')
    if trace:
        with open(trace,'a') as out:out.write(json.dumps({'path':str(Path(path).resolve()),'sha256':digest(path),'table':table,'columns':list(columns)},ensure_ascii=False)+'\n')


def read_table(name):
    """Read an exact registered SQLite table name and return a limited Frame.

    Not a CSV/path reader; no base_dir argument. Use pandas.read_csv for CSV
    files, whose joined columns can differ from the underlying SQL tables.
    Use frame.to_pandas() for arbitrary pandas work and report untracked
    transformations; inspect received definitions before interpreting fields.
    """
    public=Path(os.environ['PUBLIC_DIR'])
    contract=json.loads((public/'data_dictionary.json').read_text())
    if name not in contract['tables']:raise ValueError('unknown registered table')
    # The contract retains original source identity after a directory copy.
    # Runtime public binding selects the received immutable local database.
    database=public/Path(contract['database_file']).name
    with sqlite3.connect(f'file:{database}?mode=ro',uri=True) as db:
        value=pd.read_sql_query('SELECT * FROM "'+name.replace('"','""')+'"',db)
    definitions=contract['tables'][name]['columns']
    _access(database,name,definitions)
    _access(public/'data_dictionary.json','source_contract',definitions)
    return Frame(value,{c:traced_column(source_entry(database,name,c,definitions[c])) for c in value.columns},
                 [{'operation':'read_registered_source','source_path':str(database),'table':name,'input_row_grain':contract['tables'][name]['row_grain']}])
