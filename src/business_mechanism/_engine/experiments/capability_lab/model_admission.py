"""Transparent admission estimates; provider usage remains the actual ledger."""
import json
import math


def estimate(payload, records, policy="serialized_bytes"):
    request_bytes = len(json.dumps(payload, ensure_ascii=False).encode())
    output = payload["max_tokens"]
    if policy == "serialized_bytes":
        return {"policy": policy, "estimated_tokens": request_bytes + output,
                "request_bytes": request_bytes, "tokenizer_verified": False}
    if policy != "provider_prompt_ratio":raise ValueError("unknown model admission policy")
    ratios = []
    for record in records:
        prompt = record.get("response", {}).get("usage", {}).get("prompt_tokens")
        if type(prompt) is int and prompt > 0 and "request" in record:
            size = len(json.dumps(record["request"], ensure_ascii=False).encode())
            if size:ratios.append(prompt / size)
    reserve = math.ceil(request_bytes * max(ratios) * 1.5) + output if ratios else request_bytes + output
    return {"policy": policy, "estimated_tokens": reserve, "request_bytes": request_bytes,
            "observed_prompt_ratios": len(ratios), "safety_factor": 1.5,
            "fallback_to_bytes": not bool(ratios), "tokenizer_verified": False,
            "basis": "Historical maximum provider prompt-token/request-byte ratio; estimate, not a guaranteed token bound."}
