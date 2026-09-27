// Operation policy over the unchanged S1 graph-flow kernel. This file is new;
// the private upstream package is fetched separately at its pinned commit.
package main

import (
    "bufio"
    "encoding/binary"
    "encoding/json"
    "errors"
    "fmt"
    "io"
    "math"
    "os"
    "sort"
    "strconv"
    "syscall"
    "time"
)

type opInput struct {
    ID int `json:"id"`
    Job int `json:"job"`
    Machine int `json:"machine"`
    Work int64 `json:"work"`
    Planned int64 `json:"planned_start"`
    Release int64 `json:"release"`
    Predecessors []int `json:"predecessors"`
    ResourcePool *int `json:"resource_pool"`
}
type opDataset struct {
    Operations []opInput `json:"operations"`
    Queues [][]int `json:"queues"`
    Jobs []struct { Final int `json:"final_operation"` } `json:"jobs"`
    Extended bool `json:"extended_profile"`
    BufferCapacity int `json:"buffer_capacity"`
    SharedOperations []int `json:"shared_operations"`
    BaseSpeed []int64 `json:"base_speed_percent"`
    Semantics string `json:"semantics"`
    BufferCapacities []json.RawMessage `json:"buffer_capacities"`
    ResourcePools []struct { ID int `json:"id"`; Capacity int `json:"capacity"` } `json:"resource_pools"`
}

func opReadDataset(path string) (opDataset,error) {
    var data opDataset
    file,err:=os.Open(path);if err!=nil{return data,err};defer file.Close()
    reader:=bufio.NewReader(file)
    first,err:=reader.Peek(1);if err!=nil{return data,err}
    if first[0]!='T' { err=json.NewDecoder(reader).Decode(&data);return data,err }
    magic:=make([]byte,8);if _,err=io.ReadFull(reader,magic);err!=nil{return data,err}
    grouped:=string(magic)=="TSFGGRP1"
    if !grouped && string(magic)!="TSFGBIN1" {return data,errors.New("Invalid binary version")}
    read32:=func()(int,error){var v uint32;e:=binary.Read(reader,binary.LittleEndian,&v);return int(v),e}
    read64:=func()(int64,error){var v int64;e:=binary.Read(reader,binary.LittleEndian,&v);return v,e}
    n,err:=read32();if err!=nil{return data,err}
    jobs,err:=read32();if err!=nil{return data,err}
    machines,err:=read32();if err!=nil{return data,err}
    if n<=0 || n>10000000 || jobs<=0 || jobs>n || machines<=0 || machines>100000 {return data,errors.New("Invalid binary dimensions")}
    var types []int64
    if grouped {
        count,e:=read32();if e!=nil{return data,e};if count<=0 || count>n{return data,errors.New("Invalid type count")}
        types=make([]int64,count)
        for k:=range types {if types[k],err=read64();err!=nil{return data,err};if types[k]<=0{return data,errors.New("Invalid type work")}}
    }
    data.Operations=make([]opInput,n);data.Queues=make([][]int,machines)
    data.Jobs=make([]struct{Final int `json:"final_operation"`},jobs)
    for i:=range data.Operations {
        o:=&data.Operations[i];o.ID=i
        if o.Job,err=read32();err!=nil{return data,err}
        if o.Machine,err=read32();err!=nil{return data,err}
        if grouped {
            index,e:=read32();if e!=nil{return data,e};if index<0 || index>=len(types){return data,errors.New("Invalid type index")};o.Work=types[index]
        } else {if o.Work,err=read64();err!=nil{return data,err}}
        if o.Planned,err=read64();err!=nil{return data,err}
        if o.Release,err=read64();err!=nil{return data,err}
        count,e:=read32();if e!=nil{return data,e}
        if o.Job<0 || o.Job>=jobs || o.Machine<0 || o.Machine>=machines || o.Work<=0 || o.Planned<0 || o.Release<0 || count>n {
            return data,errors.New("Invalid binary operation")
        }
        o.Predecessors=make([]int,count)
        for k:=range o.Predecessors {if o.Predecessors[k],err=read32();err!=nil{return data,err}}
    }
    for m:=range data.Queues {
        count,e:=read32();if e!=nil{return data,e};if count>n{return data,errors.New("Invalid queue size")}
        data.Queues[m]=make([]int,count)
        for k:=range data.Queues[m] {if data.Queues[m][k],err=read32();err!=nil{return data,err}}
    }
    for j:=range data.Jobs {
        if data.Jobs[j].Final,err=read32();err!=nil{return data,err}
        i:=data.Jobs[j].Final
        if i<0 || i>=n || data.Operations[i].Job!=j{return data,errors.New("Invalid job terminal")}
    }
    if _,err=reader.ReadByte();err!=io.EOF{return data,errors.New("Trailing binary data")}
    return data,nil
}
type opScenario struct {
    ID string `json:"id"`
    Failures [][3]int64 `json:"failures"`
    Overrides [][2]int64 `json:"work_overrides"`
    Speeds [][4]int64 `json:"speed_intervals"`
    SharedFailures [][2]int64 `json:"shared_failures"`
    ResourceFailures [][4]int64 `json:"resource_failures"`
}
type opPolicy struct {
    data opDataset
    scenario opScenario
    runtime *graphFlowRuntime
    nodeIndex map[string]int
    multiplierRefs [][]float64
    completionScratch []int
    head, current, pending []int
    successors [][]int
    start, finish, left, injection []int64
    down [][][2]int64
    cursor []int
    stepEnd, stopped int64
    steps, updates, completed int
    diagnostic bool
    ext *opExtension
    pbr *pbrExtension
}
var opAllDone = errors.New("operation profile completed")

