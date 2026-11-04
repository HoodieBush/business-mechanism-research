"""Reversible structural serialization of public evidence, not summarization."""
import copy
import json

VERSION="public-context-v0.1-reversible-tables-and-asts"
OPS={"add","sub","mul","min","max","sigmoid"}
NOTE="_table: columns 给出字段顺序，rows 各行按该顺序恢复原对象；不省略行。_ast: 前缀算术树，[op,arg,...]，变量为 ['var',name]，数值原精度保留；op 为 add/sub/mul/min/max/sigmoid。ID 保持原类型；job_id 是整数，不加引号。只改变表示，不改变条件、计数、参数或依赖。"


def compact_json(value):return json.dumps(value,ensure_ascii=False,separators=(",",":"))


def ast_sequence(node):
    if type(node) in (int,float):return node
    if not isinstance(node,dict):raise ValueError("unsupported public arithmetic node")
    if set(node)=={"var"}:return ["var",node["var"]]
    if set(node)=={"op","args"} and node["op"] in OPS:return [node["op"],*[ast_sequence(a) for a in node["args"]]]
    raise ValueError("unsupported public arithmetic node")


def restore_ast(node):
    if type(node) in (int,float):return node
    if not isinstance(node,list) or not node:raise ValueError("invalid compact arithmetic tree")
    if node[0]=="var" and len(node)==2 and isinstance(node[1],str):return {"var":node[1]}
    if node[0] in OPS:return {"op":node[0],"args":[restore_ast(a) for a in node[1:]]}
    raise ValueError("invalid compact arithmetic tree")


def pack(value):
    if isinstance(value,dict):
        if set(value)=={"op","args"} and value["op"] in OPS:return {"_ast":ast_sequence(value)}
        return {k:pack(v) for k,v in value.items()}
    if isinstance(value,list):
        if len(value)>=2 and all(isinstance(row,dict) and set(row)==set(value[0]) for row in value):
            columns=list(value[0]);return {"_table":{"columns":columns,"rows":[[pack(row[k]) for k in columns] for row in value]}}
        return [pack(v) for v in value]
    return copy.deepcopy(value)


def unpack(value):
    if isinstance(value,list):return [unpack(v) for v in value]
    if not isinstance(value,dict):return copy.deepcopy(value)
    if set(value)=={"_ast"}:return restore_ast(value["_ast"])
    if set(value)=={"_table"}:
        table=value["_table"]
        if not isinstance(table,dict) or set(table)!={"columns","rows"}:raise ValueError("invalid public table envelope")
        columns=table["columns"];rows=table["rows"]
        if not isinstance(columns,list) or any(not isinstance(k,str) for k in columns) or len(set(columns))!=len(columns) or not isinstance(rows,list):raise ValueError("invalid public table columns")
        if any(not isinstance(row,list) or len(row)!=len(columns) for row in rows):raise ValueError("invalid public table row width")
        return [{k:unpack(v) for k,v in zip(columns,row)} for row in rows]
    return {k:unpack(v) for k,v in value.items()}


def assert_roundtrip(value):
    encoded=pack(value)
    if unpack(encoded)!=value:raise ValueError("public structural projection lost information")
    return encoded
