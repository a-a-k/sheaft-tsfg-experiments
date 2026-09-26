// Public G2 coupling policy and common-output observers over unchanged S1.
package main

import (
    "errors"
    "fmt"
    "math"
    "sort"
)

// S1 discards external injections <= its epsilon (1e-6 internal items).
// Exact power-of-two rescaling keeps that threshold below 1e-12 of one job.
// All public state and metrics remain in jobs; the original kernel is unchanged.
const aggKernelVolumeScale = 1048576.0

func opObserve(p *opPolicy,horizon int64) map[string]any {
    type event struct{t int64; change int}
    events:=make([][]event,len(p.data.Queues))
    for i,o:=range p.data.Operations {
        ready,known:=o.Release,true
        for _,prev:=range o.Predecessors {if p.finish[prev]<0 {known=false} else if p.finish[prev]>ready {ready=p.finish[prev]}}
        if !known || ready>horizon || (p.start[i]>=0 && p.start[i]<=ready) {continue}
        events[o.Machine]=append(events[o.Machine],event{ready,1})
        if p.start[i]>=0 && p.start[i]<=horizon {events[o.Machine]=append(events[o.Machine],event{p.start[i],-1})}
    }
    at,peak:=make([]int,len(events)),make([]int,len(events))
    for m,e:=range events {
        sort.Slice(e,func(i,j int)bool{return e[i].t<e[j].t})
        value:=0
        for i:=0;i<len(e); {
            t:=e[i].t
            for i<len(e) && e[i].t==t {value+=e[i].change;i++}
            if value>peak[m] {peak[m]=value}
        }
        at[m]=value
    }
    produced,released:=0,0
    integral:=0.0
    var cmax int64
    for _,j:=range p.data.Jobs {
        release,finish:=p.data.Operations[j.Final].Release,p.finish[j.Final]
        if release<=horizon {released++}
        if finish>=0 && finish<=horizon {produced++;if finish>cmax{cmax=finish}}
        end:=finish;if end<0 || end>horizon{end=horizon}
        if end>release {integral+=float64(end-release)}
    }
    complete:=produced==len(p.data.Jobs)
    var completion,bound any
    if complete {completion=cmax} else {bound=horizon}
    return map[string]any{"scenario_id":p.scenario.ID,"engine":"tsfg","mode":"MISSION","horizon":horizon,
        "stopped":p.stopped,"produced":produced,"released":released,"incomplete_jobs":len(p.data.Jobs)-produced,
        "queue_at_D":at,"queue_max":peak,"wip_integral":integral,"mission_success":complete,
        "completion_known":complete,"cmax":completion,"completion_lower_bound":bound,
        "run_status":"OK","output_profile":"AGG-MISSION","algorithm_id":"tsfg-op-grid-s1-cached-v1"}
}

