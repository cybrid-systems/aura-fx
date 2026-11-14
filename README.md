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

```sh
python3 bridge/fc_adapter.py probe    # 看本机能不能加载 forexconnect
python3 bridge/fc_adapter.py login    # 只读余额和 EUR/USD，不下单
```

`login` 拒绝 `FXCM_CONNECTION=Real`。`live` 还会再要 `FXCM_LIVE=1`，并且会把夹具里的单子真正送进 Demo。纸面对账通过之前不要加这个开关。

## 这台机器

当前主机是 aarch64。`forexconnect` 没有 aarch64 轮子，FXCM 的 Linux SDK 是 x86_64，所以这里登不上 Demo。纸面管道可以跑。登录要到 x86_64，并且 `pip install forexconnect` 成功之后。

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
| `bridge/fc_adapter.py` | probe、login、paper、live |

订单字段对齐 ForexConnect 的 `create_order_request`：`order_type=OM`（`TRUE_MARKET_OPEN`）、`buy_sell` 为 `B` 或 `S`、`amount` 已经是基础货币单位。live 路径把品种解析成 `SYMBOL`，不会再乘一次 `base_unit_size`。
