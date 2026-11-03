| het      | regressor   | spec                                       | term                |    coef |      se |       p |     n | note                                         |
|:---------|:------------|:-------------------------------------------|:--------------------|--------:|--------:|--------:|------:|:---------------------------------------------|
| mw50     | q_pc10k_l1  | (4) state x year x type FE                 | q_pc10k_l1          |  -0.896 |   0.286 |   0.002 | 20983 |                                              |
| mw50     | q_pc10k_l1  | (4) state x year x type FE                 | q_pc10k_l1:typ      |   0.850 |   0.271 |   0.002 | 20983 |                                              |
| mw50     | q_pc10k_l1  | (5) county x type + state x year x type FE | q_pc10k_l1          |  -4.495 |   7.403 |   0.544 |  2526 |                                              |
| mw50     | q_pc10k_l1  | (5) county x type + state x year x type FE | q_pc10k_l1:typ      |   4.559 |   7.385 |   0.537 |  2526 |                                              |
| mw50     | q_zero_l1   | (4) state x year x type FE                 | q_zero_l1           |  -0.624 |   0.396 |   0.115 | 20983 |                                              |
| mw50     | q_zero_l1   | (4) state x year x type FE                 | q_zero_l1:typ       |   0.678 |   0.370 |   0.067 | 20983 |                                              |
| mw50     | q_zero_l1   | (5) county x type + state x year x type FE | q_zero_l1           |  12.842 | nan     | nan     |  2526 | SUSPECT: likely separation / non-convergence |
| mw50     | q_zero_l1   | (5) county x type + state x year x type FE | q_zero_l1:typ       | -12.917 |   0.265 |   0.000 |  2526 | SUSPECT: likely separation / non-convergence |
| ai       | q_pc10k_l1  | (4) state x year x type FE                 | q_pc10k_l1          |  -0.200 |   0.141 |   0.157 | 22894 |                                              |
| ai       | q_pc10k_l1  | (4) state x year x type FE                 | q_pc10k_l1:typ      |   0.263 |   0.261 |   0.313 | 22894 |                                              |
| ai       | q_pc10k_l1  | (5) county x type + state x year x type FE | q_pc10k_l1          |  -0.222 |   0.240 |   0.355 |  2909 |                                              |
| ai       | q_pc10k_l1  | (5) county x type + state x year x type FE | q_pc10k_l1:typ      |   0.306 |   0.305 |   0.315 |  2909 |                                              |
| ai       | q_zero_l1   | (4) state x year x type FE                 | q_zero_l1           |  -0.179 |   0.167 |   0.284 | 22894 |                                              |
| ai       | q_zero_l1   | (4) state x year x type FE                 | q_zero_l1:typ       |   0.506 |   0.222 |   0.023 | 22894 |                                              |
| ai       | q_zero_l1   | (5) county x type + state x year x type FE | q_zero_l1           |  -0.029 |   0.298 |   0.923 |  2909 |                                              |
| ai       | q_zero_l1   | (5) county x type + state x year x type FE | q_zero_l1:typ       |  -1.557 |   1.154 |   0.177 |  2909 |                                              |
| btm      | q_pc10k_l1  | (4) state x year x type FE                 | q_pc10k_l1          |  -0.306 |   0.157 |   0.052 | 19863 |                                              |
| btm      | q_pc10k_l1  | (4) state x year x type FE                 | q_pc10k_l1:typ      |   0.688 |   0.140 |   0.000 | 19863 |                                              |
| btm      | q_pc10k_l1  | (5) county x type + state x year x type FE | q_pc10k_l1          |  -0.136 |   0.168 |   0.420 |  2843 |                                              |
| btm      | q_pc10k_l1  | (5) county x type + state x year x type FE | q_pc10k_l1:typ      |   0.402 |   0.172 |   0.019 |  2843 |                                              |
| btm      | q_zero_l1   | (4) state x year x type FE                 | q_zero_l1           |  -0.129 |   0.190 |   0.498 | 19863 |                                              |
| btm      | q_zero_l1   | (4) state x year x type FE                 | q_zero_l1:typ       |   0.538 |   0.365 |   0.140 | 19863 |                                              |
| btm      | q_zero_l1   | (5) county x type + state x year x type FE | q_zero_l1           |  -0.246 |   0.260 |   0.344 |  2843 |                                              |
| btm      | q_zero_l1   | (5) county x type + state x year x type FE | q_zero_l1:typ       |   0.215 |   0.508 |   0.672 |  2843 |                                              |
| post2021 | q_pc10k_l1  | (4) state x year FE                        | q_pc10k_l1          |  -1.384 |   0.705 |   0.050 | 15714 |                                              |
| post2021 | q_pc10k_l1  | (4) state x year FE                        | q_pc10k_l1:post2021 |   1.323 |   0.764 |   0.083 | 15714 |                                              |
| post2021 | q_pc10k_l1  | (5) county FE + state x year FE            | q_pc10k_l1          |  -1.471 |   0.838 |   0.079 |  2953 |                                              |
| post2021 | q_pc10k_l1  | (5) county FE + state x year FE            | q_pc10k_l1:post2021 |   1.604 |   0.938 |   0.087 |  2953 |                                              |
| post2021 | q_zero_l1   | (4) state x year FE                        | q_zero_l1           |  -1.254 |   0.810 |   0.121 | 15714 |                                              |
| post2021 | q_zero_l1   | (4) state x year FE                        | q_zero_l1:post2021  |   1.229 |   0.774 |   0.112 | 15714 |                                              |
| post2021 | q_zero_l1   | (5) county FE + state x year FE            | q_zero_l1           |  -1.447 |   0.915 |   0.114 |  2953 |                                              |
| post2021 | q_zero_l1   | (5) county FE + state x year FE            | q_zero_l1:post2021  |   1.294 |   0.846 |   0.126 |  2953 |                                              |
