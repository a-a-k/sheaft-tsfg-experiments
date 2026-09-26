// Optional E1X policy; service still comes from the unchanged S1 graph kernel.
package main

import (
    "errors"
    "fmt"
    "sort"
)

var opDeadlocked=errors.New("extended profile deadlock")
type opExtension struct {
    order []int
    buffered, arrived, needsShared []bool
    bufferUsed []int
    releasedAt []int64
    owner int
    deadlock bool
}

func (p *opPolicy) initExtension() error {
    n,m:=len(p.data.Operations),len(p.data.Queues)
    x:=&opExtension{buffered:make([]bool,n),arrived:make([]bool,n),needsShared:make([]bool,n),
        bufferUsed:make([]int,m),releasedAt:make([]int64,n),owner:-1}
    p.ext=x
    for i:=0;i<n;i++ {
        if len(p.data.Operations[i].Predecessors)>1 || len(p.successors[i])>1 {return errors.New("Extended buffers support chain routes only")}
        x.order=append(x.order,i);x.releasedAt[i]=-1
        p.left[i]*=100
    }
    if p.data.BufferCapacity<0 {return errors.New("Negative buffer capacity")}
    if len(p.data.BaseSpeed)!=0 && len(p.data.BaseSpeed)!=m {return errors.New("Invalid base speed vector")}
    for _,v:=range p.data.BaseSpeed {if v<=0{return errors.New("Invalid base speed")}}
    for _,i:=range p.data.SharedOperations {
        if i<0 || i>=n {return errors.New("Invalid shared-resource operation")}
        x.needsShared[i]=true
    }
    for k,v:=range p.scenario.Speeds {
        if v[0]<0 || v[0]>=int64(m) || v[1]<0 || v[2]<=v[1] || v[3]<=0 {return errors.New("Invalid speed interval")}
        for _,w:=range p.scenario.Speeds[:k] {
            if v[0]==w[0] && v[1]<w[2] && w[1]<v[2] {return errors.New("Overlapping speed assignments")}
        }
    }
    for _,v:=range p.scenario.SharedFailures {if v[0]<0 || v[1]<=v[0] {return errors.New("Invalid shared failure")}}
    sort.Slice(x.order,func(a,b int)bool {
        u,v:=p.data.Operations[x.order[a]],p.data.Operations[x.order[b]]
        if u.Planned!=v.Planned{return u.Planned<v.Planned};if u.Job!=v.Job{return u.Job<v.Job};return u.ID<v.ID
    })
    return nil
}
func (p *opPolicy) sharedAvailable(t int64)bool {
    for _,v:=range p.scenario.SharedFailures {if v[0]<=t && t<v[1] {return false}}
    return true
}
func (p *opPolicy) extRelease(i int,t int64) {
    if p.ext.releasedAt[i]>=0 {return}
    m:=p.data.Operations[i].Machine
    if p.current[m]!=i || p.finish[i]<0 {panic("Release without completed machine custody")}
    p.current[m]=-1;p.head[m]++;p.ext.releasedAt[i]=t
}
func (p *opPolicy) extCanStart(i int,t int64,allowSelf bool)bool {
    o:=p.data.Operations[i];m:=o.Machine
    if p.head[m]>=len(p.data.Queues[m]) {return false}
    ownTransfer:=allowSelf && p.current[m]>=0 && len(o.Predecessors)==1 &&
        p.current[m]==o.Predecessors[0] && p.finish[p.current[m]]>=0 &&
        p.head[m]+1<len(p.data.Queues[m]) && p.data.Queues[m][p.head[m]+1]==i
    if !ownTransfer && (p.current[m]>=0 || p.data.Queues[m][p.head[m]]!=i) {return false}
    if o.Planned>t || o.Release>t || p.pending[i]!=0 || !p.available(m,t) {return false}
    return !p.ext.needsShared[i] || (p.ext.owner<0 && p.sharedAvailable(t))
}
func (p *opPolicy) extStart(i int,t int64) {
    o:=p.data.Operations[i];m:=o.Machine
    if p.ext.buffered[i] {p.ext.bufferUsed[m]--;p.ext.buffered[i]=false}
    p.ext.arrived[i]=true;p.start[i]=t;p.current[m]=i;p.injection[m]=p.left[i]
    if p.ext.needsShared[i] {if p.ext.owner>=0{panic("Shared resource double owner")};p.ext.owner=i}
}
func (p *opPolicy) extBoundary(t int64) {
    x:=p.ext;p.stopped=t
    for iteration:=0;;iteration++ {
        if iteration>3*len(p.data.Operations)+1 {panic("Nonterminating transfer closure")}
        changed:=false
        for _,i:=range x.order {
            o:=p.data.Operations[i];m:=o.Machine
            if p.start[i]>=0 || p.pending[i]!=0 || o.Release>t {continue}
            if !x.arrived[i] {
                direct:=p.extCanStart(i,t,true)
                if !direct && p.data.BufferCapacity>0 && x.bufferUsed[m]>=p.data.BufferCapacity {continue}
                // Enter buffer or direct handoff, then release predecessor custody.
                if len(o.Predecessors)>0 {p.extRelease(o.Predecessors[0],t)}
                x.arrived[i]=true;changed=true
                if direct {p.extStart(i,t)} else {x.buffered[i]=true;x.bufferUsed[m]++}
            }
            if x.buffered[i] && p.extCanStart(i,t,false) {p.extStart(i,t);changed=true}
        }
        if !changed {break}
    }
    active:=false;future:=false
    for m:=range p.current {
        rate:=int64(100)
        if len(p.data.BaseSpeed)>0 {rate=p.data.BaseSpeed[m]}
        for _,v:=range p.scenario.Speeds {if int(v[0])==m && v[1]<=t && t<v[2] {rate=v[3]}}
        if !p.available(m,t) {rate=0}
        i:=p.current[m]
        if i>=0 && p.left[i]>0 {
            active=true
            if x.needsShared[i] && !p.sharedAvailable(t) {rate=0}
        }
        p.runtime.ResourceMultipliers[fmt.Sprintf("M%d",m)][0]=float64(rate)
        if p.data.BufferCapacity>0 && x.bufferUsed[m]>p.data.BufferCapacity {panic("Buffer overflow")}
    }
    if !active && p.completed<len(p.data.Operations) {
        for i,o:=range p.data.Operations {if p.start[i]<0 && (o.Planned>t || o.Release>t) {future=true}}
        for _,v:=range p.scenario.Failures {if v[2]>t{future=true}}
        for _,v:=range p.scenario.SharedFailures {if v[1]>t{future=true}}
        x.deadlock=!future
    }
}
func (p *opPolicy) extEndStep()error {
    if p.ext.deadlock {return opDeadlocked}
    completed:=make([]int,0,len(p.current))
    for _,i:=range p.current {
        if i>=0 && p.left[i]==0 && p.finish[i]<0 {
            p.finish[i]=p.stepEnd;completed=append(completed,i)
        }
    }
    for _,i:=range completed {
        if p.ext.needsShared[i] {
            if p.ext.owner!=i {panic("Lost shared resource owner")};p.ext.owner=-1
        }
        for _,j:=range p.successors[i] {p.pending[j]--;p.updates++}
        if len(p.successors[i])==0 || p.data.BufferCapacity==0 {p.extRelease(i,p.stepEnd)}
    }
    p.completed+=len(completed);p.stopped=p.stepEnd
    if p.diagnostic && p.completed==len(p.data.Operations) {return opAllDone}
    return nil
}
func (p *opPolicy) extOutput(row map[string]any) {
    row["engine"]="tsfg-ext";row["algorithm_id"]="tsfg-op-ext-grid-1"
    remaining:=make([]float64,len(p.left))
    for i,v:=range p.left {remaining[i]=float64(v)/100}
    row["remaining"]=remaining;row["remaining_work_units"]=p.left;row["work_scale"]=100
    row["machine_release"]=p.ext.releasedAt;row["buffer_counts"]=p.ext.bufferUsed;row["shared_owner"]=p.ext.owner
    states:=row["state"].([]string)
    for i:=range states {
        if p.finish[i]>=0 && p.ext.releasedAt[i]<0 {states[i]="BLOCKED_AFTER_PROCESSING"}
        if p.start[i]>=0 && p.finish[i]<0 && p.ext.needsShared[i] && !p.sharedAvailable(p.stopped) {states[i]="SUSPENDED"}
    }
    if p.ext.deadlock {row["run_status"]="DEADLOCK"}
}
