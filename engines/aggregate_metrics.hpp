#pragma once
#include "model.hpp"

// Observers only: independent of any transition engine. Integral units job*tick.
inline json aggregate_metrics(const Instance& in,const Result& r,Tick horizon) {
    std::vector<std::vector<std::pair<Tick,int>>> events(in.queues.size());
    std::vector<int> at(in.queues.size()),peak(in.queues.size());
    for(const auto& o:in.ops) {
        Tick ready=o.release;
        bool known=true;
        for(int p:o.pred) { if(r.finish[p]<0) known=false; else ready=std::max(ready,r.finish[p]); }
        Tick start=r.start[o.id];
        if(!known || ready>horizon || (start>=0 && start<=ready)) continue;
        events[o.machine].emplace_back(ready,1);
        if(start>=0 && start<=horizon) events[o.machine].emplace_back(start,-1);
    }
    for(std::size_t m=0;m<events.size();++m) {
        auto& e=events[m]; std::sort(e.begin(),e.end());
        int value=0;
        for(std::size_t i=0;i<e.size();) {
            Tick t=e[i].first;
            do { value+=e[i++].second; } while(i<e.size() && e[i].first==t);
            peak[m]=std::max(peak[m],value);
        }
        at[m]=value;
    }
    int produced=0,released=0;
    long double integral=0;
    for(int i:in.final_operations) {
        Tick release=in.ops[i].release,finish=r.finish[i];
        if(release<=horizon) ++released;
        if(finish>=0 && finish<=horizon) ++produced;
        integral+=std::max<Tick>(0,(finish<0 ? horizon:std::min(finish,horizon))-release);
    }
    bool complete=produced==in.jobs;
    Tick cmax=0;
    if(complete) for(int i:in.final_operations)cmax=std::max(cmax,r.finish[i]);
    return json{{"produced",produced},{"released",released},{"incomplete_jobs",in.jobs-produced},
                {"queue_at_D",at},{"queue_max",peak},{"wip_integral",double(integral)},
                {"mission_success",complete},{"completion_known",complete},
                {"cmax",complete ? json(cmax):json(nullptr)},
                {"completion_lower_bound",complete ? json(nullptr):json(horizon)}};
}
