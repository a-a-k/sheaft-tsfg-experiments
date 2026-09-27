// Indexed PBR policy; every service increment is performed by the original S1.
package main

import (
    "container/heap"
    "encoding/json"
    "errors"
    "sort"
)

type pbrRanks []int
func (q pbrRanks) Len()int{return len(q)}
func (q pbrRanks) Less(i,j int)bool{return q[i]<q[j]}
func (q pbrRanks) Swap(i,j int){q[i],q[j]=q[j],q[i]}
func (q *pbrRanks) Push(v any){*q=append(*q,v.(int))}
func (q *pbrRanks) Pop()any{a:=*q;v:=a[len(a)-1];*q=a[:len(a)-1];return v}

// Deterministic ordered waiting index. This indexes only blocked transfers or
// resource requests, not all operations at every grid boundary.
type pbrTree struct {key int; priority uint64; size int; left,right *pbrTree}
func pbrSize(t *pbrTree)int{if t==nil{return 0};return t.size}
func pbrFix(t *pbrTree){if t!=nil{t.size=1+pbrSize(t.left)+pbrSize(t.right)}}
func pbrPriority(key int)uint64{v:=uint64(key)+0x9e3779b97f4a7c15;v=(v^(v>>30))*0xbf58476d1ce4e5b9;v=(v^(v>>27))*0x94d049bb133111eb;return v^(v>>31)}
func pbrInsert(t *pbrTree,key int)*pbrTree {
    if t==nil{return &pbrTree{key:key,priority:pbrPriority(key),size:1}}
    if key<t.key {t.left=pbrInsert(t.left,key);if t.left.priority<t.priority{v:=t.left;t.left=v.right;v.right=t;pbrFix(t);t=v}} else if key>t.key {t.right=pbrInsert(t.right,key);if t.right.priority<t.priority{v:=t.right;t.right=v.left;v.left=t;pbrFix(t);t=v}}
    pbrFix(t);return t
}
func pbrMerge(a,b *pbrTree)*pbrTree {
    if a==nil{return b};if b==nil{return a}
    if a.priority<b.priority{a.right=pbrMerge(a.right,b);pbrFix(a);return a}
    b.left=pbrMerge(a,b.left);pbrFix(b);return b
}
func pbrDelete(t *pbrTree,key int)*pbrTree {
    if t==nil{return nil};if key==t.key{return pbrMerge(t.left,t.right)}
    if key<t.key{t.left=pbrDelete(t.left,key)}else{t.right=pbrDelete(t.right,key)};pbrFix(t);return t
}
func pbrAfter(t *pbrTree,key int)int{best:=-1;for t!=nil{if t.key>key{best=t.key;t=t.left}else{t=t.right}};return best}
func pbrWalk(t *pbrTree,fn func(int)){if t==nil{return};pbrWalk(t.left,fn);fn(t.key);pbrWalk(t.right,fn)}

type pbrEvent struct {time int64;kind,id int}
type pbrEvents []pbrEvent
func(q pbrEvents)Len()int{return len(q)}
func(q pbrEvents)Less(i,j int)bool{a,b:=q[i],q[j];if a.time!=b.time{return a.time<b.time};if a.kind!=b.kind{return a.kind<b.kind};return a.id<b.id}
func(q pbrEvents)Swap(i,j int){q[i],q[j]=q[j],q[i]}
func(q *pbrEvents)Push(v any){*q=append(*q,v.(pbrEvent))}
func(q *pbrEvents)Pop()any{a:=*q;v:=a[len(a)-1];*q=a[:len(a)-1];return v}

type pbrExtension struct {
    capacities,need,assigned,used,peaks,rank,order []int
    owners [][]int
    down [][][][2]int64
    downCursor [][]int
    released,transfer,entry []int64
    buffered,releaseTimer,planTimer []bool
    bufferWait,resourceWait []*pbrTree
    ready,next pbrRanks
    readySet,nextSet map[int]bool
    timers pbrEvents
    sweep bool
    cursor int
    deadlock bool
    custody [][5]int64
    custodyIndex []int
    links [][6]int64
    resourceIntegral,blockedIntegral int64
    visits int64
}

