# Pull arm results (2026-10-19): arm a (CLAUDE.md) vs arm d (CLAUDE.md tells the agent to query kb context)

Same frozen warm-up kb as phase 2; arm a reused from phase 1. The agent called kb in 18/18 runs. All 18 graded correct.

Totals over all runs (model calls / input tokens / cost): a 150 / 6.1M / $2.27, b (push) 112 / 4.4M / $1.93, c (oracle) 93 / 3.6M / $1.63, d (pull) 127 / 5.1M / $2.00. d captures 33% of the oracle gain (b: 56%).

```
task  arm  n   ok  turns  calls  explore   ctx_k   cost$
B1    a    3 100%     22     14        8     632   0.172
B1    d    3 100%     22     13        8     549   0.162
      -> d vs a: not better (gain 0.00)
B2    a    3 100%     20     16        7     661   0.150
B2    d    3 100%     23     11        7     429   0.130
      -> d vs a: not better (gain 0.00)
C1    a    3 100%     15      5        0     213   0.132
C1    d    3 100%     13      5        0     194   0.102
      -> d vs a: not better (gain 0.00)
C2    a    3 100%     20      5        0     216   0.150
C2    d    3 100%     19      5        0     216   0.146
      -> d vs a: not better (gain 0.00)
C3    a    3 100%      5      4        0     144   0.062
C3    d    3 100%      7      4        0     143   0.062
      -> d vs a: not better (gain 0.00)
C4    a    3 100%     12      4        0     144   0.075
C4    d    3 100%     13      4        0     145   0.078
      -> d vs a: not better (gain 0.00)

d better than a on 0/6 tasks; gate needs >= 4/6 -> FAIL
```
