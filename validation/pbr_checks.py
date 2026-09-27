"""Physical trace invariants independent of every transition implementation."""


def covered(a,b,intervals):
    total=0
    tail=a
    for left,right in sorted(intervals):
        left=max(a,left,tail);right=min(b,right)
        if right>left:total+=right-left;tail=right
    return total


def validate(data,scenario,row):
    ops=data['operations'];n=len(ops);m=len(data['queues']);stop=row['stopped']
    assert 0<=stop<=row['horizon']
    start,finish,remaining=row['start'],row['finish'],row['remaining']
    assert len(start)==len(finish)==len(remaining)==n
    cap=data.get('buffer_capacities',[data.get('buffer_capacity',0) or 'unbounded']*m)
    needs=[op.get('resource_pool') for op in ops]
    for i in data.get('shared_operations',[]):needs[i]=0
    pools=data.get('resource_pools',[])
    if not pools and data.get('shared_operations'):pools=[dict(id=0,capacity=1)]
    work=[op['work'] for op in ops]
    for i,value in scenario.get('work_overrides',[]):work[i]=value
    machine_down=[[] for _ in range(m)]
    for k,a,b in scenario.get('failures',[]):machine_down[k].append((a,b))
    resource_down={}
    for r,u,a,b in scenario.get('resource_failures',[])+[[0,0,a,b] for a,b in scenario.get('shared_failures',[])]:
        resource_down.setdefault((r,u),[]).append((a,b))
    for i,op in enumerate(ops):
        s,c=start[i],finish[i];released=row['machine_release'][i]
        transfer=row['transfer_at'][i];entry=row['buffer_entry'][i]
        assert type(remaining[i]) is int and 0<=remaining[i]<=work[i]
        if s is None:
            assert c is None and remaining[i]==work[i] and released==-1
        else:
            assert type(s) is int and max(op['release'],op['planned_start'])<=s<=stop
            assert all(finish[p] is not None and finish[p]<=s for p in op['predecessors'])
            end=c if c is not None else stop
            assert s<=end<=stop
            down=machine_down[op['machine']][:]
            if needs[i] is not None:
                u=row['resource_unit'][i]
                assert 0<=u<pools[needs[i]]['capacity']
                down+=resource_down.get((needs[i],u),[])
            assert covered(s,s+1,down)==0, 'Started while unavailable'
            performed=end-s-covered(s,end,down)
            assert performed+remaining[i]==work[i],('Work conservation',i,performed,remaining[i],work[i])
            if c is not None:assert c>s and remaining[i]==0
        if released>=0:assert c is not None and c<=released<=stop
        if transfer>=0:
            assert op['release']<=transfer<=stop
            for p in op['predecessors']:
                assert finish[p] is not None and finish[p]<=transfer
                if cap[ops[p]['machine']]=='unbounded':assert row['machine_release'][p]<=transfer
                else:assert row['machine_release'][p]==transfer
        if entry>=0:assert entry==transfer and (s is None or entry<=s)
        if s is not None:assert transfer>=0 and (entry>=0 or transfer==s)
    for k,queue in enumerate(data['queues']):
        for previous,following in zip(queue,queue[1:]):
            if start[following] is not None:
                assert row['machine_release'][previous]>=0 and row['machine_release'][previous]<=start[following], 'Queue bypass/custody overlap'
        occupancy=0;peak=0;events=[]
        for i in queue:
            a=row['buffer_entry'][i]
            if a<0:continue
            b=stop if start[i] is None else start[i]
            if a<b:events.extend(((a,1),(b,-1)))
            if start[i] is None:occupancy+=1
        count=0
        for _,change in sorted(events):count+=change;peak=max(peak,count)
        assert occupancy==row['buffer_counts'][k]
        assert row['buffer_peaks'][k]>=peak
        if cap[k]!='unbounded':assert row['buffer_peaks'][k]<=cap[k] and occupancy<=cap[k]
    ownership={}
    observed=set()
    for r,u,i,a,b in row['resource_ownership']:
        assert i not in observed and needs[i]==r and row['resource_unit'][i]==u
        observed.add(i)
        assert a==start[i] and b==(finish[i] if finish[i] is not None else -1)
        ownership.setdefault((r,u),[]).append((a,stop if b<0 else b,i,b))
    for i in range(n):assert (i in observed)==(start[i] is not None and needs[i] is not None)
    for r,pool in enumerate(pools):
        for u in range(pool['capacity']):
            intervals=sorted(ownership.get((r,u),[]))
            for a,b in zip(intervals,intervals[1:]):assert a[1]<=b[0], 'Resource double owner'
            active=[i for a,b,i,end in intervals if end<0]
            assert len(active)<=1 and row['resource_owners'][r][u]==(active[0] if active else -1)
    complete=all(c is not None for c in finish)
    assert row['mission_success']==row['completion_known']==complete
    assert row['cmax']==(max(finish) if complete else None)
    assert row['job_finish']==[finish[j['final_operation']] for j in data['jobs']]
    assert row['completion_lower_bound']==(None if complete else row['horizon'])
    interval_end=row['horizon'] if row['mode']=='MISSION' else stop
    blocked=sum((row['machine_release'][i] if row['machine_release'][i]>=0 else interval_end)-c
                for i,c in enumerate(finish) if c is not None)
    assert blocked==row['blocked_machine_integral'], 'Blocked integral must cover the common mission window'
    for a,b,p,i,k,r in row['coupling_witnesses']:
        assert 0<=a<b<=interval_end and ops[i]['predecessors']==[p] and ops[i]['machine']==k and needs[i]==r
        assert finish[p] is not None and finish[p]<=a and (row['machine_release'][p]<0 or row['machine_release'][p]>=b)
        assert row['transfer_at'][i]<0 or row['transfer_at'][i]>=b
    if row['run_status']=='DEADLOCK':
        assert row['deadlock_proof']==dict(no_running_operations=True,no_future_changes=True)
        assert all(s is None or c is not None for s,c in zip(start,finish))
        assert all(b<=stop for down in machine_down for a,b in down)
        assert all(b<=stop for down in resource_down.values() for a,b in down)
        for i,op in enumerate(ops):
            if start[i] is None and all(finish[p] is not None for p in op['predecessors']):
                assert max(op['release'],op['planned_start'])<=stop
