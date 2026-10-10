# 宣传文案

> 用于在各社区为本项目争取真实 Star。
> 本文件不参与比赛评审，仅为传播素材，可按需取用。
>
> ⚠️ **请只求真实 Star**。活动规则明确禁止刷量、机器人、批量注册等不正当手段，
> 违规会被取消参赛资格及奖励。下面所有文案都不含任何诱导刷量的表述。

**项目地址**：https://github.com/huangtianyu-shen/mcd-saver
**在线宣传页**：https://huangtianyu-shen.github.io/mcd-saver/

---

## 传播素材一览

| 素材 | 路径 | 用途 |
|---|---|---|
| **在线宣传落地页** | https://huangtianyu-shen.github.io/mcd-saver/ | 发帖时贴链接，比文字更有说服力；手机端可看 |
| **QQ 群专用图（1200×675，带二维码）** | [`assets/qq-card.png`](assets/qq-card.png) | QQ 群 / 微信群 —— 手机扫码直达仓库，发一张图就够 |
| 竖版海报（1080×1440） | [`assets/poster-xiaohongshu.png`](assets/poster-xiaohongshu.png) | 小红书 / 朋友圈配图 |
| 横版分享卡（1200×630） | [`assets/share-card.png`](assets/share-card.png) | V2EX 帖头图 / X 卡片 / 微信分享 |
| 仓库二维码（600×600） | [`assets/qrcode.png`](assets/qrcode.png) | 需要单独贴码的场景 |
| 落地页源码 | [`docs/index.html`](docs/index.html) | 单文件 HTML，改数据后重新截图即可 |

> 配图由 HTML + 无头浏览器渲染生成，**所有数据与仓库实测一致**，没有夸大。
> 想改文案：编辑 `docs/index.html` 或重跑海报模板，再截图。

---

## 电梯演讲（30 字版）

> 给它想吃的和预算，它领光所有券、试算全部组合，告诉你怎么点麦当劳最省。

---

## 一、V2EX 版本（技术社区，讲干货）

**标题**：
```
麦麦省钱助手 —— 基于麦当劳 MCP 的省钱决策 Skill，附三条实测踩坑（WorkBuddy × 麦当劳创意开发大赛参赛，求 Star）
```

**正文**：

```
一、先说活动

WorkBuddy 联合麦当劳发起了「麦当劳程序员创意开发大赛」：基于麦当劳官方 MCP 能力
开发一个创意 Skill。前三名有巨无霸兑换券 + WorkBuddy 积分，前 100 名有实体徽章和
汉堡回车键。排名看仓库 Star 数。

二、我做了什么

麦麦省钱助手（mcd-saver）。一句话：给它想吃的和预算，它领光所有券、试算全部组合，
告诉你怎么点麦当劳最省。

麦当劳的省钱资源散落在四个互不相通的池子里：可领券、门店可用券、会员积分、限时活动。
用户看不全、算不清，所以总在多花钱。

三、核心设计：不猜规则，只做试算

券的叠加规则、门槛判定、可用性校验全在服务端黑盒里。
我一开始想本地写规则推算，很快就发现行不通——推出来的价和真实结算价对不上。

所以改成：本地穷举搜索，服务端权威定价。
本地枚举单券 / 多券组合 / 凑单方案并剪枝，然后逐个调用官方 calculate-price 真实试算，
取最低实付。一次巡检会发起几十次真实试算，这是人工做不到的部分。

四、三条实测踩坑（文档里没写，但直接决定能不能省到钱）

1. available-coupons 返回的券没有 couponId / couponCode，只有券名和图片。
   拿去试算会被服务端拒绝。必须先 auto-bind-coupons 领进券包才有 ID。

2. 券包里的券 ≠ 这个门店能用。query-my-coupons 不做门店和渠道校验。
   实测：券包 5 张，指定门店到店场景只有 1 张真正可用。
   这是"有券却用不掉"的根本原因，必须走 query-store-coupons。

3. 券可能处于"未到使用时间"，而且只有 instructions.labels 会告诉你。
   实测 3 张券的 tradeStartDate 是次日/下周，标签明确写着"未到使用时间"。
   只看有效期会误判。

五、真实跑通的结果

上海某门店，真实账号：
  购物车 冰美式中杯 11.90 + 鸡薯双全盒 15.90 + 龙焰芝士棒鸡腿堡三件套 29.90
  不用券基准              57.70 元
  用「9.9元中杯冰美式」券  官方引擎真实试算 55.70 元   省 2.00 元

本地估算的 55.70 和官方引擎返回的 55.70 完全一致，链路成立。

六、技术

5 个零第三方依赖的 Python 脚本，只用标准库，python3 直接跑。
里面有个自己写的 MCP Streamable HTTP 客户端，服务端同时会返回纯 JSON 和 SSE 两种
响应体，都做了兼容。共调用 13 个 MCP 工具。
积分模块不编造抽奖概率，而是算盈亏平衡线：消耗积分 × 最优兑换单价 = 期望奖品需达到的价值。

七、求个 Star

仓库：https://github.com/huangtianyu-shen/mcd-saver
一页纸宣传页（图表版，比这篇好读）：https://huangtianyu-shen.github.io/mcd-saver/

如果能帮上忙，欢迎 Star，也欢迎 issue 和 PR。
```

