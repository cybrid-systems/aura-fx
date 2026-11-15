# aura-fx

Aura 决定下不下单，ForexConnect 负责把单子送到 FXCM Demo。本仓库用 Aura nightly，不自己编译 Aura。

决策在 Aura 里：三套规则放进 `std/portfolio`，`std/algo-select` 的 kNN 按最近 16 根的斜率和来回次数选一套。换规则走 `std/hot-strategy`，进程不重启。经纪商接口是 Python。两边用同一份成交规则对账，对不上就说明管道没通。

这不是收益承诺。行情是一段写死的 EUR/USD 夹具，用来把管道和选择器跑通。

## 安装

Linux x86_64 或 arm64，nightly 即可：

```sh
curl -fsSL https://raw.githubusercontent.com/cybrid-systems/aura/main/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"
```

本机测过的二进制是 `aura nightly (6b84c78b)`。

## 跑通

```sh
bash scripts/pipe.sh
```

脚本做四件事：Aura 写出 `out/session.json`，打印组合差距，热替换一条规则再 heal 回去，然后 Python 用同一条半点差把 63 笔 `OM` 单重放一遍。Aura 的盈亏和 Python 的盈亏必须一致，最后一行是 `PIPE_OK`。

Demo 登录不在这个脚本里。账号放在 `.env`（从 `.env.example` 复制），`.env` 不进 git。

forexconnect 只有 cp35–cp37 的 manylinux x86_64 轮子，要用 Python 3.7（例如 conda-forge 的 `python=3.7`），再装 `forexconnect "numpy<1.22" "pandas<1.4"`。`FXCM_URL` 必须是 `https://www.fxcorporate.com/Hosts.jsp`：走 http 时 Hosts.jsp 返回 500，登录报 ORA-499。

```sh
python3 bridge/fc_adapter.py probe    # 看本机能不能加载 forexconnect
python3 bridge/fc_adapter.py login    # 只读余额和 EUR/USD，不下单
```

`login` 拒绝 `FXCM_CONNECTION=Real`。`live` 还会再要 `FXCM_LIVE=1`，并且会把夹具里的单子真正送进 Demo。纸面对账通过之前不要加这个开关。

Demo 账户是对冲模式（`maintenance_type=Y`），反向开仓会变成锁仓。`live` 按净持仓下单：先用 `TRUE_MARKET_CLOSE` + `TRADE_ID` 平掉反向仓位（先开先平），剩下的再用 `TRUE_MARKET_OPEN` 开。

```sh
python3 bridge/fc_adapter.py live --offline              # 不登录，从空仓打印每笔的平/开计划
python3 bridge/fc_adapter.py live --dry-run              # 登录读当前持仓，打印计划，一笔不发
FXCM_LIVE=1 python3 bridge/fc_adapter.py live --max 1    # 先试 1 笔
FXCM_LIVE=1 python3 bridge/fc_adapter.py live --skip 1 --all   # 再跑剩下 62 笔
```

发单必须带 `--max N` 或 `--all`。休市时（纽约时间周五 17:00 到周日 17:15，约北京时间周六 06:00 到周一 06:15）FXCM 拒单，`live` 看到报价 `trading_status` 不是 `O`，或报价时间超过 5 分钟没动，就打印 `MARKET_CLOSED`，不发单。周六实测 Demo 报价仍显示 `trading_status=O`，只有报价时间停在周五收盘，所以要看报价时间。某一笔被拒或没成交就停在那一笔，并打印已完成几笔。

登录超时（`Wait timeout exceeded`）会换一个新会话重试，最多 3 次。这个错误说明会话在 SDK 写死的 30 秒内没到 `CONNECTED`，不是密码错（密码错会直接报 FXCM 的原因，不重试）。在本机上，进程里第一个会话要约 72 秒才连上，登出后第二次一般就能连上。三次都失败时会打印 Hosts.jsp 给出的 Demo 交易服务器地址和探测结果。

## 这台机器

当前主机是 aarch64。`forexconnect` 没有 aarch64 轮子，FXCM 的 Linux SDK 是 x86_64，所以这里登不上 Demo。纸面管道可以跑。登录要到 x86_64，并且在 Python 3.7 里 `pip install forexconnect` 成功之后。x86_64 + Python 3.7 + https 地址已实测登上 Demo（只读 `login` 输出 `LOGIN_OK`）。

## 夹具上量到的差距

