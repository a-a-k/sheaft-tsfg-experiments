# Sheaft / TSFG manufacturing execution experiment

Research implementation of protocol 1.1 for a fixed manufacturing schedule.
This is a new operation-level extension; it is not a verified port of the
sorting-centre implementation described in S1.

Implementation is in progress. No experimental correctness or performance
result is claimed until a completed GitHub Actions campaign is linked here.

The first acceptance milestone is E0-core plus Brandimarte Mk01: 481 complete
trajectories at a 0.05-unit grid and 1,443 deadline classifications per engine.
Independent C++20 GRID, DES and DAG implementations and a small SimPy oracle
will be compared. All execution takes place on GitHub-hosted runners.

- [Protocol (Russian)](Sheaft_TSFG_Experiment_Plan_GitHub_Actions_RU.md)
- [GRID specification (Russian)](TSFG_OP_SPEC_RU.md)
- [Execution rules](AGENTS.md)

S1 is referenced by its content hash in the protocol. The supplied PDF and any
previous private implementation are not distributed with this repository.

