# 真实数据结构样本（实测抓取）

> 全部样本来自对 `https://mcp.mcd.cn` 的**真实调用**，非文档转述。
> 抓取时间：2026-10-10。所有响应体统一为：
> ```json
> { "success": true, "code": 200, "message": "请求成功",
>   "datetime": "2026-10-10 13:36:57", "traceId": "...", "data": { } }
> ```
> MCP 层把它放在 `result.structuredContent`；同时 `result.content[0].text` 里有一份**给 LLM 看的字段说明 + 原始 JSON**。

---

## 1. 价格引擎 `calculate-price`（最关键 —— 一切以它为准）

**请求**
```json
{ "storeCode": "1450713", "orderType": 1, "beType": 1,
  "items": [ { "productCode": "521954", "quantity": 1 } ] }
```

**成功响应**
```json
{ "success": true, "code": 200,
  "data": {
    "productOriginalPrice": 3990,
    "productPrice": 3990,
    "originalPrice": 3990,
    "discount": 0,
    "price": 3990,
    "productList": [
      { "productCode": "521954", "productName": "麦当劳联名复古棒球帽",
        "quantity": 1, "originalSubtotal": 3990, "subtotal": 3990 }
    ],
    "takeWayList": [
      { "code": "eat-in",     "title": "堂食", "subtitle": "店内用餐" },
      { "code": "locker-out", "title": "外带", "subtitle": "店外取餐柜" }
    ]
  } }
```

**要点**
- 所有金额字段单位是 **分**（3990 = 39.90 元）。
- `data.price` 就是**实付**，这是唯一权威的"要花多少钱"。
- `takeWayList[].code` 是 `create-order` 必传的 `takeWayCode`（实测取值 `eat-in` / `locker-out`）。
- 带券时把 `couponId` + `couponCode` 挂到对应 **item** 上。

**业务失败响应（不是网络错误！）**
```json
{ "success": false, "code": 600012, "message": "每单限购1件，去看看其他餐品吧" }
```

---

## 2. 券：⚠️ 两条完全不同的数据结构

### 2.1 `available-coupons`（可领券）—— **信息很少**

```json
{ "success": true, "code": 200,
  "data": [ { "couponName": "免费脆薯饼",
              "couponImage": "https://.../免费脆薯饼600.png",
              "couponStatus": "CAN_GET",
              "label": "可领取" } ] }
```

**只有券名和图片，没有 `couponId`、没有 `couponCode`、没有面额。**
→ 因此可领券**不能直接用于下单试算**（服务端会报 `使用优惠券需要couponId和couponCode`）。
必须先 `auto-bind-coupons` 领进券包。

### 2.2 `query-my-coupons`（券包）—— **信息很全**（实测 5 张券共 40+ 字段）

```json
{ "subtitle": "", "showType": 100,
  "id": "264B97DB****（已打码）",                      // ← couponId
  "code": "MCD6109****（已打码）",                     // ← couponCode
  "title": "9.9元中杯冰美式",
  "orderType": 1,
  "orderTypes": [1, 2],                               // 1=到店 2=外送
  "beTypes": [1, 2, 3, 5],                            // 场景（会出现未公开取值）
  "reducePrice": "",
  "reducePriceText": "",
  "ifFreeCoupon": false,
  "appliedCategory": 1,
  "multipleProducts": false,
  "couponPromotionType": 1,
  "promotionChildrenType": 11,
  "totalCount": 1,
  "totalAvailableCount": 1,
  "tradeStartDate": "2026-10-10",
  "tradeEndDate": "2026-10-16",
  "discountInfo": {
    "discountValue": "9.9",                           // 券价（元）
    "discountDesc": "用券价格",                        // 语义："用券价格" = 指定价购
    "discountTypePosition": 1,
    "discountTypeText": "¥"
  },
  "instructions": {
    "labels": [ { "text": "到店", "color": "#222222", "code": 0 } ],
    "availableTime": [ { "text": "2026.10.10-2026.10.16", "color": "#222222", "type": 1 } ]
  },
  "channels": ["03", "14", "45", "54"],
  "paymentType": 0 }
```

**真实券包样本（实测）**

| title | discountValue | discountDesc | 有效期 | labels | beTypes |
|---|---|---|---|---|---|
| 9.9元中杯冰美式 | 9.9 | 用券价格 | 10-10 ~ 10-16 | — | [1,2,3,5] |
| 人气麦旋风买一送一 | 15 | 用券价格 | 10-05 ~ 10-11 | 到店 | [4] |
| 巧克力味厚松饼猪柳蛋套餐 | 29.9 | 用券价格 | 10-11 ~ 10-11 | **未到使用时间**、到店 | [1,5] |
| 巧克力味厚松饼猪柳蛋套餐 | 29.9 | 用券价格 | 10-17 ~ 10-17 | **未到使用时间**、到店 | [1,5] |
| 巧克力味厚松饼猪柳蛋套餐 | 29.9 | 用券价格 | 10-18 ~ 10-18 | **未到使用时间**、到店 | [1,5] |

