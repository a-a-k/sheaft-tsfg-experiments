#include "../model.hpp"
#include <queue>
#include <set>
#include <tuple>

namespace {
struct Event {
    Tick t; int kind, machine, generation;
    bool operator>(const Event& b) const {
        return std::tie(t,kind,machine,generation) > std::tie(b.t,b.kind,b.machine,b.generation);
    }
};
class Des final : public Engine {
    const Instance& in;
public:
    explicit Des(const Instance& x) : in(x) {}
    Result solve(const Scenario& sc, Tick horizon, bool diagnostic, Tick) const override {
        Result out(in,sc);
        const int M=in.queues.size(), N=in.ops.size();
        std::priority_queue<Event,std::vector<Event>,std::greater<Event>> calendar;
        std::vector<int> head(M), current(M,-1), generation(M), pending(N);
        std::vector<Tick> left(M), accounted(M);
        std::vector<bool> up(M,true);
        std::uint64_t popped=0, pushes=0, visits=0, updates=0;
        auto push = [&](Tick t,int kind,int m,int g) {
            if (t <= horizon) { calendar.push({t,kind,m,g}); ++pushes; }
        };
        auto availability = [&](int m, Tick t) {
            const auto& v=sc.down[m];
            auto it=std::upper_bound(v.begin(),v.end(),t,[](Tick x, const Interval& y){ return x<y.begin; });
            return it==v.begin() || t >= std::prev(it)->end;
        };
        for (int m=0;m<M;++m) {
            push(0,1,m,0);
            for (auto v : sc.down[m]) { push(v.begin,1,m,0); push(v.end,1,m,0); }
        }
        for (auto& o : in.ops) {
            pending[o.id]=o.pred.size();
            push(o.release,1,o.machine,0); push(o.planned,1,o.machine,0);
        }
        auto account = [&](int m,Tick now) {
            if (current[m] != -1 && up[m]) {
                left[m]-=now-accounted[m];
                if (left[m]<0) throw std::runtime_error("DES over-serviced operation");
            }
            accounted[m]=now;
        };
        int completed=0;
        Tick now=0;
        while (!calendar.empty() && completed<N) {
            now=calendar.top().t;
            std::vector<Event> batch;
            while (!calendar.empty() && calendar.top().t==now) {
                batch.push_back(calendar.top()); calendar.pop(); ++popped;
            }
            std::set<int> touched;
            std::vector<int> finished;
            // Completion events form an atomic batch before any availability change.
            for (auto e : batch) {
                if (e.kind != 0) { touched.insert(e.machine); continue; }
                int m=e.machine;
                if (e.generation!=generation[m] || current[m]==-1) continue;
                account(m,now);
                if (left[m]!=0) throw std::runtime_error("DES premature completion");
                int i=current[m]; out.finish[i]=now; out.remaining[i]=0;
                finished.push_back(i); current[m]=-1; ++head[m]; ++completed;
                ++generation[m]; touched.insert(m);
            }
            for (int i : finished) for (int v : in.successors[i]) {
                if (--pending[v]<0) throw std::runtime_error("DES duplicate predecessor");
                ++updates; touched.insert(in.ops[v].machine);
            }
            for (int m : touched) {
                ++visits;
                account(m,now);
                bool new_up=availability(m,now);
                if (new_up!=up[m]) {
                    up[m]=new_up; ++generation[m];
                    if (current[m]!=-1 && up[m]) push(now+left[m],0,m,generation[m]);
                }
            }
            for (int m : touched) {
                ++visits;
                if (!up[m] || current[m]!=-1 || head[m]==static_cast<int>(in.queues[m].size())) continue;
                int i=in.queues[m][head[m]];
                auto& o=in.ops[i];
                if (pending[i] || o.planned>now || o.release>now) continue;
                current[m]=i; left[m]=sc.work[i]; accounted[m]=now; out.start[i]=now;
                ++generation[m]; push(now+left[m],0,m,generation[m]);
            }
        }
        Tick stop=diagnostic && completed==N ? now : horizon;
        for (int m=0;m<M;++m) {
            account(m,stop);
            if (current[m]!=-1) out.remaining[current[m]]=left[m];
        }
        out.stopped=stop;
        out.counters={{"events_popped",popped},{"events_pushed",pushes},{"machine_visits",visits},
                      {"dependency_updates",updates},{"completed_operations",completed},{"reset_operations",N}};
        return out;
    }
};
}
std::unique_ptr<Engine> make_des(const Instance& in) { return std::make_unique<Des>(in); }