240 根夹具，三段：上行、区间、下行。每段切两窗。一手 10000 欧元，半点差 0.00008。窗口分数是报价货币盈亏。

| 窗口 | trend | meanrev | breakout |
|---|---:|---:|---:|
| up-a / up-b | 91.2 | -92.8 | 91.2 |
| range-a / range-b | -270.4 | 233.6 | 0 |
| down-a / down-b | 102.7 | -104.3 | 102.7 |

`std/algo-select` 的报告：SBS 64.63，VBS 142.50，留一法 142.50，gap-closure 1.0，6 个窗口全中。

整段重放，不是留一法：

| 规则 | 盈亏 |
|---|---:|
| 只跑 trend | -374.3 |
| 只跑 meanrev | 244.7 |
| 只跑 breakout | 546.1 |
| kNN 选择器 | 1220.1 |

选择器在趋势段用 trend（140 根），在区间段用 meanrev（84 根），没有用到 breakout。结束时仍持有 1 手空单，因为下行段还没走完。这是夹具的结尾，不是实盘持仓。

热替换：`band` 在 1.12 上先给出 1，把阈值从 1.11 放到 1.20 后给出 -1，`heal!` 之后回到 1。`HOT_OK`。

## 演化：P1–P5

```sh
bash scripts/evolve.sh
```

脚本依次跑 P1（跑两遍，`out/p1.json` 必须逐字节相同）、P2、两份对抗会话的适配器风控、P3、P4、对 `out/live-session.json` 做纸面对账和 `live --offline`，有 `MINIMAX_API_KEY` 时再跑 P5，最后一行是 `EVOLVE_OK`。每一步打印墙钟、CPU 时间、等效核数和子进程峰值内存。不登录 FXCM，不发单。密钥只从环境变量读，不打印。

以下数字都是本机（x86_64，8 核，15.6 GB，`aura nightly 6b84c78b`）跑出来的。机器上另有一个进程常驻约 2 个核，墙钟会有波动。行情是种子生成的夹具，不是历史行情。这不是收益承诺。

### 夹具与指标

`lib/tapes.aura` 用 `evo:rng` 按种子生成磁带：8 段、每段 40 根，段落在上行、区间、下行三种行情里按 0.6 的概率延续。种子 7 生成 6 条磁带，每条 7 个窗口。`lib/metrics.aura` 有 Sharpe、最大回撤和 Bailey–López de Prado 的 deflated Sharpe（按试验次数扣掉多重比较带来的期望最大 Sharpe）。

aura#5290 修好之后，相邻种子的随机流不再相关，`tape-rng` 去掉了自己的混合和预热，直接用 `(evo:rng seed tape segment)`。磁带因此和旧版不同：种子 7 这组趋势段更多（有一条 8 段全是上行），上线规则的样本外合计从 1221.13 变成 2274.35。下面新旧数字不能直接比大小。

### P1 参数演化 + 样本外门禁

前进式三折：用窗口 1..k-1 训练，在窗口 k 测试，k = 5、6、7，共 18 个样本外窗口。每种搜索每折 64 次评估、种群 8。KEEP 要同时满足：`tune:gate` 在 α=0.05 下通过（对上线规则做配对 t 检验），并且 deflated Sharpe > 0。

提交用的搜索事先定为 race：第 k 折用哪种算法，由 `tune:race` 在第 k-2、k-1 两折的测试窗口上决定（每种算法在 j 之前的窗口上拟合、在窗口 j 上打分，6 条磁带 × 2 折 = 12 个配对样本）。第 k 折的测试窗口不参与选择。选出的算法在第 k 折的参数再拿去测窗口 k。deflated Sharpe 按三种算法在 3..7 五折里打过分的所有候选计数（960 次）。

| 搜索 | 样本外合计 | t / 临界值 | deflated | DSR | 试验数 | 门禁 |
|---|---:|---:|---:|---:|---:|---|
| 上线规则 `(8 2.5 6.0 8)` | 2274.35 | | | | | |
| es | 2347.08 | 2.37 / 1.725 | 2.00 | 1.000 | 192 | KEEP |
| pso | 2375.86 | 2.34 / 1.725 | 1.29 | 0.981 | 192 | KEEP |
| abc | 2276.41 | 0.10 / 1.725 | 2.28 | 1.000 | 192 | ROLLBACK |
| **race（提交）** | 2347.08 | 2.37 / 1.725 | 1.42 | 0.994 | 960 | **KEEP** |