> **发帖提示**：V2EX 帖子里可以直接贴宣传页链接；帖头图用
> [`assets/share-card.png`](assets/share-card.png)（横版 1200×630）。

---

## 二、小红书 / 朋友圈版本（轻松向）

```
🍟 做了个「麦麦省钱助手」，帮你算怎么点麦当劳最便宜

事情是这样的：麦当劳的券散在好几个地方——可领的、门店能用的、积分、限时活动。
每次点单前都要翻一遍，还经常发现"我有券但这家店用不了"。

于是我基于麦当劳官方 MCP 做了个 Skill：
▸ 一键领光所有能领的券
▸ 穷举券的组合，逐个调官方价格引擎真实试算
▸ 告诉你最低实付是多少、差几块钱能凑单、积分怎么花最值

实测跑通了一次：购物车 57.70，用券后官方引擎试算 55.70，省 2 块。
不算多，但重点是——这个价格是官方算出来的，不是我估的。

开发中还挖到三个坑：
1️⃣ 可领的券没有 ID，得先领进券包才能用
2️⃣ 券包里的券不代表这家店能用（我 5 张券只有 1 张能用）
3️⃣ 有些券"未到使用时间"，只有标签里写了，光看日期会看漏

代码开源了，零依赖纯 Python，有兴趣可以看看 👇
github.com/huangtianyu-shen/mcd-saver

觉得有用的话帮我点个 Star 吧 ⭐
```

> **发布提示**：首图用 [`assets/poster-xiaohongshu.png`](assets/poster-xiaohongshu.png)
> （竖版 1080×1440，小红书 3:4 标准比例，直接上传即可）。
> 正文里的链接小红书不可点，需在评论区补一条，或把仓库地址放在图片底部（海报已内置）。

---

## 三、微信群 / 私聊版本（最简）

```
做了个麦麦省钱助手，基于麦当劳官方 MCP：领券 → 穷举券组合 → 逐个调官方价格引擎试算 → 输出最低实付。

实测：57.70 元的购物车，用券后 55.70（官方引擎算的，不是估的）。

顺手挖到三个坑：可领券没 ID 得先领进券包；券包里的券不代表门店能用；有些券"未到使用时间"只有标签写了。

在参加麦当劳程序员创意开发大赛，排名看 Star，觉得有意思的话帮我点一个 ⭐
github.com/huangtianyu-shen/mcd-saver
```

> **发送提示**：群里直接发 [`assets/share-card.png`](assets/share-card.png)
> 这张横版图（自带仓库地址），比纯文字链接的点击率高得多。

---

## 四、QQ 群 / QQ 空间版本

QQ **不渲染 Markdown**，所以下面两段都是纯文本，整段复制直接粘贴即可，
不要带 `**`、`#`、`[]()` 这些符号，否则会原样显示成乱码。

### 4.1 极简版（推荐，4 行看完）

```
🍟 麦麦省钱助手 —— 告诉你怎么点麦当劳最便宜

领光所有券 → 穷举券组合 → 逐个用官方价格引擎试算 → 输出最低实付
实测：57.70 的购物车，用券后 55.70（这是官方算的，不是我估的）

github.com/huangtianyu-shen/mcd-saver
在参加麦当劳程序员创意开发大赛，排名看 Star，觉得有意思帮我点个 ⭐ 谢谢！
```

