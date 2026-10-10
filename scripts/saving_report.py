#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
saving_report.py — 麦麦省钱日报渲染器（麦麦省钱助手）

把工作流 A 采集到的原始数据（券 / 积分 / 活动 / 方案）渲染成一份可直接看的 HTML 日报。

用法
----
    python saving_report.py --input bundle.json --out 省钱日报.html
    python saving_report.py --input bundle.json --pretty      # 终端摘要
    python saving_report.py --self-test

输入 JSON（bundle）
-------------------
{
  "generatedAt": "2026-10-10 13:40",
  "account":  { ...query-my-account 的 data... },
  "balance":  { ...query-my-account 的 data... },              // 同 account，兼容命名
  "claimable": [ ...available-coupons 的 data... ],
  "claimed":   {"success": true, "data": {...}},                // auto-bind-coupons 结果（可选）
  "coupons":   [ ...query-my-coupons 的 data.coupons... ],
  "calendar":  { ...campaign-calendar 的 data... },
  "pointsAdvice": { ...points_advisor.py 的输出... },           // 可选
  "planResult":   { ...coupon_optimizer.py 的输出... },         // 可选
  "verifyResults": [ {"plan": {...}, "price": {"data": {"price": 4200}}, "ok": true} ]  // 可选
}
"""
from __future__ import annotations

import argparse
import datetime as _dt
import html
import json
import os
import sys
from typing import Any

BRAND_EMOJI = "🍟"

# 类目兜底估值（与 points_advisor 保持一致，仅用于展示）
DEFAULT_CSS = "/* fallback: 未找到 assets/report.css */ body{font-family:sans-serif;max-width:860px;margin:0 auto;padding:24px;}"


def esc(s: Any) -> str:
    return html.escape(str(s if s is not None else ""))


def yuan(fen: Any) -> str:
    try:
        return f"{int(fen) / 100:.2f}"
    except (TypeError, ValueError):
        return "-"


def _load_css() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    for cand in (os.path.join(here, "..", "assets", "report.css"),
                 os.path.join(here, "assets", "report.css")):
        if os.path.exists(cand):
            with open(cand, "r", encoding="utf-8") as f:
                return f.read()
    return DEFAULT_CSS


def _pick(d: dict, *keys, default=None):
    if not isinstance(d, dict):
        return default
    lm = {str(k).lower(): v for k, v in d.items()}
    for k in keys:
        v = lm.get(k.lower())
        if v is not None:
            return v
    return default


def _int(v) -> int:
    try:
        return int(float(str(v).strip()))
    except (TypeError, ValueError):
        return 0


# --------------------------------------------------------------------------- #
# 各区块渲染
# --------------------------------------------------------------------------- #
def render_hero(bundle: dict) -> str:
    ts = bundle.get("generatedAt") or _dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    n_claim = len(bundle.get("claimable") or [])
    n_coupon = len(bundle.get("coupons") or [])
    return f"""
<div class="hero">
  <h1>{BRAND_EMOJI} 麦麦省钱日报</h1>
  <div class="sub">生成时间 {esc(ts)} · 数据来自麦当劳中国官方 MCP 服务</div>
  <div class="badge">可领 {n_claim} 张 · 已有 {n_coupon} 张</div>
