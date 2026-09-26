// E4 exact outcome evaluation. Reuses independent DES/DAG, not an H3 timer.
#include "model.hpp"
#include <chrono>
#include <cstdlib>
#include <fstream>
#include <iostream>
#include <numeric>
#include <tuple>

static void require(bool condition,const char* message) {
    if (!condition) throw std::runtime_error(message);
}
static void physical(const Instance& in,const Scenario& sc,const Result& out,Tick h) {
    for (const auto& o:in.ops) {
        int i=o.id;
        if (out.start[i]<0) {require(out.finish[i]<0 && out.remaining[i]==sc.work[i],"Unstarted work changed");continue;}
        Tick s=out.start[i],e=out.finish[i]<0 ? h:out.finish[i];
        require(s>=std::max(o.planned,o.release) && s<=e && e<=h,"Invalid operation interval");
        for (int p:o.pred) require(out.finish[p]>=0 && out.finish[p]<=s,"Precedence violation");
        Tick service=e-s;
        for (auto v:sc.down[o.machine]) {
            require(!(v.begin<=s && s<v.end),"Start during failure");
            service-=std::max<Tick>(0,std::min(e,v.end)-std::max(s,v.begin));
        }
        require(service+out.remaining[i]==sc.work[i] && out.remaining[i]>=0,"Work conservation");
        require((out.finish[i]>=0)==(out.remaining[i]==0),"Completion accounting");
    }
    for (const auto& q:in.queues) for (std::size_t k=1;k<q.size();++k)
        if (out.start[q[k]]>=0) require(out.finish[q[k-1]]>=0 && out.finish[q[k-1]]<=out.start[q[k]],"Machine overlap/queue bypass");
}
static bool complete(const Result& r) {
    return std::all_of(r.finish.begin(),r.finish.end(),[](Tick t){return t>=0;});
}
static Tick cmax(const Result& r) {return complete(r) ? *std::max_element(r.finish.begin(),r.finish.end()):unknown;}
static Result checked(const Instance& in,const Scenario& sc,const Engine& dag,const Engine& des,Tick h,bool diagnostic) {
    Result a=dag.solve(sc,h,diagnostic,100),b=des.solve(sc,h,diagnostic,100);
    require(a.start==b.start && a.finish==b.finish && a.remaining==b.remaining && a.stopped==b.stopped,"Independent engines disagree");
    physical(in,sc,a,h);
    return a;
}
static void save(const std::string& path,const json& value) {
    std::ofstream stream(path);if (!stream) throw std::runtime_error("Cannot save E4 output");
    stream<<value.dump(2)<<'\n';stream.close();
}
static Tick boundary(Tick c0,int percentage) {return ((c0*percentage+5000)/10000)*100;}

