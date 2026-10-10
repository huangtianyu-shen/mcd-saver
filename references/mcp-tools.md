# 麦当劳中国 MCP 工具全表（实测）

> 实测环境：`https://mcp.mcd.cn`，协议 Streamable HTTP，协议版本 2025-06-18，serverInfo `mcd-mcp v1.0.0`。
> 实测工具总数：**35**。
> 参数列中 **粗体** 为必填。返回值统一包在 `structuredContent` 中，含 `success / code / message / datetime / traceId / data`。

### 优惠券 / 省钱核心

| Tool | 说明 | 参数（**粗体**=必填） |
|---|---|---|
| `available-coupons` | 查询用户当前可领取的麦麦省的优惠券列表。返回券名称、图片、状态和促销标签。当用户询问有什么优惠、可以领什么券时使用此工具。 | — |
| `auto-bind-coupons` | 自动领取麦麦省所有当前可用的麦当劳优惠券。无需指定具体的优惠券和couponId，系统会自动领取用户可领的所有券。当用户说"帮我领券"、"自动领取优惠券"、"一键领券"时使用此工具。 | — |
| `query-my-coupons` | 获取用户卡包中的优惠券资产信息，用于“我有什么券 / 券详情查看”等展示与管理场景。 注意：该接口返回的是用户拥有的券，不进行门店、渠道、配送方式等下单规则校验，因此不承诺可用于当前订单。 若业务目标是“当前门店/当前订… | page:string, pageSize:string |
| `query-store-coupons` | 查询【指定门店+订单类型】下可使用的优惠券，支持到店(orderType=1,含到店自取和得来速)和外送(orderType=2,含麦乐送和团餐) | beCode:string, **beType**:integer, **orderType**:integer, reservationDate:string, **storeCode**:string |

### 活动 / 时间

| Tool | 说明 | 参数（**粗体**=必填） |
|---|---|---|
| `campaign-calendar` | 查询麦当劳中国当月的营销活动日历，返回进行中、往期和未来日期的活动。适用于查看用户进行中和即将到来的可参与活动，还可查询用户对活动的订阅状态。 | specifiedDate:string |
| `now-time-info` | 获取当前时间信息 - 返回当前服务器的完整时间信息，包括： - 时间戳（毫秒级） - 格式化的日期时间 - 年月日信息 - 时区和UTC时间 在你不知道当前时间，并且用户需要指定日期查询活动日历的时候有用 | — |

### 门店 / 地址

| Tool | 说明 | 参数（**粗体**=必填） |
|---|---|---|
| `query-nearby-stores` | 到店场景下，查询用户可点餐门店，需要用户明确是到店自取还是车道取餐 - beType=1(到店自提): 返回的门店无 beCode，后续工具调用不传 beCode - beType=5(得来速): 返回的门店有 beCo… | **beType**:integer, city:string, keyword:string, **searchType**:integer |
| `delivery-query-stores` | 外送场景下，用户选择完地址后，需要根据地址ID，查询用户当前地址可配送的门店 | **addressId**:string, **beType**:integer |
| `delivery-query-addresses` | 外送场景下，查询用户配送地址列表 | — |
| `delivery-create-address` | 创建用户配送地址 | **address**:string, **addressDetail**:string, **city**:string, **contactName**:string, gender:string, **phone**:string |

### 菜单 / 餐品

| Tool | 说明 | 参数（**粗体**=必填） |
|---|---|---|
| `query-meals` | 餐品列表, 支持到店自提(orderType=1)和外送(orderType=2)两种场景 企业团餐场景下，可按照这个规则给用户进行搭配 - **20元以下**: 小食 - **20-30元**：汉堡+小食 或 汉堡+饮… | beCode:string, **beType**:integer, **orderType**:integer, reservationDate:string, **storeCode**:string |
| `query-meal-detail` | 餐品详情, 支持到店自提(orderType=1)和外送(orderType=2)两种场景 | beCode:string, **beType**:integer, **code**:string, **orderType**:integer, reservationDate:string, **storeCode**:string |
| `list-nutrition-foods` | 获取麦当劳常见餐品的营养成分数据，包括能量、蛋白质、脂肪、碳水化合物、钠、钙等信息，当用户咨询麦当劳餐品的热量、营养，帮助用户搭配指定热量套餐时有用 | — |

