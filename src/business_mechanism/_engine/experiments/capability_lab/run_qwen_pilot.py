"""Bounded exploratory API pilot; only lab.public/tool returns enter messages.

No agent filesystem/shell tool is exposed. Raw requests and responses are saved.
"""
from __future__ import annotations

import argparse
import datetime
import json
from pathlib import Path
import time

from lab import ResearchLab, World, private_score
from model_protocol import (ACTION_SCHEMA, append_feedback, decode_submission,
                            request_model, structured_request, submission_transport, usage_summary)


SYSTEM = """你是库存商业机制研究员。你只能通过给定工具研究，不可使用外部文件或猜测生成器。目标是形成可检验的概率关系，而不是给原因标签。先确认观测、执行与分母条件；提出竞争解释与区分性预测；在看到结果前登记每个实验预测；有效冲突应修订候选结构；证据不足可未决。关注相互作用和适用条件，但不预设其存在。先在 source 研究，再用 open_transfer 获取新商品和柜点，利用剩余预算验证是否可以迁移；最终 finish 冻结模型。
每次只输出 JSON：{"tool":"工具名","args":{...}}。工具名称、参数与算术 AST 格式以任务为准。finish 的 model 必须恰好包含 role_patterns 和 expression。role_patterns 对商品描述做子串匹配。表达式必须给出经核实的购买概率，不是未核实账面销量比率。不要输出代码围栏。避免在同一陈列下反复取样却遗漏能区分候选的新条件。记下不适配而非强迫初始独立加法模型拟合。"""


def parse_action(content):
    text = content.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0]
    action = json.loads(text)
    if not isinstance(action, dict) or set(action) != {"tool", "args"}:
        raise ValueError("expected exactly tool and args")
    return action


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--family", default="complement")
    ap.add_argument("--fault", default="none")
    ap.add_argument("--calls", type=int, default=22)
    ap.add_argument("--workflow", choices=["generic", "frontier"], default="generic")
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()
    project = Path(__file__).resolve().parents[2]
    config = json.loads((project / "configs/base_model.json").read_text())
    out = args.out or Path(__file__).parent / "results" / f"pilot_v2_{args.workflow}_{args.family}_{args.fault}_s{args.seed}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    lab = ResearchLab(World(args.seed, args.family, args.fault))
    messages = [{"role": "system", "content": SYSTEM},
                {"role": "user", "content": json.dumps(lab.public(), ensure_ascii=False)}]
    records = []
    protocol_failures = 0
    result = {"phase": "exploratory_pilot_not_formal_test", "workflow": args.workflow, "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
              "model_config": config, "generation": {"temperature": 0, "max_tokens": 4096, "enable_thinking": False, **config.get("generation_options", {})},
              "private_evaluator_configuration": {"seed": args.seed, "family": args.family, "fault": args.fault},
              "initial_legal_input": messages.copy(), "calls": records, "status": "running"}
    for step in range(args.calls):
        payload = {"model": config["model"], "messages": messages, "temperature": 0,
                   "max_tokens": 4096, "chat_template_kwargs": {"enable_thinking": False},
                   "response_format": {"type": "json_object"}}
        payload.update(config.get("generation_options", {}))
        payload = structured_request(payload, config, "submit_action", ACTION_SCHEMA)
        start = time.monotonic()
        record = {"step": step, "request": payload}
        try:
            api_record=request_model(config,payload)
            record.update(api_record)
            if "response" not in record:
                raise OSError(record["error"])
            raw=record["response"]
            record["raw_response"] = raw
            content = raw["choices"][0]["message"].get("content") or ""
            try:
                action = parse_action(json.dumps(decode_submission(raw,config,"submit_action")))
                record["submission_transport"] = submission_transport(raw)
                record["action"] = action
                protocol_failures = 0
                if args.workflow == "frontier" and action["tool"] == "finish":
                    # Candidate-independent novelty audit uses only public input.
                    # It cannot name the hidden effect or read World probabilities.
                    source_arms = [r["result"]["assortment"] for r in lab.receipts if r["result"]["stage"] == "source"]
                    if not any(len(arm) >= 4 for arm in source_arms) and lab.used["sessions"] + 400 <= lab.limits["sessions"] and lab.used["arms"] < lab.limits["arms"] and lab.used["cost"] + 11 <= lab.limits["cost"]:
                        raise ValueError("反例审查未完成：当前模型的适用范围包含多个辅助商品的陈列组合，但这些条件没有测过。请选择一个可保持候选功能覆盖、同时改变未检验陈列维度的 source 实验，冻结候选预测，再决定是否扩张结构。审查不保证此维度实际有效。")
                feedback = lab.call(action["tool"], action["args"])
            except (ValueError, KeyError, TypeError) as error:
                if "action" not in record:
                    record["protocol_error"] = str(error)
                    protocol_failures += 1
                feedback = {"error": str(error), "used": lab.used.copy(),
                            "instruction": "此调用未生成有效研究证据。修正格式或动作；若预算不足，请 finish。"}
            record["feedback"] = feedback
            append_feedback(messages,raw,feedback)
        except Exception as error:
            category=record.get("error_type")
            if category in {"http","transport"}:
                record["transport_error"]=type(error).__name__+": "+str(error)
                result["status"]="transport_failure"
            elif category=="response_envelope" or "response" in record:
                record["protocol_error"]=type(error).__name__+": "+str(error)
                protocol_failures+=1
            else:
                record["execution_error"]=type(error).__name__+": "+str(error)
                result["status"]="execution_failure"
        record["elapsed_seconds"] = round(time.monotonic() - start, 3)
        records.append(record)
        result["model_usage"] = usage_summary(records)
        if protocol_failures >= 3:
            result["status"] = "protocol_failure"
        result["events"] = lab.events
        result["used"] = lab.used
        if lab.final is not None:
            result["status"] = "finished"
            result["frozen_final"] = lab.final
            result["private_score"] = private_score(lab)
        out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
        print(json.dumps({"step": step, "tool": (record.get("feedback") or {}).get("status", content[:120] if "raw_response" in record else "transport_failure"),
                          "seconds": record["elapsed_seconds"], "used": lab.used}, ensure_ascii=False), flush=True)
        if result["status"] != "running":
            break
    if result["status"] == "running":
        result["status"] = "call_limit_without_frozen_model"
        out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"output": str(out), "status": result["status"], "private_score": result.get("private_score")}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