</div>"""


def render_kpis(bundle: dict) -> str:
    account = bundle.get("account") or bundle.get("balance") or {}
    available = _int(_pick(account, "availablePoint"))
    expire_now = _int(_pick(account, "currentMouthExpirePoint", "currentMonthExpirePoint"))
    expire_next = _int(_pick(account, "nextMouthExpirePoint", "nextMonthExpirePoint"))
    coupons = bundle.get("coupons") or []
    plan = (bundle.get("planResult") or {}).get("summary") or {}
    saving = plan.get("bestPlan", {}).get("estSavingYuan") if plan.get("bestPlan") else None
    if saving is None and plan.get("bestPlan"):
        saving = plan["bestPlan"].get("estSavingYuan")

    cells = [
        ("可用积分", f"{available:,}", "分"),
        ("本月将过期", f"{expire_now:,}", "分"),
        ("券包张数", f"{len(coupons)}", "张"),
    ]
    if saving is not None:
        cells.append(("本单预计可省", str(saving), "元"))
    else:
        cells.append(("下月将过期", f"{expire_next:,}", "分"))

    out = ['<div class="kpis">']
    for i, (label, value, unit) in enumerate(cells):
        accent = " accent" if (i == 0 or label == "本单预计可省") else ""
        out.append(f'<div class="kpi{accent}"><div class="label">{esc(label)}</div>'
                   f'<div class="value">{esc(value)}<small>{esc(unit)}</small></div></div>')
    out.append("</div>")
    return "".join(out)


def render_claim(bundle: dict) -> str:
    claimable = bundle.get("claimable") or []
    claimed = bundle.get("claimed")
    rows = []
    for c in claimable:
        name = _pick(c, "couponName", "name", "title") or "(未命名券)"
        label = _pick(c, "label", "couponStatus") or ""
        tag_cls = "green" if str(_pick(c, "couponStatus") or "").upper() == "CAN_GET" else "gray"
        rows.append(f'<li><span class="dot"></span><div style="flex:1">{esc(name)}</div>'
                    f'<span class="tag {tag_cls}">{esc(label)}</span></li>')

    claimed_note = ""
    if isinstance(claimed, dict) and claimed.get("success"):
        claimed_note = '<div class="callout">✅ 已执行一键领券（auto-bind-coupons），本批券已进入券包。</div>'

    body = (f'<ul class="list">{"".join(rows)}</ul>' if rows
            else '<div class="empty">当前没有可领取的麦麦省券。</div>')
    return f"""
<section>
  <h2><span class="ico">🎁</span>可领券（麦麦省）</h2>
  <p class="hint">这些券是白送的，先领光再谈其他。</p>
  {body}
  {claimed_note}
</section>"""


def render_coupons(bundle: dict) -> str:
    coupons = bundle.get("coupons") or []
    pr = bundle.get("planResult") or {}
    usable_here = [c.get("name") for c in (pr.get("normalizedCoupons") or [])]

    if not coupons:
        body = '<div class="empty">券包为空。可先执行一键领券。</div>'
    else:
        rows = []
        for c in coupons[:40]:
            name = _pick(c, "title", "couponName", "name") or "(未命名券)"
            disc = c.get("discountInfo") if isinstance(c.get("discountInfo"), dict) else {}
            dval, ddesc = disc.get("discountValue"), disc.get("discountDesc") or ""
            start = str(_pick(c, "tradeStartDate") or "")[:10]
            end = str(_pick(c, "tradeEndDate") or "")[:10]
            labels = [l.get("text", "") for l in ((c.get("instructions") or {}).get("labels") or [])
                      if isinstance(l, dict)]
            blocked = any(t in lb for lb in labels for t in ("未到使用时间", "已过期", "已使用", "不可用"))

            tags = []
            if dval:
                tags.append(f'<span class="tag red">{esc(ddesc or "券价")} ¥{esc(dval)}</span>')
            if blocked:
                tags.append(f'<span class="tag gray">{esc("、".join(labels))}</span>')
            elif start and end:
                tags.append(f'<span class="tag yellow">{esc(start)} ~ {esc(end)}</span>')
            if usable_here and name in usable_here:
                tags.append('<span class="tag green">本店可用</span>')

            rows.append(f'<li><span class="dot"></span><div style="flex:1">{esc(name)}</div>'
                        + "".join(tags) + "</li>")
        body = f'<ul class="list">{"".join(rows)}</ul>'

    n_all = len(coupons)
    n_here = len(usable_here) if pr else 0
    insight = ""
    if pr:
        n_blocked = sum(
            1 for c in coupons
            if any(t in l.get("text", "")
                   for l in ((c.get("instructions") or {}).get("labels") or []) if isinstance(l, dict)
                   for t in ("未到使用时间", "已过期", "已使用")))
        insight = (f'<div class="callout"><b>券包体检</b>：券包共 <b>{n_all}</b> 张，'
                   f'本店当场景真正可用 <b>{n_here}</b> 张'
                   + (f'，另有 <b>{n_blocked}</b> 张尚未到使用时间或已失效' if n_blocked else "")
                   + '。<br>提醒：<code>query-my-coupons</code> 只说明"你拥有它"，'
                     '能不能用得看门店与下单方式——这正是很多人"有券却用不掉"的原因。</div>')

    return f"""
