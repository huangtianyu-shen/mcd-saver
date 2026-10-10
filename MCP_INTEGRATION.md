# MCP 接入说明

> 本文说明本项目实际使用的麦当劳中国官方 MCP 服务、调用的工具、调用流程，
> 以及这些能力组合后产生的业务价值。
> 文中所有字段名与返回结构均来自真实调用抓包，可对照 `references/data-shapes.md` 核验。

---

## 一、接入的 MCP Server

| 项目 | 内容 |
|---|---|
| 官方仓库 | <https://github.com/M-China/mcd-mcp-server> |
| 接入地址 | `https://mcp.mcd.cn` |
| 传输协议 | Streamable HTTP（MCP 协议版本 `2025-06-18`） |
| 服务端标识 | `mcd-mcp v1.0.0` |
| 鉴权方式 | 请求头 `Authorization: Bearer <MCP Token>` |
| Token 申请 | <https://open.mcd.cn/mcp>（手机号登录 → 控制台 → 激活） |
| 工具总数 | 35（本项目实际使用 13 个） |

### 配置方式

```json
{
  "mcpServers": {
    "mcd-mcp": {
      "type": "streamablehttp",
      "url": "https://mcp.mcd.cn",
      "headers": {
        "Authorization": "Bearer YOUR_MCP_TOKEN"
      }
    }
  }
}
```

Token 只通过环境变量 `MCD_MCP_TOKEN` 或客户端配置文件传入，
**不写入任何随项目公开的文件**（仓库内仅提供 `.env.example` 占位）。

### 客户端实现

`scripts/mcp_client.py` 是一个零第三方依赖的 MCP Streamable HTTP 客户端，
自行实现了完整握手与调用：

```
initialize → notifications/initialized → tools/list → tools/call
```

两个实现要点：

1. **响应体双格式兼容**：服务端对同一方法既会返回纯 JSON，也会返回 SSE
   （`data:` 行）格式，客户端两者都能解析。
2. **业务错误与协议错误分离**：麦当劳的业务失败走
   `success:false` + `code` + `message`（如 `600012` 每单限购、`600050` 无收藏门店），
   这不是 MCP 协议错误，客户端不对其进行网络重试，而是原样上报给上层决策。

---

## 二、实际调用的 Tool

共 13 个，按用途分组。

### 1. 时间与门店

| Tool | 用途 | 关键返回 |
|---|---|---|
| `now-time-info` | 对齐服务端时间，判断券是否"已到使用时间"、活动是否生效 | `data.datetime`、星期几 |
| `query-nearby-stores` | 按城市 + 关键词定位门店 | `storeCode`、`storeName`、`beType` |

### 2. 优惠券（省钱核心）

| Tool | 用途 | 关键返回 |
|---|---|---|
| `available-coupons` | 拉取"麦麦省"可领券列表 | 券名 + 图片（**无 couponId**） |
| `auto-bind-coupons` | 一键领券 | 领取结果 |
| `query-my-coupons` | 读取券包（领券后才带 ID） | `id`、`code`、`discountInfo`、`instructions.labels` |
| `query-store-coupons` | **校验某门店某场景真正可用的券** | 门店维度可用券列表 |

### 3. 菜单与餐品

| Tool | 用途 | 关键返回 |
|---|---|---|
| `query-meals` | 拉门店菜单 | 仅 `code` + `tags`，**无名称无价格** |
| `query-meal-detail` | 补商品名称 | 商品名（价格常缺失） |

### 4. 价格与试算

| Tool | 用途 | 关键返回 |
|---|---|---|
| `calculate-price` | ⭐ **权威定价引擎**，返回真实实付 | `data.price`（单位：分）、`takeWayList` |

### 5. 活动、积分与抽奖

| Tool | 用途 | 关键返回 |
|---|---|---|
| `campaign-calendar` | 活动日历，用于"择时" | `dailyList[].events` |
| `query-my-account` | 会员积分余额 | 可用积分 |
| `mall-points-products` | 积分商城兑换项 | `spuName`、`point`、`price` |
| `query-lottery-info` | 积分抽奖活动 | 奖品池、单次消耗积分 |

---

## 三、调用流程

### 主链路：一键省钱巡检

