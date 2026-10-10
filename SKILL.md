---
name: mcd-saver
description: 麦麦省钱助手 —— 基于麦当劳中国官方 MCP 服务（mcp.mcd.cn）的点餐省钱决策引擎。当用户咨询麦当劳优惠券、领券、券怎么用最划算、积分怎么花/快过期、套餐比价、凑单、活动日历、本月活动、下单前算账时使用。能力包括：一键领券、券包体检、券组合试算找最低实付、凑单建议、积分每分价值排序、活动择时、省钱日报。
agent_created: true
---

# 麦麦省钱助手 (mcd-saver)

## 一句话定位

麦当劳的省钱资源散落在**四个互不相通的池子**里：麦麦省可领券、门店可用券、会员积分、限时活动。
用户看不全、算不清，所以总是多花钱。

本 Skill 把它们收敛成一条可执行的决策链：

> **能领的券先领光 → 用真实价格引擎试算找最低实付 → 积分按"每分价值"花掉 → 在活动期下手**

核心方法论的差异点：**不猜券规则，直接试算**。麦当劳的券叠加/互斥规则是服务端黑盒，
本 Skill 用官方的 `calculate-price` 作为权威价格引擎，对候选方案逐个真实试算，
用实测结果代替规则推理——这是人工做不到的部分。

---

## 触发场景

| 用户说法 | 走哪个工作流 |
|---|---|
| "麦当劳有什么优惠"、"帮我领券"、"帮我省点钱" | **A 省钱巡检** |
| "我想吃XX，怎么买最便宜"、"帮我算一下"、"这个套餐值不值" | **B 下单算账** |
| "我有几张券怎么用最划算"、"这张券值不值"、"要不要凑单" | **B 下单算账** |
| "我有多少积分"、"积分怎么花"、"积分快过期了" | **C 积分变现** |
| "最近有什么活动"、"本月活动" | **A 省钱巡检** / 直接 `campaign-calendar` |

---

## 前置检查（每次会话第一次调用前做一次）

1. 确认麦麦 MCP 已连接：工具名以 `mcd-mcp` 前缀出现（`available-coupons`、`query-meals` 等 35 个）。
   若未连接 → 引导用户配置远程 MCP：地址 `https://mcp.mcd.cn`，协议 **Streamable HTTP**，
   请求头 `Authorization: Bearer <MCP Token>`，Token 从 https://open.mcd.cn/mcp 控制台申请。
2. 调用 `now-time-info` 拿**服务端时间**，后续所有"今天/本周/是否早餐时段"判断都以它为准，
   不要用本地时间（活动与菜单按服务端时区切档）。

---

## 工作流 A：省钱巡检（用户说"帮我省点钱 / 有什么优惠"）

目标：一次把四个池子全部盘点完，输出一张可执行的省钱日报。

```
1. now-time-info              → 服务端时间（判断早餐/正餐时段、星期几）
2. available-coupons          → 麦麦省"可领"券清单
3. 【展示后确认】auto-bind-coupons → 一键领光
4. query-my-coupons           → 已有券包
5. query-my-account           → 积分余额 + 近期将过期积分
6. campaign-calendar          → 本月活动（进行中 + 即将开始）
7. saving_report.py           → 生成省钱日报（HTML）
```

**领券的动作规范**：先展示 `available-coupons` 的清单让用户看到有什么，
然后执行 `auto-bind-coupons`。若用户话里已经明确说"帮我领/一键领/全领了"，可直接执行不再确认。
领券是无风险正收益动作（白送），不要因为怕"擅自操作"而漏掉——这是省钱助手最基础的价值。

**巡检输出必须包含**：① 新领到几张券 ② 券包里**快过期**的券 ③ 积分及最近一个过期节点
④ 今天/本周值得等的活动（例如"下周三有活动，别今天买"）。

---

## 工作流 B：下单算账（核心，最见功力）

目标：给定"想吃什么"，输出**实付最低的方案**，并用官方价格引擎验证过。

### B1. 锁定场景（必须先问清，参数错了一切都错）

| 场景 | beType | orderType | 必传 | 门店来源 |
|---|---|---|---|---|
| 到店自取 | 1 | 1 | 不传 beCode | `query-nearby-stores` |
| 得来速 | 5 | 1 | **必传 beCode** | `query-nearby-stores` |
| 麦乐送 | 2 | 2 | **必传 beCode** + addressId | `delivery-query-stores` |
| 企业团餐 | 6 | 2 | **必传 beCode** | `delivery-query-stores` |

用户没明说场景时，默认**到店自取**（beType=1, orderType=1），并在结论里标注假设。

### B2. 取数据

```
1. query-nearby-stores {beType, searchType:2, city, keyword}  → storeCode / beCode
   （searchType:1 是"收藏餐厅"，用户没收藏会返回 600050，此时要主动降级到 searchType:2）
2. query-meals {storeCode, orderType, beType}                  → 菜单（只有 code + tags！）
3. query-meal-detail {code, storeCode, orderType, beType}      → 拿名称/套餐组成/换购项
4. query-store-coupons {storeCode, orderType, beType}          → 【该店】可用券
5. query-my-coupons                                            → 券包原始资产
```

