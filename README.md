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

本机测过的二进制是 `aura nightly (cf7353373)`。

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

以下数字都是本机（x86_64，8 核，15.6 GB，`aura nightly 856727cc`）跑出来的。行情是种子生成的夹具，不是历史行情。这不是收益承诺。

### 夹具与指标

`lib/tapes.aura` 用 `evo:rng` 按种子生成磁带：8 段、每段 40 根，段落在上行、区间、下行三种行情里按 0.6 的概率延续。种子 7 生成 6 条磁带，每条 7 个窗口。`lib/metrics.aura` 有 Sharpe、最大回撤和 Bailey–López de Prado 的 deflated Sharpe（按试验次数扣掉多重比较带来的期望最大 Sharpe）。

### P1 参数演化 + 样本外门禁

前进式三折：用窗口 1..k-1 训练，在窗口 k 测试，k = 5、6、7，共 18 个样本外窗口。每种搜索每折 64 次评估、种群 8。KEEP 要同时满足：`tune:gate` 在 α=0.05 下通过（对上线规则做配对 t 检验），并且 deflated Sharpe > 0。上线规则样本外合计 1221.13。

| 搜索 | 样本外合计 | t / 临界值 | deflated | DSR | 门禁 | 用时 |
|---|---:|---:|---:|---:|---|---:|
| es | 1427.32 | 0.96 / 1.725 | 0.22 | 0.746 | ROLLBACK | 18.5 s |
| pso | 1758.70 | 2.80 / 1.725 | 0.72 | 0.984 | KEEP | 18.5 s |
| abc | 1266.74 | 0.65 / 1.725 | 0.55 | 0.953 | ROLLBACK | 18.1 s |

提交的搜索事先定为 ES。ES 第 7 折的参数 `(rule-switch 12 6.72 20.0 11)` 在子 workspace 里试验通过、上线代码没动，但门禁 ROLLBACK，上线规则仍是 `(rule-switch 8 2.5 6.0 8)`。PSO 在这组夹具上过了门禁，只是对照，不会因此换成 PSO 提交。同一种子两次运行的 `out/p1.json` 相同。

### P2 风控不变量

最大持仓 10000、最大回撤 150、每 40 根最多 24 笔，写成 workspace 里的 `risk-*` define，作为 `evo:search` 的 constraints，提交前过 `evo:feasible?`。`risk-*` 在提案器的 protected 列表里。

| 对抗候选 | 拦下它的 | 日志 |
|---|---|---|
| oversize-5 / oversize-2 | infeasible: max-pos（也超回撤） | ROLLBACK |
| always-short / inverted | infeasible: max-dd | ROLLBACK |
| flip-every-bar / flip-2-of-3 | infeasible: order-rate | ROLLBACK |
| edit-max-pos / bundle-max-dd | `prop:check-proposal`：protected | ROLLBACK |
| set-in-body / eval-in-body | 本仓库的函数体守卫（`set!`/`eval`/`risk-`） | ROLLBACK |

10/10 被拒，10/10 有 ROLLBACK 记录，上线规则和 `risk-*` 都没变。后两个候选单靠 `prop:check-proposal` 会放行，它只看 define 名字，所以加了函数体守卫。Python 适配器有自己的一套检查（持仓 10000、单笔 20000、每 40 根 32 笔），`paper` 遇到超仓会话和翻手会话都打印 `RISK_BLOCKED` 并返回 3。

### P3 并行候选与在线选择

任务集：训练窗口 1..4（24 个），测试窗口 5..7（18 个），`meta:disjoint?` 为真，故意混入一个测试窗口时能查出来。

| 项目 | 结果 |
|---|---|
| nsga2（盈亏 vs 回撤，种群 16，128 次评估） | 串行 15.1 s，fiber 并行 10.4 s，结果相同 |
| 前沿 | 3 个点，超体积 3124807 → 3309391，单调不降 |
| MAP-Elites（斜率 4 格 × 来回次数 2 格） | 填满 5/8 格，加入 3 个新成员，组合共 8 个 |
| gap-closure（留一法） | 原 3 成员 -0.535；8 成员 kNN k=1 -6.181，k=3 -1.462，tree -3.135 |
| 样本外（18 窗口，在线 feedback + drift） | 选择器 1315.74，SBS（elite-0-0）1825.05，t=-2.59 |

