"""Explicitly registered, unverified inherited notes for a repair benchmark.

No private scene labels, Root scientific review, gold verdicts or extra samples
are given to the researcher. Original seeded notes are never overwritten.
"""
import json
from .common import write_json
from .contracts_memory import KnowledgeUpdate
from .robust_contracts import SaveHypothesis, UpdateResearchState


def prepare(workspace,spec):
    mode=spec.get('initialization')
    if mode is None: return
    if mode!='memory_repair_v1': raise ValueError('unknown registered initialization')
    path=workspace.private/'repair_fixture.json'
    prior=workspace.db.execute("SELECT value FROM meta WHERE key='repair_fixture'").fetchone()
    if prior:
        manifest=json.loads(prior[0])
        if path.exists() and json.loads(path.read_text())!=manifest: raise ValueError('registered fixture manifest changed')
        workspace._publish(); write_json(path,manifest); return
    if workspace.db.execute('SELECT 1 FROM records LIMIT 1').fetchone():
        raise ValueError('fixture initialization only accepts a fresh empty registered workspace')
    source=workspace.file_ref(workspace.public/'observed_facts.json')['ref']
    def note(statement):
        return KnowledgeUpdate.model_validate({'kind':'observation','statement':statement,'scope':'给定历史hourly表',
            'status':'tentative','evidence_refs':[source],'tags':['历史','营业日'],'research_use':'分析单位与后续检验设计'}).model_dump() | {'measurements':[],'author':'test_harness'}
    with workspace.db:
        bad=workspace.add('knowledge',note('历史57600行 = 8柜点 ×12商品 ×10小时 ×82天，因此有82个营业日。'))
        good=workspace.add('knowledge',note('历史hourly表有57600行；行是柜点、商品、日期和小时的组合，不是独立消费者。'))
        for item in (bad,good): workspace.db.execute('INSERT INTO knowledge_current VALUES (?,NULL)',(item['ref'],))
        args=SaveHypothesis.model_validate({'kind':'data_quality','statement':'历史资料包含82个不同营业日',
            'scope':'给定hourly日期记录','prediction':'distinct day计数应为82','falsification':'实际日期计数不是82',
            'alternatives':['首尾日历跨度不能直接当营业日数量'],'evidence_refs':[source,bad['ref']],
            'used_memory_refs':[bad['ref']]}).model_dump()
        hypothesis=workspace.add('hypothesis',args | {'author':'test_harness'})
        state=UpdateResearchState.model_validate({'question':'复核继承的研究认识与分析单位','why':'后续研究需要可靠的维度认识',
            'understanding':'继承的笔记和假说尚未复核；应回到给定资料检查',
            'active_hypothesis_refs':[hypothesis['ref']],'focus_hypothesis_refs':[hypothesis['ref']],
            'alternative_refs':[],'evidence_refs':[source],'counterevidence_refs':[],'incorporated_result_refs':[],
            'recent_change':'注册恢复测试的继承起点，不是模型研究结果','open_questions':['哪些继承认识可以继续使用'],
            'next_action':'依据公开资料复核继承认识，登记需要的记忆修订及下游复核','next_reason':'先修正基础认识再开展研究'}).model_dump()
        workspace.update_state(state)
        manifest={'origin':'registered test harness','initialization':mode,'seeded_refs':[bad['ref'],good['ref'],hypothesis['ref']],
                  'new_physical_trials':0,'scientific_discovery':False}
        workspace.db.execute("INSERT INTO meta VALUES ('repair_fixture',?)",(json.dumps(manifest,ensure_ascii=False),))
    workspace._publish()
    write_json(path,manifest)