type aggPolicy struct {
    index map[string]int
    refs [][]float64
    share [][]float64
    mean,allocated []float64
    volumes,pending,injection []float64
    groupQueue,groupPeak []float64
    down [][][2]int64
    cursor []int
    releases []int64
    releaseCursor,groups,width,jobs,steps int
    produced,integral,stepWIP,stepLength,maxBalanceError float64
    stepEnd,stopped int64
}
func(a *aggPolicy) boundary(t int64) {
    for a.releaseCursor<len(a.releases) && a.releases[a.releaseCursor]<=t {
        a.pending[0]++;a.releaseCursor++
    }
    for k:=range a.pending {
        a.volumes[k]+=a.pending[k];a.injection[k]+=a.pending[k];a.pending[k]=0
    }
    available:=make([]float64,a.groups)
    for m:=range a.down {
        for a.cursor[m]<len(a.down[m]) && a.down[m][a.cursor[m]][1]<=t {a.cursor[m]++}
        if a.cursor[m]==len(a.down[m]) || t<a.down[m][a.cursor[m]][0] {available[m/a.width]++}
    }
    for k:=range a.mean {
        capacity:=0.0
        for g:=0;g<a.groups;g++ {capacity+=available[g]*a.share[g][k]}
        a.refs[k][0]=capacity/a.mean[k]*aggKernelVolumeScale
    }
    a.observe()
}
func(a *aggPolicy) observe() {
    for g:=range a.groupQueue {a.groupQueue[g]=0}
    total:=a.produced
    for k,v:=range a.volumes {
        volume:=v+a.pending[k]
        total+=volume
        waiting:=math.Max(0,volume-a.allocated[k])
        if a.allocated[k]>0 {
            for g:=0;g<a.groups;g++ {a.groupQueue[g]+=waiting*a.share[g][k]/a.allocated[k]}
        }
    }
    for g,q:=range a.groupQueue {if q>a.groupPeak[g]{a.groupPeak[g]=q}}
    error:=math.Abs(total-float64(a.releaseCursor))
    if error>a.maxBalanceError {a.maxBalanceError=error}
    if error>1e-8*math.Max(1,float64(a.jobs)) {panic("G2 material balance error")}
}
func(a *aggPolicy) BeginStep(_ int,t,step float64) {
    a.boundary(opExact(t));a.stepEnd=opExact(t+step);a.stepLength=step
    a.stepWIP=float64(a.releaseCursor)-a.produced;a.steps++
}
func(a *aggPolicy) AvailableInputItems()float64{return 0}
func(a *aggPolicy) HandlesNodeOutput(id string)bool{_,ok:=a.index[id];return ok}
func(a *aggPolicy) PullNodeInput(id string,available float64)float64 {
    k,ok:=a.index[id];if !ok{return 0}
    amount:=a.injection[k]
    if amount>available/aggKernelVolumeScale+1e-8 {panic("G2 unexpected finite buffer")}
    a.injection[k]=0;return amount*aggKernelVolumeScale
}
func(a *aggPolicy) RouteNodeOutput(id string,processed,_ float64)(float64,float64) {
    kernelProcessed:=processed;processed/=aggKernelVolumeScale
    k:=a.index[id];a.volumes[k]-=processed
    if a.volumes[k] < -1e-8 {panic("G2 negative inventory")}
    if k+1==len(a.mean) {a.produced+=processed} else {a.pending[k+1]+=processed}
    return 0,kernelProcessed
}
func(a *aggPolicy) EndStep(_,_,_ float64)error {
    a.stopped=a.stepEnd
    a.integral+=(a.stepWIP+float64(a.releaseCursor)-a.produced)*a.stepLength/2
    a.observe()
    inventory:=0.0
    for k,v:=range a.volumes {inventory+=math.Max(0,v)+a.pending[k]}
    if a.releaseCursor==a.jobs && inventory<=1e-8 {a.produced=float64(a.jobs);return opAllDone}
    return nil
}