<section>
  <h2><span class="ico">🎫</span>我的券包</h2>
  <p class="hint">券包 ≠ 能用。下面标出了每张券的券价、有效期与可用状态。</p>
  {body}
  {insight}
</section>"""


def render_points(bundle: dict) -> str:
    adv = bundle.get("pointsAdvice")
    if not adv:
        return ""
    s = adv.get("summary") or {}
    ranking = adv.get("redemptionRanking") or []
    lottery = adv.get("lottery") or {}
    urgency = adv.get("expiryUrgency") or []
    recs = adv.get("recommendations") or []

    max_vpp = max([r.get("valuePerPointYuan") or 0 for r in ranking] or [1]) or 1

    rows = []
    for r in ranking[:8]:
        vpp = r.get("valuePerPointYuan") or 0
        pct = max(4, round(vpp / max_vpp * 100))
        conf = r.get("confidence")
        tag = {"high": '<span class="tag green">接口价</span>',
               "low": '<span class="tag yellow">类目估值</span>'}.get(conf, '<span class="tag gray">估算</span>')
        rows.append(
            f'<div class="rank-row" style="display:flex;gap:10px;align-items:center">'
            f'<div class="name" style="flex:1;min-width:0">{esc(r.get("name"))}</div>'
            f'<div class="bar"><i style="width:{pct}%"></i></div>'
            f'<div class="vpp">{vpp:.4f} 元/分</div>'
            f'<div style="flex:0 0 92px;text-align:right">{esc(r.get("points"))} 分 {tag}</div>'
            f'</div>')

    urg_html = "".join(
        f'<div class="callout{" urgent" if u.get("level") == "urgent" else ""}">{esc(u.get("message"))}</div>'
        for u in urgency)

    lot_html = f'<div class="callout">{esc(lottery.get("verdict"))}</div>' if lottery.get("verdict") else ""
    rec_html = ("".join(f"<li>{esc(r)}</li>" for r in recs)) if recs else '<li class="empty">暂无建议</li>'

    return f"""
<section>
  <h2><span class="ico">🪙</span>积分怎么花最值</h2>
  <p class="hint">统一尺子：<b>每 1 积分值多少元</b>。数值越高越值得换。抽奖按"盈亏平衡线"判断。</p>
  {urg_html}
  <div style="margin-top:14px">{"".join(rows) if rows else '<div class="empty">没有可估值的兑换项。</div>'}</div>
  {lot_html}
  <div class="callout" style="background:#F7F7F5;border-left-color:#B9B7B2">
    <b>行动建议</b><ul style="margin:6px 0 0 18px;padding:0">{rec_html}</ul>
  </div>
