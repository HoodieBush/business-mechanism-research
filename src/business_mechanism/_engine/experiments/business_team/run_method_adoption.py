"""Supplied-literature diagnostic using the existing native role/runtime tools.

This isolates method adoption, not autonomous search or multi-agent effectiveness.
Fixtures, literature and evaluation rubric are frozen before model calls. All
scientific decisions are the Actor's; the adapter has no expected-answer gate.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from langgraph.checkpoint.sqlite import SqliteSaver

from execution import PythonWorkspace,last_number
from workspace import ResearchWorkspace, sha, write_json
from langgraph_migration.provider import APIJournal, GatewayChatModel
from langgraph_migration.runtime import CONTRACTS, FrameworkRoles
from langgraph_migration.sources import enable_research

ROOT = Path(__file__).resolve().parents[2]
MENU = ('read_context', 'read_artifact', 'query_data', 'run_python', 'submit_result')
PROMPT = ('你是企业算法研究团队的验证研究员。本次为方法采用组件诊断，不是新机制发现。'
          '独立审查公开任务的原主张和已有证据，使用实际工具检查数据和可用方法。'
          '说明分析对象、目标量、方法条件和结论边界。按任务需要复算，保留失败和未决；'
          '可以按实际工具权限使用可获得的原文资料，也可以使用已有方法知识；目录为空不代表没有相关研究。'
          '不得编造观测、引用或执行，不把另一指标的结果替代原主张。'
          '最终用submit_result交付实际发现、证据文件和下一步。')
QUESTION = ('请审查 task.json 的原主张，独立检查数据、程序身份及研究设计，'
            '通过实际分析说明证据支持什么、不能支持什么。若采用资料中的方法，'
            '说明出处、实际阅读部分及本地适用条件；可以不用不适合的方法。'
            '用真实代码或数据证据支撑判断，最后 submit_result。')


class UnlimitedJournal(APIJournal):
    def __init__(self, root, config):
        super().__init__(root, config, budget=float('inf'))

    def public_view(self):
        result = super().public_view()
        result.update(shared_admission_limit=None, remaining_admission_estimate=None,
                      admission_policy='No model-token/call quota; retain measured and unknown usage accounting.')
        return result


class MethodWorkspace(ResearchWorkspace):
    """Thin adapter: reuse reference, SQL, sandbox, delivery and receipt services."""
    framework_contracts = {k: CONTRACTS[k] for k in MENU}
    framework_role_tools = {'verifier': MENU}
    framework_terminal_tools = ('submit_result',)
    framework_descriptions = {
        'read_context': '读取当前任务、资料目录、字段定义和合法工作目录。无隐藏答案。',
        'read_artifact': '读取收到的文件或真实artifact ID。数据文件只给字段和小样本，完整统计使用Python/SQL；文献等文本每次18000字符，可用offset续读。目录路径不是文件。',
        'query_data': '对business.sqlite执行只读SELECT。output_semantics说明每行、单位、聚合含义；不自动认证科学推断。',
        'run_python': '保存并运行自写Python，pandas/NumPy/SciPy/statsmodels可用。PUBLIC_DIR和ARTIFACT_DIR只读；仅写本次WORK_DIR。网络禁止，45秒为单脚本保护，失败可修正。',
        'submit_result': '交付实际分析：summary、evidence_files、findings、next_step。只引用收到的文件或artifact ID，不把口头计划当运行结果；后端不认证科学真值。',
    }

    def __init__(self, root):
        self.root = Path(root).resolve()
        self.public, self.shared = self.root/'public', self.root/'artifacts'
        self.shared.mkdir(exist_ok=True)
        self.state = json.loads((self.shared/'research_history.json').read_text()) if (self.shared/'research_history.json').exists() else {
            k: [] for k in ('tasks', 'results', 'hypotheses', 'experiments', 'algorithms', 'events', 'artifact_reviews')}
        self.path_aliases = {}
        self.require_artifact_review = False  # All supplied observations are original diagnostic inputs.
        self.query_count = last_number(self.shared,'query_','.csv')
        self.operation = None
        self.delegate = None
        self.workers = {'verifier': PythonWorkspace(self.shared/'verifier', self.public, self.shared, per_execution=True)}
        self.role_prompts = {'verifier': PROMPT}
        self.tool_menus = {'verifier': list(MENU)}
        self.contract = json.loads((self.public/'data_dictionary.json').read_text())
        self.registered_sources = {str(p) for p in self.public.rglob('*') if p.is_file()}
        self.registered_data_sources = {str(self.public/'business.sqlite')}
        self.data_source = {'dictionary_version': self.contract['version'],
                            'dictionary_sha256': sha(self.public/'data_dictionary.json'),
                            'database_sha256': sha(self.public/'business.sqlite')}
        self.persist()

    def initial_context(self):
        declared = Path(self.contract['database_file'])
        received = declared if declared.is_absolute() else self.public / declared
        database = self.readable(str(received))
        # Reuse the same alias/permission resolver as received artifacts. An
        # archival absolute path is not a current Python path. The bound path
        # must also identify the database used by this adapter's SQL service.
        if database != (self.public / 'business.sqlite').resolve():
            raise ValueError('dictionary database_file does not identify the registered SQL database')
        return {'task_file': str(self.public/'task.json'),
                'data_dictionary_file': str(self.public/'data_dictionary.json'),
                'business_database': str(database),
                'source_binding': {**self.data_source,
                    'dictionary_version_field': 'version',
                    'metadata_version_field': 'dictionary_version',
                    'meaning': 'Metadata dictionary_version records the source dictionary version value; the dictionary itself names that field version. Different field names do not imply different version values. business_database is the current readable Python/SQL path; dictionary.database_file may retain an archival location. Original dictionary bytes and source hashes remain unchanged. Hash binding identifies source bytes, not scientific truth.'},
                'relative_input_path_base': 'Resolve dictionary/task relative input filenames against PUBLIC_DIR. Current Python working directory is WORK_DIR, for generated outputs.',
                'data_files': [str(p) for p in sorted(self.public.glob('*.csv'))],
                'program_identity_file': str(self.public/'program_identity.json') if (self.public/'program_identity.json').exists() else None,
                'literature_index': str(self.public/'literature_index.json'),
                'public_directory': str(self.public), 'shared_artifacts': str(self.shared),
                'python_access': 'Ordinary pandas/sqlite3, PUBLIC_DIR, ARTIFACT_DIR and WORK_DIR. Open supplied SQLite with sqlite3.connect("file:" + database_path + "?mode=ro", uri=True); query_data also provides readonly SQL. Read CSV with its full received path. No network or access to other conditions.'}

    def task_binding(self, task):
        return {'public_sources': {str(p.relative_to(self.public)): sha(p) for p in sorted(self.public.rglob('*')) if p.is_file()},
                'prompt': PROMPT, 'question': QUESTION}

    def _tool(self, role, name, args):
        if name not in self.tool_menus.get(role, ()):
            raise ValueError('tool outside role permissions')
        if name == 'read_artifact':
            from langgraph_migration.collaboration import CollaborativeWorkspace
            path = self.readable(args['path'])
            view = CollaborativeWorkspace.text_view(self, path, args.get('offset', 0))
            return {**view, 'artifact_id': self.reference(path), 'sha256': sha(path)}
        return super()._tool(role, name, args)

    def capture_task(self, role, task, binding):
        return {'workspace_root': str(self.root), 'task_id': task['id'], 'role': role, 'stage': 'method_adoption_diagnostic'}


def diagnostic_inputs(case, source):
    """Return public facts separately from private interpretation labels."""
    if case == 'M01':
        records = []
        for eid, program, condition in [('D0001', 'baseline', 'standard'), ('D0002', 'numeric_refit', 'standard'),
                                        ('D0003', 'baseline', 'replication_1'), ('D0004', 'numeric_refit', 'replication_1')]:
            frame = pd.read_csv(source/f'B101/artifacts/development_evaluations/{eid}/site_days.csv')
            frame['program'] = program
            frame['condition'] = condition
            records.append(frame)
        frame = pd.concat(records, ignore_index=True)
        task = {'question': 'numeric_refit是否已证明在两注册条件下，净利、鲜食报损、观测缺货小时三项均不劣于baseline？',
                'design': '这是同一售货柜结构的程序回放，程序在同一条件使用共同外生随机流。两条件不是两个独立业务世界。没有新随机化现场试验。',
                'metrics': {'net_profit': 'currency/site/day; higher is better', 'fresh_waste': 'items/site/day; lower is better',
                            'observed_stockout_hours': 'SKU-hours/site/day; lower is better'},
                'decision_tolerance': '业务方未指定可容忍损失的非劣界限。',
                'program_identity_file': 'program_identity.json', 'target_scope': '注册窗口内的经营比较；进一步推断须说明条件。'}
        identity = {}
        for eid, program, condition in [('D0001','baseline','standard'),('D0002','numeric_refit','standard'),
                                        ('D0003','baseline','replication_1'),('D0004','numeric_refit','replication_1')]:
            directory=source/f'B101/artifacts/development_evaluations/{eid}'
            receipt=json.loads((directory/'receipt.json').read_text())
            code=source/'B101/public'/Path(receipt['code_file']).name
            if sha(code)!=receipt['code_sha256']:raise ValueError('source program bytes do not match evaluation receipt')
            identity[eid]={k:receipt[k] for k in ('code_sha256','history_sha256','contract_sha256','condition_id')}
            identity[eid].update(evaluation_id=eid,program_label=program,observation_condition=condition,
                                 code_file='programs/'+code.name,source_code_file=receipt['code_file'],
                                 source_receipt_sha256=sha(directory/'receipt.json'),source_data_sha256=sha(directory/'site_days.csv'),
                                 relative_paths_base='Current PUBLIC_DIR; source_code_file records archival origin, while code_file is the readable local copy.',
                                 mapping_scope='program_label and observation_condition identify rows in observations.csv; common random streams apply within the same condition, not across conditions.')
        return frame, task, {'program_identity.json': identity}, 'real_receipt_reanalysis'
    if case in ('M02', 'M03'):
        independent = case == 'M03'
        effects = np.random.default_rng(7619).normal(.6, .4, 32) if independent else np.random.default_rng(7620).normal(0., 1., 8)
        records = []
        for unit, effect in enumerate(effects):
            for day in range(10):
                for program, value in [('baseline', 100.), ('candidate', 100.+float(effect))]:
                    records.append({'independent_unit': f'u{unit:02d}', 'day': day, 'program': program, 'net_profit': value})
        task = {'question': 'candidate是否有证据提高每个独立评价单位等权的期望净利？请报告效应与推断边界。',
                'design': '构造的方法诊断数据。independent_unit之间为独立抽样；同一单位内10条日记录共享该单位的收益差，不是重新独立抽样。两程序严格配对。',
                'population_model': '独立单位的收益差为同一正态总体的独立抽样，均值和方差未知；不将日记录当独立单位。',
                'metric': 'net_profit: currency/day; 每个独立单位等权。',
                'primary_comparison': '预先指定candidate-baseline净利一项，方向为正；alpha=.05。没有第二个经营指标或新处理。'}
        return pd.DataFrame(records), task, {}, 'independent_positive_control' if independent else 'dependent_repeated_measurements'
    if case == 'M04':
        frame, _, identity, _ = diagnostic_inputs('M01', source)
        task = {'question': '原预测：numeric_refit使鲜食hour 11–13的mean_signed_gap(pred-recorded_sales)比baseline向0缩小至少1.3件/行。现有材料是否足以检验？',
                'scope': 'standard与replication_1注册窗口；保持原预测对象和粒度。',
                'design': '仅提供这些柜点日经营回执；未提供逐小时预测或逐小时记录销量；工具不能新增采样。',
                'units': '净利为货币/柜点日，报损为件/柜点日，缺货为SKU小时/柜点日；原预测为件/商品小时行。',
                'program_identity_file': 'program_identity.json'}
        return frame, task, identity, 'missing_required_measurement'
    raise ValueError('unknown diagnostic case')


def create_inputs(root, case, arm, source, literature):
    root = Path(root)
    public = root/'public'
    public.mkdir(parents=True)
    frame, task, extra, private_kind = diagnostic_inputs(case, source)
    frame.to_csv(public/'observations.csv', index=False)
    with sqlite3.connect(public/'business.sqlite') as con:
        frame.to_sql('observations', con, index=False)
    write_json(public/'task.json', task)
    for name, value in extra.items():
        write_json(public/name, value)
    if 'program_identity.json' in extra:
        (public/'programs').mkdir()
        for record in extra['program_identity.json'].values():
            original=source/'B101/public'/Path(record['source_code_file']).name
            target=public/record['code_file']
            shutil.copyfile(original,target)
            if sha(target)!=record['code_sha256']:raise ValueError('exported program differs from source receipt')
    definitions = {c: {'meaning': {'site': '柜点标识', 'day': '窗口内业务日标识；重复行不自动独立',
                                 'date': '业务日期', 'program': '实际执行的程序身份', 'condition': '注册外生流条件',
                                 'independent_unit': '研究设计中独立抽样的评价单位', 'net_profit': '该程序该单位日净收益',
                                 'fresh_waste': '鲜食报损件数', 'observed_stockout_hours': '观测到的商品缺货小时数'}[c],
                       'unit': 'currency' if c == 'net_profit' else 'items' if c == 'fresh_waste' else 'SKU-hours' if c == 'observed_stockout_hours' else 'identifier'} for c in frame.columns}
    write_json(public/'data_dictionary.json', {'version': 'method-adoption-diagnostic-v1', 'database_file': 'business.sqlite',
               'tables': {'observations': {'columns': definitions, 'row_grain': 'program × condition/site/day or program × independent_unit/day; actual columns and task.json determine the design'}}})
    shutil.copyfile(ROOT/'experiments/business_team/source_access.py', public/'source_access.py')
    index = []
    if arm == 'provided_literature':
        paper = public/'literature'
        paper.mkdir()
        for name in ('mackinnon_nielsen_webb_2022.txt', 'mackinnon_nielsen_webb_2022.html', 'source.json'):
            shutil.copyfile(literature/name, paper/name)
        metadata = json.loads((literature/'source.json').read_text())
        index.append({'title': metadata['title'], 'url': metadata['url'], 'version': metadata['version'],
                      'text_file': 'literature/mackinnon_nielsen_webb_2022.txt', 'original_file': 'literature/mackinnon_nielsen_webb_2022.html',
                      'extraction_limit': metadata['extraction'], 'access': 'read_artifact accepts received full paths, PUBLIC_DIR plus the relative filename; offset for further text.'})
    elif arm not in ('local_only','autonomous_research'):
        raise ValueError('unknown information condition')
    write_json(public/'literature_index.json', index)
    return private_kind


def setup(specfile):
    spec = json.loads(Path(specfile).read_text())
    expected = {f'{case}_{arm}' for case in spec['case_ids'] for arm in spec['arms']}
    if len(spec['execution_order']) != len(expected) or set(spec['execution_order']) != expected:
        raise ValueError('execution order must cover every declared case/condition exactly once')
    if spec['round_reported_token_budget'] is not None:
        raise ValueError('this diagnostic follows the user no-token-quota policy')
    output = ROOT/'experiments/business_team/results'/spec['phase']
    if output.exists():
        raise ValueError('phase exists; resume exact frozen version, never overwrite')
    output.mkdir(parents=True)
    test = subprocess.run([sys.executable, '-m', 'unittest', '-v', 'test_sources.py', 'test_model_pacing.py', 'test_tool_outputs.py', 'test_program_selection.py', 'test_method_adoption.py', 'test_context_contracts.py', 'test_langgraph_migration.py'],
                          cwd=Path(__file__).parent, capture_output=True, text=True)
    (output/'preflight-tests.log').write_text(test.stdout+test.stderr)
    if test.returncode:
        raise RuntimeError('preflight failed; no model calls')
    source = ROOT/spec['source_run']
    literature = ROOT/spec['literature_directory']
    private = {}
    for case in spec['case_ids']:
        for arm in spec['arms']:
            name = f'{case}_{arm}'
            private[name] = create_inputs(output/name, case, arm, source, literature)
            ws = MethodWorkspace(output/name)
            if arm=='autonomous_research':enable_research(ws)
            FrameworkRoles(ws, None, None)  # Build accurate manual, without constructing/calling a model.
    write_json(output/'private_diagnostic_labels.json', {'labels': private, 'scope': 'Not Actor accessible or an automatic scientific answer checker.'})
    old = json.loads((source/'manifest.json').read_text())
    files = [ROOT/p for p in old['source_sha256']]+[Path(__file__).resolve(), Path(__file__).with_name('test_method_adoption.py'), Path(__file__).with_name('test_program_selection.py'), Path(specfile).resolve()]
    files += list((Path(__file__).parent/'langgraph_migration').glob('*.py'))
    files += [Path(__file__).with_name('test_model_pacing.py'),Path(__file__).with_name('test_tool_outputs.py'),Path(__file__).with_name('test_sources.py')]
    files += [Path(__file__).with_name('test_context_contracts.py')]
    hashes = {}
    for path in files:
        target = output/'snapshot'/path.relative_to(ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
        hashes[str(path.relative_to(ROOT))] = sha(path)
    inputs = {str(p.relative_to(output)): sha(p) for p in output.glob('M*/public/**/*') if p.is_file()}
    manifest = {'status': 'prepared', 'created_at': datetime.now(timezone.utc).isoformat(), 'specification': spec,
                'source_sha256': hashes, 'public_input_sha256': inputs,
                'private_input_sha256': {'private_diagnostic_labels.json': sha(output/'private_diagnostic_labels.json')}, 'cases': [],
                'scope': spec.get('scope','One existing role diagnostic; no autonomous search or multiagent-effect claim.'),
                'model_call_pacing': {'target_tokens_per_minute':20000,'scope':'all APIJournal roles/context/retries share one durable process lock and pacing ledger','policy':'reported usage; unknown usage reserved by estimate; no idle burst credit; no total quota'}}
    write_json(output/'manifest.json', manifest)
    return output


def run(specfile, resume=False):
    spec = json.loads(Path(specfile).read_text())
    output = ROOT/'experiments/business_team/results'/spec['phase'] if resume else setup(specfile)
    manifest = json.loads((output/'manifest.json').read_text())
    if any(sha(ROOT/p) != h for p, h in manifest['source_sha256'].items()):
        raise ValueError('frozen source changed')
    if any(sha(output/p) != h for p, h in manifest['public_input_sha256'].items()):
        raise ValueError('frozen public input changed')
    if any(sha(output/p) != h for p, h in manifest['private_input_sha256'].items()):
        raise ValueError('frozen diagnostic labels changed')
    config = json.loads((ROOT/'configs/base_model.json').read_text())
    config['request_timeout_seconds'] = 180
    journal = UnlimitedJournal(output, config)
    prior = {r['id']: r for r in manifest['cases']}
    connection = sqlite3.connect(output/'checkpoints.sqlite', check_same_thread=False)
    saver = SqliteSaver(connection)
    try:
        for name in spec['execution_order']:
            ws = MethodWorkspace(output/name)
            if name in {f'{case}_autonomous_research' for case in spec['case_ids']}:enable_research(ws)
            roles = FrameworkRoles(ws, saver, lambda role: GatewayChatModel(journal=journal, research_role=role))
            record = prior.get(name, {'id': name})
            print('START', name, flush=True)
            try:
                result = roles.run('verifier', {'id': 'M_review', 'question': QUESTION, 'inputs': [str(ws.public/'task.json')]})
                record.update(status='delivered', result=result)
            except KeyboardInterrupt:
                record.update(status='interrupted')
                raise
            except Exception as error:
                record.update(status='failed', error_type=type(error).__name__, error=str(error)[:1600])
            finally:
                prior[name] = record
                manifest.update(status='running', cases=list(prior.values()), usage=journal.usage())
                write_json(output/'manifest.json', manifest)
            print('END', name, record['status'], flush=True)
    except KeyboardInterrupt:
        manifest['status'] = 'interrupted'
        raise
    finally:
        connection.close()
        write_json(output/'manifest.json', manifest)
    manifest.update(status='completed_with_failures' if any(r['status'] != 'delivered' for r in prior.values()) else 'delivered_pending_scientific_review',
                    completed_at=datetime.now(timezone.utc).isoformat(), usage=journal.usage(),
                    frozen_sources_unchanged=all(sha(ROOT/p) == h for p, h in manifest['source_sha256'].items()))
    write_json(output/'manifest.json', manifest)
    print(json.dumps({'status': manifest['status'], 'usage': manifest['usage']}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--spec', required=True)
    parser.add_argument('--prepare-only', action='store_true')
    parser.add_argument('--resume', action='store_true')
    args = parser.parse_args()
    if args.prepare_only:
        print(setup(args.spec))
    else:
        run(args.spec, args.resume)