⚠️ **`query-meals` 只返回商品编码，没有价格**。价格有两种拿法：
- 单件零售价：调 `query-meal-detail`（注意：部分商品详情里没有价格，需用 `calculate-price` 单件试算）
- 直接算总价：交给 `calculate-price`

### B3. 生成候选方案（脚本负责，不靠脑补）

把购物车 + 候选券交给优化器：

```bash
python scripts/coupon_optimizer.py --input plan.json --out plan_result.json
```

优化器输出**排序后的候选方案**，每个方案自带可直接执行的 `calculate-price` 参数（`verify.arguments`）。

### B4. 真实试算（关键步骤，不可跳过）

对优化器给出的每个候选方案，**实际调用 `calculate-price`**，取服务端返回的 `data.price`（单位：分）。

不要自己用券面额去加减推算实付——券的叠加规则、可用性、门槛判定都在服务端，
本地推算出来的"理论价"经常和真实结算价不一致。

### B5. 出结论

用对比表输出，务必包含：
- **方案对比表**：方案 / 用了哪些券 / 实付 / 省了多少 / 相对最优的差距
- **明确推荐**：一句话"就按方案 N 下单，实付 X 元，比不用券省 Y 元"
- **凑单提示**（若优化器给了 `fillers`）：再买一件便宜的反而更省时，讲清"加 A 花 a 元、多减 b 元、净赚 c 元"
- **下单引导**：用户确认后再走 `create-order`

---

## 工作流 C：积分变现（"积分怎么花 / 快过期了"）

```
1. query-my-account      → availablePoint / currentMouthExpirePoint / nextMouthExpirePoint
2. mall-points-products  → 积分可兑换商品（可按 catRuleIds 筛类目）
3. mall-product-detail   → 目标商品的 SKU 与所需积分
4. query-lottery-info    → 积分抽奖活动（消耗规则 + 奖品池）
5. points_advisor.py     → 按"每积分价值（元/分）"排序 + 过期紧急度
```

**普通积分兑换**是确定性收益，**抽奖**是期望收益——脚本会把两者换算到同一把尺子上。
积分即将过期时，优先把快过期的积分花掉，即使单位价值略低也比归零强。

必须遵守：`draw-lottery` 执行前，**先展示** `query-lottery-info` 的活动信息与消耗，
得到用户明确同意后才能抽。抽奖是消耗型不可逆操作。

---

## 铁律清单（这些不遵守一定出错）

1. **价格单位是"分"**。`calculate-price` 返回的 `data.price`、`productOriginalPrice` 等全部要 ÷100 才是元。
   展示给用户时必须换算，且保留 1–2 位小数。
2. **业务失败不是协议错误**。MCP 层返回 `success:false` + `code` + `message`（如 `600012 每单限购1件`、
   `600050 收藏餐厅为空`）。必须读 `message` 并据此调整，不要当成网络故障重试。
3. **`query-my-coupons` 返回的券 ≠ 能用**。它不做门店/渠道校验。要判断"这张券在这个店能不能用"，
   必须走 `query-store-coupons`。
4. **`query-meals` 没有价格**，别指望它给出金额。
5. **`beCode` 传递规则**是最高频的踩坑点：到店自取不传，得来速/外送/团餐必传。
6. **`takeWayCode` 不能猜**，必须取自 `calculate-price` 返回的 `data.takeWayList[].code`
   （实测值为 `eat-in` 堂食、`locker-out` 外带）。
7. **限量商品**（如联名周边）常有"每单限购1件"，批量下单前先试算一次探边界。
8. **`reservationDate` 格式 `yyyy-MM-dd HH:mm`**，仅预约场景传，非预约不要传。
9. **限流 600 次/分钟**，试算方案多时控制节奏，超限是 429。
10. **Token 是用户私密凭证**，禁止写进任何要公开发布的文件（尤其是参赛仓库）。

---

## 脚本与参考文件

| 文件 | 用途 |
|---|---|
| `scripts/mcp_client.py` | 轻量 MCP 客户端（Streamable HTTP），可独立跑通全部 35 个工具 |
| `scripts/coupon_optimizer.py` | **核心**：券组合候选方案生成 + 凑单建议 + 剪枝，输出可直接试算的参数 |
| `scripts/points_advisor.py` | 积分"每分价值"排序、过期紧急度、抽奖期望值 |
| `scripts/saving_report.py` | 把巡检结果渲染成省钱日报 HTML |
| `references/mcp-tools.md` | 35 个工具全表（实测）与参数速查 |
| `references/data-shapes.md` | 各接口真实返回结构样本（实测抓取） |
| `references/saving-playbook.md` | 省钱打法手册：券类型、活动节奏、常见组合 |

---

## 输出风格

用**钱**说话，不用术语。每个结论都要能换算成"省了几块钱"。
不确定的地方明确标注"需试算确认"，绝不把估算价说成结算价。