func aggSolve(data opDataset,sc opScenario,horizon,delta int64,diagnostic bool)(map[string]any,error) {
    n,m,jobs:=len(data.Operations),len(data.Queues),len(data.Jobs)
    if n==0 || m==0 || jobs==0 || horizon<0 || delta<=0 || data.Extended {return nil,errors.New("Invalid G2 dimensions/profile")}
    groups:=10;if m<groups {groups=m}
    if m%groups!=0 {return nil,errors.New("G2 requires equal machine groups")}
    routes:=make([][]int,jobs)
    work:=make([]int64,n)
    for i,o:=range data.Operations {
        if o.ID!=i || o.Job<0 || o.Job>=jobs || o.Machine<0 || o.Machine>=m || o.Work<=0 || o.Release%delta!=0 {return nil,errors.New("Invalid G2 operation")}
        routes[o.Job]=append(routes[o.Job],i);work[i]=o.Work
    }
    for _,v:=range sc.Overrides {if v[0]<0 || v[0]>=int64(n) || v[1]<=0{return nil,errors.New("Invalid G2 work override")};work[v[0]]=v[1]}
    stages:=len(routes[0])
    a:=&aggPolicy{index:map[string]int{},refs:make([][]float64,stages),share:make([][]float64,groups),
        mean:make([]float64,stages),allocated:make([]float64,stages),volumes:make([]float64,stages),pending:make([]float64,stages),
        injection:make([]float64,stages),groupQueue:make([]float64,groups),groupPeak:make([]float64,groups),
        down:make([][][2]int64,m),cursor:make([]int,m),groups:groups,width:m/groups,jobs:jobs}
    for g:=range a.share {a.share[g]=make([]float64,stages)}
    for j,route:=range routes {
        if len(route)!=stages || data.Jobs[j].Final!=route[len(route)-1] {return nil,errors.New("G2 requires equal simple routes")}
        release:=data.Operations[route[0]].Release;a.releases=append(a.releases,release)
        for k,i:=range route {
            o:=data.Operations[i]
            if o.Release!=release || (k==0 && len(o.Predecessors)!=0) || (k>0 && (len(o.Predecessors)!=1 || o.Predecessors[0]!=route[k-1])) {return nil,errors.New("G2 assembly/non-chain UNSUPPORTED")}
            a.share[o.Machine/a.width][k]+=float64(work[i]);a.mean[k]+=float64(work[i])
        }
    }
    for k:=range a.mean {a.mean[k]/=float64(jobs)}
    sort.Slice(a.releases,func(i,j int)bool{return a.releases[i]<a.releases[j]})
    for g,row:=range a.share {
        total:=0.0;for _,v:=range row{total+=v}
        if total>0 {for k:=range row {a.share[g][k]/=total;a.allocated[k]+=float64(a.width)*a.share[g][k]}}
    }
    for _,f:=range sc.Failures {
        if f[0]<0 || f[0]>=int64(m) || f[1]<0 || f[2]<=f[1] || f[1]%delta!=0 || f[2]%delta!=0 {return nil,errors.New("Invalid G2 failure")}
        a.down[f[0]]=append(a.down[f[0]],[2]int64{f[1],f[2]})
    }
    for m,row:=range a.down {
        sort.Slice(row,func(i,j int)bool{return row[i][0]<row[j][0]})
        merged:=make([][2]int64,0,len(row))
        for _,v:=range row {
            if len(merged)>0 && v[0]<=merged[len(merged)-1][1] {if v[1]>merged[len(merged)-1][1]{merged[len(merged)-1][1]=v[1]}} else {merged=append(merged,v)}
        }
        a.down[m]=merged
    }
    runtime:=&graphFlowRuntime{IntervalS:1,ResourceMultipliers:map[string][]float64{}}
    facility:=facilityFile{};resources:=[]resource{}
    for k:=0;k<=stages;k++ {
        id:=fmt.Sprintf("G%d",k)
        facility.Nodes=append(facility.Nodes,facilityNode{ID:id,Kind:"workstation",FlowRole:"main",Replicas:1,Buffer:facilityBuffer{CapacityItems:(float64(jobs)+1)*aggKernelVolumeScale}})
        resources=append(resources,resource{ID:id,Capacity:3600,Order:2*k})
        if k<stages {
            a.index[id]=k;runtime.ResourceMultipliers[id]=[]float64{0};a.refs[k]=runtime.ResourceMultipliers[id]
            edge,next:=fmt.Sprintf("GE%d",k),fmt.Sprintf("G%d",k+1)
            facility.Edges=append(facility.Edges,facilityEdge{ID:edge,From:id,To:next,FlowRole:"main"})
            resources=append(resources,resource{ID:edge,Capacity:0,Order:2*k+1,From:id,To:next})
        }
    }
    complete:=false
    if horizon>0 {
        experiment:=experimentFile{HorizonS:float64(horizon),DtS:float64(delta),MeasurementWindows:[]float64{float64(horizon)}}
        _,err:=runGraphLocalTemporalCapacityModelWithRuntimeAndSink(facility,experiment,resources,arithmetic{},runtime,"",a)
        if err!=nil && !errors.Is(err,opAllDone){return nil,err}
        complete=errors.Is(err,opAllDone)
    }
    cmax:=a.stopped
    if !complete {a.boundary(horizon)} else {a.observe()}
    if !diagnostic {a.stopped=horizon}
    at,peak:=make([]float64,m),make([]float64,m)
    for machine:=range at {at[machine]=a.groupQueue[machine/a.width];peak[machine]=a.groupPeak[machine/a.width]}
    produced:=int(math.Floor(a.produced+1e-7));if produced>jobs{produced=jobs}
    var completion,bound any;if complete {completion=cmax} else {bound=horizon}
    mode:="MISSION";if diagnostic{mode="DIAGNOSTIC"}
    return map[string]any{"scenario_id":sc.ID,"engine":"tsfg-agg","mode":mode,"horizon":horizon,"stopped":a.stopped,
        "produced":produced,"fluid_produced":a.produced,"released":a.releaseCursor,"incomplete_jobs":jobs-produced,
        "queue_at_D":at,"queue_max":peak,"wip_integral":a.integral,"mission_success":complete,
        "completion_known":complete,"cmax":completion,"completion_lower_bound":bound,"run_status":"OK",
        "output_profile":"AGG-MISSION","algorithm_id":"tsfg-g2-fluid-s1-v2","material_balance_max_abs":a.maxBalanceError,
        "kernel_volume_scale":aggKernelVolumeScale,
        "counters":map[string]int{"upstream_steps":a.steps,"stages":stages,"individual_states":0}},nil
}
