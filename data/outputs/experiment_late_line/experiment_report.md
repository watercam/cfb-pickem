# Late line vs close forecast

## 1. Executive summary

**Experiment L:** B. Weak/modest evidence.

On 2282 OOS 1h favorites, A1 log loss 0.5409 vs B1 0.5407; Brier 0.1827 vs 0.1825.

**Experiment S:** Forecast-close beats A24 — 72h→24h movement helps a 24h deadline.

On 2206 OOS games with both p_24 and p_1h (S sample n=3668, with 1h n=3648): A24 log loss 0.5407, Forecast 0.5404, Oracle 0.5408.

The oracle gap is small: the 1h line is not much more informative about winners than the 24h line in this sample.

Late-line experiment from `/Users/cameron/Documents/GitHub/cfb-pickem/data/raw/odds_api/snapshots`. L modeled n=3754; S modeled n=3668. V1 backtest_dataset.parquet and backtest_report.md were not overwritten.

## 2. Credits / new timestamps

- Snapshot horizons (hours): [1, 24, 72]
- Unique planned timestamps: 4460
- Already in cache before this fetch: 3074
- New T-1h GETs this session: 1386
- Estimated credits spent on those GETs: 27720
- Cache after fetch: 4460 / 4460 (rebuild saw 0 missing)
- Book: Pinnacle only. No substitute sportsbook.

## 3. Coverage

- Clock-24 rows with `p_24`: 7546
- Clock-1 rows with `p_1h`: 7528
- Experiment L modeled favorites (1h ML + 24h spread): 3754
- Experiment S modeled favorites (24h ML): 3668
- S favorites that also have `p_1h` (forecast/oracle sample): 3648

| exclusion_code | row_count |
| --- | --- |
| NOT_FBS_VS_FBS | 54320 |
| CANCELLED | 0 |
| NO_FINAL_RESULT | 56 |
| TEAM_UNMAPPED | 54248 |
| MISSING_DECISION_SNAPSHOT | 30 |
| MISSING_REFERENCE_SNAPSHOT | 164 |
| MISSING_1H_SNAPSHOT | 110 |
| MISSING_1H_MONEYLINE | 288 |
| PINNACLE_MISSING | 0 |
| MISSING_CURRENT_MONEYLINE | 350 |
| MISSING_SPREAD | 230 |
| LOOKAHEAD_GUARD | 0 |

## 4. Experiment L (decide at 1h)

**Verdict L: B. Weak/modest evidence**

A1 is clamp(p at 1h). B1 adds a train-only 7×6 lookup on 24h→1h spread move.

| fold_id | test_season | model | n | log_loss | brier | ece | accuracy |
| --- | --- | --- | --- | --- | --- | --- | --- |
| pooled_oos | 2023-2025 | A1 | 2282 | 0.540947 | 0.18269 | 0.0183654 | 0.718668 |
| pooled_oos | 2023-2025 | B1 | 2282 | 0.540688 | 0.182459 | 0.0197466 | 0.717791 |

### 24h→1h movement buckets (L modeled rows)

| movement_bucket | n | mean_current_p | win_rate | raw_residual |
| --- | --- | --- | --- | --- |
| <= -3.0 | 10 | 0.7831 | 0.8 | 0.0169 |
| -3.0 to -1.5 | 98 | 0.7197 | 0.7347 | 0.015 |
| -1.5 to -0.5 | 377 | 0.7158 | 0.7507 | 0.0349 |
| -0.5 to +0.5 | 2238 | 0.717 | 0.7006 | -0.0164 |
| +0.5 to +1.5 | 798 | 0.7444 | 0.7419 | -0.0026 |
| +1.5 to +3.0 | 195 | 0.7133 | 0.7077 | -0.0056 |
| >= +3.0 | 38 | 0.683 | 0.6579 | -0.0251 |

## 5. Experiment S (decide at 24h)

A24 is clamp(p at 24h) vs the game winner. Forecast-close predicts p_1h from `p_24` and `spread_move_72_24` only, then scores clamp(p_hat_1h) vs the winner. Oracle is clamp(actual p_1h) vs the winner — not available at a 24h deadline.

**Forecast-close vs A24:** Forecast **beats** A24 out of sample.

| fold_id | test_season | model | n | log_loss | brier | ece | accuracy |
| --- | --- | --- | --- | --- | --- | --- | --- |
| pooled_oos | 2023-2025 | A24 | 2206 | 0.540669 | 0.182616 | 0.023281 | 0.716682 |
| pooled_oos | 2023-2025 | Forecast | 2206 | 0.540389 | 0.182593 | 0.0229525 | 0.713509 |
| pooled_oos | 2023-2025 | Oracle | 2206 | 0.540808 | 0.182607 | 0.0187318 | 0.718948 |

