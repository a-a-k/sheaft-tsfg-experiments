"""Exact shared-type representation; execution still retains every operation."""
import hashlib
import json
from pathlib import Path
import struct
import time

from experiments.scale_data import read_binary


def write_grouped(data, path):
    begin=time.monotonic()
    jobs=[[] for _ in data['jobs']]
    for o in data['operations']:jobs[o['job']].append(o)
    registry={}
    route_cache={}
    types=[]
    mapping=[None]*len(data['operations'])
    for route in jobs:
        cache_key=tuple(id(o['alternatives']) for o in route)
        digest=route_cache.get(cache_key)
        if digest is None:
            description=[sorted((a['machine'],a['work']) for a in o['alternatives']) for o in route]
            digest=hashlib.sha256(json.dumps(description,separators=(',',':')).encode()).hexdigest()
            route_cache[cache_key]=digest
        for k,o in enumerate(route):
            key=(digest,k,o['release'],data['metadata']['D_ticks'],o['machine'],o['work'])
            if key not in registry:
                registry[key]=len(types)
                types.append(o['work'])
            mapping[o['id']]=registry[key]
    path=Path(path)
    with path.open('wb') as f:
        f.write(b'TSFGGRP1')
        f.write(struct.pack('<IIII',len(mapping),len(jobs),len(data['queues']),len(types)))
        f.write(struct.pack(f'<{len(types)}q',*types))
        for o in data['operations']:
            f.write(struct.pack('<IIIqqI',o['job'],o['machine'],mapping[o['id']],o['planned_start'],o['release'],len(o['predecessors'])))
            f.write(struct.pack(f"<{len(o['predecessors'])}I",*o['predecessors']))
        for q in data['queues']:
            f.write(struct.pack('<I',len(q)))
            f.write(struct.pack(f'<{len(q)}I',*q))
        f.write(struct.pack(f'<{len(jobs)}I',*(j['final_operation'] for j in data['jobs'])))
    preparation=time.monotonic()-begin
    decoded=read_binary(path)
    for a,b in zip(data['operations'],decoded['operations']):
        assert all(a[k]==b[k] for k in ('id','job','machine','work','planned_start','release','predecessors'))
    assert decoded['queues']==data['queues']
    assert [j['final_operation'] for j in decoded['jobs']]==[j['final_operation'] for j in data['jobs']]
    return dict(representation='G1-exact-shared-types',type_count=len(types),individual_state_count=len(mapping),
                input_bytes=path.stat().st_size,preparation_wall_s=preparation,codec_validation='PASS',
                type_registry_sha256=hashlib.sha256(json.dumps(list(registry),separators=(',',':')).encode()).hexdigest(),
                grouping_criteria=['route and all alternatives/work','stage','release','deadline','assigned machine','fixed queue policy'])
