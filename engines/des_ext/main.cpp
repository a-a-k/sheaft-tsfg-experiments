// Independent PBR event-driven reference. No TSFG transition code is shared.
#include "../model.hpp"
#include <array>
#include <chrono>
#include <cstdlib>
#include <fstream>
#include <iostream>
#include <map>
#include <numeric>
#include <queue>
#include <set>
#include <sstream>
#include <tuple>

struct PBR {
    const Instance& in;
    Scenario sc;
    int n,m;
    Tick t=0,H;
    bool diagnostic,in_sweep=false,deadlock=false;
    int cursor=-1,done=0;
    std::vector<int> cap,need,unit,head,current,used,peak,rank,order,pool_base,pool_capacity,owners;
    std::vector<Tick> start,finish,left,released,transfer,entered;
    std::vector<bool> buffered,release_timer,plan_timer;
    std::vector<std::vector<Interval>> unit_down;
    std::vector<std::set<int>> buffer_wait,resource_wait;
    std::set<int> candidates,next_pass;
    using Event=std::tuple<Tick,int,int>;
    std::priority_queue<Event,std::vector<Event>,std::greater<Event>> events;
    std::vector<std::array<Tick,5>> custody;
    std::vector<int> custody_index;
    std::vector<std::array<Tick,6>> links;
    std::map<std::array<Tick,4>,std::size_t> link_index;
    Tick wait_integral=0,blocked_integral=0;
    std::uint64_t boundaries=0,visits=0;

