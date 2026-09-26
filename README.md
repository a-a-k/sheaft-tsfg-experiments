# Sheaft / TSFG manufacturing execution experiment

Fixed manufacturing schedule experiment using the existing Go TSFG kernel from
S1 with a new operation policy adapter. [Reuse specification](docs/TSFG_REUSE_RU.md)
amends protocol 1.1 and records exactly which code is reused.

Implementation is in progress. No experimental correctness or performance
result is claimed until a completed GitHub Actions campaign is linked here.

The first acceptance milestone is E0-core plus Brandimarte Mk01: 481 complete
trajectories at a 0.05-unit grid and 1,443 deadline classifications per engine.
The original TSFG plus adapter, independent C++20 DES/DAG, and a small SimPy oracle
will be compared. The earlier standalone C++ GRID is an auxiliary control only.
All execution takes place on GitHub-hosted runners.

- [Protocol (Russian)](Sheaft_TSFG_Experiment_Plan_GitHub_Actions_RU.md)
- [GRID specification (Russian)](TSFG_OP_SPEC_RU.md)
- [Execution rules](AGENTS.md)

S1 is referenced by its content hash in the protocol. The supplied PDF and any
previous private implementation are not distributed with this repository.
Reproducing the TSFG participant requires read access to the pinned private
source. Actions uses a dedicated read-only deploy key; private source and its
compiled binary are excluded from public artifacts.
