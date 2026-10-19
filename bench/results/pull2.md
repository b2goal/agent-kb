# Pull v2 results (2026-10-19): arm e = pull + account facts + 'call kb alone first'

Same frozen warm-up kb (relearned with account facts); arm a reused. kb called in 18/18 runs; all 18 correct.

Totals (calls / input tokens / cost): a 150 / 6.1M / $2.27, d 127 / 5.1M / $2.00, e 140 / 5.6M / $2.07, b 112 / 4.4M / $1.93, c 93 / 3.6M / $1.63.
Account facts: B2 exploration 7 -> 3 (= oracle), calls 16 -> 9 (all 3 runs). 'Alone first' adds one call on code tasks (C3, C4: 4 -> 5).

```
task  arm  n   ok  turns  calls  explore   ctx_k   cost$
B1    a    3 100%     22     14        8     632   0.172
B1    e    3 100%     25     13        8     569   0.186
      -> e vs a: not better (gain 0.00)
B2    a    3 100%     20     16        7     661   0.150
B2    e    3 100%     14      9        3     339   0.101
      -> e vs a: better (gain 0.57)
C1    a    3 100%     15      5        0     213   0.132
C1    e    3 100%     14      5        0     195   0.110
      -> e vs a: not better (gain 0.00)
C2    a    3 100%     20      5        0     216   0.150
C2    e    3 100%     17      5        0     209   0.144
      -> e vs a: not better (gain 0.00)
C3    a    3 100%      5      4        0     144   0.062
C3    e    3 100%      6      5        0     178   0.066
      -> e vs a: not better (gain -1.00)
C4    a    3 100%     12      4        0     144   0.075
C4    e    3 100%     12      5        0     179   0.081
      -> e vs a: not better (gain -1.00)

e better than a on 1/6 tasks; gate needs >= 4/6 -> FAIL
```