### 价格 / 下单

| Tool | 说明 | 参数（**粗体**=必填） |
|---|---|---|
| `calculate-price` | 计算商品的价格（含优惠），支持到店自提(orderType=1)和外送(orderType=2)两种场景 | beCode:string, **beType**:integer, gmServiceCode:string, items:array<obj>, needTableware:boolean, **orderType**:integer, reservationDate:string, **storeCode**:string, withOrder:object |
| `create-order` | 创建麦当劳订单，支持到店(orderType=1)和外送(orderType=2)两种场景下单, 必须先确定订单类型，必填 (1：到店，2外送) | addressId:string, beCode:string, **beType**:integer, gmServiceCode:string, items:array<obj>, needTableware:boolean, **orderType**:integer, remark:string, reservationDate:string, **storeCode**:string, takeWayCode:string, withOrder:object |
| `cancel-order` | 取消订单，非商城订单 | **cancelReasonCode**:string, **orderId**:string |
| `query-order` | 查询订单详细信息 | **orderId**:string |
| `order-list` | 查询麦当劳历史订单，非商城订单，商城订单需要使用mall-order-list | — |

### 积分 / 商城

| Tool | 说明 | 参数（**粗体**=必填） |
|---|---|---|
| `query-my-account` | 查询用户积分账户详情 - 当用户询问"我有多少积分"、"查下我的积分"、"积分余额"、"查询过期积分"时使用 | — |
| `mall-points-products` | 查询可兑换餐品券列表 - 当用户询问"有哪些积分兑换商品"、"积分可以兑换什么"、"查看积分商城"时使用 支持类目规则筛选：商品券(1>4)、实物商品(2)、周边产品(2>8)、实物礼品卡(2>9)、生日类派对(1>6>… | catRuleIds:string |
| `mall-product-detail` | 查询积分兑换商品详情 - 当用户询问"这个商品详情是什么"、"查看商品详细信息"、用户点击商品查看详情时使用 返回商品的所有SKU规格信息，用户需要选择具体SKU后才能下单兑换  前提条件： - 已知商品SPU ID，需… | **spuId**:integer |
| `mall-create-order` | 创建积分兑换订单，仅支持shopId=2（从 mall-product-detail 获取） - 当用户询问"用积分兑换这个商品"、"兑换这个券"、用户确认兑换商品时使用,切记：如果单个商品一个订单下单；如果用户需要兑换… | addressId:string, count:integer, **skuId**:integer, **spuCategory**:string |
| `mall-order-list` | 查询麦麦商城订单列表 | lastId:number, size:integer |
| `mall-order-detail` | 查询麦麦商城订单详情 | **orderId**:string |

### 积分抽奖

| Tool | 说明 | 参数（**粗体**=必填） |
|---|---|---|
| `query-lottery-info` | 查看当前积分抽奖活动信息，包括活动基本信息、抽奖消耗规则、单次所需积分、剩余可抽次数、当前可用积分与公开奖品列表，不执行抽奖。 | — |
| `draw-lottery` | 使用后台配置的抽奖消耗规则参加一次当前积分抽奖并返回结果，服务端原子完成次数或积分扣减与抽奖。 重要约束：仅能在向用户展示 query-lottery-info 返回的 drawDecision.nextConsumpt… | — |
| `query-my-prizes` | 查询当前登录会员通过积分抽奖获得的本期及历史奖品（可用/已使用/已过期/已领取/已失效）。 | pageNum:string, pageSize:string |

### 派对 / 主题活动

| Tool | 说明 | 参数（**粗体**=必填） |
|---|---|---|
| `query-party-city` | 活动派对商品配置场次城市列表, 必须先确定spuId(从 mall-points-products 获取）或查询商品详情（从 mall-product-detail 获取) | **spuId**:number |
| `query-party-store` | 查询指定城市下支持主题派对的门店列表。当用户选择了城市后，需要查看该城市有哪些门店可举办生日类派对/主题类派对/麦麦体验营/品鉴会/读书会/积分兑换活动时使用 Preconditions： - 必须先通过 query-p… | **code**:string, latitude:number, longitude:number, spuId:number |
| `query-party-store-date` | 查询指定门店支持生日类派对/主题类派对/麦麦体验营/品鉴会/读书会/积分兑换活动的可预约日期列表。当用户选择了门店后，需要查看该门店哪些日期可预约时使用。 | **spuId**:number, **storeCode**:string |
| `query-party-store-session` | 查询指定门店、指定日期下的生日类派对/主题类派对/麦麦体验营/品鉴会/读书会/积分兑换活动场次列表。当用户选择了日期后，需要查看当天有哪些场次可预约时使用。 | **dateStr**:string, **spuId**:number, **storeCode**:string |
| `party-order-create` | 创建生日类派对/主题类派对/麦麦体验营/品鉴会/读书会/积分兑换活动, 仅支持shopId=5（从 mall-product-detail 获取）的调用，   支持包场(partyType=1)、拼团(partyType… | code:string, count:integer, dateStr:string, id:number, leftNum:integer, partyTimeInfo:object, **partyType**:integer, skuId:number, spuId:number, storeCode:string, timeEnd:string, timeStart:string |

### 团餐 / 其他

| Tool | 说明 | 参数（**粗体**=必填） |
|---|---|---|
| `query-meal-assistance` | 仅支持企业团餐场景(beType=6)在calculate-price前需要获取当前门店可用的助餐服务 | beCode:string, beType:integer, orderType:integer, reservationDate:string, **storeCode**:string |
| `query-promotions` | 查询当前门店企业团餐场景下可用的促销规则（满减/满折），仅返回当前时间有效且适用在售餐品的规则原始数据 | beCode:string, **beType**:integer, **orderType**:integer, reservationDate:string, **storeCode**:string |
| `query-survey-coupon` | 按订单号查询当前 MCP 用户本人订单的 CSAT 满意度答卷，并返回该订单关联奖券的标题、核销时间、核销状态和点餐方式。 | **orderId**:string |

---

## 场景参数速查（最重要）

### beType / orderType 对照

| 场景 | beType | orderType | beCode | storeCode 来源 |
|---|---|---|---|---|
| 到店自取 | 1 | 1 | 不传 | `query-nearby-stores`(beType=1) |
| 得来速 DT | 5 | 1 | **必传** | `query-nearby-stores`(beType=5) |
| 麦乐送 | 2 | 2 | **必传** | `delivery-query-stores` |
| 企业团餐 | 6 | 2 | **必传** | `delivery-query-stores` |

### 常见业务错误码

| code | 含义 | 处理 |
|---|---|---|
| 200 | 成功 | — |
| 600050 | 收藏餐厅列表为空 | 降级到 `searchType=2` + city + keyword |
| 600012 | 每单限购 N 件 | 拆分下单或减少数量 |
| 401 | Token 无效/过期/未提供 | 检查 Authorization 头 |
| 429 | 触发限流（>600 次/分钟） | 降低调用频率 |

### 高频踩坑

- `query-meals` **只返回商品编码**（`code` + `tags`），不含价格。
- `query-meal-detail` 对部分商品（如周边）**不返回价格**，需用 `calculate-price` 单件试算。
- 价格字段单位一律为 **分**，展示前 ÷100。
- `takeWayCode` 必须取自 `calculate-price` → `data.takeWayList[].code`（实测：`eat-in` 堂食、`locker-out` 外带）。
- `query-my-coupons` 不校验门店可用性，判断这个店能不能用必须走 `query-store-coupons`。
- `reservationDate` 格式 `yyyy-MM-dd HH:mm`，仅预约场景传。

---

## 完整参考

工具原始 JSON Schema 见 `references/_raw_tools_schema.json`（35 个工具的完整 `inputSchema`）。