```
now-time-info                 对齐服务端时间
      ↓
query-nearby-stores           定位门店 → storeCode
      ↓
available-coupons             看有哪些券可领
      ↓
auto-bind-coupons             领进券包（可领券无 ID，必须先领）
      ↓
query-my-coupons              取带 couponId 的券对象
      ↓
query-store-coupons      ┐
query-meals              ├─→  门店可用券 + 菜单 + 商品名
query-meal-detail        ┘
      ↓
calculate-price  ←────────── 单件试算补齐零售价（菜单接口无价格）
      ↓
【本地穷举搜索】单券 / 多券组合 / 凑单方案 → 剪枝 → 候选方案集
      ↓
calculate-price  ←────────── 逐个候选方案真实试算（权威定价）
      ↓
取最低实付方案 + 凑单净收益建议
```

### 并行链路：积分与活动

```
query-my-account         →  积分余额
mall-points-products     →  兑换项 → 计算"元/分"，排序
query-lottery-info       →  抽奖消耗 → 用机会成本算盈亏平衡线
campaign-calendar        →  今日/未来活动 → 择时建议
```

---

## 四、为什么这样编排：业务价值

单个 MCP 工具都很"碎"——菜单接口不给价格、可领券接口不给 ID、
券包接口不做门店校验。真正产生价值的是**把这些原子能力编排成闭环**。

### 1. 券叠加规则是黑盒 → 用试算代替推算

麦当劳的券叠加规则、门槛判定、可用性校验全在服务端。
本地写死规则推算，必然与真实结算价不符。

> 因此本项目采用 **本地穷举搜索 + 服务端权威定价**：
> 本地枚举单券 / 多券组合 / 凑单方案并剪枝，再逐个调用
> `calculate-price` 真实试算，取最低实付。

这是人工做不到的部分：一次巡检会发起数十次真实试算。

### 2. 实测发现的三条隐性规则（官方文档未写明）

这三条直接决定"能不能真的省到钱"，全部来自真实调用验证：

| # | 发现 | 影响 |
|---|---|---|
| 1 | `available-coupons` 只返回券名和图片，**没有 `couponId` / `couponCode`** | 拿去试算会被拒（`使用优惠券需要couponId和couponCode`），必须先 `auto-bind-coupons` 领进券包 |
| 2 | `query-my-coupons` **不做门店与渠道校验** | 实测券包 5 张，指定门店到店场景**只有 1 张真能用**。必须走 `query-store-coupons`。这是"有券却用不掉"的根本原因 |
| 3 | 券可用性藏在 `instructions.labels[].text` | 实测 3 张券标签写着"未到使用时间"（`tradeStartDate` 是次日/下周）。只看有效期会误判 |

### 3. 积分决策用"机会成本"而非编造期望值

- 兑换项统一折算成 **元/分**，跨品类可比。
- 抽奖不编造概率，而是算**盈亏平衡线**：
  消耗积分 × 最优兑换单价 = 期望奖品需达到的价值。
  实测案例：抽奖耗 24 分 × 0.09 元/分 = **2.16 元**，
  奖品期望值高于 2.16 元才划算。

### 4. 真实验证结果

门店 `1450713`（上海黄浦华旭国际大厦餐厅），真实账号运行：

```
购物车   冰美式中杯 11.90 + 鸡薯双全盒 15.90 + 龙焰芝士棒鸡腿堡三件套 29.90
不用券基准                    57.70 元
用「9.9元中杯冰美式」券        官方引擎试算 55.70 元   ✅ 省 2.00 元
```

本地估算 55.70 与 `calculate-price` 返回的 55.70 **完全一致**，
验证了"本地搜索 + 服务端定价"这条链路成立。

---

## 五、安全边界

| 规则 | 说明 |
|---|---|
| 金额单位统一为**分** | 接口收发用分，展示层 ÷100 转元，禁止双重换算 |
| 价格只认服务端 | 本地估算一律标注"估算"，实付以 `calculate-price` 的 `data.price` 为准 |
| 写操作必须用户确认 | 下单、取消、抽奖不自动执行；领券属纯收益可执行但会明确告知 |
| 业务错误不重试 | `success:false` + `code` 是业务结果，不当网络故障 |
| Token 不入库 | 仅环境变量传入，`.gitignore` 覆盖 `.env`，仓库内无真实凭据 |

---

## 六、命令行验证

```bash
export MCD_MCP_TOKEN=你的Token

# 列出全部 35 个工具（证明 MCP 连通）
python scripts/mcp_client.py tools

# 直接调用任意工具
python scripts/mcp_client.py call query-my-account

# 一键端到端巡检，输出省钱日报
python scripts/daily_scan.py --city 上海市 --keyword 人民广场 --out 省钱日报.html
```