int main(int argc,char** argv) {
    try {
        require(std::getenv("GITHUB_ACTIONS") && std::string(std::getenv("GITHUB_ACTIONS"))=="true","Actions only");
        require(argc==4 || argc==6,"reserve rank INPUT OUTPUT | reserve evaluate INPUT SCENARIOS RANKING OUTPUT");
        auto started=std::chrono::steady_clock::now();
        std::ifstream input(argv[2],std::ios::binary);Instance in=read_binary(input);
        Tick c0=0;for(const auto& o:in.ops)c0=std::max(c0,o.planned+o.work);
        Tick deadline=c0*11/10;
        std::string mode=argv[1];
        if (mode=="rank") {
            require(argc==4,"Rank arguments");
            auto dag=make_dag(in),des=make_des(in);
            std::vector<Tick> delays(in.queues.size());std::vector<int> misses(in.queues.size());
            json rows=json::array();
            for (int m=0;m<static_cast<int>(in.queues.size());++m) {
                json cases=json::array();
                for (int a:{10,30,50,70,90}) for(int b:{5,10,20}) {
                    Tick begin=boundary(c0,a),end=std::max(begin+100,boundary(c0,a+b));
                    json raw={{"id",std::to_string(m)+"-"+std::to_string(a)+"-"+std::to_string(b)},
                        {"failures",json::array({json::array({m,begin,end})})},{"work_overrides",json::array()}};
                    auto sc=read_scenario(in,raw);auto out=checked(in,sc,*dag,*des,deadline*10,true);
                    Tick end_time=cmax(out);require(end_time>=c0,"Unknown/nonmonotone ranking completion");
                    delays[m]+=end_time-c0;misses[m]+=end_time>deadline;
                    cases.push_back({{"a",a},{"b",b},{"cmax_ticks",end_time}});
                }
                rows.push_back({{"machine",m},{"sum_delay_ticks",delays[m]},
                    {"R",static_cast<double>(delays[m])/(15*c0)},{"F",misses[m]},{"cases",cases}});
                if (m%20==19) {save(argv[3],json{{"status","RUNNING"},{"completed_resources",m+1},{"ranking_rows",rows}});std::cout<<"ranked "<<m+1<<'\n'<<std::flush;}
            }
            std::vector<int> order(in.queues.size());std::iota(order.begin(),order.end(),0);
            std::sort(order.begin(),order.end(),[&](int a,int b){return std::tuple{-delays[a],-misses[a],a}<std::tuple{-delays[b],-misses[b],b};});
            require(order.size()>=6,"At least six resources required");
            std::vector<int> top(order.begin(),order.begin()+3),bottom(order.begin()+3,order.end());
            std::sort(bottom.begin(),bottom.end(),[&](int a,int b){return std::tuple{delays[a],misses[a],a}<std::tuple{delays[b],misses[b],b};});
            bottom.resize(3);
            save(argv[3],json{{"status","PASS"},{"C0_ticks",c0},{"D_ticks",deadline},{"T",top},{"B",bottom},
                {"ranking_rows",rows},{"scenarios",in.queues.size()*15},{"engines",{"dag","des"}},
                {"physical_checks",in.queues.size()*15},{"ranking_version","balanced-M1-R-F-ID-v1"}});
        } else if (mode=="evaluate") {
            require(argc==6,"Evaluation arguments");
            json scenarios,ranking;std::ifstream(argv[3])>>scenarios;std::ifstream(argv[4])>>ranking;
            require(ranking.at("status")=="PASS" && ranking.at("C0_ticks")==c0,"Missing fixed ranking");
            std::vector<int> targets={-1};
            for(int m:ranking.at("T"))targets.push_back(m);
            for(int m:ranking.at("B"))targets.push_back(m);
            require(targets.size()==7,"Invalid intervention groups");
            for(auto& o:in.ops){o.work*=11;o.planned*=11;o.release*=11;}
            deadline*=11;auto dag=make_dag(in),des=make_des(in);
            json records=json::array();std::size_t count=0;
            for (auto raw:scenarios) {
                for(auto& f:raw.at("failures")){f[1]=f[1].get<Tick>()*11;f[2]=f[2].get<Tick>()*11;}
                require(raw.at("work_overrides").empty(),"H5 workload is fixed");
                auto baseline=read_scenario(in,raw);
                json outcomes=json::array(),completion=json::array(),produced=json::array();
                for(int machine:targets) {
                    Scenario sc=baseline;
                    if (machine>=0) for(int i:in.queues.at(machine))sc.work[i]=sc.work[i]/11*10;
                    Result out=checked(in,sc,*dag,*des,deadline,false);
                    bool success=complete(out);outcomes.push_back(success);
                    completion.push_back(success ? json(cmax(out)):json(nullptr));
                    int output=0;for(int i:in.final_operations)output+=out.finish[i]>=0;
                    produced.push_back(output);
                }
                records.push_back({{"scenario_id",raw.at("id")},{"outcomes",outcomes},{"produced_jobs",produced},
                    {"cmax_scaled_ticks",completion},{"exact_engine_agreement",true}});
                ++count;
                if(count%50==0){save(argv[5],json{{"status","RUNNING"},{"records",records},{"targets",targets}});std::cout<<"evaluated "<<count<<'\n'<<std::flush;}
            }
            double elapsed=std::chrono::duration<double>(std::chrono::steady_clock::now()-started).count();
            save(argv[5],json{{"status","PASS"},{"records",records},{"targets",targets},{"time_scale",11},
                {"D_scaled_ticks",deadline},{"physical_checks",count*7},{"engines",{"dag","des"}},
                {"wall_including_checks_s",elapsed},{"scope","Exact reference verification of H5; not a TSFG performance claim"}});
        } else throw std::runtime_error("Unknown reserve command");
        return 0;
    } catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 2;}
}