### 4.2 完整版（技术群、校友群这类人群愿意读的群）

```
🍟 做了个「麦麦省钱助手」，帮你算怎么点麦当劳最便宜

麦当劳的券散在好几个地方——可领的、门店能用的、积分、限时活动，
每次点单前都要翻一遍，还经常发现"我有券但这家店用不了"。

于是我基于麦当劳官方 MCP 做了个小工具：
· 一键领光所有能领的券
· 穷举券的组合，逐个调官方价格引擎真实试算
· 告诉你最低实付是多少、差几块能凑单

实测跑通了一次：购物车 57.70，用券后 55.70，省 2 块。
重点是这个价格是官方算出来的，不是我估的。

开发中还挖到三个坑：
1. 可领的券没有 ID，得先领进券包才能用
2. 券包里的券不代表这家店能用（我 5 张券只有 1 张能用）
3. 有些券"未到使用时间"，只有标签里写了，光看日期会看漏

代码开源了，零依赖纯 Python：
github.com/huangtianyu-shen/mcd-saver

在参加麦当劳程序员创意开发大赛，排名看 Star，
觉得有意思的话帮我点个 Star 吧 ⭐ 感谢！
```

### 4.3 发群操作建议（照着做就行）

1. **先发图**：群相册里传 [`assets/qq-card.png`](assets/qq-card.png)
   —— 这张图右半边就是二维码，**手机上直接长按识别就能跳到仓库**，
   省掉"让人手敲网址"这一步，转化率最高。
2. **再发文字**：粘贴上面 4.1 极简版。图 + 文分两条发，比一条长消息更容易被看到。
3. **手机党多**的话，文案里补一句在线宣传页（手机上打开比 GitHub 好用）：
   https://huangtianyu-shen.github.io/mcd-saver/
4. **一个群只发一次**，刷屏会被踢甚至被举报。
5. 长消息在 QQ 里会被折叠成"全文"，所以**极简版优先**；技术群、校友群再上完整版。

> 如果想自己在文件里贴二维码，用 [`assets/qrcode.png`](assets/qrcode.png)（600×600，透明背景外的白底）。

---

## 五、X / Twitter（英文）

```
Built "mcd-saver" — a money-saving Skill on McDonald's China official MCP.

Coupons are scattered across 4 disconnected pools (claimable / store-valid / points / campaigns).
Instead of guessing the stacking rules (they're server-side black boxes), it enumerates combos
locally and runs each through the official calculate-price engine, then picks the lowest.

Real run: ¥57.70 cart → ¥55.70 after coupon, verified by the official engine.

Landing page: https://huangtianyu-shen.github.io/mcd-saver/
⭐ github.com/huangtianyu-shen/mcd-saver
```

> **Post tip**: attach [`assets/share-card.png`](assets/share-card.png) (1200×630) —
> it renders as a native Twitter/X summary card without needing a meta tag.

---

## 六、发布 Checklist

- [ ] **先自己 Star 一次**（Star = 0 不进排行榜，任何奖励都拿不到）
- [ ] **发帖一定带图**：小红书用竖版、V2EX/微信/X 用横版 —— 带图帖的点击率远高于纯链接
- [ ] **贴在线宣传页** https://huangtianyu-shen.github.io/mcd-saver/ ，
      别人不用装环境就能看懂项目，比让他去读 README 转化率高
- [ ] V2EX 发在 `/go/create` 或 `/go/programmer` 节点，别发错版
- [ ] 遵守各社区版规，不要在无关板块刷帖
- [ ] 每个社区只发一次，不要重复刷屏
- [ ] **不要买 Star、不要用机器人、不要批量注册** —— 活动规则明确禁止，
      一经发现取消参赛资格和全部奖励
- [ ] 有人提问或提 issue 及时回复，真实互动比刷量有用得多

---

## 七、时效性

| 事项 | 时间 |
|---|---|
| 报名及拉票截止 | 2026-10-25 23:59 |
| 定榜 | 2026-10-26 00:00 |
| 奖品信息提交截止 | 2026-11-14 |

过了 10-25 拉票就没有意义了，别在截止时间后继续发。
