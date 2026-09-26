# Project execution rules

All compilation, dependency resolution, dataset generation, tests, simulation,
measurements and report generation MUST run on GitHub-hosted GitHub Actions.
Do not run project Python scripts, C++ programs, compilers, tests or experiments
on the local workstation. Local editing, reading, Git operations and retrieval
of completed Actions artifacts are allowed.

The authorized first milestone is protocol/specification 1.1, E0-core and the
complete Mk01 E1 campaign: 481 trajectories and 1,443 deadline outcomes per
engine. E1X and E2–E4 are subsequent research stages, not acceptance substitutes.

Keep TSFG-GRID, DES and DAG transition logic independent. Shared input parsing
and output metrics are allowed. Record all failures; never fabricate results.
Public repository creation and publication of this experimental implementation
are explicitly authorized. Do not publish credentials or private source code.

