# WorkBuddy 开发上下文

> 本文件用于核验本项目是否真实使用腾讯 WorkBuddy 智能体开发，
> 以参与「麦当劳程序员创意开发大赛 × WorkBuddy」联动活动专项奖励。
> 内容取自真实开发会话，未做修饰。

---

## 一、开发方式

| 项目 | 内容 |
|---|---|
| 开发工具 | 腾讯 WorkBuddy（Agent 模式） |
| 开发日期 | 2026 年 10 月 10 日 |
| 开发方式 | 全程在 WorkBuddy 对话中完成：需求澄清 → MCP 逆向探测 → 脚本开发 → 真实账号验证 → 打包发布 |
| 官方 MCP 接入 | 通过 WorkBuddy 自定义连接器配置 `mcd-mcp`（`https://mcp.mcd.cn`） |
| 赛事主办方仓库 | <https://github.com/M-China/mcd-developer-innovation-challenge> |

---

## 二、关键对话上下文

以下为开发过程中的核心指令与执行轨迹（按时间顺序）。

### 阶段 1：需求与工具确认

**用户**：（提供大赛活动截图）帮我基于麦当劳的 MCP 能力，帮我开发一个麦麦省钱助手 skill

**用户**：`github.com/M-China/mcd-mcp-server`

**WorkBuddy 执行**：
- 调研 MCP 官方仓库与 Skill 规范
- 读取内置 `skill-creator` 的 `SKILL.md` 规范

### 阶段 2：MCP 真实探测（不靠文档猜测）

**用户**：`<MCP Token 已隐去>`（在麦当劳开放平台申请的访问令牌，仅用于本地连接）

**WorkBuddy 执行**：编写探测脚本 `_probe/mcp_probe.py`，实际连接
`https://mcp.mcd.cn` 完成 MCP 握手，拉取**真实工具列表**：

```
实测工具总数：35
协议版本：2025-06-18
serverInfo：mcd-mcp v1.0.0
```

随后连续四轮探测（`mcp_probe2/3/4.py`），抓取关键工具的真实返回结构：
- 可领券、券包、门店券
- 门店、菜单、餐品详情
- 价格计算、活动日历、积分商城、抽奖信息

**这一轮决定了整个项目的设计**：发现菜单接口不返回价格、
可领券不带 ID、券包不做门店校验——于是确定了
「本地穷举搜索 + 服务端权威定价」的架构。

### 阶段 3：Skill 与脚本开发

**WorkBuddy 执行**（均带 `--self-test` 自检，逐个修 bug）：

| 脚本 | 自检发现并修复的问题 |
|---|---|
| `coupon_optimizer.py` | 券适用商品误判（中文语义匹配缺失）、凑单逻辑缺失 |
| `points_advisor.py` | 分/元单位换算错误（需再除 100）、机会成本口径错误 |
| `saving_report.py` | 渲染 token 断言过严 |
| `daily_scan.py` | 购物车商品无名称导致券匹配全落空 |

### 阶段 4：真实账号端到端验证

**WorkBuddy 执行**：

```bash
MCD_MCP_TOKEN=*** python scripts/daily_scan.py \
  --city 上海市 --keyword 人民广场 --out 省钱日报.html
```

真实结果：

```
服务端时间  2026-10-10 13:47（周六）
门店        麦当劳上海黄浦华旭国际大厦餐厅（1450713）
券包        5 张 | 本店当前场景可用 1 张 | 3 张"未到使用时间"

演示购物车  冰美式中杯 11.90 + 鸡薯双全盒 15.90 + 龙焰芝士棒鸡腿堡三件套 29.90
不用券基准              57.70 元
用「9.9元中杯冰美式」券  官方引擎真实试算 55.70 元  ✅ 省 2.00 元
```

**本地估算 55.70 与官方 `calculate-price` 返回完全一致**，链路成立。

### 阶段 5：发布与报名

**用户**：帮我上传到 GitHub 上

**WorkBuddy 执行**：
- 安全扫描（工作区 + git 历史 + MCP Token 三重检查）
- 因本机代理封锁 `github.com`，改用 **GitHub Git Trees API** 完成推送
- 创建公开仓库并配置 topics

**用户**：接下来帮我报名参赛

**WorkBuddy 执行**：
- 读取官方赛事仓库 `M-China/mcd-developer-innovation-challenge` 的
  `README.md` 与 `activityGuidelines.md`
- 补齐 `CONTEST_DECLARATION.md`（官方原文，不可改动）、`MCP_INTEGRATION.md`、
  本文件 `workbuddy.md`
- 按要求提交报名 Issue

---

## 三、WorkBuddy 在本项目中的作用

1. **能力探测自动化**：4 轮脚本化探测拿到 35 个工具的真实 Schema 与返回结构，
   人工逐条试错成本极高。
2. **开发 + 自检闭环**：每个脚本内置 `--self-test`，WorkBuddy 边写边跑，
   过程中修掉 4 个真实 bug。
3. **真实数据验证**：直接用用户账号跑通端到端，而非 mock 数据。
4. **发布链路兜底**：网络受限时改用 API 完成发布，未中断交付。

---

## 四、核验材料

| 材料 | 位置 |
|---|---|
| MCP 真实工具全表 | `references/mcp-tools.md` |
| 工具完整 JSON Schema | `references/_raw_tools_schema.json` |
| 真实返回结构样本 | `references/data-shapes.md` |
| MCP 编排说明 | `MCP_INTEGRATION.md` |
| 真实运行日报 | 项目根目录 `省钱日报.html`（运行产物，未入库） |
| 本文件 | `workbuddy.md` |

---

## 五、声明

本项目真实使用腾讯 WorkBuddy 智能体开发，上述上下文取自真实开发会话。
项目为参赛者独立开发，非麦当劳官方产品，亦非 WorkBuddy 官方产品。
