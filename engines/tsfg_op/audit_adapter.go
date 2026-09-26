// Optional audit hooks. Profiles and source inputs remain private to the runner.
package main

import (
    "encoding/json"
    "fmt"
    "os"
    "path/filepath"
    "runtime/pprof"
    "time"
)

func opAuditProfile()(func(),error) {
    path:=os.Getenv("TSFG_CPU_PROFILE")
    if path=="" {return func(){},nil}
    file,err:=os.Create(path);if err!=nil{return nil,err}
    if err=pprof.StartCPUProfile(file);err!=nil {file.Close();return nil,err}
    return func(){pprof.StopCPUProfile();file.Close()},nil
}

func init() {
    if os.Getenv("TSFG_REPLAY_OZON")!="true" {return}
    if os.Getenv("GITHUB_ACTIONS")!="true" {fmt.Fprintln(os.Stderr,"Actions only");os.Exit(2)}
    if err:=opAuditOriginal();err!=nil {fmt.Fprintln(os.Stderr,"Original replay failed");os.Exit(2)}
    os.Exit(0)
}
func opAuditOriginal()error {
    stop,err:=opAuditProfile();if err!=nil{return err};defer stop()
    base:=".private/upstream/contracts/examples/baseline"
    facility,policy,experiment,err:=readScenarioInputs(filepath.Join(base,"facility.json"),filepath.Join(base,"policy.json"),filepath.Join(base,"experiment.json"))
    if err!=nil{return err}
    experiment=applyConvergenceOverrides(experiment,86400,3600,1,0,0)
    experiment.DtS=5
    if err=validateScenarioInputs(facility,policy,experiment);err!=nil{return err}
    start:=time.Now()
    result,err:=simulate(facility,policy,experiment);if err!=nil{return err}
    elapsed:=time.Since(start).Seconds()
    metrics:=map[string]float64{}
    for _,name:=range []string{"sorted_items_per_hour","dispatched_items_per_hour","physical_wip_change_items_per_hour","graph_local_material_balance_error_items"} {
        metrics[name]=convergenceResultMetric(result,name)
    }
    summary:=map[string]any{"case":"original healthy_100k convergence workload","horizon_s":86400,"delta_s":5,
        "replications":1,"simulation_wall_s":elapsed,"profile_enabled":os.Getenv("TSFG_CPU_PROFILE")!="",
        "workload_fingerprint":convergenceWorkloadFingerprint(facility,policy,experiment),"metrics":metrics,
        "scope":"Replay of original workload, not a TSFG/DES speedup comparison"}
    encoded,err:=json.MarshalIndent(summary,"","  ");if err!=nil{return err}
    return os.WriteFile(os.Getenv("TSFG_REPLAY_OUTPUT"),encoded,0600)
}
