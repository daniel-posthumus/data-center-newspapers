| term    |   coef |    se |     p |    n | sample                  | spec                            | outcome      |
|:--------|-------:|------:|------:|-----:|:------------------------|:--------------------------------|:-------------|
| q_pc10k |  0.322 | 0.437 | 0.463 |  765 | announced >= 2024-07-01 | bivariate                       | detect_lag_m |
| q_pc10k |  0.297 | 0.414 | 0.474 |  765 | announced >= 2024-07-01 | controls                        | detect_lag_m |
| q_pc10k | -0.248 | 0.342 | 0.468 |  762 | announced >= 2024-07-01 | controls + state FE + ann-month | detect_lag_m |
| q_zero  |  0.564 | 0.499 | 0.259 |  765 | announced >= 2024-07-01 | bivariate                       | detect_lag_m |
| q_zero  |  0.075 | 0.452 | 0.868 |  765 | announced >= 2024-07-01 | controls                        | detect_lag_m |
| q_zero  |  0.195 | 0.393 | 0.621 |  762 | announced >= 2024-07-01 | controls + state FE + ann-month | detect_lag_m |
| q_pc10k | -0.333 | 1.740 | 0.848 | 1065 | all dated               | bivariate                       | detect_lag_m |
| q_pc10k |  2.338 | 1.831 | 0.202 | 1065 | all dated               | controls                        | detect_lag_m |
| q_pc10k | -0.116 | 0.364 | 0.751 | 1029 | all dated               | controls + state FE + ann-month | detect_lag_m |
| q_zero  | -3.621 | 1.436 | 0.012 | 1065 | all dated               | bivariate                       | detect_lag_m |
| q_zero  | -3.461 | 1.434 | 0.016 | 1065 | all dated               | controls                        | detect_lag_m |
| q_zero  |  0.049 | 0.420 | 0.907 | 1029 | all dated               | controls + state FE + ann-month | detect_lag_m |