func opExact(x float64) int64 {
    n := int64(math.Round(x))
    if math.Abs(x-float64(n)) > 1e-8 { panic("Nonintegral upstream service") }
    return n
}
func (p *opPolicy) available(m int, t int64) bool {
    for p.cursor[m] < len(p.down[m]) && p.down[m][p.cursor[m]][1] <= t { p.cursor[m]++ }
    return p.cursor[m] == len(p.down[m]) || t < p.down[m][p.cursor[m]][0]
}
func (p *opPolicy) boundary(t int64) {
    if p.pbr!=nil {p.pbrBoundary(t);return}
    if p.ext!=nil {p.extBoundary(t);return}
    p.stopped = t
    for m, queue := range p.data.Queues {
        up := p.available(m,t)
        value := 0.0
        if up { value = 1 }
        p.multiplierRefs[m][0] = value
        if !up || p.current[m] >= 0 || p.head[m] == len(queue) { continue }
        i := queue[p.head[m]]
        o := p.data.Operations[i]
        if p.pending[i] != 0 || o.Planned > t || o.Release > t { continue }
        p.current[m] = i
        p.start[i] = t
        p.injection[m] = p.left[i]
    }
}
func (p *opPolicy) BeginStep(_ int, t, step float64) {
    p.boundary(opExact(t))
    p.stepEnd = opExact(t+step)
    if p.pbr!=nil {p.pbrMetrics(opExact(t),p.stepEnd)}
    p.steps++
}
func (p *opPolicy) AvailableInputItems() float64 { return 0 }
func (p *opPolicy) HandlesNodeOutput(id string) bool { _, ok := p.nodeIndex[id]; return ok }
func (p *opPolicy) PullNodeInput(id string, available float64) float64 {
    m, ok := p.nodeIndex[id]
    if !ok { return 0 }
    amount := p.injection[m]
    if float64(amount) > available { panic("Unexpected source admission constraint") }
    p.injection[m] = 0
    return float64(amount)
}
func (p *opPolicy) RouteNodeOutput(id string, processed, _ float64) (float64,float64) {
    m := p.nodeIndex[id]
    amount := opExact(processed)
    if amount != 0 {
        i := p.current[m]
        if i < 0 || amount > p.left[i] { panic("Invalid upstream service accounting") }
        p.left[i] -= amount
    }
    return 0,processed
}
func (p *opPolicy) EndStep(_,_,_ float64) error {
    if p.pbr!=nil {return p.pbrEndStep()}
    if p.ext!=nil {return p.extEndStep()}
    completed := p.completionScratch[:0]
    for m,i := range p.current {
        if i >= 0 && p.left[i] == 0 {
            p.finish[i] = p.stepEnd
            p.current[m] = -1
            p.head[m]++
            completed = append(completed,i)
        }
    }
    for _,i := range completed {
        for _,j := range p.successors[i] { p.pending[j]--; p.updates++ }
    }
    p.completed += len(completed)
    p.stopped = p.stepEnd
    if p.completed == len(p.data.Operations) { return opAllDone }
    return nil
}