验收没过：gap-closure 没到 1.0，样本外也输给 SBS。新成员在训练窗口里互相很像，kNN 选不准，还不如一直跑最好的那个成员。drift 在 18 个窗口里报了 8 次。

### P4 实时回路

磁带 s99-t1（280 根，三种行情都有）。每根先过前置风控（持仓钳位、频率限制），每笔单子带上特征、成员、规则版本、候选 id，写进 `out/live-session.json`，并在 evo 日志里记一条 `ORDER`。drift 时先 `evo:trial` 最近 80 根，过门禁才 `hot-strategy:swap!`。

| 项目 | 结果 |
|---|---|
| 订单 / 盈亏 / 期末持仓 / 最大回撤 | 30 笔 / 529.78 / -10000 / 83.81 |
| drift 触发的替换 | 4 次全部被门禁拒绝，0 次上线 |
| 第 200 根注入反向规则 | 第 218 根回撤越线，同一根 `heal!`，延迟 0 根，不重启 |
| Python `paper` | 30 笔，盈亏一致，`PIPE_OK` |
| `live --offline` | `DRY_RUN_OK` |

drift 几乎每根都报（276/280），所以靠冷却期（20 根）和重试间隔（10 根）挡住频繁替换。`live --dry-run` 这次没登上 Demo：3 次都是 `Wait timeout exceeded`，Hosts.jsp 探测交易服务器返回 http-500，没有发单。

### P5 LLM 提案（离线）

MiniMax-M3.1-Flash，`reasoning_effort=minimal`，`llm:rate-limit-set! 20`。每轮让模型写 3 个 `(define (rule-entry ...))`，同时给出之前提案的训练盈亏。提案只能改 `rule-*`，与 ES 走同一套门禁（`prop:check-proposal`、函数体守卫、子 workspace 试验、风控约束、`tune:gate` + deflated）。两边同样 12 个候选，与上线规则比样本外（1221.13）。

| 方法 | 候选 | KEEP | 不可行 | 训练最好的那个：训练 / 样本外 | t | 用时 |
|---|---:|---:|---:|---:|---:|---:|
| ES | 12 | 0 | 0 | 1731.65 / 1082.65 | -1.27 | 4.0 s |
| LLM | 12 | 0 | 4 | 1863.22 / 1254.22 | 0.36 | 83.5 s |

5 次调用全部成功，单次 11.7–29.3 s。另一次运行 LLM 的最好结果是 1902.21 / 1197.89，t=-0.27：模型输出不固定，每次结果都会变。两边都没有候选过门禁，LLM 没有显示出明确优势，所以默认关闭，只在 `scripts/evolve.sh` 里有密钥时跑。

P5 还读 `out/p4.json` 写一段中文复盘到 `out/review.md`，不在逐根路径里。

### 资源

| 步骤 | 墙钟 | 等效核数 | 峰值内存 |
|---|---:|---:|---:|
| P1（3 种搜索并行） | 54.8 s | 6.2 | 334 MB |
| P2 | 6.3 s | 1.0 | 309 MB |
| P3 | 46.6 s | 3.0 | 487 MB |
| P4 | 7.0 s | 1.0 | 351 MB |
| P5 | 103.7 s | 0.1（等网络） | 328 MB |

fiber 并行的收益有限：nsga2 只快了约 1.5 倍。主线程在 fiber 跑过之后分配变慢，所以重活都放进 fiber 里跑。

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
| `lib/wf.aura` | 前进式切分、搜索、门禁、提交 |
| `lib/members.aura` / `lib/p1state.aura` | 组合成员、读 P1 结果 |
| `p1-evolve.aura` … `p5-llm.aura` | P1–P5 |
| `scripts/evolve.sh` | 跑 P1–P5，最后打印 `EVOLVE_OK` |
| `bridge/fc_adapter.py` | probe、login、paper、live（含 --offline / --dry-run），自带风控检查 |

订单字段对齐 ForexConnect 的 `create_order_request`：`order_type=OM`（`TRUE_MARKET_OPEN`）、`buy_sell` 为 `B` 或 `S`、`amount` 已经是基础货币单位。live 路径按品种在 OFFERS 里找报价（`Common.get_offer` 会跳过订阅状态不是 `T` 的报价），不会再乘一次 `base_unit_size`。
