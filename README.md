# google-one-tools-offer-reconcile

**离线对账 Google One 订阅 offer 扫描记录：上游把各地区扫描结果落成 `scan_result_*.json`，却没有任何东西校验这些记录是否还符合它自己声明的政策——本工具补上这一格。**

为什么现在需要它：`hatsunemiku-ai/google-one-tools` 的扫描产物会随账号资格和地区上下架而漂移，而仓库里已经固化的记录不会自己更新。用户在 issue 里报「30tb 查不到了」，仓库里五个地区的记录却仍然挂着 `g1.30tb`，没人能离线判断哪条记录已经过期、哪条金额与币种对不上。

Upstream: https://github.com/hatsunemiku-ai/google-one-tools

## 上游是什么、它缺什么

上游是一个用 Frida 注入模拟器内 Google One 进程、调用 Play BillingClient 的工具包：扫描账号可用的全部订阅 offer（免费/付费），并拉起任意 SKU 的 Play 收银台。它把各地区的扫描结果原样提交为 `scan_result_us.json` / `scan_result_gb.json` / `scan_result_hk.json` / `scan_result_in.json` / `scan_result_tr.json`，字段为 `offers[].phases[]`（`micros` / `cur` / `period` / `cycles` / `free` / `fmt`）。

它缺的是**对自身产物的对账能力**，三条真实证据：

- **A 级 · open issue**：[issue #2「30tb现在好像查询不到了？」](https://github.com/hatsunemiku-ai/google-one-tools/issues/2)（open，2 条评论，多名用户确认查不到），而五个地区的记录里 `g1.30tb` 仍以付费 offer 形式存在。
- **B 级 · README 明文声明**：[README.md#L3](https://github.com/hatsunemiku-ai/google-one-tools/blob/main/README.md#L3) ——「`g1.30tb`已在大部分区域下架」。声明与已提交记录直接矛盾，仓库没有任何检查能发现。
- **C 级 · 记录内部不自洽**：多条 `phases[].period` 写成 `P13W1D` / `P4W3D` / `P26W2D`，这不是合法 ISO-8601 时长（ISO-8601 不允许周与天混写）；同一产品在一条记录里重复出现且 `token` 已脱敏为 `<REDACTED>`，无法区分「多个 token」与「扫描重复」。

## 这个工具做什么、不做什么

**做**：读取上游提交的 `scan_result_*.json`（文件或目录），离线执行五类判定，输出结构化报告与明确退出码：

| code | 级别 | 含义 |
|---|---|---|
| `stale_delisted_sku` | error | 记录里仍在宣传的 SKU，命中了用户声明的下架清单 |
| `schema` | error | 缺字段、类型错误、`period` 非法、`cur` 非三位码、`micros` 为负 |
| `amount_coherence` | error | `fmt` 的金额与 `micros` 不符，或 `fmt` 的货币符号与 `cur` 不符 |
| `duplicate_offer` | warning | 同一记录内同产品重复出现且无可区分字段 |
| `region_divergence` | info | 同一产品在不同地区 phase 形状不同（或仅部分地区有） |

**不做**：不连网、不调用 Frida/adb、不猜测账号资格、不修改上游记录、不猜测未声明的下架 SKU（下架清单必须由用户显式提供）。

## 安装 / 用法

零第三方依赖，Python 3.8+ 即可，无需安装：

```bash
git clone https://github.com/linmoxi33/google-one-tools-offer-reconcile.git
cd google-one-tools-offer-reconcile

# 第一条命令：对 examples/ 里的真实上游记录做对账
python3 bin/google-one-offer-reconcile examples/in \
    --json --delisted examples/in/delisted.txt
```

对上游仓库（已 clone 到本地）直接跑：

```bash
python3 bin/google-one-offer-reconcile /path/to/google-one-tools \
    --delisted /path/to/google-one-tools/README.md.delisted
# 或用内联 SKU： --delisted-sku g1.30tb
```

### `--json` 输出示例（节选）

```json
{
  "tool": "google-one-tools-offer-reconcile",
  "version": "1.0.0",
  "records": [{"file": "examples/in/scan_result_us.json", "tag": "us", "candidates": 179, "offers": 59}],
  "delisted_policy": ["g1.30tb"],
  "findings": [
    {"severity": "error", "code": "stale_delisted_sku",
     "file": "examples/in/scan_result_us.json", "product": "g1.30tb",
     "detail": "g1.30tb is declared delisted upstream but is still advertised in this record"},
    {"severity": "error", "code": "schema",
     "file": "examples/in/scan_result_us.json", "product": "g1.2tb.1month_eft",
     "detail": "period must be an ISO-8601 duration, got 'P4W3D'"}
  ],
  "summary": {"error": 16, "warning": 34, "info": 38, "records": 2},
  "ok": false
}
```

### 退出码

| 码 | 含义 |
|---|---|
| `0` | 无 error 级发现 |
| `1` | 存在 error 级发现 |
| `2` | 用法或输入错误（文件不存在、JSON 非法、目录内无 `scan_result_*.json`） |

### 测试

```bash
python3 -m unittest discover -s tests -v   # 15 passed
```

## 本轮创新

**B 档 · 首次把「上游自己提交的扫描产物」当成可对账的证据对象，用「声明-记录一致性」而非「重新扫描」来发现漂移。** 台账里既有的审计都是对上游代码/配置做静态复刻，或对上游运行时行为做差分；没有一条把上游**已经落盘的产物记录**与上游**自己写下的声明**（README 下架声明、issue 中的失效报告）做离线对账。新在三点：(1) 用 `--delisted` 把「上游声明」显式变成可判定的政策输入，而不是硬编码某个 SKU；(2) 把「过期记录」从猜测变成 `stale_delisted_sku` 的确定性判定；(3) 顺带发现上游 `period` 字段并非合法 ISO-8601（`P13W1D` 这类周+天混写），这是重新扫描也看不见、只有对账已提交记录才能得到的结论。与同上游的其它工具无功能重合（上游此前无任何对账脚本）。

## 局限

- 下架清单是**用户输入**：工具不会自动推断哪些 SKU 已下架，必须由使用者从上游 README/issue 提供，否则 `stale_delisted_sku` 不会触发。
- 只读已提交的记录，不重新扫描；记录本身过期时，工具能指出矛盾，但不能替上游刷新数据。
- `amount_coherence` 的货币符号表只覆盖常见币种；未收录的符号会被跳过而不是报错。
- `region_divergence` 是 info 级，地区间真实差异（不同地区不同价）与缺陷需要人工结合上下文判断。
- 上游扫描依赖 Frida/adb 与模拟器，本工具刻意不触碰该链路，因此无法验证「实时扫描结果」与「已提交记录」之间的差异。