    PBR(const Instance& instance,const json& data,const json& raw,Tick horizon,bool diag)
      :in(instance),sc(read_scenario(in,raw)),n(in.ops.size()),m(in.queues.size()),H(horizon),diagnostic(diag),
       cap(m,-1),need(n,-1),unit(n,-1),head(m),current(m,-1),used(m),peak(m),rank(n),order(n),
       start(n,-1),finish(n,-1),left(sc.work),released(n,-1),transfer(n,-1),entered(n,-1),
       buffered(n),release_timer(n),plan_timer(n),buffer_wait(m),custody_index(n,-1) {
        if(H<0 || H%5)throw std::runtime_error("Unaligned horizon");
        if(raw.contains("speed_intervals") && !raw["speed_intervals"].empty())throw std::runtime_error("Fractional speed is a separate profile");
        if(data.contains("base_speed_percent"))for(const auto& speed:data["base_speed_percent"])
            if(speed.get<int>()!=100)throw std::runtime_error("Non-unit speed");
        if(data.contains("buffer_capacities")) {
            if(data["buffer_capacities"].size()!=std::size_t(m))throw std::runtime_error("Buffer dimensions");
            for(int k=0;k<m;++k) {
                const auto& c=data["buffer_capacities"][k];
                if(c.is_string()) {if(c!="unbounded")throw std::runtime_error("Unknown capacity");}
                else {cap[k]=c.get<int>();if(cap[k]<0)throw std::runtime_error("Negative capacity");}
            }
        } else if(data.value("buffer_capacity",0)>0)std::fill(cap.begin(),cap.end(),data["buffer_capacity"].get<int>());
        json pools=data.value("resource_pools",json::array());
        if(pools.empty() && data.contains("shared_operations") && !data["shared_operations"].empty())pools=json::array({{{"id",0},{"capacity",1}}});
        int total=0;
        for(const auto& p:pools) {
            if(p.at("id").get<int>()!=int(pool_capacity.size()) || p.at("capacity").get<int>()<=0)throw std::runtime_error("Invalid pool");
            pool_base.push_back(total);pool_capacity.push_back(p["capacity"]);total+=pool_capacity.back();
        }
        owners.assign(total,-1);unit_down.resize(total);resource_wait.resize(pools.size());
        for(const auto& o:data["operations"])if(o.contains("resource_pool") && !o["resource_pool"].is_null())need.at(o["id"])=o["resource_pool"];
        if(data.contains("shared_operations"))for(int i:data["shared_operations"])need.at(i)=0;
        auto failure=[&](int r,int u,Tick a,Tick b) {
            if(r<0 || r>=int(pool_capacity.size()) || u<0 || u>=pool_capacity[r] || a<0 || b<=a || a%5 || b%5)
                throw std::runtime_error("Invalid unit failure");
            unit_down[pool_base[r]+u].push_back({a,b});events.emplace(a,2,r);events.emplace(b,2,r);
        };
        if(raw.contains("resource_failures"))for(const auto& f:raw["resource_failures"])failure(f[0],f[1],f[2],f[3]);
        if(raw.contains("shared_failures"))for(const auto& f:raw["shared_failures"])failure(0,0,f[0],f[1]);
        for(int k=0;k<m;++k)for(auto v:sc.down[k]) {
            if(v.begin%5 || v.end%5)throw std::runtime_error("Unaligned failure");
            events.emplace(v.begin,1,k);events.emplace(v.end,1,k);
        }
        std::iota(order.begin(),order.end(),0);
        std::sort(order.begin(),order.end(),[&](int a,int b){const auto& x=in.ops[a];const auto& y=in.ops[b];
            return std::tie(x.planned,x.job,x.id,x.machine)<std::tie(y.planned,y.job,y.id,y.machine);});
        for(int k=0;k<n;++k)rank[order[k]]=k;
        for(const auto& o:in.ops) {
            if(o.pred.size()>1 || in.successors[o.id].size()>1)throw std::runtime_error("Chain routes required");
            if(o.work%5 || o.release%5 || o.planned%5 || left[o.id]%5)throw std::runtime_error("Unaligned operation");
            if(need[o.id]<-1 || need[o.id]>=int(pools.size()))throw std::runtime_error("Invalid operation pool");
            if(o.pred.empty())events.emplace(o.release,0,o.id);
        }
    }
    static bool up(const std::vector<Interval>& down,Tick at) {
        for(auto d:down)if(d.begin<=at && at<d.end)return false;
        return true;
    }
    int free_unit(int r)const {
        for(int u=0;u<pool_capacity[r];++u) {
            int k=pool_base[r]+u;
            if(owners[k]<0 && up(unit_down[k],t))return u;
        }
        return -1;
    }
    void activate(int i) {
        if(i<0 || start[i]>=0)return;
        int r=rank[i];
        if(in_sweep && r<=cursor)next_pass.insert(r);else candidates.insert(r);
    }
    void wake(const std::set<int>& waiting) {
        if(waiting.empty())return;
        auto pos=in_sweep?waiting.upper_bound(cursor):waiting.begin();
        if(pos==waiting.end())pos=waiting.begin();
        activate(order[*pos]);
    }
    void wake_buffer(int k) {if(cap[k]<0 || used[k]<cap[k])wake(buffer_wait[k]);}
    void wake_resource(int r) {if(r>=0 && free_unit(r)>=0)wake(resource_wait[r]);}
    void wake_head(int k) {
        if(head[k]<int(in.queues[k].size()))activate(in.queues[k][head[k]]);
        if(current[k]>=0 && finish[current[k]]>=0 && !in.successors[current[k]].empty())activate(in.successors[current[k]][0]);
    }
    bool possible(int i,bool self,bool resource=true)const {
        const auto& o=in.ops[i];int k=o.machine;
        if(start[i]>=0 || o.planned>t || o.release>t || !up(sc.down[k],t))return false;
        for(int p:o.pred)if(finish[p]<0)return false;
        if(current[k]<0) {
            if(head[k]>=int(in.queues[k].size()) || in.queues[k][head[k]]!=i)return false;
        } else {
            int p=current[k];
            if(!self || o.pred.empty() || o.pred[0]!=p || finish[p]<0 || head[k]+1>=int(in.queues[k].size()) || in.queues[k][head[k]+1]!=i)return false;
        }
        return !resource || need[i]<0 || free_unit(need[i])>=0;
    }
    void release(int i) {
        if(released[i]>=0)return;
        int k=in.ops[i].machine;
        if(current[k]!=i || finish[i]<0 || in.queues[k][head[k]]!=i)throw std::runtime_error("Invalid custody release");
        current[k]=-1;++head[k];released[i]=t;wake_head(k);
    }
    void begin(int i) {
        int k=in.ops[i].machine,r=need[i];
        if(current[k]>=0)throw std::runtime_error("Machine overlap");
        buffer_wait[k].erase(rank[i]);
        if(buffered[i]) {buffered[i]=false;--used[k];wake_buffer(k);}
        start[i]=t;current[k]=i;
        if(r>=0) {
            resource_wait[r].erase(rank[i]);unit[i]=free_unit(r);
            if(unit[i]<0)throw std::runtime_error("Resource overlap");
            owners[pool_base[r]+unit[i]]=i;
            custody_index[i]=custody.size();custody.push_back({r,unit[i],i,t,-1});wake_resource(r);
        }
    }
    void consider(int i) {
        ++visits;const auto& o=in.ops[i];int k=o.machine,r=need[i];
        if(r>=0)resource_wait[r].erase(rank[i]);
        if(start[i]>=0)return;
        for(int p:o.pred)if(finish[p]<0)return;
        if(o.release>t) {
            if(!release_timer[i]) {events.emplace(o.release,0,i);release_timer[i]=true;}
            return;
        }
        if(o.planned>t && !plan_timer[i]) {events.emplace(o.planned,0,i);plan_timer[i]=true;}
        if(r>=0 && possible(i,true,false) && free_unit(r)<0)resource_wait[r].insert(rank[i]);
        if(transfer[i]<0) {
            bool direct=possible(i,true);
            if(!direct && cap[k]>=0 && used[k]>=cap[k]) {buffer_wait[k].insert(rank[i]);return;}
            buffer_wait[k].erase(rank[i]);
            for(int p:o.pred)release(p);
            transfer[i]=t;
            if(direct)begin(i);
            else {buffered[i]=true;entered[i]=t;++used[k];peak[k]=std::max(peak[k],used[k]);}
        }
        if(buffered[i] && possible(i,false))begin(i);
        wake_buffer(k);wake_resource(r);
    }
    bool processing(int i)const {
        return up(sc.down[in.ops[i].machine],t) && (need[i]<0 || up(unit_down[pool_base[need[i]]+unit[i]],t));
    }
    json solve() {
        for(;;) {
            ++boundaries;in_sweep=false;cursor=-1;
            std::vector<int> ended;
            for(int i:current)if(i>=0 && finish[i]<0 && left[i]==0) {finish[i]=t;ended.push_back(i);++done;}
            for(int i:ended) {
                int r=need[i];
                if(r>=0) {owners[pool_base[r]+unit[i]]=-1;custody[custody_index[i]][4]=t;wake_resource(r);}
                for(int child:in.successors[i])activate(child);
                if(in.successors[i].empty() || cap[in.ops[i].machine]<0)release(i);
            }
            while(!events.empty() && std::get<0>(events.top())<=t) {
                auto [at,type,id]=events.top();events.pop();(void)at;
                if(type==0)activate(id);
                else if(type==1)wake_head(id);
                else {wake_resource(id);for(int k=0;k<m;++k)if(head[k]<int(in.queues[k].size()) && need[in.queues[k][head[k]]]==id)wake_head(k);}
            }
            in_sweep=true;
            while(!candidates.empty() || !next_pass.empty()) {
                if(candidates.empty()) {candidates.swap(next_pass);cursor=-1;}
                auto it=candidates.begin();cursor=*it;candidates.erase(it);consider(order[cursor]);
            }
            in_sweep=false;
            bool active=false;
            for(int i:current)if(i>=0 && finish[i]<0)active=true;
            if(t==H || (diagnostic && done==n))break;
            if(done==n) {t=H;break;}
            if(!active && events.empty()) {deadlock=true;break;}
            Tick next=H;
            if(!events.empty())next=std::min(next,std::get<0>(events.top()));
            for(int i:current)if(i>=0 && finish[i]<0 && processing(i))next=std::min(next,t+left[i]);
            if(next<=t)throw std::runtime_error("Nonadvancing DES calendar");
            Tick elapsed=next-t;
            for(const auto& waiting:resource_wait)wait_integral+=elapsed*waiting.size();
            for(int i:current)if(i>=0 && finish[i]>=0)blocked_integral+=elapsed;
            for(int r=0;r<int(resource_wait.size());++r)for(int position:resource_wait[r]) {
                int i=order[position],k=in.ops[i].machine;
                for(int p:in.ops[i].pred)if(finish[p]>=0 && released[p]<0 && transfer[i]<0 && cap[k]>=0 && used[k]>=cap[k]) {
                    std::array<Tick,6> link{t,next,p,i,k,r};
                    std::array<Tick,4> key{p,i,k,r};auto previous=link_index.find(key);
                    if(previous!=link_index.end() && links[previous->second][1]==t)links[previous->second][1]=next;
                    else {link_index[key]=links.size();links.push_back(link);}
                }
            }
            for(int i:current)if(i>=0 && finish[i]<0 && processing(i))left[i]-=elapsed;
            t=next;
        }
        json starts=json::array(),finishes=json::array(),jobs=json::array(),states=json::array();
        if(deadlock && !diagnostic)for(int i:current)if(i>=0 && finish[i]>=0)blocked_integral+=H-t;
        std::sort(links.begin(),links.end());
        for(int i=0;i<n;++i) {
            starts.push_back(start[i]<0?json(nullptr):json(start[i]));finishes.push_back(finish[i]<0?json(nullptr):json(finish[i]));
            states.push_back(finish[i]>=0?(released[i]>=0?"DONE":"BLOCKED_AFTER_PROCESSING"):
                start[i]<0?"NOT_STARTED":processing(i)?"PROCESSING":"SUSPENDED");
        }
        json job_results=json::array();
        for(int i:in.final_operations){jobs.push_back(finishes[i]);job_results.push_back({{"job_id",job_results.size()},
            {"finish",finishes[i]},{"completion_lower_bound",finish[i]>=0?json(nullptr):json(H)},
            {"produced",finish[i]>=0},{"status",finish[i]>=0?"COMPLETE":deadlock?"DEADLOCK":"CENSORED"}});}
        json pools=json::array();
        for(int r=0;r<int(pool_capacity.size());++r) {json row=json::array();for(int u=0;u<pool_capacity[r];++u)row.push_back(owners[pool_base[r]+u]);pools.push_back(row);}
        return json{{"scenario_id",sc.id},{"engine","des-ext"},{"algorithm_id","DES-EXT-v2.2"},{"mode",diagnostic?"DIAGNOSTIC":"MISSION"},
            {"horizon",H},{"stopped",t},{"start",starts},{"finish",finishes},{"remaining",left},{"state",states},{"job_finish",jobs},{"job_results",job_results},
            {"mission_success",done==n},{"completion_known",done==n},{"cmax",done==n?json(*std::max_element(finish.begin(),finish.end())):json(nullptr)},
            {"completion_lower_bound",done==n?json(nullptr):json(H)},{"run_status",deadlock?"DEADLOCK":done==n?"OK":"CENSORED"},
            {"machine_release",released},{"transfer_at",transfer},{"buffer_entry",entered},{"buffer_counts",used},{"buffer_peaks",peak},
            {"resource_unit",unit},{"resource_owners",pools},{"resource_ownership",custody},
            {"resource_wait_integral",wait_integral},{"blocked_machine_integral",blocked_integral},{"coupling_witnesses",links},
            {"deadlock_proof",deadlock?json{{"no_running_operations",true},{"no_future_changes",true}}:json(nullptr)},
            {"counters",{{"boundaries",boundaries},{"candidate_visits",visits}}}};
    }
};

