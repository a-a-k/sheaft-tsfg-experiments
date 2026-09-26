#include "../model.hpp"
#include <queue>
#include <set>

namespace {
class Dag final : public Engine {
    const Instance& in;
    std::vector<int> order, previous;
public:
    explicit Dag(const Instance& x) : in(x), previous(x.ops.size(),-1) {
        const int N=in.ops.size();
        std::vector<std::set<int>> predecessors(N);
        for (const auto& o : in.ops) for (int p : o.pred) predecessors[o.id].insert(p);
        for (auto& queue : in.queues) for (std::size_t k=1;k<queue.size();++k) {
            previous[queue[k]]=queue[k-1]; predecessors[queue[k]].insert(queue[k-1]);
        }
        std::vector<std::vector<int>> next(N);
        std::vector<int> indegree(N);
        std::priority_queue<int,std::vector<int>,std::greater<int>> ready;
        for (int i=0;i<N;++i) {
            indegree[i]=predecessors[i].size();
            for (int p : predecessors[i]) next[p].push_back(i);
            if (!indegree[i]) ready.push(i);
        }
        while (!ready.empty()) {
            int i=ready.top(); ready.pop(); order.push_back(i);
            for (int v : next[i]) if (--indegree[v]==0) ready.push(v);
        }
        if (static_cast<int>(order.size())!=N) throw std::runtime_error("Cyclic fixed schedule");
    }
    Result solve(const Scenario& sc, Tick horizon, bool diagnostic, Tick) const override {
        Result out(in,sc);
        std::uint64_t calendar_queries=0;
        int completed=0;
        Tick latest=0;
        // Direct topological recurrence; no event queue or time-step simulation.
        for (int i : order) {
            const auto& o=in.ops[i];
            Tick ready=std::max(o.planned,o.release);
            bool blocked=false;
            for (int p : o.pred) {
                if (out.finish[p]==unknown) blocked=true;
                else ready=std::max(ready,out.finish[p]);
            }
            if (previous[i]!=-1) {
                if (out.finish[previous[i]]==unknown) blocked=true;
                else ready=std::max(ready,out.finish[previous[i]]);
            }
            if (blocked || ready>horizon) continue;
            Tick t=ready;
            auto& down=sc.down[o.machine];
            std::size_t k=0;
            while (k<down.size() && down[k].end<=t) { ++k; ++calendar_queries; }
            while (k<down.size() && down[k].begin<=t) {
                t=down[k].end; ++k; ++calendar_queries;
            }
            if (t>horizon) continue;
            out.start[i]=t;
            Tick remain=sc.work[i];
            while (remain>0 && t<horizon) {
                ++calendar_queries;
                Tick edge=k<down.size() ? std::min(horizon,down[k].begin) : horizon;
                Tick chunk=std::min(remain,edge-t);
                remain-=chunk; t+=chunk;
                if (!remain) break; // Completion exactly at a failure boundary wins.
                if (t==horizon) break;
                if (k<down.size() && t==down[k].begin) { t=std::min(horizon,down[k].end); ++k; }
            }
            out.remaining[i]=remain;
            if (!remain) { out.finish[i]=t; latest=std::max(latest,t); ++completed; }
        }
        out.stopped=diagnostic && completed==static_cast<int>(in.ops.size()) ? latest : horizon;
        out.counters={{"vertices",order.size()},{"calendar_queries",calendar_queries},
                      {"completed_operations",completed},{"reset_operations",in.ops.size()}};
        return out;
    }
};
}
std::unique_ptr<Engine> make_dag(const Instance& in) { return std::make_unique<Dag>(in); }
