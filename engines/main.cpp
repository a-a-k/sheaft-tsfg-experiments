#include "model.hpp"
#include "aggregate_metrics.hpp"
#include <chrono>
#include <cstdlib>
#include <cstdio>
#include <fstream>
#include <iostream>
#include <sys/resource.h>

using Clock = std::chrono::steady_clock;
static double seconds(Clock::time_point a,Clock::time_point b) { return std::chrono::duration<double>(b-a).count(); }
static json times(const std::vector<Tick>& values) {
    json a=json::array();
    for (Tick t : values) a.push_back(t==unknown ? json(nullptr) : json(t));
    return a;
}

int main(int argc,char** argv) {
    try {
        if (!std::getenv("GITHUB_ACTIONS") || std::string(std::getenv("GITHUB_ACTIONS"))!="true")
            throw std::runtime_error("Execution is restricted to GitHub Actions");
        if (argc!=8) throw std::runtime_error("Usage: simulator ENGINE DATA SCENARIOS OUTPUT MODE HORIZON DELTA");
        std::string name=argv[1], mode=argv[5];
        bool aggregate=std::getenv("TSFG_OUTPUT_PROFILE") && std::string(std::getenv("TSFG_OUTPUT_PROFILE"))=="AGG-MISSION";
        if (mode!="MISSION" && mode!="DIAGNOSTIC") throw std::runtime_error("Unknown mode");
        Tick horizon=std::stoll(argv[6]), delta=std::stoll(argv[7]);
        if (horizon<0) throw std::runtime_error("Negative horizon");
        auto t0=Clock::now();
        std::ifstream datafile(argv[2],std::ios::binary), scenariosfile(argv[3]);
        json scenarios; scenariosfile>>scenarios;
        Instance in;
        if (datafile.peek()=='T') in=read_binary(datafile);
        else { json data; datafile>>data; in=read_instance(data); }
        auto t1=Clock::now();
        std::unique_ptr<Engine> engine;
        if (name=="grid") engine=make_grid(in);
        else if (name=="des") engine=make_des(in);
        else if (name=="dag") engine=make_dag(in);
        else throw std::runtime_error("Unknown engine");
        auto t2=Clock::now();
        std::ofstream output(argv[4]);
        if (!output) throw std::runtime_error("Cannot open result output");
        std::size_t count=0;
        json prefixes=json::object();
        for (const auto& raw : scenarios) {
            auto begin=Clock::now();
            Scenario sc=read_scenario(in,raw);
            Result r=engine->solve(sc,horizon,mode=="DIAGNOSTIC",delta);
            auto end=Clock::now();
            json row;
            if(aggregate) {
                row=aggregate_metrics(in,r,horizon);
                row["scenario_id"]=sc.id;row["engine"]=name;row["mode"]=mode;
                row["horizon"]=horizon;row["stopped"]=r.stopped;row["run_status"]="OK";
                row["output_profile"]="AGG-MISSION";
                row["kernel_elapsed_s"]=seconds(begin,end);
            } else {
            bool complete=std::all_of(r.finish.begin(),r.finish.end(),[](Tick x){ return x>=0; });
            json states=json::array(), jobs=json::array();
            for (const auto& o : in.ops) {
                std::string state="NOT_STARTED";
                if (r.finish[o.id]>=0) state="DONE";
                else if (r.start[o.id]>=0) {
                    bool down=false;
                    for (auto v : sc.down[o.machine]) if (v.begin<=r.stopped && r.stopped<v.end) down=true;
                    state=down ? "SUSPENDED" : "PROCESSING";
                }
                states.push_back(state);
            }
            for (int terminal : in.final_operations) {
                Tick finish=r.finish.at(terminal);
                jobs.push_back(finish<0 ? json(nullptr) : json(finish));
            }
            row={{"scenario_id",sc.id},{"engine",name},{"mode",mode},{"horizon",horizon},
                {"stopped",r.stopped},{"start",times(r.start)},{"finish",times(r.finish)},
                {"remaining",r.remaining},{"state",states},{"job_finish",jobs},
                {"mission_success",complete},{"completion_known",complete},
                {"cmax",complete ? json(*std::max_element(r.finish.begin(),r.finish.end())) : json(nullptr)},
                {"completion_lower_bound",complete ? json(nullptr) : json(horizon)},
                {"run_status","OK"},{"counters",r.counters},{"kernel_elapsed_s",seconds(begin,end)}};
            }
            output << row.dump() << '\n'; output.flush(); ++count;
            if (count==1 || count==10 || count==100 || count==1000)
                prefixes[std::to_string(count)]=seconds(t2,Clock::now());
            std::string progress=std::string(argv[4])+".progress.json";
            { std::ofstream p(progress+".tmp");
              p << json({{"scenarios_completed",count},{"T_import_s",seconds(t0,t1)},
                  {"T_build_s",seconds(t1,t2)},{"T_batch_elapsed_s",seconds(t2,Clock::now())},
                  {"prefix_batch_s",prefixes}}).dump(); }
            if (std::rename((progress+".tmp").c_str(),progress.c_str())) throw std::runtime_error("Cannot persist progress");
        }
        output.close();
        auto t3=Clock::now();
        rusage usage{}; getrusage(RUSAGE_SELF,&usage);
        json meta={{"engine",name},{"scenarios_completed",count},{"T_import_s",seconds(t0,t1)},
            {"T_build_s",seconds(t1,t2)},{"T_batch_with_output_s",seconds(t2,t3)},
            {"rss_peak_bytes",static_cast<std::uint64_t>(usage.ru_maxrss)*1024},
            {"cpu_s",usage.ru_utime.tv_sec+usage.ru_utime.tv_usec/1e6+usage.ru_stime.tv_sec+usage.ru_stime.tv_usec/1e6},
            {"prefix_batch_s",prefixes},{"output_profile",aggregate ? "AGG-MISSION":"SCHEDULE"}};
        std::ofstream(std::string(argv[4])+".meta.json") << meta.dump(2) << '\n';
        return 0;
    } catch (const std::exception& e) {
        std::cerr<<e.what()<<'\n'; return 2;
    }
}