int main(int argc,char** argv) {
    try {
        if(!std::getenv("GITHUB_ACTIONS") || std::string(std::getenv("GITHUB_ACTIONS"))!="true")throw std::runtime_error("Actions only");
        if(argc!=6)throw std::runtime_error("des-ext DATA SCENARIOS OUTPUT MODE HORIZON");
        auto begin=std::chrono::steady_clock::now();
        std::ifstream input(argv[1]),scenarios(argv[2]);json data,rows;input>>data;scenarios>>rows;
        auto in=read_instance(data);std::string mode=argv[4];
        auto imported=std::chrono::steady_clock::now();
        if(mode!="MISSION" && mode!="DIAGNOSTIC")throw std::runtime_error("Unknown mode");
        std::ofstream output(argv[3]);if(!output)throw std::runtime_error("Output unavailable");
        for(const auto& row:rows) {PBR engine(in,data,row,std::stoll(argv[5]),mode=="DIAGNOSTIC");output<<engine.solve().dump()<<'\n';output.flush();}
        output.close();auto closed=std::chrono::steady_clock::now();
        std::ifstream status("/proc/self/status");std::string line;std::int64_t peak=0;
        while(std::getline(status,line))if(line.starts_with("VmHWM:")){std::istringstream field(line.substr(6));field>>peak;peak*=1024;}
        if(peak<=0)throw std::runtime_error("VmHWM unavailable");
        std::ofstream meta(std::string(argv[3])+".meta.json");
        meta<<json{{"engine","DES-EXT-v2.2"},{"scenarios_completed",rows.size()},{"VmHWM_bytes",peak},
            {"memory_counter","/proc/self/status VmHWM after exec"},
            {"T_import_s",std::chrono::duration<double>(imported-begin).count()},
            {"T_batch_with_output_s",std::chrono::duration<double>(closed-imported).count()}}.dump();
        return 0;
    } catch(const std::exception& error) {std::cerr<<error.what()<<'\n';return 2;}
}