</section>"""


def render_calendar(bundle: dict) -> str:
    cal = bundle.get("calendar")
    if not cal:
        return ""
    days = cal.get("dailyList") or cal.get("days") or []
    if not days:
        return ""
    today_html, upcoming = "", []
    for d in days:
        title = ""
        evs = d.get("events") or []
        titles = [(_pick(e.get("articleDto") or {}, "title") or _pick(e, "activityTitle") or "") for e in evs]
        titles = [t for t in titles if t]
        if d.get("today"):
            today_html = f'<div class="callout"><strong>今日活动（{esc(d.get("date"))}）</strong><br>' \
                         + "<br>".join(f"· {esc(t)}" for t in titles) + "</div>"
        elif titles:
            upcoming.append(f'<li><span class="dot"></span><div style="flex:1">{esc(d.get("date"))}　'
                            f'{esc(" / ".join(titles[:3]))}</div></li>')
    up_html = f'<ul class="list">{"".join(upcoming[:5])}</ul>' if upcoming else ""
    return f"""
<section>
  <h2><span class="ico">📅</span>活动日历（择时就是省钱）</h2>
  <p class="hint">同样的东西，活动期买可能便宜一截。下面标出今天和接下来值得等的。</p>
  {today_html}
  {up_html}
</section>"""


def render_plans(bundle: dict) -> str:
    pr = bundle.get("planResult")
    if not pr:
        return ""
    plans = pr.get("plans") or []
    baseline = pr.get("baseline") or {}
    fillers = pr.get("fillers") or []
    verify = {str(v.get("plan", {}).get("rank")): v for v in (bundle.get("verifyResults") or [])}

    rows = []
    for p in plans[:6]:
        is_best = p.get("rank") == 1
        v = verify.get(str(p.get("rank")))
        real = ""
        if v and v.get("ok"):
            real = f'{yuan((v.get("price") or {}).get("data", {}).get("price"))}'
        elif v:
            real = '<span class="tag gray">试算失败</span>'
        else:
            real = '<span class="tag gray">待试算</span>'
        rows.append(
            f'<tr class="{"best" if is_best else ""}">'
            f'<td>{"⭐ " if is_best else ""}{esc(" + ".join(p.get("names") or []))}</td>'
            f'<td class="num">{esc(yuan(p.get("estPayable")))}</td>'
            f'<td class="num">{esc(yuan(p.get("estSaving")))}</td>'
            f'<td class="num">{real}</td></tr>')

    filler_html = ""
    if fillers:
        filler_html = ('<div class="callout"><b>凑单建议</b><ul style="margin:6px 0 0 18px;padding:0">'
                       + "".join(f'<li>{esc(f.get("message"))}</li>' for f in fillers)
                       + "</ul></div>")

    return f"""
<section>
  <h2><span class="ico">🧮</span>下单方案对比</h2>
  <p class="hint">"估算"列仅用于排序；<b>"真实试算"列</b>来自官方价格引擎 <code>calculate-price</code>，
     才是你实际要付的钱（单位：元）。</p>
  <table>
    <thead><tr><th>方案（券组合）</th><th class="num">估算实付</th>
    <th class="num">估算省</th><th class="num">真实试算</th></tr></thead>
    <tbody>{"".join(rows)}</tbody>
  </table>
  <div class="callout" style="background:#F7F7F5;border-left-color:#B9B7B2">
    不用券的基准价：<b>{esc(yuan(baseline.get("payable")))} 元</b>
  </div>
  {filler_html}
</section>"""


def render(bundle: dict) -> str:
    css = _load_css()
    parts = [
        render_hero(bundle),
        render_kpis(bundle),
        render_claim(bundle),
        render_coupons(bundle),
        render_points(bundle),
        render_calendar(bundle),
        render_plans(bundle),
    ]
    generated = bundle.get("generatedAt") or _dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>麦麦省钱日报 · {esc(generated)}</title>
<style>
{css}
</style>
</head>
<body>
<div class="wrap">
{"".join(p for p in parts if p)}
<footer>
  <div>本报告由 <b>麦麦省钱助手 (mcd-saver)</b> 生成 · 数据源：麦当劳中国 MCP 服务 <code>https://mcp.mcd.cn</code></div>
  <div>金额单位：人民币元；服务端价格字段单位为"分"，报告内已换算。</div>
  <div>标有"估算"的数字由本地启发式算法产出，仅用于方案排序；<b>最终应付金额以官方 <code>calculate-price</code> 返回为准</b>。</div>
</footer>
</div>
</body>
</html>"""


