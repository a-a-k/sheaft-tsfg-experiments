# Sheaft / TSFG manufacturing execution experiment

Revision 2.2 execution is closed at its predeclared limits and admission gates.
Its scientific status remains **PARTIAL**: timeouts, nominal deadlocks and budget
gates leave required observations unavailable.
[Final v2.2 report](docs/results/revision-v2/final/FINAL_REPORT_RU.md) ·
[Verified evidence archive](https://github.com/a-a-k/sheaft-tsfg-experiments/releases/tag/revision-v2-final-package-16366e27dea4).

All three admitted F1/100k PBR rounds ran: 18 DES processes completed and 18 TSFG
processes timed out at 300 seconds. Every common completed trajectory matched;
there are no complete paired points for accepting the speed hypothesis.
Both F1/10k reserve holdouts (independent failures and common causes) completed
1,000 scenarios each and failed
the prespecified benefit criterion after the fixed 32-test Holm correction.
The other six reserve regions retain explicit admission or budget gate reasons.
The original campaign below remains preserved.
The [first package report](docs/results/revision-v2/first-package/FIRST_PACKAGE_REPORT_RU.md)
now includes all 36 PBR preliminary inputs (30 completed K10 campaigns and six
nominal deadlocks), exact combined Mk01 checks and the six fluid diagnostics.
[Complete first-package traces and verified archive](https://github.com/a-a-k/sheaft-tsfg-experiments/releases/tag/revision-v2-first-package-7a7dedbed12c).
The [complete APS matrix](docs/results/revision-v2/aps-matrix/APS_MATRIX_REPORT_RU.md)
contains 60 validated primary processes: 10 unique inputs at each of 100k and one
million operations, three repeats each. The maximum of the million-input medians
is **74.73 s**, on one CPU with a 4 GiB memory limit.
[All million-operation plans and verified report archive](https://github.com/a-a-k/sheaft-tsfg-experiments/releases/tag/revision-v2-aps-matrix-68ce2dfe0dfb).
The [first APS archive](https://github.com/a-a-k/sheaft-tsfg-experiments/releases/tag/revision-v2-aps-first-c2c51bbdecce)
also retains the complete compact million-operation input collection.
The [complete E4 archive and output reanalysis](https://github.com/a-a-k/sheaft-tsfg-experiments/releases/tag/revision-v2-e4-1bab7db283f5)
is also published. Earlier milestone archives remain immutable.
All computation and report generation ran on GitHub-hosted Actions. Workflows,
including the complete legacy campaign, are dispatched explicitly so publishing
documentation does not trigger additional experiments outside the fixed budgets.

Fixed manufacturing schedule experiment using the existing Go TSFG kernel from
S1 with a new operation policy adapter. [Reuse specification](docs/TSFG_REUSE_RU.md)
amends protocol 1.1 and records exactly which code is reused.

DES-REF and DAG-REF are our independent, open research implementations. DAG-REF
computes execution along operation dependencies and fixed machine queues; it is
not a competing vendor. BFG and PlantTwin were not directly benchmarked, so the
reported speed ratios do not describe those commercial products.

The research report also evaluates the product implication: DAG is a candidate
for the primary exact engine when checking an existing fixed schedule. Dynamic
dispatch, finite buffers, schedule optimization and the business value of reserve
recommendations require separate treatment and validation; speed alone does not
establish a production-ready product.

The original v0.2 research campaign completed on 27 September 2026. All 72 main
measurement blocks and their independent replay checks finished. Of 432 measured
processes, 336 completed correctly and 96 timed out. H3 has no supported region:
four decisions are NOT_SUPPORTED with complete paired evidence and twelve are
INSUFFICIENT_COMPLETED. Timeouts are retained as bounds, not completion times.
G2 passed the complete mission accuracy class on 6 of 48 datasets and the
diagnostic class on none; it was faster than exact DAG on none of the six admitted
datasets. H5 was not supported. Isolated engine peak memory remains unsupported.

[Final report in Russian](docs/results/full-study/REPORT_RU.md) ·
[PDF, inputs and verified evidence](https://github.com/a-a-k/sheaft-tsfg-experiments/releases/tag/v0.2.0-full-study)

The final report includes the required product implications: use DAG as a
candidate engine for checking fixed plans, then validate forecasts and decision
value on real production data. Unperformed extensions and protocol deviations
are disclosed; completion of this campaign does not mean every broader idea in
the original plan was implemented.

The first full correctness campaign passed in
[GitHub Actions run 36230395401](https://github.com/a-a-k/sheaft-tsfg-experiments/actions/runs/36230395401)
at commit `75776d6c81806fdd2a53c8faf95e8283ef2409f6`: 481 complete trajectories,
52,910 exact operation-time comparisons and 1,443 deadline classifications per
engine, with zero mismatches, false successes or false failures. CP-SAT proved
the baseline optimum C0=40. S1's 157 regression tests and E0 also passed.
The 48-dataset E2 screen completed with
140 correct complete processes and four timeouts; standalone paired K=100 is
evaluated separately. No positive H3 claim is made from this screen.

The full-study pipeline collects the pinned campaign evidence, generates the
Russian PDF and tables, and publishes a [release](https://github.com/a-a-k/sheaft-tsfg-experiments/releases)
only after every required campaign and artifact checksum passes admission.
The final archive retains timeouts, incomplete H3 decisions and disclosed limitations.
Preliminary reports have a separate status and cannot pass final publication admission.

The [implementation audit](docs/TSFG_AUDIT_RU.md) reproduced the original Ozon
case and reduced adapter time by 31–32% without changing S1 source. The historical
2.8–7.4× figure was an analytical scheduling-work estimate, not a paired elapsed
time comparison with production DES. [Execution deviations](docs/EXECUTION_DEVIATIONS_RU.md)
are recorded explicitly, including the actual eight-byte seed derivation.

A subsequent [G2 numerical audit](docs/G2_NUMERICAL_CORRECTION_RU.md) found that
small fluid transfers could be discarded by the original kernel's internal threshold.
The corrected coupling rescales internal units without changing S1 or the frozen
exact H3 participant. All 48 aggregation points and both G2 rankings were repeated;
the original evidence is retained separately.

- [E3 aggregation and accuracy specification](docs/AGGREGATION_SPEC_RU.md)
- [E4 fixed ranking and independent holdout](docs/RESERVE_SPEC_RU.md)
- [Supplementary BURST, equipment, assembly and K=1000](docs/SUPPLEMENTARY_SPEC_RU.md)
- [Pinned campaign run registry](provenance/campaign.json)

[First Mk01 milestone report (Russian)](docs/results/mk01/REPORT_RU.md) ·
[Mk01 inputs, traces and evidence](https://github.com/a-a-k/sheaft-tsfg-experiments/releases/tag/v0.1.0-mk01)

The release ZIP is the unchanged Actions artifact (SHA-256
`391b3a42367d96ae6acef94dc423d36e34df9f0208eb6ce4ea970f68ca2d7d6f`).
Report paths to `input/`, `traces/`, `../build/` and `../e0/` refer to that archive.

The completed first acceptance milestone is E0-core plus Brandimarte Mk01: 481 complete
trajectories at a 0.05-unit grid and 1,443 deadline classifications per engine.
The original TSFG plus adapter, independent C++20 DES/DAG, and a small SimPy oracle
were compared. The earlier standalone C++ GRID is an auxiliary control only.
All execution takes place on GitHub-hosted runners.

- [Protocol (Russian)](Sheaft_TSFG_Experiment_Plan_GitHub_Actions_RU.md)
- [GRID specification (Russian)](TSFG_OP_SPEC_RU.md)
- [Execution rules](AGENTS.md)
- [Revised estimate for subsequent stages (Russian)](docs/NEXT_STEPS_RU.md)

S1 is referenced by its content hash in the protocol. The supplied PDF and any
previous private implementation are not distributed with this repository.
Reproducing the TSFG participant requires read access to the pinned private
source. Actions uses a dedicated read-only deploy key; private source and its
compiled binary are excluded from public artifacts.
