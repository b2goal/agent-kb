# Phase 1 results (2026-10-19): arm a (CLAUDE.md) vs arm c (oracle pack)

Model claude-sonnet-5-5, Claude Code 2.1.303, 6 tasks x 2 arms x 3 reps, interleaved. All 36 runs graded correct.

```
task  arm  n   ok  turns  calls  explore   ctx_k   cost$
B1    a    3 100%     22     14        8     632   0.172
B1    c    3 100%     15      9        5     351   0.111
      -> c vs a: better (gain 0.38)
B2    a    3 100%     20     16        7     661   0.150
B2    c    3 100%     12      7        3     263   0.090
      -> c vs a: better (gain 0.57)
C1    a    3 100%     15      5        0     213   0.132
C1    c    3 100%      9      3        0     109   0.068
      -> c vs a: better (gain 2.00)
C2    a    3 100%     20      5        0     216   0.150
C2    c    3 100%     13      4        0     173   0.126
      -> c vs a: better (gain 1.00)
C3    a    3 100%      5      4        0     144   0.062
C3    c    3 100%      5      3        0     105   0.052
      -> c vs a: better (gain 1.00)
C4    a    3 100%     12      4        0     144   0.075
C4    c    3 100%     10      4        0     145   0.077
      -> c vs a: not better (gain 0.00)

c better than a on 5/6 tasks; gate needs >= 4/6 -> PASS
```
