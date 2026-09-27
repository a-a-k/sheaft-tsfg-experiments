"""Compact APS-BASIC input. No selected machine, schedule or queue is admitted."""
import hashlib
import json
from pathlib import Path

SCHEMA = 'APS-BASIC-catalog-v1'


def compact_json(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'))


def semantic_prefix(tick_unit, machines):
    return ('{"tick_unit":' + compact_json(tick_unit) + ',"machines":' + str(machines) + ',"operations":[').encode()


def canonical_operation(op):
    return dict(id=op['id'], job=op['job'], release=op['release'], predecessors=sorted(op['predecessors']),
                alternatives=[dict(machine=a['machine'], work=a['work'])
                              for a in sorted(op['alternatives'], key=lambda a: a['machine'])])


def write_task(operations, machines, tick_unit, path):
    """Streaming conversion; catalog IDs never participate in the semantic hash."""
    catalogs = {}
    hasher = hashlib.sha256(semantic_prefix(tick_unit, machines))
    count = 0
    alternatives = 0
    with Path(path).open('w', encoding='utf-8', newline='\n') as output:
        output.write(compact_json(dict(schema=SCHEMA, machines=machines, tick_unit=tick_unit)) + '\n')
        for op in operations:
            row = canonical_operation(op)
            assert row['id'] == count
            key = tuple((a['machine'], a['work']) for a in row['alternatives'])
            assert key and len({m for m, _ in key}) == len(key)
            assert all(type(m) is int and 0 <= m < machines and type(p) is int and p > 0 for m, p in key)
            if key not in catalogs:
                catalogs[key] = len(catalogs)
                output.write(compact_json(['C', catalogs[key], key]) + '\n')
            output.write(compact_json(['O', row['id'], row['job'], row['release'], row['predecessors'], catalogs[key]]) + '\n')
            if count: hasher.update(b',')
            hasher.update(compact_json(row).encode())
            count += 1
            alternatives += len(key)
        hasher.update(b']}')
        summary = dict(task_sha256=hasher.hexdigest(), operations=count, catalog_entries=len(catalogs),
                       expanded_alternatives=alternatives, catalog_alternatives=sum(len(k) for k in catalogs))
        output.write(compact_json(['END', summary]) + '\n')
    return summary


def read_task(path):
    catalog, ops = [], []
    with Path(path).open(encoding='utf-8') as file:
        header = json.loads(next(file))
        assert set(header) == {'schema', 'machines', 'tick_unit'} and header['schema'] == SCHEMA
        for line in file:
            row = json.loads(line)
            if row[0] == 'C':
                assert len(row) == 3 and row[1] == len(catalog)
                # The scheduler reads alternatives but never mutates them.
                catalog.append(tuple(dict(machine=m, work=p) for m, p in row[2]))
            elif row[0] == 'O':
                assert len(row) == 6 and row[1] == len(ops)
                _, i, job, release, predecessors, reference = row
                ops.append(dict(id=i, job=job, release=release, predecessors=predecessors, alternatives=catalog[reference]))
            elif row[0] == 'END':
                summary = row[1]
                assert len(ops) == summary['operations'] and len(catalog) == summary['catalog_entries']
                assert not file.read(1)
                return {**header, **summary, 'operation_count': summary['operations'], 'operations': ops}
            else:
                raise ValueError('Unknown APS record')
    raise ValueError('Truncated task')
