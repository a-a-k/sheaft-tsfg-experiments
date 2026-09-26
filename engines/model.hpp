#pragma once
#include <nlohmann/json.hpp>
#include <algorithm>
#include <cstdint>
#include <istream>
#include <memory>
#include <stdexcept>
#include <string>
#include <vector>

using json = nlohmann::json;
using Tick = std::int64_t;
constexpr Tick unknown = -1;
struct Op { int id, job, machine; Tick work, planned, release; std::vector<int> pred; };
struct Instance {
    std::vector<Op> ops;
    std::vector<std::vector<int>> queues;
    std::vector<std::vector<int>> successors;
    int jobs{};
    std::vector<int> final_operations;
};
struct Interval { Tick begin, end; };
struct Scenario {
    std::string id;
    std::vector<Tick> work;
    std::vector<std::vector<Interval>> down;
};
struct Result {
    std::vector<Tick> start, finish, remaining;
    Tick stopped{};
    json counters = json::object();
    explicit Result(const Instance& in, const Scenario& sc)
        : start(in.ops.size(), unknown), finish(in.ops.size(), unknown), remaining(sc.work) {}
};
class Engine {
public:
    virtual ~Engine() = default;
    virtual Result solve(const Scenario&, Tick horizon, bool diagnostic, Tick delta) const = 0;
};
std::unique_ptr<Engine> make_grid(const Instance&);
std::unique_ptr<Engine> make_des(const Instance&);
std::unique_ptr<Engine> make_dag(const Instance&);

inline Instance read_instance(const json& j) {
    Instance in;
    in.jobs = j.at("jobs").size();
    for (const auto& job : j.at("jobs")) in.final_operations.push_back(job.at("final_operation"));
    in.queues = j.at("queues").get<std::vector<std::vector<int>>>();
    for (const auto& x : j.at("operations")) {
        Op o{x.at("id"), x.at("job"), x.at("machine"), x.at("work"),
             x.at("planned_start"), x.at("release"), x.at("predecessors").get<std::vector<int>>()};
        if (o.id != static_cast<int>(in.ops.size()) || o.work <= 0 || o.planned < 0 || o.release < 0
            || o.machine < 0 || o.machine >= static_cast<int>(in.queues.size()))
            throw std::runtime_error("Invalid operation input");
        in.ops.push_back(o);
    }
    in.successors.resize(in.ops.size());
    std::vector<int> seen(in.ops.size());
    for (int m=0; m<static_cast<int>(in.queues.size()); ++m)
        for (int i : in.queues[m]) {
            if (i < 0 || i >= static_cast<int>(in.ops.size()) || in.ops[i].machine != m || ++seen[i] != 1)
                throw std::runtime_error("Invalid fixed queue");
        }
    for (const auto& o : in.ops) {
        if (seen[o.id] != 1) throw std::runtime_error("Operation missing from queue");
        for (int p : o.pred) {
            if (p < 0 || p >= static_cast<int>(in.ops.size()) || p == o.id)
                throw std::runtime_error("Invalid predecessor");
            in.successors[p].push_back(o.id);
        }
    }
    return in;
}

// TSFGBIN1: little-endian, documented in docs/BINARY_FORMAT_RU.md.
inline std::uint64_t read_uint(std::istream& stream, int bytes) {
    std::uint64_t value=0;
    for (int k=0;k<bytes;++k) {
        int c=stream.get();
        if (c==std::char_traits<char>::eof()) throw std::runtime_error("Truncated binary input");
        value |= std::uint64_t(static_cast<unsigned char>(c)) << (8*k);
    }
    return value;
}
inline Instance read_binary(std::istream& stream) {
    char magic[8]; stream.read(magic,8);
    if (std::string(magic,8)!="TSFGBIN1") throw std::runtime_error("Invalid binary version");
    int n=read_uint(stream,4), jobs=read_uint(stream,4), machines=read_uint(stream,4);
    if (n<=0 || n>10000000 || jobs<=0 || jobs>n || machines<=0 || machines>100000)
        throw std::runtime_error("Invalid binary dimensions");
    Instance in; in.jobs=jobs; in.ops.reserve(n); in.successors.resize(n); in.queues.resize(machines);
    for (int i=0;i<n;++i) {
        Op o{}; o.id=i; o.job=read_uint(stream,4); o.machine=read_uint(stream,4);
        o.work=read_uint(stream,8); o.planned=read_uint(stream,8); o.release=read_uint(stream,8);
        int count=read_uint(stream,4);
        if (o.job<0 || o.job>=jobs || o.machine<0 || o.machine>=machines || o.work<=0 ||
            o.planned<0 || o.release<0 || count<0 || count>n) throw std::runtime_error("Invalid binary operation");
        for (int k=0;k<count;++k) {
            int p=read_uint(stream,4);
            if (p<0 || p>=n || p==i) throw std::runtime_error("Invalid binary dependency");
            o.pred.push_back(p); in.successors[p].push_back(i);
        }
        in.ops.push_back(std::move(o));
    }
    std::vector<bool> seen(n);
    for (int m=0;m<machines;++m) {
        int count=read_uint(stream,4);
        if (count<0 || count>n) throw std::runtime_error("Invalid binary queue size");
        for (int k=0;k<count;++k) {
            int i=read_uint(stream,4);
            if (i<0 || i>=n || seen[i] || in.ops[i].machine!=m) throw std::runtime_error("Invalid binary queue");
            seen[i]=true; in.queues[m].push_back(i);
        }
    }
    if (std::find(seen.begin(),seen.end(),false)!=seen.end()) throw std::runtime_error("Missing binary operation");
    for (int j=0;j<jobs;++j) {
        int i=read_uint(stream,4);
        if (i<0 || i>=n || in.ops[i].job!=j) throw std::runtime_error("Invalid binary job terminal");
        in.final_operations.push_back(i);
    }
    if (stream.peek()!=std::char_traits<char>::eof()) throw std::runtime_error("Trailing binary data");
    return in;
}

// Canonical input normalization only: no scheduling or time advancement here.
inline Scenario read_scenario(const Instance& in, const json& j) {
    Scenario sc;
    sc.id = j.at("id");
    for (auto& o : in.ops) sc.work.push_back(o.work);
    sc.down.resize(in.queues.size());
    for (auto& v : j.at("work_overrides")) {
        int i = v.at(0); Tick p = v.at(1);
        if (p <= 0) throw std::runtime_error("Non-positive work");
        sc.work.at(i) = p;
    }
    for (auto& v : j.at("failures")) {
        int m=v.at(0); Tick a=v.at(1), b=v.at(2);
        if (a < 0 || b <= a) throw std::runtime_error("Invalid failure interval");
        sc.down.at(m).push_back({a,b});
    }
    for (auto& intervals : sc.down) {
        std::sort(intervals.begin(), intervals.end(), [](auto a, auto b) {
            return a.begin < b.begin || (a.begin == b.begin && a.end < b.end);
        });
        std::vector<Interval> merged;
        for (auto v : intervals) {
            if (!merged.empty() && v.begin <= merged.back().end)
                merged.back().end = std::max(merged.back().end, v.end);
            else merged.push_back(v);
        }
        intervals = std::move(merged);
    }
    return sc;
}