### Close-forecast error (p_hat_1h vs actual p_1h)

| fold_id | test_season | n | mae | brier |
| --- | --- | --- | --- | --- |
| fold_1 | 2023 | 714 | 0.0118864 | 0.000307431 |
| fold_2 | 2024 | 749 | 0.0120208 | 0.000318196 |
| fold_3 | 2025 | 743 | 0.0114338 | 0.0003127 |
| pooled_oos | 2023-2025 | 2206 | 0.0117796 | 0.000312861 |

## 6. Limitations

- 1 hour before kickoff is not the close; some games may already be underway relative to a 1h target if kickoff timestamps are noisy.
- Missing 1h Pinnacle moneylines drop out of L and of S forecast/oracle.
- A24 can still score games that lack a 1h snapshot.
- Oracle beating A24 is not evidence to ship a 24h→1h movement feature.
- No 4h snapshot, public %, contest sim, or optimizer wiring.

## 7. Go / no-go for a 4h fetch

**No-go for 4h.** L and S do not disagree in a way that needs an in-between clock. Skip 4h until a later question requires it.

## 8. L train matrix (not a production ship unless verdict L is A)

| probability_band | probability_min | probability_max | movement_bucket | movement_min | movement_max | sample_size | raw_adjustment | shrunk_adjustment | ci_lower | ci_upper | production_adjustment |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 50-55% | 0.5 | 0.55 | <= -3.0 | -999 | -3 | 0 | 0 | 0 |  |  | 0 |
| 50-55% | 0.5 | 0.55 | -3.0 to -1.5 | -3 | -1.5 | 11 | 0.0327528 | 0 | -0.238773 | 0.288168 | 0 |
| 50-55% | 0.5 | 0.55 | -1.5 to -0.5 | -1.5 | -0.5 | 57 | 0.0909856 | 0.0227464 | -0.0435547 | 0.201536 | 0 |
| 50-55% | 0.5 | 0.55 | -0.5 to +0.5 | -0.5 | 0.5 | 235 | -0.0192111 | -0.00960554 | -0.0902502 | 0.0452293 | 0 |
| 50-55% | 0.5 | 0.55 | +0.5 to +1.5 | 0.5 | 1.5 | 53 | 0.0127379 | 0.00318447 | -0.113888 | 0.137842 | 0 |
| 50-55% | 0.5 | 0.55 | +1.5 to +3.0 | 1.5 | 3 | 46 | -0.0372462 | -0 | -0.200288 | 0.137276 | 0 |
| 50-55% | 0.5 | 0.55 | >= +3.0 | 3 | 999 | 13 | -0.0663959 | -0 | -0.299295 | 0.215783 | 0 |
| 55-60% | 0.55 | 0.6 | <= -3.0 | -999 | -3 | 0 | 0 | 0 |  |  | 0 |
| 55-60% | 0.55 | 0.6 | -3.0 to -1.5 | -3 | -1.5 | 4 | 0.161577 | 0 | -0.0929929 | 0.431706 | 0 |
| 55-60% | 0.55 | 0.6 | -1.5 to -0.5 | -1.5 | -0.5 | 23 | -0.0627581 | -0 | -0.279693 | 0.153779 | 0 |
| 55-60% | 0.55 | 0.6 | -0.5 to +0.5 | -0.5 | 0.5 | 326 | -0.0747493 | -0.03 | -0.126866 | -0.0189508 | 0 |
| 55-60% | 0.55 | 0.6 | +0.5 to +1.5 | 0.5 | 1.5 | 71 | 0.0908553 | 0.0227138 | -0.0151504 | 0.195491 | 0 |
| 55-60% | 0.55 | 0.6 | +1.5 to +3.0 | 1.5 | 3 | 11 | -0.0227794 | -0 | -0.298779 | 0.25194 | 0 |
| 55-60% | 0.55 | 0.6 | >= +3.0 | 3 | 999 | 6 | -0.0622828 | -0 | -0.394428 | 0.272445 | 0 |
| 60-70% | 0.6 | 0.7 | <= -3.0 | -999 | -3 | 0 | 0 | 0 |  |  | 0 |
| 60-70% | 0.6 | 0.7 | -3.0 to -1.5 | -3 | -1.5 | 25 | -3.90794e-05 | -0 | -0.200075 | 0.175443 | 0 |
| 60-70% | 0.6 | 0.7 | -1.5 to -0.5 | -1.5 | -0.5 | 98 | 0.0340686 | 0.00851715 | -0.0505439 | 0.129566 | 0 |
| 60-70% | 0.6 | 0.7 | -0.5 to +0.5 | -0.5 | 0.5 | 513 | -0.0114571 | -0.0103114 | -0.0492862 | 0.0296073 | 0 |
| 60-70% | 0.6 | 0.7 | +0.5 to +1.5 | 0.5 | 1.5 | 193 | -0.0258536 | -0.0129268 | -0.0894378 | 0.036357 | 0 |
| 60-70% | 0.6 | 0.7 | +1.5 to +3.0 | 1.5 | 3 | 23 | -0.00596002 | -0 | -0.159726 | 0.154709 | 0 |
| 60-70% | 0.6 | 0.7 | >= +3.0 | 3 | 999 | 3 | -0.00918725 | -0 | -0.174475 | 0.321389 | 0 |
| 70-80% | 0.7 | 0.8 | <= -3.0 | -999 | -3 | 7 | -0.0349563 | -0 | -0.444355 | 0.259824 | 0 |
| 70-80% | 0.7 | 0.8 | -3.0 to -1.5 | -3 | -1.5 | 33 | -0.0165821 | -0 | -0.172091 | 0.133936 | 0 |
| 70-80% | 0.7 | 0.8 | -1.5 to -0.5 | -1.5 | -0.5 | 91 | 0.0551322 | 0.013783 | -0.0288703 | 0.129912 | 0 |
| 70-80% | 0.7 | 0.8 | -0.5 to +0.5 | -0.5 | 0.5 | 480 | -0.0254587 | -0.019094 | -0.0627476 | 0.0138297 | 0 |
| 70-80% | 0.7 | 0.8 | +0.5 to +1.5 | 0.5 | 1.5 | 184 | 0.00323462 | 0.00161731 | -0.0590293 | 0.0620873 | 0 |
| 70-80% | 0.7 | 0.8 | +1.5 to +3.0 | 1.5 | 3 | 54 | -0.0181431 | -0.00453578 | -0.116826 | 0.0736376 | 0 |
| 70-80% | 0.7 | 0.8 | >= +3.0 | 3 | 999 | 5 | 0.0193215 | 0 | -0.382766 | 0.231204 | 0 |
| 80-90% | 0.8 | 0.9 | <= -3.0 | -999 | -3 | 3 | 0.138019 | 0 | 0.123064 | 0.152617 | 0 |
| 80-90% | 0.8 | 0.9 | -3.0 to -1.5 | -3 | -1.5 | 19 | 0.0347805 | 0 | -0.108906 | 0.142463 | 0 |
| 80-90% | 0.8 | 0.9 | -1.5 to -0.5 | -1.5 | -0.5 | 73 | 0.0111739 | 0.00279349 | -0.0935185 | 0.0992577 | 0 |
| 80-90% | 0.8 | 0.9 | -0.5 to +0.5 | -0.5 | 0.5 | 450 | 0.0184264 | 0.0138198 | -0.0115422 | 0.0477709 | 0 |
| 80-90% | 0.8 | 0.9 | +0.5 to +1.5 | 0.5 | 1.5 | 181 | -0.0253393 | -0.0126696 | -0.087786 | 0.0311513 | 0 |
| 80-90% | 0.8 | 0.9 | +1.5 to +3.0 | 1.5 | 3 | 42 | 0.0619132 | 0 | -0.0432034 | 0.135208 | 0 |
| 80-90% | 0.8 | 0.9 | >= +3.0 | 3 | 999 | 7 | -0.00469826 | -0 | -0.294318 | 0.156207 | 0 |
| 90%+ | 0.9 | 1 | <= -3.0 | -999 | -3 | 0 | 0 | 0 |  |  | 0 |
| 90%+ | 0.9 | 1 | -3.0 to -1.5 | -3 | -1.5 | 6 | 0.0587499 | 0 | 0.0479507 | 0.0721245 | 0 |
| 90%+ | 0.9 | 1 | -1.5 to -0.5 | -1.5 | -0.5 | 35 | 0.00695809 | 0 | -0.0881998 | 0.0679314 | 0 |
| 90%+ | 0.9 | 1 | -0.5 to +0.5 | -0.5 | 0.5 | 234 | 0.00832476 | 0.00416238 | -0.0272456 | 0.0376174 | 0 |
| 90%+ | 0.9 | 1 | +0.5 to +1.5 | 0.5 | 1.5 | 116 | -0.00185331 | -0.000926657 | -0.0474982 | 0.0400667 | 0 |
| 90%+ | 0.9 | 1 | +1.5 to +3.0 | 1.5 | 3 | 19 | -0.0320006 | -0 | -0.19745 | 0.0745662 | 0 |
| 90%+ | 0.9 | 1 | >= +3.0 | 3 | 999 | 4 | 0.0617062 | 0 | 0.0509163 | 0.0885538 | 0 |