func opSolve(data opDataset, sc opScenario, horizon, delta int64, diagnostic bool) (map[string]any,error) {
    prepareStarted:=time.Now()
    n,m := len(data.Operations),len(data.Queues)
    if n == 0 || m == 0 || horizon < 0 || delta <= 0 { return nil,errors.New("Invalid operation profile dimensions") }
    runtime := &graphFlowRuntime{IntervalS:1, ResourceMultipliers:map[string][]float64{}}
    p := &opPolicy{data:data,scenario:sc,runtime:runtime,nodeIndex:map[string]int{},
        multiplierRefs:make([][]float64,m),completionScratch:make([]int,0,m),
        head:make([]int,m),current:make([]int,m),pending:make([]int,n),successors:make([][]int,n),
        start:make([]int64,n),finish:make([]int64,n),left:make([]int64,n),injection:make([]int64,m),
        down:make([][][2]int64,m),cursor:make([]int,m),diagnostic:diagnostic}
    for i,o := range data.Operations {
        if o.ID != i || o.Machine < 0 || o.Machine >= m || o.Work <= 0 || o.Planned < 0 || o.Release < 0 {
            return nil,errors.New("Invalid operation")
        }
        p.start[i],p.finish[i],p.left[i] = -1,-1,o.Work
        p.pending[i] = len(o.Predecessors)
        for _,prev := range o.Predecessors {
            if prev < 0 || prev >= n || prev == i { return nil,errors.New("Invalid predecessor") }
            p.successors[prev] = append(p.successors[prev],i)
        }
    }
    for _,o := range sc.Overrides {
        if o[0] < 0 || o[0] >= int64(n) || o[1] <= 0 { return nil,errors.New("Invalid work override") }
        p.left[o[0]] = o[1]
    }
    if data.Semantics=="PBR-EXACT-v2.2" {
        if delta!=5 || horizon%5!=0 {return nil,errors.New("PBR-EXACT-v2.2 requires delta=5 and aligned horizon")}
        if err:=p.initPBR();err!=nil{return nil,err}
    } else if data.Extended {
        for _,v:=range sc.Speeds {if v[1]%delta!=0 || v[2]%delta!=0{return nil,errors.New("Unaligned speed interval")}}
        for _,v:=range sc.SharedFailures {if v[0]%delta!=0 || v[1]%delta!=0{return nil,errors.New("Unaligned shared failure")}}
        if err:=p.initExtension();err!=nil{return nil,err}
    }
    for i,o := range data.Operations {
        if p.left[i]%delta != 0 || o.Planned%delta != 0 || o.Release%delta != 0 { return nil,errors.New("Unaligned operation") }
    }
    for _,f := range sc.Failures {
        if f[0] < 0 || f[0] >= int64(m) || f[1] < 0 || f[2] <= f[1] || f[1]%delta != 0 || f[2]%delta != 0 {
            return nil,errors.New("Invalid failure")
        }
        p.down[f[0]] = append(p.down[f[0]],[2]int64{f[1],f[2]})
    }
    for j := range p.down {
        items := p.down[j]
        sort.Slice(items,func(a,b int) bool { return items[a][0] < items[b][0] })
        merged := make([][2]int64,0,len(items))
        for _,v := range items {
            if len(merged)>0 && v[0]<=merged[len(merged)-1][1] {
                if v[1]>merged[len(merged)-1][1] { merged[len(merged)-1][1] = v[1] }
            } else { merged=append(merged,v) }
        }
        p.down[j]=merged
    }
    seen := make([]bool,n)
    var buffer int64 = 1
    for _,work := range p.left { buffer += work }
    if buffer > 1<<50 || horizon > 1<<50 { return nil,errors.New("Exact integer range exceeded") }
    facility := facilityFile{}
    resources := []resource{}
    for j:=0;j<=m;j++ {
        id := fmt.Sprintf("M%d",j)
        facility.Nodes = append(facility.Nodes,facilityNode{ID:id,Kind:"workstation",FlowRole:"main",Replicas:1,
            Buffer:facilityBuffer{CapacityItems:float64(buffer)}})
        resources = append(resources,resource{ID:id,Capacity:3600,Order:j*2})
        if j<m {
            p.current[j] = -1
            p.nodeIndex[id] = j
            runtime.ResourceMultipliers[id] = []float64{1}
            p.multiplierRefs[j] = runtime.ResourceMultipliers[id]
            for _,i := range data.Queues[j] {
                if i<0 || i>=n || seen[i] || data.Operations[i].Machine!=j { return nil,errors.New("Invalid machine queue") }
                seen[i]=true
            }
            edge := fmt.Sprintf("E%d",j)
            next := fmt.Sprintf("M%d",j+1)
            facility.Edges = append(facility.Edges,facilityEdge{ID:edge,From:id,To:next,FlowRole:"main"})
            resources = append(resources,resource{ID:edge,Capacity:0,Order:j*2+1,From:id,To:next})
        }
    }
    for _,found := range seen { if !found { return nil,errors.New("Missing operation in queues") } }
    prepareSeconds:=time.Since(prepareStarted).Seconds()
    upstreamStarted:=time.Now()
    p.boundary(0)
    if horizon>0 {
        experiment := experimentFile{HorizonS:float64(horizon),DtS:float64(delta),MeasurementWindows:[]float64{float64(horizon)}}
        _,err := runGraphLocalTemporalCapacityModelWithRuntimeAndSink(facility,experiment,resources,arithmetic{},runtime,"",p)
        if err != nil && !errors.Is(err,opAllDone) && !errors.Is(err,opDeadlocked) { return nil,err }
        if errors.Is(err,opAllDone) && !diagnostic {p.stopped=horizon}
        if err == nil { p.boundary(horizon) }
    }
    upstreamSeconds:=time.Since(upstreamStarted).Seconds()
    resultStarted:=time.Now()
    if os.Getenv("TSFG_OUTPUT_PROFILE")=="AGG-MISSION" {
        row:=opObserve(p,horizon)
        if diagnostic {row["mode"]="DIAGNOSTIC"}
        return row,nil
    }
    starts,finishes := make([]any,n),make([]any,n)
    states := make([]string,n)
    var cmax int64
    for i,o := range data.Operations {
        if p.start[i]>=0 { starts[i]=p.start[i] }
        states[i]="NOT_STARTED"
        if p.finish[i]>=0 {
            finishes[i]=p.finish[i];states[i]="DONE"
            if p.finish[i]>cmax { cmax=p.finish[i] }
        } else if p.start[i]>=0 {
            states[i]="PROCESSING"
            if !p.available(o.Machine,p.stopped) { states[i]="SUSPENDED" }
        }
    }
    jobs:=make([]any,len(data.Jobs))
    for i,j := range data.Jobs { jobs[i]=finishes[j.Final] }
    var completion,bound any
    complete:=p.completed==n
    if complete { completion=cmax } else { bound=horizon }
    mode:="MISSION"
    if diagnostic { mode="DIAGNOSTIC" }
    row:=map[string]any{"scenario_id":sc.ID,"engine":"tsfg","mode":mode,"horizon":horizon,
        "stopped":p.stopped,"start":starts,"finish":finishes,"remaining":p.left,"state":states,
        "job_finish":jobs,"mission_success":complete,"completion_known":complete,"cmax":completion,
        "completion_lower_bound":bound,"run_status":"OK",
        "counters":map[string]int{"upstream_steps":p.steps,"dependency_updates":p.updates},
        "algorithm_id":"tsfg-op-grid-s1-cached-v1"}
    if p.ext!=nil {p.extOutput(row)}
    if p.pbr!=nil {p.pbrOutput(row)}
    row["phase_seconds"]=map[string]float64{"adapter_prepare":prepareSeconds,
        "upstream_with_policy":upstreamSeconds,"result_prepare":time.Since(resultStarted).Seconds()}
    return row,nil
}

