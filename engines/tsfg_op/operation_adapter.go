// Operation policy over the unchanged S1 graph-flow kernel. This file is new;
// the private upstream package is fetched separately at its pinned commit.
package main

import (
    "encoding/json"
    "errors"
    "fmt"
    "math"
    "os"
    "sort"
    "strconv"
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
}
type opDataset struct {
    Operations []opInput `json:"operations"`
    Queues [][]int `json:"queues"`
    Jobs []struct { Final int `json:"final_operation"` } `json:"jobs"`
}
type opScenario struct {
    ID string `json:"id"`
    Failures [][3]int64 `json:"failures"`
    Overrides [][2]int64 `json:"work_overrides"`
}
type opPolicy struct {
    data opDataset
    scenario opScenario
    runtime *graphFlowRuntime
    nodeIndex map[string]int
    head, current, pending []int
    successors [][]int
    start, finish, left, injection []int64
    down [][][2]int64
    cursor []int
    stepEnd, stopped int64
    steps, updates, completed int
    diagnostic bool
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
    p.stopped = t
    for m, queue := range p.data.Queues {
        up := p.available(m,t)
        value := 0.0
        if up { value = 1 }
        p.runtime.ResourceMultipliers[fmt.Sprintf("M%d",m)][0] = value
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
    completed := make([]int,0,len(p.current))
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
    if p.diagnostic && p.completed == len(p.data.Operations) { return opAllDone }
    return nil
}

func opSolve(data opDataset, sc opScenario, horizon, delta int64, diagnostic bool) (map[string]any,error) {
    n,m := len(data.Operations),len(data.Queues)
    if n == 0 || m == 0 || horizon < 0 || delta <= 0 { return nil,errors.New("Invalid operation profile dimensions") }
    runtime := &graphFlowRuntime{IntervalS:1, ResourceMultipliers:map[string][]float64{}}
    p := &opPolicy{data:data,scenario:sc,runtime:runtime,nodeIndex:map[string]int{},
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
    p.boundary(0)
    if horizon>0 {
        experiment := experimentFile{HorizonS:float64(horizon),DtS:float64(delta),MeasurementWindows:[]float64{float64(horizon)}}
        _,err := runGraphLocalTemporalCapacityModelWithRuntimeAndSink(facility,experiment,resources,arithmetic{},runtime,"",p)
        if err != nil && !errors.Is(err,opAllDone) { return nil,err }
        if err == nil { p.boundary(horizon) }
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
    return map[string]any{"scenario_id":sc.ID,"engine":"tsfg","mode":mode,"horizon":horizon,
        "stopped":p.stopped,"start":starts,"finish":finishes,"remaining":p.left,"state":states,
        "job_finish":jobs,"mission_success":complete,"completion_known":complete,"cmax":completion,
        "completion_lower_bound":bound,"run_status":"OK",
        "counters":map[string]int{"upstream_steps":p.steps,"dependency_updates":p.updates}},nil
}

func init() {
    if os.Getenv("TSFG_OP_DRIVER")!="true" { return }
    if os.Getenv("GITHUB_ACTIONS")!="true" { fmt.Fprintln(os.Stderr,"Actions only");os.Exit(2) }
    if err:=opCommand();err!=nil { fmt.Fprintln(os.Stderr,err);os.Exit(2) }
    os.Exit(0)
}
func opCommand() error {
    if len(os.Args)!=8 { return errors.New("Expected ENGINE DATA SCENARIOS OUTPUT MODE HORIZON DELTA") }
    if os.Args[1]!="tsfg" || (os.Args[5]!="MISSION" && os.Args[5]!="DIAGNOSTIC") { return errors.New("Invalid engine/mode") }
    horizon,err:=strconv.ParseInt(os.Args[6],10,64);if err!=nil{return err}
    delta,err:=strconv.ParseInt(os.Args[7],10,64);if err!=nil{return err}
    input,err:=os.ReadFile(os.Args[2]);if err!=nil{return err}
    var data opDataset;if err=json.Unmarshal(input,&data);err!=nil{return err}
    input,err=os.ReadFile(os.Args[3]);if err!=nil{return err}
    var scenarios []opScenario;if err=json.Unmarshal(input,&scenarios);err!=nil{return err}
    output,err:=os.Create(os.Args[4]);if err!=nil{return err};defer output.Close()
    encoder:=json.NewEncoder(output)
    for _,sc:=range scenarios {
        begin:=time.Now()
        row,err:=opSolve(data,sc,horizon,delta,os.Args[5]=="DIAGNOSTIC");if err!=nil{return err}
        row["kernel_elapsed_s"]=time.Since(begin).Seconds()
        if err=encoder.Encode(row);err!=nil{return err}
    }
    return nil
}
