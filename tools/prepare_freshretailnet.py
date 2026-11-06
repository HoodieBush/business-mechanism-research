"""Download official FreshRetailNet-50K and build a train-only SQLite adapter.

Requires pyarrow in a separate data preparation environment. No model calls.
The original eval split is downloaded and verified but never put into SQLite.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import urllib.request


DATASET = 'Dingdong-Inc/FreshRetailNet-50K'
HUB = 'https://huggingface.co'
FIELDS = {
    'city_id': ('INTEGER', '匿名城市编码，无真实城市名称或可推断的顺序。'),
    'store_id': ('INTEGER', '匿名门店编码；与product_id共同定义一条门店商品序列。'),
    'management_group_id': ('INTEGER', '匿名商品经营分组编码。'),
    'first_category_id': ('INTEGER', '一级品类编码；不提供商品名称或用途文本。'),
    'second_category_id': ('INTEGER', '二级品类编码。'),
    'third_category_id': ('INTEGER', '三级品类编码。'),
    'product_id': ('INTEGER', '匿名商品编码；不自动代表跨品类可比的物理单位。'),
    'dt': ('TEXT', '原始日期，ISO YYYY-MM-DD；一行是一家门店的一种商品的一天。'),
    'sale_amount': ('REAL', '原始全局缩放后的日观测销量；原始量纲及缩放系数未公开，不解释为人民币、订单数或未截断需求。'),
    'hours_sale': ('TEXT', '原始24小时观测销量数组，以JSON保存；索引0至23对应当天小时，与sale_amount采用相同缩放；不补齐缺货需求。'),
    'stock_hour6_22_cnt': ('INTEGER', '原始06:00至22:00缺货小时计数，对应hours_stock_status[6:22]，即小时6至21。'),
    'hours_stock_status': ('TEXT', '原始24小时缺货状态数组，以JSON保存；1表示该小时缺货，0表示未标注缺货；不提供缺失需求真值。'),
    'discount': ('REAL', '折扣率：1.0为不打折，0.9为九折；无绝对价格、成本或毛利。'),
    'holiday_flag': ('INTEGER', '原始节假日指示；保留原始编码。'),
    'activity_flag': ('INTEGER', '原始活动指示；无活动安排的随机化信息。'),
    'precpt': ('REAL', '原始总降水量；数据卡未明确单位，不自行认定为毫米。'),
    'avg_temperature': ('REAL', '原始平均温度；数据卡未明确单位。'),
    'avg_humidity': ('REAL', '原始平均湿度；数据卡未明确单位。'),
    'avg_wind_level': ('REAL', '原始平均风力；数据卡未明确单位及标度。'),
}


def sha256(path):
    result = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def download(raw, revision=None, mirror=False):
    metadata_url = f'{HUB}/api/datasets/{DATASET}'
    if revision:
        metadata_url += '/revision/' + revision
    metadata_url += '?blobs=true'
    with urllib.request.urlopen(metadata_url, timeout=30) as response:
        meta = json.load(response)
    revision = meta['sha']
    if not re.fullmatch('[0-9a-f]{40}', revision):
        raise ValueError('Expected an immutable dataset commit.')
    raw.mkdir(parents=True, exist_ok=True)
    manifest_path = raw / 'download_manifest.json'
    if manifest_path.exists():
        previous = json.loads(manifest_path.read_text())
        if previous['revision'] != revision:
            raise ValueError('Existing raw files belong to another revision; use a new raw directory or --revision.')
    wanted = {'README.md', 'data/train.parquet', 'data/eval.parquet'}
    entries = [item for item in meta['siblings'] if item['rfilename'] in wanted]
    if {item['rfilename'] for item in entries} != wanted:
        raise ValueError('Official dataset layout differs from the expected two splits.')

    def fetch(item):
        name = item['rfilename']
        target = raw / name
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.is_symlink():
            raise ValueError('Refusing a raw file symlink.')
        expected_hash = item.get('lfs', {}).get('sha256')
        url = f'{HUB}/datasets/{DATASET}/resolve/{revision}/{name}?download=true'
        download_url = url.replace(HUB, 'https://hf-mirror.com', 1) if mirror else url
        reused = target.exists()
        if not target.exists():
            partial = target.with_suffix(target.suffix + '.part')
            if partial.is_symlink():
                raise ValueError('Refusing a partial file symlink.')
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({})) if mirror else urllib.request.build_opener()
            with opener.open(download_url, timeout=60) as response, partial.open('wb') as stream:
                if response.status != 200:
                    raise ValueError('Expected a complete file response: ' + name)
                while block := response.read(1024 * 1024):
                    stream.write(block)
            if partial.stat().st_size != item['size'] or (expected_hash and sha256(partial) != expected_hash):
                raise ValueError('Downloaded size/hash mismatch: ' + name)
            partial.replace(target)
        actual_hash = sha256(target)
        if target.stat().st_size != item['size'] or (expected_hash and actual_hash != expected_hash):
            raise ValueError('Existing raw file failed official size/hash validation: ' + name)
        print(json.dumps({'file': name, 'bytes': target.stat().st_size, 'sha256': actual_hash, 'verified': True}), flush=True)
        return {'file': name, 'bytes': target.stat().st_size, 'sha256': actual_hash, 'url': url,
                'download_url': None if reused else download_url, 'reused_verified_local_file': reused,
                'official_lfs_sha256': expected_hash}

    with ThreadPoolExecutor(max_workers=3) as pool:
        files = list(pool.map(fetch, entries))
    manifest = {'dataset': DATASET, 'revision': revision, 'license': 'CC-BY-4.0',
                'source': f'{HUB}/datasets/{DATASET}', 'downloaded_at': datetime.now(timezone.utc).isoformat(), 'files': files}
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
    return manifest


def prepare(raw, output, manifest):
    import pyarrow.parquet as pq

    staging = output.with_name(output.name + '.preparing')
    if output.exists() or staging.exists():
        raise ValueError('Output/staging already exists; choose a new output rather than overwriting.')
    staging.mkdir(parents=True)
    parquet = pq.ParquetFile(raw / 'data/train.parquet')
    if set(parquet.schema_arrow.names) != set(FIELDS):
        raise ValueError('Unexpected source columns; inspect before converting.')
    names = list(FIELDS)
    db = sqlite3.connect(staging / 'business.sqlite')
    audits = {'rows': 0, 'invalid_hour_lengths': 0, 'invalid_stock_codes': 0,
              'stock_count_mismatches': 0, 'daily_hourly_sum_mismatches': 0, 'null_cells': {name: 0 for name in names}}
    try:
        db.execute('PRAGMA journal_mode=DELETE')
        db.execute('PRAGMA synchronous=NORMAL')
        definition = ','.join('"' + name + '" ' + kind for name, (kind, _) in FIELDS.items())
        db.execute('CREATE TABLE retail_daily (' + definition + ', PRIMARY KEY(store_id,product_id,dt))')
        insert = 'INSERT INTO retail_daily VALUES (' + ','.join('?' for _ in names) + ')'
        for batch in parquet.iter_batches(batch_size=10000, columns=names):
            values = batch.to_pydict()
            rows = []
            for index in range(batch.num_rows):
                row = [values[name][index] for name in names]
                for col, name in enumerate(names):
                    audits['null_cells'][name] += row[col] is None
                sales = values['hours_sale'][index]
                stock = values['hours_stock_status'][index]
                if sales is None or stock is None or len(sales) != 24 or len(stock) != 24:
                    audits['invalid_hour_lengths'] += 1
                else:
                    valid_stock = all(value in (0, 1) for value in stock)
                    audits['invalid_stock_codes'] += not valid_stock
                    if valid_stock:
                        audits['stock_count_mismatches'] += sum(stock[6:22]) != values['stock_hour6_22_cnt'][index]
                    total = values['sale_amount'][index]
                    if total is not None and all(value is not None for value in sales):
                        audits['daily_hourly_sum_mismatches'] += abs(sum(sales) - total) > 1e-7 * max(1, abs(total))
                for name in ('hours_sale', 'hours_stock_status'):
                    col = names.index(name)
                    row[col] = None if row[col] is None else json.dumps(row[col], separators=(',', ':'), allow_nan=False)
                rows.append(row)
            with db:
                db.executemany(insert, rows)
            audits['rows'] += batch.num_rows
            if audits['rows'] % 250000 == 0:
                print(json.dumps({'converted_train_rows': audits['rows']}), flush=True)
        db.execute('CREATE INDEX retail_daily_date ON retail_daily(dt)')
        db.execute('CREATE INDEX retail_daily_product_date ON retail_daily(product_id,dt)')
        db.execute('''CREATE VIEW retail_hourly AS
            SELECT d.city_id,d.store_id,d.product_id,d.dt,CAST(h.key AS INTEGER) AS hour,
                   CAST(h.value AS REAL) AS sale_amount,
                   CAST(json_extract(d.hours_stock_status,'$[' || h.key || ']') AS INTEGER) AS stockout_flag,
                   d.discount,d.holiday_flag,d.activity_flag
            FROM retail_daily AS d,json_each(d.hours_sale) AS h''')
        db.execute('ANALYZE')
        db.commit()
        integrity = db.execute('PRAGMA quick_check').fetchone()[0]
        count, stores, products, start, end = db.execute('SELECT count(*),count(DISTINCT store_id),count(DISTINCT product_id),min(dt),max(dt) FROM retail_daily').fetchone()
        series = db.execute('SELECT count(*) FROM (SELECT store_id,product_id FROM retail_daily GROUP BY store_id,product_id)').fetchone()[0]
        if count != parquet.metadata.num_rows or integrity != 'ok':
            raise ValueError('SQLite row conservation or integrity failed.')
        sample = db.execute('SELECT * FROM retail_daily ORDER BY rowid LIMIT 32').fetchall()
        for before, after in zip(pq.ParquetFile(raw / 'data/train.parquet').iter_batches(batch_size=32, columns=names).__next__().to_pylist(), sample):
            restored = dict(zip(names, after))
            for name in ('hours_sale', 'hours_stock_status'):
                restored[name] = json.loads(restored[name]) if restored[name] is not None else None
            if restored != before:
                raise ValueError('Parquet-to-SQLite exact value round trip failed.')
    finally:
        db.close()
    hourly_definitions = {name: FIELDS[name][1] for name in ('city_id', 'store_id', 'product_id', 'dt', 'discount', 'holiday_flag', 'activity_flag')}
    hourly_definitions.update(hour='数组索引0至23，对应当地日内小时；时区未另行提供。',
                              sale_amount='该小时观测销量，来自hours_sale对应元素；与日销量同一全局缩放单位。',
                              stockout_flag='该小时缺货标记：1=缺货，0=未标注缺货，保留原始编码。')
    dictionary = {'tables': {'retail_daily': {'columns': {name: definition for name, (_, definition) in FIELDS.items()}},
                             'retail_hourly': {'columns': hourly_definitions}},
                  'provenance': manifest, 'supplied_split': 'train', 'eval_supplied_to_researcher': False,
                  'transformations': ['全量保留train原始行和字段；两列小时数组转为JSON文本。',
                                      'retail_hourly为按需展开24小时的视图；不复制或填补原始数据。',
                                      '不将eval并入研究输入，不补需求、不插补、不删除异常。']}
    (staging / 'data_dictionary.json').write_text(json.dumps(dictionary, ensure_ascii=False, indent=2) + '\n')
    (staging / 'business_brief.md').write_text(f'''# FreshRetailNet-50K 观察数据研究输入

来源：Dingdong-Inc/FreshRetailNet-50K，版本提交{manifest['revision']}。
发布方：Dingdong Limited；许可：CC BY 4.0；数据页：{HUB}/datasets/{DATASET}。
文献：Wang等，FreshRetailNet-50K: A Stockout-Annotated Censored Demand Dataset for Latent Demand Recovery and Forecasting in Fresh Retail，2025，https://arxiv.org/abs/2505.16319。

本输入仅含官方train的全部{count}个门店商品日，{series}条门店商品序列，{stores}个门店、{products}个商品，日期{start}至{end}。
官方eval原件由部署者独立保留，本阶段不提供，不声称本阶段已完成留出验证。
retail_daily保留原始日级字段；两列小时数组以JSON保存。retail_hourly是按需展开数组的SQL视图，hour为0至23，适合先限定门店/商品/日期再查询。

研究任务：从收到的观测中自主识别值得检验的业务关系、记录口径或适用边界，提出可证伪假说，进行有范围的检验和独立核验；允许反驳和未决，不预设必须发现正向机制或提高预测分数。

数据含销量、小时缺货标签、匿名商品/门店层级、折扣、活动、节假日和天气协变量。ID不提供商品用途或真实名称。
sale_amount和hours_sale采用发布方的全局缩放，系数未公开，不称作人民币或订单数。销量是实际观测，缺货期未满足需求没有真值；缺货时的零销量不自动等于零需求。
缺货计数的时间窗为小时6至21（Python切片[6:22]），与官方基线一致。逐小时1表示缺货。
没有库存水平、补货动作、进货或报废量、绝对价格、成本、订单级购买者、客流、随机化分配、商品文本或现场新测量权限。
分析是观察性的；折扣、缺货与销量可能共同受到既有经营决策影响。需要识别假设及混杂，不把相关关系直接表述为补货或促销的因果效果。
相同门店商品的多天记录及同店同日记录存在依赖；不能默认每行是独立实验单位。重复分析同一数据不等于新增独立证据。
字段未说明的单位、缺失、时区或经营规则应明确列为未知，必要的新数据或干预列入报告，不虚构获得它们。
''', encoding='utf-8')
    audit = {'status': 'passed', 'scope': 'data adaptation, not model/scientific acceptance', 'rows': count,
             'stores': stores, 'products': products, 'series': series, 'date_range': [start, end],
             'source_rows': parquet.metadata.num_rows, 'integrity': integrity, 'exact_roundtrip_rows': len(sample),
             'source_audits': audits, 'source_anomalies_preserved': True, 'eval_included': False, 'model_calls': 0,
             'database_bytes': (staging / 'business.sqlite').stat().st_size,
             'database_sha256': sha256(staging / 'business.sqlite'), 'source': manifest}
    (staging / 'conversion_receipt.json').write_text(json.dumps(audit, ensure_ascii=False, indent=2) + '\n')
    staging.replace(output)
    print(json.dumps({k: audit[k] for k in ('status', 'rows', 'series', 'stores', 'products', 'date_range', 'database_bytes', 'source_audits', 'eval_included', 'model_calls')}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--raw-dir', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--revision', help='Optional immutable official dataset commit.')
    parser.add_argument('--download-only', action='store_true')
    parser.add_argument('--mirror', action='store_true', help='Use hf-mirror.com directly for file bytes; metadata and expected hashes still come from the official Hub.')
    args = parser.parse_args()
    if args.revision and not re.fullmatch('[0-9a-f]{40}', args.revision):
        parser.error('--revision must be a full commit hash')
    raw, output = args.raw_dir.expanduser().absolute(), args.output.expanduser().absolute()
    if raw.is_symlink() or output.is_symlink() or raw == output or raw.is_relative_to(output) or output.is_relative_to(raw):
        parser.error('Raw and prepared inputs must be separate regular directories')
    if not args.download_only and (output.exists() or output.with_name(output.name + '.preparing').exists()):
        parser.error('Output/staging already exists; choose a new output')
    manifest = download(raw, args.revision, args.mirror)
    if not args.download_only:
        prepare(raw, output, manifest)