func(p *opPolicy)initPBR()error {
    n,m:=len(p.data.Operations),len(p.data.Queues)
    x:=&pbrExtension{capacities:make([]int,m),need:make([]int,n),assigned:make([]int,n),used:make([]int,m),peaks:make([]int,m),
        rank:make([]int,n),order:make([]int,n),released:make([]int64,n),transfer:make([]int64,n),entry:make([]int64,n),
        buffered:make([]bool,n),releaseTimer:make([]bool,n),planTimer:make([]bool,n),bufferWait:make([]*pbrTree,m),
        readySet:map[int]bool{},nextSet:map[int]bool{},cursor:-1,custody:make([][5]int64,0),links:make([][6]int64,0),
        custodyIndex:make([]int,n),owners:make([][]int,0)}
    p.pbr=x
    for k:=range x.capacities{x.capacities[k]=-1;if p.data.BufferCapacity>0{x.capacities[k]=p.data.BufferCapacity}}
    if len(p.data.BufferCapacities)>0 {
        if len(p.data.BufferCapacities)!=m{return errors.New("Invalid PBR buffer dimensions")}
        for k,raw:=range p.data.BufferCapacities {
            if string(raw)==`"unbounded"`{x.capacities[k]=-1;continue}
            if err:=json.Unmarshal(raw,&x.capacities[k]);err!=nil || x.capacities[k]<0{return errors.New("Invalid PBR buffer capacity")}
        }
    }
    for r,pool:=range p.data.ResourcePools {
        if pool.ID!=r || pool.Capacity<=0{return errors.New("Invalid PBR pool")}
        units:=make([]int,pool.Capacity);for u:=range units{units[u]=-1};x.owners=append(x.owners,units)
    }
    if len(x.owners)==0 && len(p.data.SharedOperations)>0{x.owners=append(x.owners,[]int{-1})}
    x.down=make([][][][2]int64,len(x.owners));x.downCursor=make([][]int,len(x.owners));x.resourceWait=make([]*pbrTree,len(x.owners))
    for r,units:=range x.owners{x.down[r]=make([][][2]int64,len(units));x.downCursor[r]=make([]int,len(units))}
    for i,o:=range p.data.Operations {
        if len(o.Predecessors)>1 || len(p.successors[i])>1{return errors.New("PBR chain routes required")}
        x.order[i]=i;x.need[i]=-1;x.assigned[i]=-1;x.released[i]=-1;x.transfer[i]=-1;x.entry[i]=-1;x.custodyIndex[i]=-1
        if o.ResourcePool!=nil{x.need[i]=*o.ResourcePool}
        if x.need[i]< -1 || x.need[i]>=len(x.owners){return errors.New("Invalid PBR operation pool")}
        if o.Work%5!=0{return errors.New("Unaligned PBR work")}
        if p.pending[i]==0{heap.Push(&x.timers,pbrEvent{o.Release,0,i})}
    }
    for _,i:=range p.data.SharedOperations{if i<0 || i>=n{return errors.New("Invalid shared operation")};x.need[i]=0}
    if len(p.scenario.Speeds)>0{return errors.New("Fractional speed is a separate profile")}
    for _,v:=range p.data.BaseSpeed{if v!=100{return errors.New("PBR unit speed required")}}
    failures:=append([][4]int64{},p.scenario.ResourceFailures...)
    for _,v:=range p.scenario.SharedFailures{failures=append(failures,[4]int64{0,0,v[0],v[1]})}
    for _,v:=range failures {
        r,u,a,b:=int(v[0]),int(v[1]),v[2],v[3]
        if r<0 || r>=len(x.owners) || u<0 || u>=len(x.owners[r]) || a<0 || b<=a || a%5!=0 || b%5!=0{return errors.New("Invalid PBR unit failure")}
        x.down[r][u]=append(x.down[r][u],[2]int64{a,b});heap.Push(&x.timers,pbrEvent{a,2,r});heap.Push(&x.timers,pbrEvent{b,2,r})
    }
    for r:=range x.down{for u:=range x.down[r]{items:=x.down[r][u];sort.Slice(items,func(a,b int)bool{return items[a][0]<items[b][0]});merged:=make([][2]int64,0,len(items));for _,v:=range items{if len(merged)>0 && v[0]<=merged[len(merged)-1][1]{if v[1]>merged[len(merged)-1][1]{merged[len(merged)-1][1]=v[1]}}else{merged=append(merged,v)}};x.down[r][u]=merged}}
    for _,v:=range p.scenario.Failures{heap.Push(&x.timers,pbrEvent{v[1],1,int(v[0])});heap.Push(&x.timers,pbrEvent{v[2],1,int(v[0])})}
    sort.Slice(x.order,func(a,b int)bool{u,v:=p.data.Operations[x.order[a]],p.data.Operations[x.order[b]];if u.Planned!=v.Planned{return u.Planned<v.Planned};if u.Job!=v.Job{return u.Job<v.Job};return u.ID<v.ID})
    for r,i:=range x.order{x.rank[i]=r}
    return nil
}
func(p *opPolicy)pbrUnitUp(r,u int,t int64)bool {
    x:=p.pbr;for x.downCursor[r][u]<len(x.down[r][u]) && x.down[r][u][x.downCursor[r][u]][1]<=t{x.downCursor[r][u]++}
    return x.downCursor[r][u]==len(x.down[r][u]) || t<x.down[r][u][x.downCursor[r][u]][0]
}
func(p *opPolicy)pbrFree(r int,t int64)int{for u,owner:=range p.pbr.owners[r]{if owner<0 && p.pbrUnitUp(r,u,t){return u}};return -1}
func(p *opPolicy)pbrActivate(i int) {
    if i<0 || p.start[i]>=0{return};x:=p.pbr;r:=x.rank[i]
    if x.sweep && r<=x.cursor{if !x.nextSet[r]{x.nextSet[r]=true;heap.Push(&x.next,r)}}else{if !x.readySet[r]{x.readySet[r]=true;heap.Push(&x.ready,r)}}
}
func(p *opPolicy)pbrWake(tree *pbrTree){x:=p.pbr;cursor:=-1;if x.sweep{cursor=x.cursor};r:=pbrAfter(tree,cursor);if r<0{r=pbrAfter(tree,-1)};if r>=0{p.pbrActivate(x.order[r])}}
func(p *opPolicy)pbrWakeBuffer(m int){x:=p.pbr;if x.capacities[m]<0 || x.used[m]<x.capacities[m]{p.pbrWake(x.bufferWait[m])}}
func(p *opPolicy)pbrWakeResource(r int,t int64){if r>=0 && p.pbrFree(r,t)>=0{p.pbrWake(p.pbr.resourceWait[r])}}
func(p *opPolicy)pbrWakeHead(m int){if p.head[m]<len(p.data.Queues[m]){p.pbrActivate(p.data.Queues[m][p.head[m]])};i:=p.current[m];if i>=0 && p.finish[i]>=0 && len(p.successors[i])>0{p.pbrActivate(p.successors[i][0])}}
func(p *opPolicy)pbrCan(i int,t int64,self,resource bool)bool {
    x:=p.pbr;o:=p.data.Operations[i];m:=o.Machine
    if p.start[i]>=0 || p.pending[i]!=0 || o.Release>t || o.Planned>t || !p.available(m,t){return false}
    if p.current[m]<0{if p.head[m]>=len(p.data.Queues[m]) || p.data.Queues[m][p.head[m]]!=i{return false}}else{
        prev:=p.current[m];if !self || len(o.Predecessors)==0 || o.Predecessors[0]!=prev || p.finish[prev]<0 || p.head[m]+1>=len(p.data.Queues[m]) || p.data.Queues[m][p.head[m]+1]!=i{return false}
    }
    return !resource || x.need[i]<0 || p.pbrFree(x.need[i],t)>=0
}
func(p *opPolicy)pbrRelease(i int,t int64){x:=p.pbr;if x.released[i]>=0{return};m:=p.data.Operations[i].Machine;if p.current[m]!=i || p.finish[i]<0{panic("Invalid PBR machine release")};p.current[m]=-1;p.head[m]++;x.released[i]=t;p.pbrWakeHead(m)}
func(p *opPolicy)pbrStart(i int,t int64) {
    x:=p.pbr;m:=p.data.Operations[i].Machine;r:=x.need[i]
    if p.current[m]>=0{panic("PBR machine overlap")};x.bufferWait[m]=pbrDelete(x.bufferWait[m],x.rank[i])
    if x.buffered[i]{x.buffered[i]=false;x.used[m]--;p.pbrWakeBuffer(m)}
    p.start[i]=t;p.current[m]=i;p.injection[m]=p.left[i]
    if r>=0{x.resourceWait[r]=pbrDelete(x.resourceWait[r],x.rank[i]);u:=p.pbrFree(r,t);if u<0{panic("PBR resource overlap")};x.assigned[i]=u;x.owners[r][u]=i;x.custodyIndex[i]=len(x.custody);x.custody=append(x.custody,[5]int64{int64(r),int64(u),int64(i),t,-1});p.pbrWakeResource(r,t)}
}
func(p *opPolicy)pbrConsider(i int,t int64) {
    x:=p.pbr;o:=p.data.Operations[i];m,r:=o.Machine,x.need[i];x.visits++
    if r>=0{x.resourceWait[r]=pbrDelete(x.resourceWait[r],x.rank[i])}
    if p.start[i]>=0 || p.pending[i]!=0{return}
    if o.Release>t{if !x.releaseTimer[i]{heap.Push(&x.timers,pbrEvent{o.Release,0,i});x.releaseTimer[i]=true};return}
    if o.Planned>t && !x.planTimer[i]{heap.Push(&x.timers,pbrEvent{o.Planned,0,i});x.planTimer[i]=true}
    if r>=0 && p.pbrCan(i,t,true,false) && p.pbrFree(r,t)<0{x.resourceWait[r]=pbrInsert(x.resourceWait[r],x.rank[i])}
    if x.transfer[i]<0 {
        direct:=p.pbrCan(i,t,true,true)
        if !direct && x.capacities[m]>=0 && x.used[m]>=x.capacities[m]{x.bufferWait[m]=pbrInsert(x.bufferWait[m],x.rank[i]);return}
        x.bufferWait[m]=pbrDelete(x.bufferWait[m],x.rank[i]);for _,prev:=range o.Predecessors{p.pbrRelease(prev,t)};x.transfer[i]=t
        if direct{p.pbrStart(i,t)}else{x.buffered[i]=true;x.entry[i]=t;x.used[m]++;if x.used[m]>x.peaks[m]{x.peaks[m]=x.used[m]}}
    }
    if x.buffered[i] && p.pbrCan(i,t,false,true){p.pbrStart(i,t)}
    p.pbrWakeBuffer(m);p.pbrWakeResource(r,t)
}
func(p *opPolicy)pbrBoundary(t int64) {
    x:=p.pbr;p.stopped=t;x.sweep=false;x.cursor=-1
    for len(x.timers)>0 && x.timers[0].time<=t {
        event:=heap.Pop(&x.timers).(pbrEvent)
        if event.kind==0{p.pbrActivate(event.id)}else if event.kind==1{p.pbrWakeHead(event.id)}else{
            p.pbrWakeResource(event.id,t);for m,q:=range p.data.Queues{if p.head[m]<len(q) && x.need[q[p.head[m]]]==event.id{p.pbrWakeHead(m)}}
        }
    }
    x.sweep=true
    for len(x.ready)>0 || len(x.next)>0 {
        if len(x.ready)==0{x.ready,x.next=x.next,x.ready;x.readySet,x.nextSet=x.nextSet,x.readySet;x.cursor=-1}
        x.cursor=heap.Pop(&x.ready).(int);delete(x.readySet,x.cursor);p.pbrConsider(x.order[x.cursor],t)
    }
    x.sweep=false;active:=false
    for m,i:=range p.current{rate:=0.0;if p.available(m,t){rate=1};if i>=0 && p.finish[i]<0{active=true;if x.need[i]>=0 && !p.pbrUnitUp(x.need[i],x.assigned[i],t){rate=0}};p.multiplierRefs[m][0]=rate}
    x.deadlock=p.completed<len(p.data.Operations) && !active && len(x.timers)==0
}
func(p *opPolicy)pbrEndStep()error {
    x:=p.pbr;if x.deadlock{return opDeadlocked};done:=p.completionScratch[:0]
    for _,i:=range p.current{if i>=0 && p.left[i]==0 && p.finish[i]<0{p.finish[i]=p.stepEnd;done=append(done,i)}}
    for _,i:=range done {
        r:=x.need[i];if r>=0{x.owners[r][x.assigned[i]]=-1;x.custody[x.custodyIndex[i]][4]=p.stepEnd;p.pbrWakeResource(r,p.stepEnd)}
        for _,child:=range p.successors[i]{p.pending[child]--;p.updates++;p.pbrActivate(child)}
        if len(p.successors[i])==0 || x.capacities[p.data.Operations[i].Machine]<0{p.pbrRelease(i,p.stepEnd)}
    }
    p.completed+=len(done);p.stopped=p.stepEnd;if p.completed==len(p.data.Operations){return opAllDone};return nil
}
func(p *opPolicy)pbrMetrics(t,end int64) {
    x:=p.pbr;if x.deadlock{return};dt:=end-t
    for _,tree:=range x.resourceWait{x.resourceIntegral+=int64(pbrSize(tree))*dt}
    for _,i:=range p.current{if i>=0 && p.finish[i]>=0{x.blockedIntegral+=dt}}
    for r,tree:=range x.resourceWait{pbrWalk(tree,func(position int){i:=x.order[position];m:=p.data.Operations[i].Machine;for _,prev:=range p.data.Operations[i].Predecessors{
        if p.finish[prev]>=0 && x.released[prev]<0 && x.transfer[i]<0 && x.capacities[m]>=0 && x.used[m]>=x.capacities[m]{v:=[6]int64{t,end,int64(prev),int64(i),int64(m),int64(r)};same:=len(x.links)>0;if same{last:=x.links[len(x.links)-1];same=last[1]==t;for k:=2;k<6;k++{same=same && last[k]==v[k]}};if same{x.links[len(x.links)-1][1]=end}else{x.links=append(x.links,v)}}
    }})}
}
func(p *opPolicy)pbrOutput(row map[string]any) {
    x:=p.pbr;row["engine"]="tsfg-ext";row["algorithm_id"]="TSFG-EXT-v2.2"
    row["machine_release"]=x.released;row["transfer_at"]=x.transfer;row["buffer_entry"]=x.entry;row["buffer_counts"]=x.used;row["buffer_peaks"]=x.peaks
    row["resource_unit"]=x.assigned;row["resource_owners"]=x.owners;row["resource_ownership"]=x.custody
    row["resource_wait_integral"]=x.resourceIntegral;row["blocked_machine_integral"]=x.blockedIntegral;row["coupling_witnesses"]=x.links
    row["deadlock_proof"]=nil
    states:=row["state"].([]string)
    for i:=range states{if p.finish[i]>=0 && x.released[i]<0{states[i]="BLOCKED_AFTER_PROCESSING"};if p.start[i]>=0 && p.finish[i]<0 && x.need[i]>=0 && !p.pbrUnitUp(x.need[i],x.assigned[i],p.stopped){states[i]="SUSPENDED"}}
    if x.deadlock && p.stopped<row["horizon"].(int64){row["run_status"]="DEADLOCK";row["deadlock_proof"]=map[string]bool{"no_running_operations":true,"no_future_changes":true}}else if p.completed<len(p.data.Operations){row["run_status"]="CENSORED"}
    row["counters"].(map[string]int)["candidate_visits"]=int(x.visits)
}
