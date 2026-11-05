| Variant | Baseline (homogeneous) | Heterogeneous | Bursty + heavy tail | Flash crowd | Server crash | Gray failure | Crash error rate |
|---|---:|---:|---:|---:|---:|---:|---:|
| static speeds (no learning) | 0.99* | 1.02* | 0.99 | 0.98* | 1.02* | 1.13* | 0.13% |
| no error penalty | 1.00 | 1.00 | 0.99 | 0.98* | 1.00 | 1.00 | 1.63% |
| no concurrency compensation | 1.01* | 0.96* | 1.01 | 1.06* | 1.00 | 1.01 | 0.09% |
| two-choice sampling | 1.07* | 1.00 | 1.13* | 1.07* | 1.04* | 1.05* | 0.24% |
| FCFS expected-delay form | 1.11* | 0.99 | 0.99 | 1.02* | 1.00 | 1.05* | 0.04% |
| piggybacked queue instead of D*o | 1.01* | 0.95* | 0.99 | 1.01 | 0.97* | 0.97* | 0.03% |
| ASED (full) | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 0.13% |