func init() {
    if os.Getenv("TSFG_OP_DRIVER")!="true" { return }
    if os.Getenv("GITHUB_ACTIONS")!="true" { fmt.Fprintln(os.Stderr,"Actions only");os.Exit(2) }
    if err:=opCommand();err!=nil { fmt.Fprintln(os.Stderr,err);os.Exit(2) }
    os.Exit(0)
}
func opCommand() error {
    stopProfile,err:=opAuditProfile();if err!=nil{return err};defer stopProfile()
    t0:=time.Now()
    if len(os.Args)!=8 { return errors.New("Expected ENGINE DATA SCENARIOS OUTPUT MODE HORIZON DELTA") }
    if (os.Args[1]!="tsfg" && os.Args[1]!="tsfg-ext" && os.Args[1]!="tsfg-agg") || (os.Args[5]!="MISSION" && os.Args[5]!="DIAGNOSTIC") { return errors.New("Invalid engine/mode") }
    horizon,err:=strconv.ParseInt(os.Args[6],10,64);if err!=nil{return err}
    delta,err:=strconv.ParseInt(os.Args[7],10,64);if err!=nil{return err}
    data,err:=opReadDataset(os.Args[2]);if err!=nil{return err}
    if os.Args[1]=="tsfg-ext" {data.Extended=true}
    input,err:=os.ReadFile(os.Args[3]);if err!=nil{return err}
    var scenarios []opScenario;if err=json.Unmarshal(input,&scenarios);err!=nil{return err}
    t1:=time.Now()
    output,err:=os.Create(os.Args[4]);if err!=nil{return err};defer output.Close()
    encoder:=json.NewEncoder(output)
    prefixes:=map[string]float64{}
    count:=0
    for _,sc:=range scenarios {
        begin:=time.Now()
        var row map[string]any
        if os.Args[1]=="tsfg-agg" {row,err=aggSolve(data,sc,horizon,delta,os.Args[5]=="DIAGNOSTIC")} else {
            row,err=opSolve(data,sc,horizon,delta,os.Args[5]=="DIAGNOSTIC")
        }
        if err!=nil{return err}
        row["kernel_elapsed_s"]=time.Since(begin).Seconds()
        if err=encoder.Encode(row);err!=nil{return err}
        count++
        if count==1 || count==10 || count==100 || count==1000 {prefixes[strconv.Itoa(count)]=time.Since(t1).Seconds()}
        progress:=map[string]any{"scenarios_completed":count,"T_import_s":t1.Sub(t0).Seconds(),
            "T_build_s":0,"T_batch_elapsed_s":time.Since(t1).Seconds(),"prefix_batch_s":prefixes}
        encoded,e:=json.Marshal(progress);if e!=nil{return e}
        path:=os.Args[4]+".progress.json"
        if e=os.WriteFile(path+".tmp",encoded,0600);e!=nil{return e}
        if e=os.Rename(path+".tmp",path);e!=nil{return e}
    }
    if err=output.Close();err!=nil{return err}
    batch:=time.Since(t1).Seconds()
    var usage syscall.Rusage
    if err=syscall.Getrusage(syscall.RUSAGE_SELF,&usage);err!=nil{return err}
    meta:=map[string]any{"engine":"tsfg","scenarios_completed":count,"T_import_s":t1.Sub(t0).Seconds(),
        "T_build_s":0,"T_batch_with_output_s":batch,"rss_peak_bytes":usage.Maxrss*1024,
        "cpu_s":float64(usage.Utime.Sec+usage.Stime.Sec)+float64(usage.Utime.Usec+usage.Stime.Usec)/1e6,
        "prefix_batch_s":prefixes,"output_profile":"SCHEDULE",
        "construction_policy":"original graph and policy rebuilt per scenario; included in batch"}
    if os.Args[1]=="tsfg-agg" || os.Getenv("TSFG_OUTPUT_PROFILE")=="AGG-MISSION" {meta["output_profile"]="AGG-MISSION"}
    meta["engine"]=os.Args[1]
    if data.Semantics=="PBR-EXACT-v2.2" {peak,e:=pbrVmHWM();if e!=nil{return e};meta["VmHWM_bytes"]=peak;meta["memory_counter"]="/proc/self/status VmHWM after exec"}
    encoded,err:=json.MarshalIndent(meta,"","  ");if err!=nil{return err}
    if err=os.WriteFile(os.Args[4]+".meta.json",encoded,0600);err!=nil{return err}
    return nil
}
