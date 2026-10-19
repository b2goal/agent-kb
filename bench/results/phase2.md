# Phase 2 results (2026-10-19): arm a (CLAUDE.md) vs arm b (kb pack, learned from 6 warm-up sessions)

Model claude-sonnet-5-5, Claude Code 2.1.303. Arm a runs reused from phase 1 (same fixture, model, CLI). 18 arm-b runs; 10 that hit the account usage limit were discarded and re-run. All 36 graded correct.

b captures 56% of the oracle (c) gain on model calls (sum of medians a/b/c = 48/38/30).

```
task  arm  n   ok  turns  calls  explore   ctx_k   cost$
B1    a    3 100%     22     14        8     632   0.172
B1    b    3 100%     18     12        6     502   0.140
      -> b vs a: better (gain 0.25)
B2    a    3 100%     20     16        7     661   0.150
B2    b    3 100%     14     10        3     394   0.114
      -> b vs a: better (gain 0.57)
C1    a    3 100%     15      5        0     213   0.132
C1    b    3 100%     13      4        0     164   0.115
      -> b vs a: better (gain 1.00)
C2    a    3 100%     20      5        0     216   0.150
C2    b    3 100%     16      4        0     166   0.139
      -> b vs a: better (gain 1.00)
C3    a    3 100%      5      4        0     144   0.062
C3    b    3 100%      5      4        0     143   0.061
      -> b vs a: not better (gain 0.00)
C4    a    3 100%     12      4        0     144   0.075
C4    b    3 100%     12      4        0     144   0.076
      -> b vs a: not better (gain 0.00)

b better than a on 4/6 tasks; gate needs >= 4/6 -> PASS
```
