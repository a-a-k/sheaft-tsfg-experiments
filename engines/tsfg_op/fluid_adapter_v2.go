// Public fluid coupling policy. The unchanged private S1 kernel serves all work.
package main

import (
    "encoding/json"
    "errors"
    "fmt"
    "math"
    "os"
    "strconv"
)

type pfCase struct {
    ID string `json:"id"`
    Volumes []float64 `json:"volumes"`
    Rates []float64 `json:"rates"`
    SinkRate float64 `json:"sink_rate"`
    Capacity *float64 `json:"capacity"`
    SinkDown [][2]float64 `json:"sink_down"`
}
type pfPolicy struct {
    data pfCase
    q,peak,injection,refs,done []float64
    multipliers [][]float64
    index map[string]int
    step,before,t,total,produced,integral,balance float64
    minStep,maxStep float64
    steps int
}
func(p *pfPolicy) BeginStep(_ int,t,dt float64) {
    internalStep:=dt;t/=32;dt/=32
    if p.steps==0 || dt<p.minStep {p.minStep=dt};p.maxStep=math.Max(p.maxStep,dt)
    p.t=t+dt;p.step=dt;p.before=0;p.steps++
    for i:=range p.q {p.before+=p.q[i];p.done[i]=0}
    last:=len(p.q)-1;rate:=p.data.SinkRate
    for _,interval:=range p.data.SinkDown {if t>=interval[0]-1e-10 && t<interval[1]-1e-10 {rate=0}}
    output:=math.Min(p.q[last],rate*dt)
    sum:=0.0
    for i,r:=range p.data.Rates {p.refs[i]=math.Min(p.q[i],r*dt);sum+=p.refs[i]}
    factor:=1.0
    if p.data.Capacity!=nil && sum>0 {factor=math.Min(1,math.Max(0,*p.data.Capacity-p.q[last]+output)/sum)}
    for i:=range p.data.Rates {p.refs[i]*=factor}
    p.refs[last]=output
    for i,v:=range p.refs {p.multipliers[i][0]=v/internalStep*aggKernelVolumeScale}
}
func(p *pfPolicy) AvailableInputItems()float64{return 0}
func(p *pfPolicy) HandlesNodeOutput(id string)bool{_,ok:=p.index[id];return ok}
func(p *pfPolicy) PullNodeInput(id string,_ float64)float64 {
    i,ok:=p.index[id];if !ok{return 0};amount:=p.injection[i];p.injection[i]=0
    return amount*aggKernelVolumeScale
}
func(p *pfPolicy) RouteNodeOutput(id string,processed,_ float64)(float64,float64) {
    p.done[p.index[id]]+=processed/aggKernelVolumeScale
    return 0,processed
}
func(p *pfPolicy) EndStep(_,_,_ float64)error {
    last:=len(p.q)-1;incoming:=0.0;after:=0.0
    for i,v:=range p.done {p.q[i]-=v;if i<last{incoming+=v}}
    p.q[last]+=incoming;p.injection[last]+=incoming;p.produced+=p.done[last]
    for i,v:=range p.q {
        if v< -1e-8 {return errors.New("PF negative queue")}
        if math.Abs(v)<1e-9 {p.q[i]=0};after+=p.q[i]
        p.peak[i]=math.Max(p.peak[i],p.q[i])
    }
    p.balance=math.Max(p.balance,math.Abs(p.total-after-p.produced))
    if p.balance>1e-7 || (p.data.Capacity!=nil && p.q[last]>*p.data.Capacity+1e-8) {return errors.New("PF balance/capacity failure")}
    p.integral+=(p.before+after)*p.step/2
    if after<1e-8 {p.produced=p.total;return opAllDone}
    return nil
}
func pfSolve(data pfCase,horizon float64)(map[string]any,error) {
    n:=len(data.Volumes)+1
    p:=&pfPolicy{data:data,q:make([]float64,n),peak:make([]float64,n),injection:make([]float64,n),
        refs:make([]float64,n),done:make([]float64,n),multipliers:make([][]float64,n),index:map[string]int{}}
    copy(p.q,data.Volumes);copy(p.peak,p.q);copy(p.injection,p.q)
    for _,v:=range data.Volumes {p.total+=v}
    runtime:=&graphFlowRuntime{IntervalS:1,ResourceMultipliers:map[string][]float64{}}
    facility:=facilityFile{};resources:=[]resource{}
    for i:=0;i<=n;i++ {
        id:=fmt.Sprintf("PF%d",i)
        facility.Nodes=append(facility.Nodes,facilityNode{ID:id,Kind:"workstation",FlowRole:"main",Replicas:1,
            Buffer:facilityBuffer{CapacityItems:(p.total+1)*aggKernelVolumeScale}})
        resources=append(resources,resource{ID:id,Capacity:3600,Order:2*i})
        if i<n {
            p.index[id]=i;runtime.ResourceMultipliers[id]=[]float64{0};p.multipliers[i]=runtime.ResourceMultipliers[id]
            edge,next:=fmt.Sprintf("PFE%d",i),fmt.Sprintf("PF%d",i+1)
            facility.Edges=append(facility.Edges,facilityEdge{ID:edge,From:id,To:next,FlowRole:"main"})
            resources=append(resources,resource{ID:edge,Capacity:0,Order:2*i+1,From:id,To:next})
        }
    }
    // S1 enforces a minimum internal time step. A power-of-two unit change
    // expresses 0.005 physical seconds as 0.16 internal units, without changing
    // the original kernel or the frozen physical diagnostic contract.
    experiment:=experimentFile{HorizonS:horizon*32,DtS:0.005*32,MeasurementWindows:[]float64{horizon*32}}
    _,err:=runGraphLocalTemporalCapacityModelWithRuntimeAndSink(facility,experiment,resources,arithmetic{},runtime,"",p)
    if err!=nil && !errors.Is(err,opAllDone){return nil,err}
    complete:=errors.Is(err,opAllDone);var cmax,bound any
    if complete {cmax=p.t} else {bound=horizon}
    return map[string]any{"id":data.ID,"produced":p.produced,"queue_at_D":p.q,"queue_max":p.peak,
        "wip_integral":p.integral,"completion_known":complete,"mission_success":complete,"cmax":cmax,
        "completion_lower_bound":bound,"material_balance_max_abs":p.balance,"steps":p.steps,
        "delta":0.005,"actual_min_step":p.minStep,"actual_max_step":p.maxStep,"kernel_time_scale":32,
        "algorithm":"PF-S1-grid-v2.2","individual_operation_times":"UNSUPPORTED"},nil
}
func init() {
    if os.Getenv("TSFG_PF_DRIVER")!="true" {return}
    if len(os.Args)!=4 {fmt.Fprintln(os.Stderr,"pf input horizon output");os.Exit(2)}
    raw,err:=os.ReadFile(os.Args[1]);if err!=nil{fmt.Fprintln(os.Stderr,err);os.Exit(2)}
    var data pfCase
    if err=json.Unmarshal(raw,&data);err!=nil{fmt.Fprintln(os.Stderr,err);os.Exit(2)}
    horizon,err:=strconv.ParseFloat(os.Args[2],64);if err!=nil{os.Exit(2)}
    result,err:=pfSolve(data,horizon);if err!=nil{fmt.Fprintln(os.Stderr,err);os.Exit(2)}
    encoded,err:=json.Marshal(result);if err!=nil{os.Exit(2)}
    if err=os.WriteFile(os.Args[3],encoded,0600);err!=nil{os.Exit(2)}
    os.Exit(0)
}
