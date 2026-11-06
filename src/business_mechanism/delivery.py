"""Readable report from actual versioned records, never generated scientific prose."""
from pathlib import Path
from experiments.insight_research.common import write_json
import json


def pending_text(packet):
    """Render attributed candidate work and criticism, never certify it."""
    records=packet.get('records',{})
    formal=packet.get('formal_report')
    title='# 商业机制研究过程（正式报告另存 '+formal['ref']+'）' if formal else '# 商业机制研究阶段报告（尚未形成正式报告）'
    parts=[title,'',packet.get('question',''),'',
        '执行状态：'+packet.get('execution_status','pending'),'',
        '本文件把已保存原件整理为可读进展。以下判断是研究者的候选意见，质疑也不自动成立；它们尚未作为核验通过的成果发布。','',
        '## 已提出的假说','']
    for h in records.get('hypothesis',[]):
        parts += ['### '+h['ref'], '',h['statement'],'','适用范围：'+h['scope'],'','原预测：'+h['prediction'],'']
    if not records.get('hypothesis'):parts+=['尚未保存正式假说。','']
    latest={}
    for a in records.get('assessment',[]):latest[a['hypothesis_ref']]=a
    parts+=['## 最近记录的候选判断','']
    for a in latest.values():
        parts+=['### '+a['ref']+'（对应 '+a['hypothesis_ref']+'）','',
            '作者当时提交的状态：'+{'supported':'支持','refuted':'反驳','unresolved':'未决'}.get(a['status'],a['status']),
            '',a['rationale'],'','证据引用：'+', '.join(a.get('result_refs',[])), '',
            '这不是本文件对判断正确性或当前有效性的认证，须结合下方质疑与完整版本链阅读。','']
    if not latest:parts+=['尚未保存候选判断。','']
    replies={(b['review_ref'],b['issue_id']):b for b in records.get('review_response',[])}
    parts+=['## 独立质疑与研究者处置','']
    issues=0
    for q in records.get('review',[]):
        for i in q.get('issues',[]):
            issues+=1;b=replies.get((q['ref'],i['issue_id']))
            parts+=['### '+q['ref']+' / '+i['issue_id'],'',i['description'],'',
                '依据类型：'+{'observed':'原件观察','recomputed':'工具计算证据（新计算或有来源记录的旧计算复用）','conjecture':'待检验推测'}.get(i['basis'],i['basis'])+
                '；质疑者标记：'+('重要未决问题' if i['blocking'] else '补充意见'),'']
            if b:
                parts+=['研究者处置：'+{'accept':'接受','revise':'修订','rebut':'有依据反驳','defer':'明确暂缓'}.get(b['disposition'],b['disposition']),
                        '',b['rationale'],'','修订/替代对象：'+', '.join(b.get('replacement_refs',[])),'']
            else:parts+=['尚未保存研究者对此意见的正式回应。','']
    if not issues:parts+=['尚无已保存的问题条目；这不等于已经通过独立核验。','']
    states=records.get('state',[])
    parts+=['## 研究进展与下一步','']
    if states:
        state=states[-1]
        parts+=[state.get('understanding',''),'', '下一步：'+state.get('next_action','尚未登记'),'',state.get('next_reason',''),'']
    else:parts+=['尚未保存阶段状态；以上列出真实假说、判断、审查和回应原件。','']
    parts+=['当前交接原因：'+packet.get('reason','尚在研究'),'',
        '完整原件、被替代/撤回状态和证据文件见同目录latest.json及研究工作区；前阶段正式报告另存F*.md。程序未改写科学记录。','']
    return '\n'.join(parts)


def export_saved_progress(path):
    root=Path(path).expanduser().resolve();folder=root/'deliveries'
    packet=json.loads((folder/'latest.json').read_text())
    target=folder/'阶段进展报告.md';target.write_text(pending_text(packet))
    return str(target)


def export_report(backend):
    ws = backend.ws; report = ws.report()
    directory = backend.root/'deliveries'; directory.mkdir(exist_ok=True)
    if hasattr(ws, 'study_budget'):
        from .convergence import agenda
        write_json(directory/'research_agenda.json', agenda(ws))
    if not report:
        current = directory/'当前研究报告.md'
        source=directory/'latest.json'
        packet=json.loads(source.read_text()) if source.exists() else {'question':ws.question,'execution_status':'ready','records':{}}
        text=pending_text(packet)
        current.write_text(text)
        (directory/'阶段进展报告.md').write_text(text)
        return None
    parts = ['# 商业机制研究报告', '', ws.question, '',
             '报告引用：'+report['ref'], '', '阶段状态：'+{'inconclusive':'未决','supported':'有范围的数据支持','refuted':'当前预测被反驳'}.get(report.get('stage_status'),report.get('stage_status','未决')), '',
             '以下内容直接取自研究者提交和独立核验记录。程序保证版本与来源关系，不认证科学正确性。', '', '## 本阶段判断', '']
    for ref in report.get('assessment_refs', []):
        a = ws.record(ref); h = ws.record(a['hypothesis_ref'])
        status={'supported':'当前证据支持','refuted':'当前证据反驳','unresolved':'尚未判定'}.get(a['status'],a['status'])
        parts += ['### '+h['statement'], '', '假说：'+h['ref']+'；判断：'+ref+'；状态：'+status, '',
                  '适用范围：'+h['scope'], '', '原预测：'+h['prediction'], '', a['rationale'], '',
                  '结果引用：'+', '.join(a['result_refs']), '']
    if not report.get('assessment_refs'):
        parts += ['本阶段没有作为已支持成果发布的判断；以下保留其他假说的处置、证据边界与下一步。', '']
    for title, field in [('其他假说及处置', 'other_hypotheses'), ('适用范围与限制', 'limitations'),
                         ('尚未解决的问题', 'open_questions'), ('需要的数据或实验', 'measurement_requests')]:
        parts += ['## '+title, '']
        value = report.get(field, [])
        items = [f'{k}：{v}' for k,v in value.items()] if isinstance(value, dict) else value
        parts += ['- '+str(v) for v in items] or ['无新增条目。']
        parts += ['']
    parts += ['## 核验与追溯', '', '核验引用：'+str(report.get('review_ref', '')), '',
              '草稿版本：'+str(report.get('reviewed_draft_ref', '')), '',
              '回应引用：'+', '.join(report.get('review_response_refs', [])), '',
              '原始数据、假说、计算、反证与全部审查意见保存在同一工作区；latest.json提供原件索引。', '']
    text = '\n'.join(parts)
    (directory/'当前研究报告.md').write_text(text)
    (directory/(report['ref']+'.md')).write_text(text)
    write_json(directory/(report['ref']+'.json'), report)
    return str(directory/(report['ref']+'.md'))