race 三折都选了 es。第 7 折参数 `(rule-switch 7 3.84 2.0 10)` 在子 workspace 里试验通过，`evo:commit!` 经 `hot-strategy:swap!` 上线，后面 P2–P5 都从它启动。两次运行的 `out/p1.json` 相同。

这个 KEEP 不稳。同样的代码换夹具再跑（不进 `evolve.sh`）：

| 夹具 | 上线规则 | es | pso | abc | race |
|---|---:|---:|---:|---:|---:|
| 种子 7（本版磁带） | 2274.35 | 2347.08 KEEP | 2375.86 KEEP | 2276.41 | 2347.08 KEEP |
| 种子 7（旧的混合种子磁带） | 1081.70 | 1543.60 | 1323.50 | 1230.87 | 1367.14 |
| 种子 11 | 1269.25 | 1461.65 | 1533.51 | 1332.19 | 1457.59 |
| 种子 23 | 1137.89 | 1676.59 KEEP | 1493.70 | 1320.85 | 1450.77 |

四组里 race 只过了一组，es 过了两组，pso 过了一组。race 多付的试验数让 deflated Sharpe 更难过，在这几组上也没有比单用 es 更好。所以「换成 PSO」或「race 选算法」都没有显示出稳定优势。race 留作提交方式，是因为它事先定好、不偷看测试窗口，不是因为它更强。

P1 现在要跑五折（3..7，前两折只给 race 用），墙钟从约 55 s 涨到 66–84 s，等效 5.9 核。

### P2 风控不变量

最大持仓 10000、最大回撤 150、每 40 根最多 24 笔，写成 workspace 里的 `risk-*` define，作为 `evo:search` 的 constraints，提交前过 `evo:feasible?`。`risk-*` 在提案器的 protected 列表里。

| 对抗候选 | 拦下它的 | 日志 |
|---|---|---|
| oversize-5 / oversize-2 | infeasible: max-pos（也超回撤） | ROLLBACK |
| always-short / inverted | infeasible: max-dd | ROLLBACK |
| flip-every-bar / flip-2-of-3 | infeasible: order-rate | ROLLBACK |
| edit-max-pos / bundle-max-dd | `prop:check-proposal`：protected | ROLLBACK |
| set-in-body / eval-in-body | `prop:check-proposal`：protected | ROLLBACK |

10/10 被拒，10/10 有 ROLLBACK 记录，上线规则和 `risk-*` 都没变。aura#5291 修好后，函数体里对 `risk-*` 的 `set!` / `eval` 由 `prop:check-proposal` 自己拦下（旧版它会放行）。本仓库的函数体守卫保留，作为第二道：它对任何名字的 `set!`、`eval`、`mutate`、`getenv`、`write-file` 都拒，protected 列表管不到这些。Python 适配器有自己的一套检查（持仓 10000、单笔 20000、每 40 根 32 笔），`paper` 遇到超仓会话和翻手会话都打印 `RISK_BLOCKED` 并返回 3。

### P3 并行候选与在线选择

任务集：训练窗口 1..4（24 个），测试窗口 5..7（18 个），`meta:disjoint?` 为真，故意混入一个测试窗口时能查出来。

| 项目 | 结果 |
|---|---|
| nsga2（盈亏 vs 回撤，种群 16，128 次评估） | 串行 12.0 s，fiber 并行 8.7–11.7 s，结果相同 |
| 前沿 | 超体积 2860560 → 3282859，单调不降 |
| MAP-Elites（斜率 4 格 × 来回次数 2 格） | 填满 5/8 格，加入 5 个新成员，组合共 10 个 |
| gap-closure（留一法） | 原 3 成员 0.65；10 成员 kNN k=1 -5.68，k=3 -1.48，tree -0.43 |
| 样本外：kNN 选择器 | 2318.80，SBS（elite-2-0）2414.93，t=-2.04 |
| 样本外：regime 选择器（`lib/regime.aura`） | 2414.93，与 SBS 相同，t=0 |
| 样本外：事后最优（oracle） | 2430.74 |

验收没过，选择器没有超过 SBS。

`lib/regime.aura` 是这次换上的选择器：用窗口开始前一根的斜率（上/平/下）和来回次数（高/低）分格，切点取训练特征的中位数。默认跑 SBS，某一格里只有在 `tune:gate`（α=0.10，至少 3 个窗口）认为别的成员确实赢过 SBS 时才换，测试窗口收盘后才把它加进格子。结果 18 个窗口一次都没离开 SBS，所以不再输给 SBS（kNN 少 96），但也赢不了。

