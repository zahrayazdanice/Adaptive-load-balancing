| Condition | Policy | Failed requests | Outage P99 (ms) |
|---|---:|---:|---:|
| Connection refused, health checks only | RR | 5772 ± 59 | 1585 |
| Connection refused, health checks only | WRR | 340 ± 13 | 884 |
| Connection refused, health checks only | LC | 533 ± 16 | 555 |
| Connection refused, health checks only | P2C | 406 ± 19 | 1193 |
| Connection refused, health checks only | LRT | 1007 ± 73 | 403 |
| Connection refused, health checks only | ASED | 80 ± 5 | 388 |
| Connection refused, + outlier detection | RR | 5639 ± 53 | 1572 |
| Connection refused, + outlier detection | WRR | 70 ± 14 | 955 |
| Connection refused, + outlier detection | LC | 33 ± 1 | 560 |
| Connection refused, + outlier detection | P2C | 73 ± 16 | 1205 |
| Connection refused, + outlier detection | LRT | 30 ± 2 | 402 |
| Connection refused, + outlier detection | ASED | 33 ± 1 | 389 |
| Blackhole (1 s timeout), health checks only | RR | 5772 ± 59 | 1585 |
| Blackhole (1 s timeout), health checks only | WRR | 340 ± 13 | 884 |
| Blackhole (1 s timeout), health checks only | LC | 31 ± 1 | 550 |
| Blackhole (1 s timeout), health checks only | P2C | 128 ± 21 | 1198 |
| Blackhole (1 s timeout), health checks only | LRT | 40 ± 4 | 401 |
| Blackhole (1 s timeout), health checks only | ASED | 22 ± 2 | 390 |
| Blackhole (1 s timeout), + outlier detection | RR | 5735 ± 54 | 1590 |
| Blackhole (1 s timeout), + outlier detection | WRR | 216 ± 10 | 932 |
| Blackhole (1 s timeout), + outlier detection | LC | 31 ± 1 | 550 |
| Blackhole (1 s timeout), + outlier detection | P2C | 103 ± 18 | 1201 |
| Blackhole (1 s timeout), + outlier detection | LRT | 35 ± 3 | 401 |
| Blackhole (1 s timeout), + outlier detection | ASED | 22 ± 2 | 389 |
