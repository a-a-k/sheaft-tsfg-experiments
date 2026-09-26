#include "../model.hpp"

namespace {
class Grid final : public Engine {
    const Instance& in;
public:
    explicit Grid(const Instance& x) : in(x) {}
    Result solve(const Scenario& sc, Tick horizon, bool diagnostic, Tick delta) const override {
        if (delta <= 0 || horizon < 0) throw std::runtime_error("Invalid grid/horizon");
        for (const auto& o : in.ops)
            if (sc.work[o.id] % delta || o.planned % delta || o.release % delta)
                throw std::runtime_error("UNSUPPORTED_INPUT: unaligned operation");
        for (auto& calendar : sc.down) for (auto v : calendar)
            if (v.begin % delta || v.end % delta)
                throw std::runtime_error("UNSUPPORTED_INPUT: unaligned calendar");

        Result out(in, sc);
        const int M = in.queues.size(), N = in.ops.size();
        std::vector<int> head(M), current(M,-1), pending(N);
        std::vector<std::size_t> cursor(M);
        std::vector<Tick> left(M);
        std::vector<bool> up(M,true);
        for (auto& o : in.ops) pending[o.id] = o.pred.size();
        Tick t=0;
        int complete=0;
        std::uint64_t steps=0, visits=0, updates=0, boundaries=0;

        auto mark_boundary = [&]() {
            for (int m=0; m<M; ++m) {
                ++visits;
                while (cursor[m] < sc.down[m].size() && sc.down[m][cursor[m]].end <= t) {
                    ++cursor[m]; ++boundaries;
                }
                const bool now_up = cursor[m] == sc.down[m].size()
                    || t < sc.down[m][cursor[m]].begin;
                if (up[m] && !now_up) ++boundaries;
                up[m] = now_up;
            }
            // All simultaneous completions and predecessor updates have already
            // committed. This machine sweep cannot propagate a zero-time finish.
            for (int m=0; m<M; ++m) {
                ++visits;
                if (!up[m] || current[m] != -1 || head[m] == static_cast<int>(in.queues[m].size())) continue;
                int i=in.queues[m][head[m]];
                if (pending[i] || in.ops[i].release > t || in.ops[i].planned > t) continue;
                current[m]=i; left[m]=sc.work[i]; out.start[i]=t;
            }
        };
        mark_boundary();
        while (t < horizon && complete < N) {
            Tick h=std::min(delta,horizon-t);
            std::vector<int> finished;
            for (int m=0; m<M; ++m) {
                ++visits;
                if (current[m] == -1 || !up[m]) continue;
                if (left[m] < h) throw std::runtime_error("GRID internal completion inside step");
                left[m]-=h;
                if (!left[m]) finished.push_back(current[m]);
            }
            t+=h; ++steps;
            for (int i : finished) {
                int m=in.ops[i].machine;
                out.finish[i]=t; out.remaining[i]=0;
                current[m]=-1; ++head[m]; ++complete;
            }
            for (int i : finished) for (int next : in.successors[i]) {
                if (--pending[next] < 0) throw std::runtime_error("Duplicate GRID predecessor completion");
                ++updates;
            }
            mark_boundary();
        }
        for (int m=0; m<M; ++m) if (current[m] != -1) out.remaining[current[m]]=left[m];
        out.stopped=diagnostic ? t : horizon;
        out.counters={{"steps",steps},{"machine_visits",visits},{"dependency_updates",updates},
                      {"availability_boundaries",boundaries},{"completed_operations",complete},
                      {"reset_operations",N},{"internal_events",0}};
        return out;
    }
};
}
std::unique_ptr<Engine> make_grid(const Instance& in) { return std::make_unique<Grid>(in); }