原因在夹具本身：事后最优只比 SBS 多 15.8（18 个窗口）。10 个成员大多是同一族 `rule-switch`，elite-2-0 几乎在每个窗口都是最好或并列最好；行情在窗口边界上才换段，开窗前的特征反映的是上一段。选择器能拿的空间不到 1%，这组夹具上没有可学的东西。要让选择器有意义，成员得更不一样（不同的规则族），或者特征要有前瞻性，这两样都不是换选择算法能解决的。

aura#5292 修好后，串行基线改回在主线程直接 `map`，`portfolio:matrix` 也不再包进 fiber。并行仍只快 1.0–1.4 倍：规则闭包每根都读捕获的参数，这种循环多 fiber 扩展不上去，已建 aura#5297。

### P4 实时回路

磁带 s99-t0（280 根，上行、区间、下行都有）。每根先过前置风控（持仓钳位、频率限制），每笔单子带上特征、成员、规则版本、候选 id，写进 `out/live-session.json`，并在 evo 日志里记一条 `ORDER`。

drift 改用 Page-Hinkley（`lib/drift.aura`），看的是上线规则每根的盈亏是否开始持续低于自己的均值。δ、λ 在种子 7 的 6 条磁带上标定（网格 δ∈{0,1,2,4} × λ∈{50,…,300}，按「行情换段后 40 根内报警」算命中，取命中减误报最大的一组，平局取报警少的），不看实盘磁带。标定结果 δ=0、λ=150。报警后由 regime 选择器按当前特征挑成员，先 `evo:trial` 最近 80 根，过门禁才 `hot-strategy:swap!`。如果报警时在跑的规则不是过过门禁的成员（比如注入的那条），直接 `hot-strategy:heal!` 回上一版。

| 项目 | 旧触发（kNN `select:drift?`） | 新触发（Page-Hinkley） |
|---|---:|---:|
| 报漂移的根数 | 264 / 280 | 1 次报警 |
| 尝试替换 | 6 次（1 次上线，5 次被拒） | 0 次 |
| 第 200 根注入反向规则后 | 第 221 根被一次普通替换换掉，没有走 heal | 第 225 根报警，同一根 `heal!`，延迟 0 根 |
| 订单 / 盈亏 / 期末持仓 / 最大回撤 | 23 / 611.28 / -10000 / 57.19 | 23 / 584.25 / -10000 / 70.7 |
| `P4_OK` | 否 | 是 |

两列是同一份代码、同一条磁带，只换触发条件。Page-Hinkley 唯一的一次报警就是注入的故障（25 根后发现，回撤 66.95，还没到 75 的 heal 线）。4 次行情换段一次都没报：上线规则在这几次换段时没有亏，所以按这个检测器的定义不算漂移。标定集上 14 次换段也只命中 1 次（λ=50 时命中 3 次、误报 2 次），它是一个「规则在亏」的检测器，不是行情换段检测器。新触发的盈亏比旧的少 27，因为注入的规则多跑了 4 根。

aura#5299：`select:drift?` 的奖励漂移项阈值不随样本量折算，平稳的 i.i.d. 流上也有约 45% 的步数报漂移，这是 264/280 的主要原因。heal 之后 `hot-strategy:version` 不变，heal 之后的订单仍标 `rule-rev=2`（与被撤回的那条同号），已建 aura#5298。

| 其他 | 结果 |
|---|---|
| Python `paper` | 23 笔，盈亏一致，`PIPE_OK` |
| `live --offline` | `DRY_RUN_OK` |

另修了本仓库一个越界：旧代码第 80 根起就可能去取「最近 80 根」窗口，会读到第 1 根之前，现在第 119 根起才尝试替换。

### P5 LLM 提案（离线）

MiniMax-M3.1-Flash，`reasoning_effort=minimal`，`llm:rate-limit-set! 20`。每轮让模型写 3 个 `(define (rule-entry ...))`，同时给出之前提案的训练盈亏。提示里现在写明搜索用的参数范围（n 4..24、trend-pips 0.5..10、fade-pips 2..20、chop-split 2..16）、上线规则（P1 提交后的那条）按行情分的训练盈亏、训练段上斜率和来回次数的 10/50/90 分位。提案只能改 `rule-*`，与 ES 走同一套门禁（`prop:check-proposal`、函数体守卫、子 workspace 试验、风控约束、`tune:gate` + deflated）。两边同样 12 个候选，与上线规则比样本外（2297.29）。

