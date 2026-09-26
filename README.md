# Sheaft / TSFG manufacturing execution experiment

Fixed manufacturing schedule experiment using the existing Go TSFG kernel from
S1 with a new operation policy adapter. [Reuse specification](docs/TSFG_REUSE_RU.md)
amends protocol 1.1 and records exactly which code is reused.

DES-REF and DAG-REF are our independent, open research implementations. DAG-REF
computes execution along operation dependencies and fixed machine queues; it is
not a competing vendor. BFG and PlantTwin were not directly benchmarked, so the
reported speed ratios do not describe those commercial products.

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
exact H3 participant. All 48 aggregation points and both G2 rankings are repeated;
the original evidence is retained separately.

- [E3 aggregation and accuracy specification](docs/AGGREGATION_SPEC_RU.md)
- [E4 fixed ranking and independent holdout](docs/RESERVE_SPEC_RU.md)
- [Supplementary BURST, equipment, assembly and K=1000](docs/SUPPLEMENTARY_SPEC_RU.md)
- [Pinned campaign run registry](provenance/campaign.json)

[Read the generated report (Russian)](docs/results/mk01/REPORT_RU.md) ·
[Download all inputs, traces and evidence](https://github.com/a-a-k/sheaft-tsfg-experiments/releases/tag/v0.1.0-mk01)

The release ZIP is the unchanged Actions artifact (SHA-256
`391b3a42367d96ae6acef94dc423d36e34df9f0208eb6ce4ea970f68ca2d7d6f`).
Report paths to `input/`, `traces/`, `../build/` and `../e0/` refer to that archive.

The completed first acceptance milestone is E0-core plus Brandimarte Mk01: 481 complete
trajectories at a 0.05-unit grid and 1,443 deadline classifications per engine.
The original TSFG plus adapter, independent C++20 DES/DAG, and a small SimPy oracle
will be compared. The earlier standalone C++ GRID is an auxiliary control only.
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