# --------------------------------------------------------------------------- #
# 自检
# --------------------------------------------------------------------------- #
def self_test() -> int:
    bundle = {
        "generatedAt": "2026-10-10 13:45",
        "account": {"availablePoint": "3200", "currentMouthExpirePoint": "800",
                    "nextMouthExpirePoint": "1200"},
        "claimable": [
            {"couponName": "免费脆薯饼", "couponStatus": "CAN_GET", "label": "可领取"},
            {"couponName": "人气麦旋风买一送一", "couponStatus": "CAN_GET", "label": "可领取"},
        ],
        "claimed": {"success": True, "data": {}},
        "coupons": [{"couponName": "9.9元中杯冰美式", "expireTime": "2026-10-31 23:59:59"}],
        "calendar": {"dailyList": [
            {"date": "2026-10-10", "today": True,
             "events": [{"articleDto": {"title": "超值9.9元早餐两件套"}}]},
            {"date": "2026-10-12", "today": False,
             "events": [{"articleDto": {"title": "蓝莓爆爆珠麦旋风上新"}}]},
        ]},
        "pointsAdvice": {
            "summary": {"availablePoint": 3200},
            "redemptionRanking": [
                {"name": "免费脆薯饼券", "points": 100, "valuePerPointYuan": 0.09, "confidence": "high"},
                {"name": "麦辣鸡腿堡券", "points": 400, "valuePerPointYuan": 0.06, "confidence": "high"},
            ],
            "lottery": {"verdict": "单次抽奖耗 24 积分，盈亏平衡线 2.16 元。"},
            "expiryUrgency": [{"level": "urgent", "message": "本月 800 积分即将过期"}],
            "recommendations": ["先兑脆薯饼券"],
        },
        "planResult": {
            "baseline": {"payable": 6300},
            "plans": [
                {"rank": 1, "names": ["下单立减5元券"], "estPayable": 5800, "estSaving": 500},
                {"rank": 2, "names": ["麦旋风买一送一", "立减5元券"], "estPayable": 4300, "estSaving": 2000},
            ],
            "fillers": [{"message": "把麦旋风加到 2 件，实付不变多得一杯"}],
        },
        "verifyResults": [
            {"plan": {"rank": 1}, "ok": True, "price": {"data": {"price": 5800}}},
        ],
    }
    out = render(bundle)
    fails = []
    for token in ["麦麦省钱日报", "免费脆薯饼", "0.0900 元/分", "今日活动", "真实试算", "58.00",
                  "<!DOCTYPE html>", "凑单建议"]:
        if token not in out:
            fails.append(f"HTML 缺少 {token}")
    if out.count("<section") < 4:
        fails.append("区块数量不足")

    print("=== 日报渲染自检 ===")
    print(f"生成 HTML 长度: {len(out):,} 字符")
    print(f"包含区块: {out.count('<section')} 个")
    if fails:
        print("自检失败 ❌")
        for f in fails:
            print("  -", f)
        return 1
    print("自检通过 ✅")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="麦麦省钱日报渲染器")
    ap.add_argument("--input", "-i", help="bundle JSON 路径（- 表示 stdin）")
    ap.add_argument("--out", "-o", help="输出 HTML 路径")
    ap.add_argument("--self-test", action="store_true", help="运行内置样例自检")
    args = ap.parse_args()

    if args.self_test:
        return self_test()
    if not args.input:
        ap.print_help()
        return 2

    bundle = json.load(sys.stdin) if args.input == "-" else json.load(open(args.input, encoding="utf-8"))
    html_out = render(bundle)

    out_path = args.out or "省钱日报.html"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html_out)
    print(f"✅ 已生成 {out_path}（{len(html_out):,} 字符）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