| 方法 | 候选 | KEEP | 不可行 | 训练最好的那个：训练 / 样本外 | t | 用时 |
|---|---:|---:|---:|---:|---:|---:|
| ES | 12 | 0 | 0 | 1891.33 / 2205.93 | -2.94 | 3.6 s |
| LLM | 12 | 0 | 2（回撤超限） | 1983.91 / 1970.20 | -4.14 | 40.8 s |

5 次调用全部成功，单次 3.0–14.2 s，`llm:call-stats` 记到 success 5（aura#5293 修好前一直是 0）。连续多次 `evo:trial` 之后 `getenv` 不再被拒（aura#5289），所以去掉了按批提交的绕法说明和读环境变量的探针。LLM 训练段上比 ES 好，但样本外更差，两边都没有候选过门禁，默认仍关闭，只在 `scripts/evolve.sh` 里有密钥时跑。

提示里还加了两句绕法：保持仓位写 `(+ prev 0)` 而不是 `prev`，不要在同一条规则里混用整数分支和 `rule-switch` 调用。原因是 Aura 的 rebind 类型门会误拒这类写法（aura#5300）：没加时，12 个提案里有 11 个在 `evo:trial` 的 apply 那一步就被拒，没进回测。只加第一句时，两次运行仍各有 6、8 个被类型门拒掉；两句都加上、再说明斜率已经是点数不要再乘 10000 之后，表里这一次没有被类型门拒的，2 个不可行都是回撤超限。这只是一次运行，模型输出每次都会变。

P5 还读 `out/p4.json` 写一段中文复盘到 `out/review.md`，不在逐根路径里。

### 资源

| 步骤 | 墙钟 | 等效核数 | 峰值内存 |
|---|---:|---:|---:|
| P1（每批 8 个候选并行） | 66–84 s | 5.9 | 401 MB |
| P2 | 6.8–8.7 s | 1.0 | 315 MB |
| P3 | 41–47 s | 3.1–3.6 | 487 MB |
| P4 | 8.6–9.0 s | 1.5–1.7 | 381 MB |
| P5 | 39–49 s | 0.3（等网络） | 331 MB |

aura#5292 修好后，跑过 fiber 的主线程分配不再变慢（原 issue 的复现：hash 循环 2958 ms → 147 ms）。但 fiber 并行本身仍受 aura#5297 限制。

## 布局

| 路径 | 作用 |
|---|---|
| `lib/tape.aura` | 240 根夹具 |
| `lib/signal.aura` | trend / meanrev / breakout，以及 slope、chop |
| `lib/book.aura` | 纸面成交和 `OM` 订单 |
| `lib/desk.aura` | portfolio + kNN |
| `main.aura` | 写出 `out/session.json` |
| `advantage.aura` | SBS / VBS / 整段盈亏 |
| `hot.aura` | 一条规则的 swap / heal |
| `lib/tapes.aura` | 按种子生成的磁带和窗口 |
| `lib/metrics.aura` | Sharpe、回撤、deflated Sharpe |
| `lib/engine.aura` | 可调规则、模拟、风控 define、并行 map |
| `lib/regime.aura` | 按行情分格、默认 SBS 的选择器 |
| `lib/drift.aura` | Page-Hinkley 漂移检测与标定打分 |
| `lib/wf.aura` | 前进式切分、搜索、race、门禁、提交 |
| `lib/members.aura` / `lib/p1state.aura` | 组合成员、读 P1 结果 |
| `p1-evolve.aura` … `p5-llm.aura` | P1–P5 |
| `scripts/evolve.sh` | 跑 P1–P5，最后打印 `EVOLVE_OK` |
| `bridge/fc_adapter.py` | probe、login、paper、live（含 --offline / --dry-run），自带风控检查 |

订单字段对齐 ForexConnect 的 `create_order_request`：`order_type=OM`（`TRUE_MARKET_OPEN`）、`buy_sell` 为 `B` 或 `S`、`amount` 已经是基础货币单位。live 路径按品种在 OFFERS 里找报价（`Common.get_offer` 会跳过订阅状态不是 `T` 的报价），不会再乘一次 `base_unit_size`。