**要点**
- `id` / `code` 就是下单要的 `couponId` / `couponCode`。
- `discountInfo.discountDesc` 承载语义：`用券价格` = 指定价购；另有折扣 / 满减等写法。
- `instructions.labels[].text` 直接告诉你**现在能不能用**（"未到使用时间"），这是本地就能判断的强信号。
- `beTypes` 会出现未公开取值（如 `4`），做场景过滤时要留退路。
- **券包 5 张，本店当前场景可用只有 1 张** —— 这是最容易被用户误解的一点。

---

## 3. `query-meals`（菜单）—— **只有编码，没有价格**

```json
{ "data": [
    { "name": "人气热卖",
      "meals": [
        { "code": "9900016076", "tags": ["心形薯饼同款比心"] },
        { "code": "9900016073", "tags": ["韩式辣椒黄油风味"] },
        { "code": "521954" }
      ] },
    { "name": "...", "meals": [ ... ] } ] }
```

实测 15 个分类、133 个餐品。
→ 要拿到"叫什么、多少钱"，必须再用 `query-meal-detail`（名称）+ `calculate-price` 单件试算（价格）。

## 4. `query-meal-detail`（餐品详情）

```json
{ "data": { "code": "521954",
            "name": "麦当劳联名复古棒球帽",
            "rounds": [],
            "image": "https://menu-img.mcd.cn/pcm/prod/menu/ProductPool/product/MS_521954_600.png",
            "supportModify": false } }
```
注意：**周边类商品详情里没有价格**。

## 5. `query-nearby-stores`（门店）

```json
{ "data": [ { "storeCode": "1450713",
              "storeName": "麦当劳上海黄浦华旭国际大厦餐厅",
              "address": "南京东路街道西藏中路336号",
              "distance": 144,
              "businessStatus": true,
              "businessStartTime": "00:00", "businessEndTime": "23:59",
              "reservation": true,
              "reservationTimeOptions": [ { "date": "2026-10-10", "today": true,
                "reservationOptionText": "午餐(10:44至14:15)，下午茶(14:44至16:45)…" } ] } ] }
```
- `searchType=1`（收藏餐厅）无收藏时返回 `{"success": false, "code": 600050, "message": "收藏餐厅列表为空，请您提供城市+关键词进行搜索"}` → 必须降级到 `searchType=2` + city + keyword。

## 6. `query-my-account`（积分）

```json
{ "data": { "availablePoint": "0", "accumulativePoint": "0",
            "currency": "麦享会积分",
            "currentMouthExpirePoint": "0",   // 本月将过期
            "nextMouthExpirePoint": "0",      // 下月将过期
            "expiredPoint": "0", "frozenPoint": "0", "usedPoint": "0",
            "accountId": "0ACCD84D-…" } }
```
注意字段拼写是 `Mouth`（接口原文如此），不是 `Month`。

## 7. `query-lottery-info`（积分抽奖）

```json
{ "data": { "status": { "code": "SUCCESS", "message": "成功" },
            "activityCode": "269t", "activityName": "周六麦金喜抽奖",
            "activityStatusText": "进行中",
            "beginTime": "2025-09-06 00:00:00", "endTime": "2030-12-31 23:59:59",
            "drawPoint": "24", "drawTypeText": "消耗积分抽奖",
            "availablePoint": "0",
            "drawDecision": { "resourceEligible": false, "reason": "积分不足",
                              "nextConsumption": { "type": "POINTS", "points": "24", "chances": 0,
                                                   "text": "本次将消耗 24 积分" } },
            "prizes": [ { "name": "积分霸王餐", "imageUrl": "https://...", "typeText": "优惠券" },
                        { "name": "麦金卡7天", "typeText": "会员卡" },
                        { "name": "圆筒冰淇淋4折优惠券", "typeText": "优惠券" } ] } }
```
→ `drawDecision.resourceEligible` 直接告诉你能不能抽；`prizes` 没有中奖概率。

## 8. `campaign-calendar`（活动日历）

```json
{ "data": { "currentTime": "2026-10-10 13:36:58",
            "dailyList": [ { "date": "2026-10-10", "today": true,
              "dateText": "2026年10月10日 往期回顾",
              "events": [ { "activityCode": "45f3", "activityStage": 3, "eventType": 4,
                "articleDto": { "title": "超值𝟗.𝟗元早餐两件套陪你开工啦😋",
                                "content": "…", "highlights": "9.9元超值早餐正式上新!",
                                "buttonText": "立即领券",
                                "imgList": ["https://cms-cdn.mcd.cn/…jpg"],
                                "appJumpUrl": "mcdapp://page?…" } } ] } ] } }
```
实测返回 12 天（含往期 + 今天 + 未来）。活动标题在 `articleDto.title`，不在 `activityTitle`（通常是空串）。

---

## 9. 实测踩坑汇总

| 现象 | 真因 | 处理 |
|---|---|---|
| 可领券拿去试算被拒 | `available-coupons` 无 couponId/Code | 先 `auto-bind-coupons` 再取 `query-my-coupons` |
| 菜单里没有价格 | `query-meals` 只返回 code | 用 `calculate-price` 单件试算 |
| 券包有券却用不了 | 券包不校验门店/场景 | 用 `query-store-coupons` |
| 明明有券却"未到使用时间" | `instructions.labels` 标注 | 读 labels，不要只看有效期 |
| 商品名称拿不到 | 菜单不给名称 | `query-meal-detail` |
| 明明是业务错误却像系统故障 | 失败走 `success:false` + code | 读 `message`，不要无脑重试 |
