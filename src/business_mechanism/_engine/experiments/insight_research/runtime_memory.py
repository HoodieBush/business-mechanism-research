"""Memory-aware single researcher; exact request reconstruction without copies."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from .common import Pending, digest, encoded, write_json
from .runtime import Journal, Runtime, PROMPT
from token_budget import reservation_bound

MEMORY_PROMPT = '''
研究记忆由假说卡片和宏观条目构成。当前上下文自动提供焦点卡片与相关条目；条目含来源、条件和状态，不能把记忆当真值。read_memory(ref="card:"+假说引用)可展开卡片，search_memory(hypothesis_ref=原假说引用,kind="process")可定位完整过程，event记录关联自己的原模型响应。
重要检验或探索后，用update_research_state更新当前认识、focus_hypothesis_refs和hypothesis_notes；有可复用的新认识时在knowledge_updates增量写入内容、条件、来源、反证及用途。没有新认识就不增条目。修正旧条目用supersedes_ref和revision_reason，保留旧版。provided_rule是给定规则，不能汇报成新发现；执行失败不能当科学反证。
窗口切换仍是同一研究，session_progress、已有state和近期过程入口说明进度；结合state.next_action及原证据继续决定研究动作。state是最新认识，不必复写已保存的背景和规则。unincorporated_results为空即没有待吸收正式结果，不需要搜索空的plan/result再确认。状态保存回执只含引用，完整状态可用read_memory回读。
还没有假说时，资料读取和探索计算也可能改变认识。若窗口提示uncheckpointed_work有新增活动，用update_research_state保存对当前问题有用的认识、来源、尚不确定什么及下一步理由，允许明确尚无insight；不要求新增假说或宏观条目。事件入口用于查原件，证据仍引用实际资料/产物。没有新增研究活动就不因容量提示重复保存。
提出新假说或检验时，可在used_memory_refs记录实际采用的K引用或card:引用，说明它怎样影响问题、预测或方法。仅引用不代表正确使用；有条件差异和冲突时回读原件。自主选择研究动作，允许未决。'''


def reconstruct_request(private, attempt):
    """Recover the original logical JSON payload, including message field order."""
    private = Path(private)
    archive = json.loads((private / 'requests' / (str(attempt) + '.json')).read_text())
    if archive.get('format') != 'message_objects_v1': return archive
    payload = {}
    for key, value in archive['fields']:
        if key == 'messages':
            messages = []
            for ref in value:
                path = private / 'message_objects' / (ref + '.json')
                raw = path.read_bytes()
                if hashlib.sha256(raw).hexdigest() != ref: raise Pending('archived message object changed')
                messages.append(json.loads(raw))
            payload[key] = messages
        else: payload[key] = value
    if digest(payload) != archive['payload_sha256']: raise Pending('reconstructed request identity changed')
    return payload


class MemoryJournal(Journal):
    def persist_request(self, attempt, payload):
        objects = self.ws.private / 'message_objects'; objects.mkdir(exist_ok=True)
        refs = []
        for message in payload['messages']:
            raw = json.dumps(message, ensure_ascii=False, allow_nan=False).encode()
            ref = hashlib.sha256(raw).hexdigest(); path = objects / (ref + '.json')
            if path.exists() and path.read_bytes() != raw: raise Pending('message archive hash collision or corruption')
            if not path.exists(): path.write_bytes(raw)
            refs.append(ref)
        fields = [[k, refs if k == 'messages' else v] for k, v in payload.items()]
        write_json(self.ws.private / 'requests' / (str(attempt) + '.json'),
                   {'format': 'message_objects_v1', 'fields': fields, 'payload_sha256': digest(payload)})
        context = json.loads(payload['messages'][1]['content'])
        selection = context.get('memory_selection', {})
        with self.ws.db:
            self.ws.db.execute('INSERT OR IGNORE INTO retrievals VALUES (?,?)', (attempt, encoded({
                'attempt': attempt, 'status': 'request_prepared', 'focus': context.get('focus_hypothesis_refs', []),
                'context_sha256': digest(context), **selection})))

    def persist_response(self, attempt, record):
        record = deepcopy(record)
        record.pop('request', None)
        record['request_archive'] = 'requests/' + str(attempt) + '.json'
        super().persist_response(attempt, record)


class MemoryRuntime(Runtime):
    def __init__(self, workspace, model_config, *, journal=None):
        super().__init__(workspace, model_config, journal=journal or MemoryJournal(workspace, model_config))

    def initial(self):
        context = self.ws.context()
        context['session_progress'] = {
            'responses_completed': self.cp['responses'],
            'continuing_same_research': self.cp['responses'] > 0,
        }
        context['uncheckpointed_work'] = self.ws.checkpoint_work()
        return [{'role': 'system', 'content': PROMPT + MEMORY_PROMPT},
                {'role': 'user', 'content': encoded(context)}]

    def context_notice(self):
        if self.ws.unincorporated():
            return '上下文中的unincorporated_results列出实际待吸收结果；依据原预测与实际证据更新认识，原件可按引用回读。'
        if not self.ws.state() and self.ws.db.execute('SELECT 1 FROM hypothesis_status LIMIT 1').fetchone():
            return '已有假说但尚无研究状态；下一次窗口重建需要带来源的当前认识、焦点及下一步理由。'
        if self.ws.checkpoint_work()['pending']:
            return '窗口接近切换，uncheckpointed_work有尚未保存认识的资料或分析。请保存有来源的当前认识、未确定项和下一步理由；不必复写背景或检索不存在的结果，也不要求形成结论。'
        # Capacity alone is not a research event. Do not repeatedly ask for
        # state maintenance or an audit of nonexistent results (SCI-020).
        return None

    def compact(self):
        if self.ws.checkpoint_work()['pending']:
            if self.cp['pending']: raise Pending('complete already-paid tool calls before changing context')
            # Retain the latest actual checkpoint turn and EVERYTHING after it.
            # Only earlier, already accounted-for work can leave this window.
            state = self.ws.state()
            messages = self.cp['messages']
            if state:
                for i in range(len(messages)-1, 1, -1):
                    if messages[i]['role'] != 'tool': continue
                    try: receipt = json.loads(messages[i]['content'])
                    except (ValueError, TypeError): continue
                    if not isinstance(receipt, dict) or receipt.get('ref') != state['ref']: continue
                    start = next((j for j in range(i-1, 1, -1) if messages[j]['role'] == 'assistant'), None)
                    if start is None: break
                    rebuilt = self.initial() + messages[start:]
                    if len(encoded(self.payload(rebuilt)).encode()) <= self.ws.settings['limits']['max_request_bytes']:
                        self.cp['messages'] = rebuilt; self.cp['context_windows'] += 1; self.save()
                        return
                    break
            raise Pending('new research work has no saved interpretation; original context retained before compaction')
        return super().compact()

    def prepare_payload(self, payload):
        if not isinstance(self.journal, MemoryJournal): return payload
        remaining = min(self.journal.snapshot()['remaining_admission_tokens'],
            self.ws.settings['limits']['token_allowance'] - self.journal.state['accounted_tokens'])
        if reservation_bound(payload) <= remaining: return payload
        # The original total authorization is unchanged. Reduce optional old
        # turns before stopping for admission, without slicing scientific fields.
        self.compact()
        cap = min(self.ws.settings['limits']['max_request_bytes'],
                  (remaining-payload['max_tokens']-16384)//2)
        if self.ws.checkpoint_work()['pending'] and len(encoded(self.payload()).encode()) > cap:
            raise Pending('complete unsaved research suffix cannot fit remaining admission; new work retained')
        while len(encoded(self.payload()).encode()) > cap:
            messages = self.cp['messages']
            start = next((i for i, m in enumerate(messages[2:], 2) if m['role'] == 'assistant'), None)
            if start is None: raise Pending('fixed memory view cannot fit remaining conservative admission; no request sent')
            end = next((i for i, m in enumerate(messages[start+1:], start+1) if m['role'] == 'assistant'), len(messages))
            self.cp['messages'] = messages[:2] + messages[end:]
        self.save()
        return self.payload()

    def drain(self, deadline=None):
        pending = self.cp.get('pending')
        self.ws.response_ref = 'process:' + str(pending['response']) if pending else None
        return super().drain(deadline)

    def accept(self, raw, delivery=None):
        super().accept(raw, delivery)
        ref = 'process:' + str(self.cp['responses'])
        # The large raw response/thoughts remain an owner-only original.
        # Only visible model text is indexed; no default whole-thought search.
        try: content = raw['choices'][0]['message'].get('content', '') or ''
        except (KeyError, IndexError, TypeError, AttributeError): content = ''
        focus = (self.ws.state() or {}).get('focus_hypothesis_refs', [])
        self.ws.response_ref = ref
        with self.ws.db:
            self.ws.event('response:' + str(self.cp['responses']), 'model_response',
                          {'purpose': str(content)[:2000]}, {'process_ref': ref})
