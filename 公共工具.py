from __future__ import annotations

import html
import json
import math
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import requests


根目录 = Path(__file__).resolve().parent
缓存目录 = 根目录 / "缓存"
结果目录 = 根目录 / "结果"
缓存目录.mkdir(parents=True, exist_ok=True)
结果目录.mkdir(parents=True, exist_ok=True)

东方财富列表接口 = "https://push2.eastmoney.com/api/qt/clist/get"
东方财富日线接口 = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
东方财富财务接口 = "https://datacenter.eastmoney.com/securities/api/data/v1/get"
腾讯日线接口 = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
接口令牌 = "bd1d9ddb04089700cf9c27f6f7426281"
请求头 = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36",
    "Referer": "https://quote.eastmoney.com/",
}

板块字段 = "f12,f14,f2,f3,f6,f8,f20,f21,f24,f25,f62,f104,f105,f109,f124,f164,f174"
成分股字段 = (
    "f12,f14,f2,f3,f6,f8,f9,f10,f20,f21,f23,f24,f25,f37,f38,f39,f40,f45,"
    "f46,f49,f57,f61,f62,f100,f109,f114,f115,f124,f164,f174"
)
ETF字段 = "f12,f14,f2,f3,f6,f8,f20,f21,f24,f25,f62,f109,f124"

每类预选板块数 = 30
每类最终板块数 = 6
每板块研究股票数 = 14
正式主线展示数 = 6
每条主线股票展示数 = 6

非产业概念关键词 = (
    "昨日", "涨停", "跌停", "连板", "首板", "打板", "炸板", "破净", "破发",
    "高价股", "低价股", "百元股", "大盘股", "中盘股", "小盘股", "次新股",
    "融资融券", "沪股通", "深股通", "机构重仓", "基金重仓", "社保重仓",
    "券商重仓", "QFII", "MSCI", "富时罗素", "标准普尔", "预盈预增",
    "预亏预减", "高送转", "股权转让", "转债标的", "AH股",
    "权重股", "茅指数", "核心资产", "蓝筹股", "绩优股", "价值股", "成长股",
    "上证", "中证", "深证", "沪深", "指数", "创业板", "科创板",
    "热股", "人气", "排行", "热门股",
)


def 数值(value: Any, default: float = np.nan) -> float:
    if value in (None, "", "-"):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def 百分比(value: Any, digits: int = 1) -> str:
    value = 数值(value)
    return "-" if math.isnan(value) else f"{value * 100:.{digits}f}%"


def 百分点(value: Any, digits: int = 1) -> str:
    value = 数值(value)
    return "-" if math.isnan(value) else f"{value:.{digits}f}%"


def 金额(value: Any) -> str:
    value = 数值(value)
    if math.isnan(value):
        return "-"
    if abs(value) >= 1e8:
        return f"{value / 1e8:.1f}亿"
    if abs(value) >= 1e4:
        return f"{value / 1e4:.0f}万"
    return f"{value:.0f}"


def 请求_json(url: str, params: dict[str, Any], referer: str | None = None) -> dict[str, Any]:
    headers = dict(请求头)
    if referer:
        headers["Referer"] = referer
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            response = requests.get(url, params=params, headers=headers, timeout=12)
            response.raise_for_status()
            return response.json()
        except Exception as exc:
            last_error = exc
            time.sleep(0.4 + attempt * 0.6)
    raise RuntimeError(f"接口请求失败：{url}；{last_error}")


def 获取全部列表(fs: str, fields: str, sort_field: str = "f6") -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    page = 1
    while page <= 20:
        payload = 请求_json(
            东方财富列表接口,
            {
                "pn": page,
                "pz": 100,
                "po": 1,
                "np": 1,
                "ut": 接口令牌,
                "fltt": 2,
                "invt": 2,
                "fid": sort_field,
                "fs": fs,
                "fields": fields,
            },
        )
        data = payload.get("data") or {}
        diff = data.get("diff") or []
        if isinstance(diff, dict):
            diff = list(diff.values())
        rows.extend(diff)
        total = int(data.get("total") or len(rows))
        if len(rows) >= total or not diff:
            break
        page += 1
    return rows


def 获取板块列表(kind: str) -> pd.DataFrame:
    fs = "m:90+t:2" if kind == "行业" else "m:90+t:3"
    rows = 获取全部列表(fs, 板块字段)
    records = []
    for row in rows:
        up = 数值(row.get("f104"), 0)
        down = 数值(row.get("f105"), 0)
        records.append(
            {
                "板块代码": str(row.get("f12") or ""),
                "板块名称": str(row.get("f14") or ""),
                "类型": kind,
                "当日涨幅": 数值(row.get("f3")),
                "五日涨幅": 数值(row.get("f109")),
                "六十日涨幅": 数值(row.get("f24")),
                "年内涨幅": 数值(row.get("f25")),
                "成交额": 数值(row.get("f6"), 0),
                "换手率": 数值(row.get("f8")),
                "当日资金估算": 数值(row.get("f62"), 0),
                "五日资金估算": 数值(row.get("f164"), 0),
                "十日资金估算": 数值(row.get("f174"), 0),
                "上涨家数": up,
                "下跌家数": down,
                "当日上涨广度": up / (up + down) if up + down > 0 else np.nan,
                "行情时间戳": 数值(row.get("f124"), 0),
            }
        )
    frame = pd.DataFrame(records)
    if kind == "概念":
        frame = frame[
            ~frame["板块名称"].apply(
                lambda name: str(name).endswith("_")
                or any(word.lower() in str(name).lower() for word in 非产业概念关键词)
            )
        ]
    return frame.drop_duplicates("板块代码").reset_index(drop=True)


def 证券标识(code: str) -> str:
    return ("1." if code.startswith(("5", "6", "9")) else "0.") + code


def 获取腾讯日线(code: str, limit: int = 380) -> pd.DataFrame:
    cache = 缓存目录 / f"股票_{code}.csv"
    symbol = ("sh" if code == "000300" or code.startswith(("5", "6", "9")) else "sz") + code
    payload = 请求_json(
        腾讯日线接口,
        {"param": f"{symbol},day,,,{limit},qfq"},
        referer="https://gu.qq.com/",
    )
    node = ((payload.get("data") or {}).get(symbol)) or {}
    rows = node.get("qfqday") or node.get("day") or []
    records = []
    for row in rows:
        if len(row) < 6:
            continue
        records.append(
            {
                "日期": row[0],
                "开盘": 数值(row[1]),
                "收盘": 数值(row[2]),
                "最高": 数值(row[3]),
                "最低": 数值(row[4]),
                "成交量": 数值(row[5]),
            }
        )
    frame = pd.DataFrame(records)
    if frame.empty:
        if cache.exists():
            return pd.read_csv(cache, parse_dates=["日期"]).set_index("日期")
        raise RuntimeError(f"{code}没有日线数据")
    frame["日期"] = pd.to_datetime(frame["日期"])
    frame = frame.set_index("日期").sort_index()
    frame.to_csv(cache, encoding="utf-8-sig")
    return frame


def 获取板块日线(code: str, limit: int = 280) -> pd.DataFrame:
    cache = 缓存目录 / f"板块_{code}.csv"
    payload = 请求_json(
        东方财富日线接口,
        {
            "secid": f"90.{code}",
            "fields1": "f1,f2,f3,f4,f5,f6",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
            "klt": 101,
            "fqt": 1,
            "beg": "20240101",
            "end": "20500101",
            "lmt": limit,
        },
    )
    rows = ((payload.get("data") or {}).get("klines")) or []
    records = []
    for row in rows:
        parts = str(row).split(",")
        if len(parts) < 11:
            continue
        records.append(
            {
                "日期": parts[0],
                "开盘": 数值(parts[1]),
                "收盘": 数值(parts[2]),
                "最高": 数值(parts[3]),
                "最低": 数值(parts[4]),
                "成交量": 数值(parts[5]),
                "成交额": 数值(parts[6]),
                "换手率": 数值(parts[10]),
            }
        )
    frame = pd.DataFrame(records)
    if frame.empty:
        if cache.exists():
            return pd.read_csv(cache, parse_dates=["日期"]).set_index("日期")
        raise RuntimeError(f"{code}没有板块日线数据")
    frame["日期"] = pd.to_datetime(frame["日期"])
    frame = frame.set_index("日期").sort_index()
    frame.to_csv(cache, encoding="utf-8-sig")
    return frame


def 收益(frame: pd.DataFrame, days: int, offset: int = 0) -> float:
    close = frame["收盘"].dropna()
    if len(close) <= days + offset:
        return np.nan
    end = close.iloc[-1 - offset]
    start = close.iloc[-1 - offset - days]
    return end / start - 1 if start else np.nan


def 年内收益(frame: pd.DataFrame) -> float:
    current = frame.index.max()
    year = frame.loc[frame.index.year == current.year, "收盘"].dropna()
    return year.iloc[-1] / year.iloc[0] - 1 if len(year) >= 2 else np.nan


def 排名分(series: pd.Series) -> pd.Series:
    return series.rank(pct=True, method="average").fillna(0.0)


def 构造预选分数(boards: pd.DataFrame, benchmark: pd.DataFrame) -> pd.DataFrame:
    result = boards.copy()
    benchmark_5 = 收益(benchmark, 5) * 100
    benchmark_60 = 收益(benchmark, 60) * 100
    benchmark_ytd = 年内收益(benchmark) * 100
    result["五日超额"] = result["五日涨幅"] - benchmark_5
    result["六十日超额"] = result["六十日涨幅"] - benchmark_60
    result["年内超额"] = result["年内涨幅"] - benchmark_ytd
    result["资金成交比"] = result["当日资金估算"] / result["成交额"].replace(0, np.nan)
    scored = []
    for _, group in result.groupby("类型"):
        group = group.copy()
        group["预选分"] = (
            排名分(group["五日超额"]) * 15
            + 排名分(group["六十日超额"]) * 25
            + 排名分(group["年内超额"]) * 10
            + 排名分(group["当日上涨广度"]) * 15
            + 排名分(np.log1p(group["成交额"])) * 10
            + 排名分(group["资金成交比"].clip(-0.2, 0.2)) * 5
            + (group["五日超额"] > 0).astype(int) * 5
            + (group["六十日超额"] > 0).astype(int) * 10
            + (group["年内超额"] > 0).astype(int) * 5
        )
        scored.append(group)
    return pd.concat(scored, ignore_index=True).sort_values("预选分", ascending=False)


def 并行获取板块日线(boards: pd.DataFrame) -> dict[str, pd.DataFrame]:
    result: dict[str, pd.DataFrame] = {}
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(获取板块日线, code): code for code in boards["板块代码"]}
        for future in as_completed(futures):
            code = futures[future]
            try:
                result[code] = future.result()
            except Exception as exc:
                print(f"板块日线缺失 {code}: {exc}")
    return result


def 补充主线价格特征(
    boards: pd.DataFrame, histories: dict[str, pd.DataFrame], benchmark: pd.DataFrame
) -> pd.DataFrame:
    result = boards.copy()
    benchmark_rel20 = benchmark["收盘"].pct_change(20)
    persistence: dict[str, float] = {}
    features: dict[str, dict[str, Any]] = {}
    for kind, group in result.groupby("类型"):
        relative_series = {}
        for code in group["板块代码"]:
            frame = histories.get(code)
            if frame is None:
                continue
            common = frame.index.intersection(benchmark.index)
            relative_series[code] = (
                frame.loc[common, "收盘"].pct_change(20) - benchmark_rel20.reindex(common)
            )
        if relative_series:
            relative = pd.DataFrame(relative_series).sort_index()
            ranks = relative.rank(axis=1, ascending=False, pct=True, method="average")
            for code in relative.columns:
                persistence[code] = float((ranks[code].tail(10) <= 0.30).mean())

    for code, frame in histories.items():
        common = frame.index.intersection(benchmark.index)
        aligned = frame.loc[common]
        bench = benchmark.loc[common]
        close = aligned["收盘"]
        amount = aligned["成交额"]
        features[code] = {
            "五日实际超额": (收益(aligned, 5) - 收益(bench, 5)) * 100,
            "二十日实际超额": (收益(aligned, 20) - 收益(bench, 20)) * 100,
            "六十日实际超额": (收益(aligned, 60) - 收益(bench, 60)) * 100,
            "十日排名持续率": persistence.get(code, 0),
            "板块量能比": amount.tail(5).mean() / amount.tail(20).mean() if len(amount) >= 20 and amount.tail(20).mean() else np.nan,
            "板块多周期趋势": bool(
                len(close) >= 60
                and close.iloc[-1] > close.tail(20).mean() > close.tail(60).mean()
            ),
            "板块行情日期": aligned.index.max().strftime("%Y-%m-%d"),
        }
    feature_frame = pd.DataFrame.from_dict(features, orient="index")
    feature_frame.index.name = "板块代码"
    result = result.merge(feature_frame.reset_index(), on="板块代码", how="left")
    scored = []
    for _, group in result.groupby("类型"):
        group = group.copy()
        group["相对强度分"] = (
            排名分(group["二十日实际超额"]) * 10 + 排名分(group["六十日实际超额"]) * 10
        )
        group["持续性分"] = group["十日排名持续率"].fillna(0) * 15
        group["初步广度分"] = 排名分(group["当日上涨广度"]) * 10
        group["参与度分"] = (
            排名分(np.log1p(group["成交额"])) * 5 + 排名分(group["板块量能比"]) * 5
        )
        group["市场结构初分"] = (
            group["相对强度分"] + group["持续性分"] + group["初步广度分"] + group["参与度分"]
        )
        scored.append(group)
    return pd.concat(scored, ignore_index=True).sort_values("市场结构初分", ascending=False)


def 获取板块成分股(board_code: str, limit: int = 80) -> pd.DataFrame:
    rows = 获取全部列表(f"b:{board_code}", 成分股字段, sort_field="f6")[:limit]
    records = []
    for row in rows:
        code = str(row.get("f12") or "")
        name = str(row.get("f14") or "")
        if not code.startswith(("60", "00")) or "ST" in name.upper() or "退" in name:
            continue
        records.append(
            {
                "股票代码": code,
                "股票名称": name,
                "现价": 数值(row.get("f2")),
                "当日涨幅": 数值(row.get("f3")),
                "成交额": 数值(row.get("f6"), 0),
                "换手率": 数值(row.get("f8")),
                "总市值": 数值(row.get("f20"), 0),
                "流通市值": 数值(row.get("f21"), 0),
                "市盈率": 数值(row.get("f9")),
                "市净率": 数值(row.get("f23")),
                "行业": str(row.get("f100") or ""),
            }
        )
    return pd.DataFrame(records).drop_duplicates("股票代码").head(每板块研究股票数)


def 财务证券代码(code: str) -> str:
    return code + (".SH" if code.startswith("6") else ".SZ")


def 获取财务摘要(code: str) -> list[dict[str, Any]]:
    cache = 缓存目录 / f"财务_{code}.json"
    try:
        payload = 请求_json(
            东方财富财务接口,
            {
                "reportName": "RPT_F10_FINANCE_MAINFINADATA",
                "columns": "ALL",
                "filter": f'(SECUCODE="{财务证券代码(code)}")',
                "pageNumber": 1,
                "pageSize": 8,
                "sortTypes": -1,
                "sortColumns": "REPORT_DATE",
            },
            referer="https://emweb.securities.eastmoney.com/",
        )
        rows = ((payload.get("result") or {}).get("data")) or []
        cache.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
        return rows
    except Exception:
        if cache.exists():
            return json.loads(cache.read_text(encoding="utf-8"))
        return []


def 并行获取股票资料(codes: list[str]) -> tuple[dict[str, pd.DataFrame], dict[str, list[dict[str, Any]]]]:
    histories: dict[str, pd.DataFrame] = {}
    financials: dict[str, list[dict[str, Any]]] = {}
    with ThreadPoolExecutor(max_workers=8) as pool:
        price_futures = {pool.submit(获取腾讯日线, code): code for code in codes}
        for future in as_completed(price_futures):
            code = price_futures[future]
            try:
                histories[code] = future.result()
            except Exception as exc:
                print(f"股票日线缺失 {code}: {exc}")
    with ThreadPoolExecutor(max_workers=6) as pool:
        finance_futures = {pool.submit(获取财务摘要, code): code for code in codes}
        for future in as_completed(finance_futures):
            financials[finance_futures[future]] = future.result()
    return histories, financials


def 股票价格特征(frame: pd.DataFrame, benchmark: pd.DataFrame) -> dict[str, float]:
    common = frame.index.intersection(benchmark.index)
    stock = frame.loc[common]
    bench = benchmark.loc[common]
    daily = stock["收盘"].pct_change()
    volatility = daily.tail(252).std() * math.sqrt(252)
    rel6 = 收益(stock, 126, 21) - 收益(bench, 126, 21)
    rel12 = 收益(stock, 252, 21) - 收益(bench, 252, 21)
    recognition = np.nan
    if volatility and not math.isnan(volatility):
        values = [value / volatility for value in (rel6, rel12) if not math.isnan(value)]
        recognition = float(np.mean(values)) if values else np.nan
    return {
        "二十日股票超额": (收益(stock, 20) - 收益(bench, 20)) * 100,
        "六十日股票超额": (收益(stock, 60) - 收益(bench, 60)) * 100,
        "长期认可原值": recognition,
    }


def 最新财务(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return rows[0] if rows else {}


def 构造成分股总表(
    board_members: dict[str, pd.DataFrame],
    board_names: dict[str, str],
    histories: dict[str, pd.DataFrame],
    financials: dict[str, list[dict[str, Any]]],
    benchmark: pd.DataFrame,
) -> pd.DataFrame:
    records = []
    for board_code, members in board_members.items():
        for _, member in members.iterrows():
            code = member["股票代码"]
            price_feature = 股票价格特征(histories[code], benchmark) if code in histories else {}
            latest = 最新财务(financials.get(code, []))
            records.append(
                {
                    **member.to_dict(),
                    "板块代码": board_code,
                    "板块名称": board_names[board_code],
                    **price_feature,
                    "财报期": latest.get("REPORT_DATE_NAME", ""),
                    "公告日期": str(latest.get("NOTICE_DATE") or "")[:10],
                    "营业收入": 数值(latest.get("TOTALOPERATEREVE")),
                    "归母净利润": 数值(latest.get("PARENTNETPROFIT")),
                    "营收增长": 数值(latest.get("TOTALOPERATEREVETZ")),
                    "利润增长": 数值(latest.get("PARENTNETPROFITTZ")),
                    "扣非利润增长": 数值(latest.get("KCFJCXSYJLRTZ")),
                    "净资产收益率": 数值(latest.get("ROEJQ")),
                    "投入资本回报率": 数值(latest.get("ROIC")),
                    "毛利率": 数值(latest.get("XSMLL")),
                    "资产负债率": 数值(latest.get("ZCFZL")),
                    "经营现金利润比": 数值(latest.get("NCO_NETPROFIT")),
                    "不良率": 数值(latest.get("NON_PERFORMING_LOAN")),
                    "拨备覆盖": 数值(latest.get("BLDKBBL")),
                    "资本充足率": 数值(latest.get("NEWCAPITALADER")),
                    "近四期盈利为正比例": (
                        np.mean([数值(row.get("PARENTNETPROFIT"), 0) > 0 for row in financials.get(code, [])[:4]])
                        if financials.get(code)
                        else np.nan
                    ),
                }
            )
    return pd.DataFrame(records)


def 完成主线评分(boards: pd.DataFrame, members: pd.DataFrame) -> pd.DataFrame:
    result = boards.copy()
    additions = []
    for _, board in result.iterrows():
        group = members[members["板块代码"].eq(board["板块代码"])]
        valid_price = group["二十日股票超额"].notna()
        breadth20 = (group.loc[valid_price, "二十日股票超额"] > 0).mean() if valid_price.any() else np.nan
        valid60 = group["六十日股票超额"].notna()
        breadth60 = (group.loc[valid60, "六十日股票超额"] > 0).mean() if valid60.any() else np.nan
        leaders = int(
            (
                (group["二十日股票超额"] > 0)
                & (group["六十日股票超额"] > 0)
                & (group["总市值"].rank(pct=True) >= 0.5)
            ).sum()
        )
        earnings_valid = group["营收增长"].notna() & group["利润增长"].notna()
        earnings_breadth = (
            ((group.loc[earnings_valid, "营收增长"] > 0) & (group.loc[earnings_valid, "利润增长"] > 0)).mean()
            if earnings_valid.any()
            else np.nan
        )
        breadth_score = (
            (0 if math.isnan(数值(board["当日上涨广度"])) else board["当日上涨广度"] * 5)
            + (0 if math.isnan(数值(breadth20)) else breadth20 * 10)
            + (0 if math.isnan(数值(breadth60)) else breadth60 * 5)
        )
        leader_score = min(leaders / 3, 1) * 10
        if valid_price.any() and group.loc[valid_price, "二十日股票超额"].median() > 0:
            leader_score += 5
        fact_score = 0 if math.isnan(数值(earnings_breadth)) else earnings_breadth * 15
        identity = (
            数值(board["相对强度分"], 0)
            + 数值(board["持续性分"], 0)
            + breadth_score
            + leader_score
            + 数值(board["参与度分"], 0)
            + fact_score
        )
        market_gate = sum(
            [
                数值(board["二十日实际超额"], -999) > 0,
                数值(board["六十日实际超额"], -999) > 0,
                数值(board["十日排名持续率"], 0) >= 0.5,
            ]
        ) >= 2
        structure_gate = leaders >= 3 and 数值(breadth20, 0) >= 0.5
        fact_gate = 数值(earnings_breadth, 0) >= 0.5
        crowded = 数值(board["板块量能比"], 0) >= 1.8 and 数值(breadth20, 0) < 0.5
        if identity >= 75 and market_gate and structure_gate and fact_gate and 数值(breadth20, 0) >= 0.65:
            phase = "扩散"
        elif identity >= 70 and market_gate and structure_gate and fact_gate:
            phase = "确认"
        elif identity >= 65 and market_gate and fact_gate:
            phase = "形成"
        elif identity >= 55:
            phase = "萌芽"
        else:
            phase = "观察"
        if crowded and phase in {"扩散", "确认"}:
            phase = "拥挤"
        continuation = (
            数值(earnings_breadth, 0) * 25
            + 数值(breadth20, 0) * 15
            + min(leaders / 3, 1) * 15
            + 数值(board["十日排名持续率"], 0) * 20
            + (10 if market_gate else 0)
            + (10 if 数值(board["六十日实际超额"], -999) > 0 else 0)
            + (5 if 数值(board["板块量能比"], 0) <= 1.8 else 0)
            - (15 if crowded else 0)
        )
        confidence = "高" if continuation >= 70 and 数值(board["六十日实际超额"], -999) > 0 else "中" if continuation >= 50 else "低"
        missing = []
        if math.isnan(数值(earnings_breadth)):
            missing.append("盈利扩散")
        missing.extend(["产业催化", "主营收入纯度"])
        additions.append(
            {
                "板块代码": board["板块代码"],
                "二十日上涨广度": breadth20,
                "六十日上涨广度": breadth60,
                "核心龙头数量": leaders,
                "盈利扩散比例": earnings_breadth,
                "广度分": breadth_score,
                "龙头结构分": leader_score,
                "事实验证分": fact_score,
                "主线身份分": identity,
                "主线阶段": phase,
                "延续置信度": confidence,
                "延续评分": continuation,
                "市场门": market_gate,
                "结构门": structure_gate,
                "事实门": fact_gate,
                "缺失证据": "、".join(missing),
            }
        )
    result = result.merge(pd.DataFrame(additions), on="板块代码", how="left")
    phase_order = {"扩散": 5, "确认": 4, "拥挤": 3, "形成": 2, "萌芽": 1, "观察": 0}
    result["阶段序"] = result["主线阶段"].map(phase_order).fillna(0)
    return result.sort_values(["阶段序", "主线身份分", "延续评分"], ascending=False)


def 分位(group: pd.DataFrame, column: str, inverse: bool = False) -> pd.Series:
    values = group[column]
    ranked = values.rank(pct=True, method="average", ascending=not inverse)
    return ranked.fillna(0)


def 评价第一梯队(members: pd.DataFrame) -> pd.DataFrame:
    rows = []
    financial_words = ("银行", "证券", "保险", "金融")
    for board_code, group in members.groupby("板块代码"):
        group = group.copy()
        group["市值分位"] = 分位(group, "总市值")
        group["收入分位"] = 分位(group, "营业收入")
        group["净资产收益率分位"] = 分位(group, "净资产收益率")
        group["投入资本回报分位"] = 分位(group, "投入资本回报率")
        group["现金质量分位"] = 分位(group, "经营现金利润比")
        group["毛利率分位"] = 分位(group, "毛利率")
        group["低负债分位"] = 分位(group, "资产负债率", inverse=True)
        group["营收增长分位"] = 分位(group, "营收增长")
        group["利润增长分位"] = 分位(group, "利润增长")
        group["长期认可分位"] = 分位(group, "长期认可原值")
        group["成交分位"] = 分位(group, "成交额")
        group["流通市值分位"] = 分位(group, "流通市值")
        for _, stock in group.iterrows():
            is_financial = any(word in str(stock["板块名称"]) or word in str(stock["行业"]) for word in financial_words)
            industry_score = 12 + stock["市值分位"] * 10 + stock["收入分位"] * 8
            if is_financial:
                quality_score = (
                    stock["净资产收益率分位"] * 10
                    + stock["利润增长分位"] * 8
                    + (0 if math.isnan(数值(stock["不良率"])) else (1 - min(stock["不良率"] / 5, 1)) * 6)
                    + (0 if math.isnan(数值(stock["拨备覆盖"])) else min(stock["拨备覆盖"] / 300, 1) * 6)
                )
            else:
                quality_score = (
                    stock["净资产收益率分位"] * 8
                    + stock["投入资本回报分位"] * 5
                    + stock["现金质量分位"] * 7
                    + stock["毛利率分位"] * 5
                    + stock["低负债分位"] * 5
                )
            growth_score = (
                stock["营收增长分位"] * 8
                + stock["利润增长分位"] * 8
                + 数值(stock["近四期盈利为正比例"], 0) * 4
            )
            recognition_score = stock["长期认可分位"] * 15
            investability = stock["成交分位"] * 3 + stock["流通市值分位"] * 2
            risk = 0
            risk_reasons = []
            if 数值(stock["归母净利润"], 1) <= 0:
                risk += 10
                risk_reasons.append("最新归母利润为负")
            if not is_financial and 数值(stock["经营现金利润比"], 1) < 0:
                risk += 5
                risk_reasons.append("经营现金与利润背离")
            if not is_financial and 数值(stock["资产负债率"], 0) > 85:
                risk += 5
                risk_reasons.append("资产负债率较高")
            if 数值(stock["营收增长"], 0) < -30:
                risk += 3
                risk_reasons.append("营收下降较快")
            if 数值(stock["利润增长"], 0) < -50:
                risk += 5
                risk_reasons.append("利润下降较快")
            total = industry_score + quality_score + growth_score + recognition_score + investability - risk
            roles = []
            if stock["市值分位"] >= 0.7 or stock["收入分位"] >= 0.7:
                roles.append("产业核心")
            if quality_score + growth_score >= 35:
                roles.append("业绩核心")
            if stock["长期认可分位"] >= 0.7:
                roles.append("市场核心")
            core_fields = [
                "营业收入", "归母净利润", "营收增长", "利润增长", "净资产收益率",
                "资产负债率", "经营现金利润比", "长期认可原值",
            ]
            coverage = np.mean([not math.isnan(数值(stock[field])) for field in core_fields])
            confidence = "A" if coverage >= 0.85 else "B" if coverage >= 0.65 else "C"
            official = (
                total >= 75
                and industry_score >= 20
                and quality_score >= 18
                and "产业核心" in roles
                and len(roles) >= 2
            )
            rows.append(
                {
                    **stock.to_dict(),
                    "产业地位代理分": industry_score,
                    "基本面质量分": quality_score,
                    "增长持续性分": growth_score,
                    "中长期认可分": recognition_score,
                    "可投资性分": investability,
                    "风险扣分": risk,
                    "第一梯队总分": total,
                    "角色": "、".join(roles) or "待确认",
                    "数据覆盖率": coverage,
                    "数据置信等级": confidence,
                    "评价状态": "正式第一梯队" if official else "第一梯队候选",
                    "风险说明": "、".join(risk_reasons) or "未触发量化硬风险",
                    "产业纯度状态": "仅确认板块成分关系，待主营业务分部收入核验",
                }
            )
    return pd.DataFrame(rows).sort_values(["板块代码", "第一梯队总分"], ascending=[True, False])


def 选择去重主线(
    mainline_all: pd.DataFrame,
    board_members: dict[str, pd.DataFrame],
    limit: int,
) -> pd.DataFrame:
    selected_rows = []
    selected_members: list[set[str]] = []
    for _, row in mainline_all.iterrows():
        frame = board_members.get(row["板块代码"], pd.DataFrame())
        members = set(frame["股票代码"].tolist()) if not frame.empty else set()
        duplicated = False
        for existing in selected_members:
            denominator = min(len(members), len(existing))
            overlap = len(members & existing) / denominator if denominator else 0
            if overlap >= 0.50:
                duplicated = True
                break
        if duplicated:
            continue
        selected_rows.append(row)
        selected_members.append(members)
        if len(selected_rows) >= limit:
            break
    return pd.DataFrame(selected_rows).reset_index(drop=True)


ETF同义词 = [
    (("黄金", "白银", "贵金属"), ("黄金", "有色")),
    (("有色", "铜", "铝", "稀土", "小金属"), ("有色", "稀土", "矿业")),
    (("半导体", "芯片", "光刻", "存储", "集成电路"), ("半导体", "芯片", "集成电路")),
    (("通信", "光模块", "光通信", "CPO", "5G", "6G"), ("通信", "5G", "人工智能", "AI")),
    (("软件", "计算机", "信创", "数据", "云计算"), ("软件", "计算机", "云计算", "大数据", "人工智能")),
    (("机器人", "自动化", "智能制造"), ("机器人", "智能制造")),
    (("创新药", "医药", "医疗", "生物", "CRO", "研发外包"), ("创新药", "医药", "医疗", "生物科技")),
    (("银行",), ("银行",)),
    (("证券", "券商"), ("证券", "券商")),
    (("保险",), ("保险", "非银")),
    (("煤炭", "动力煤", "焦煤"), ("煤炭",)),
    (("石油", "油气"), ("油气", "石油")),
    (("光伏", "新能源", "锂电", "电池"), ("光伏", "新能源", "电池", "锂电")),
    (("军工", "国防", "航天", "航空"), ("军工", "国防")),
    (("消费", "食品", "饮料", "白酒", "超级品牌"), ("消费", "食品", "酒")),
    (("农业", "养殖", "种植"), ("农业", "畜牧", "养殖")),
    (("电力", "发电", "公用事业"), ("电力", "绿色电力", "公用事业")),
    (("地产", "房地产"), ("地产", "房地产")),
    (("化工", "化学"), ("化工",)),
]


def ETF关键词(board_name: str) -> tuple[str, ...]:
    for triggers, keywords in ETF同义词:
        if any(word in board_name for word in triggers):
            return keywords
    compact = board_name.replace("行业", "").replace("概念", "").replace("设备", "")
    return (compact,) if len(compact) >= 2 else ()


def 获取ETF替代工具(mainlines: pd.DataFrame) -> pd.DataFrame:
    etfs = pd.DataFrame(
        [
            {
                "ETF代码": str(row.get("f12") or ""),
                "ETF名称": str(row.get("f14") or ""),
                "成交额": 数值(row.get("f6"), 0),
                "规模代理": 数值(row.get("f20"), 0),
                "当日涨幅": 数值(row.get("f3")),
                "五日涨幅": 数值(row.get("f109")),
            }
            for row in 获取全部列表("b:MK0021,b:MK0022,b:MK0023,b:MK0024", ETF字段)
        ]
    )
    rows = []
    for _, board in mainlines.iterrows():
        keywords = ETF关键词(board["板块名称"])
        if not keywords:
            continue
        candidates = etfs[etfs["ETF名称"].apply(lambda name: any(word.lower() in name.lower() for word in keywords))].copy()
        if "超级品牌" in board["板块名称"]:
            candidates = candidates[~candidates["ETF名称"].str.contains("消费电子", na=False)]
        if candidates.empty:
            continue
        candidates["匹配分"] = candidates["ETF名称"].apply(
            lambda name: sum(1 for word in keywords if word.lower() in name.lower())
        )
        candidates = candidates.sort_values(["匹配分", "成交额", "规模代理"], ascending=False).head(2)
        for _, etf in candidates.iterrows():
            rows.append(
                {
                    "主线": board["板块名称"],
                    **etf.to_dict(),
                    "评价说明": "按主题名称匹配、成交额和规模代理排序；费率与跟踪误差待补",
                }
            )
    return pd.DataFrame(rows)


def 市场状态(benchmark: pd.DataFrame) -> tuple[str, str]:
    close = benchmark["收盘"]
    ma20 = close.tail(20).mean()
    ma60 = close.tail(60).mean()
    ret20 = 收益(benchmark, 20)
    if close.iloc[-1] > ma20 > ma60 and ret20 > 0:
        return "强趋势", f"沪深300站上20日和60日均线，20日收益{ret20 * 100:.1f}%"
    if close.iloc[-1] > ma60 or ret20 > 0:
        return "修复或震荡", f"沪深300结构尚未形成完整多头，20日收益{ret20 * 100:.1f}%"
    return "防守", f"沪深300位于60日均线下方且20日收益{ret20 * 100:.1f}%"


def 证据摘要(row: pd.Series) -> str:
    good = []
    bad = []
    if 数值(row["二十日实际超额"], -999) > 0:
        good.append(f"20日超额{百分点(row['二十日实际超额'])}")
    else:
        bad.append(f"20日超额{百分点(row['二十日实际超额'])}")
    if 数值(row["六十日实际超额"], -999) > 0:
        good.append(f"60日超额{百分点(row['六十日实际超额'])}")
    else:
        bad.append(f"60日超额{百分点(row['六十日实际超额'])}")
    good.append(f"20日广度{百分比(row['二十日上涨广度'])}")
    good.append(f"盈利扩散{百分比(row['盈利扩散比例'])}")
    if 数值(row["板块量能比"], 0) > 1.8:
        bad.append("量能偏拥挤")
    return "；".join(good[:4]) + ("。反证：" + "、".join(bad) if bad else "")


def 生成看板(
    benchmark: pd.DataFrame,
    mainlines: pd.DataFrame,
    first_tier: pd.DataFrame,
    etfs: pd.DataFrame,
    board_counts: dict[str, int],
) -> None:
    state, state_reason = 市场状态(benchmark)
    generated = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    market_date = benchmark.index.max().strftime("%Y-%m-%d")
    rows_main = []
    for _, row in mainlines.iterrows():
        rows_main.append(
            f"<tr><td><strong>{html.escape(row['板块名称'])}</strong><small>{row['类型']}</small></td>"
            f"<td><span class='phase p-{html.escape(row['主线阶段'])}'>{html.escape(row['主线阶段'])}</span></td>"
            f"<td>{row['主线身份分']:.1f}</td><td>{html.escape(row['延续置信度'])} / {row['延续评分']:.1f}</td>"
            f"<td>{百分比(row['十日排名持续率'])}</td><td>{百分比(row['二十日上涨广度'])}</td>"
            f"<td>{int(row['核心龙头数量'])}</td><td>{百分比(row['盈利扩散比例'])}</td>"
            f"<td>{html.escape(证据摘要(row))}<small class='gap'>缺口：{html.escape(row['缺失证据'])}</small></td></tr>"
        )

    tier_sections = []
    for _, board in mainlines.head(正式主线展示数).iterrows():
        group = first_tier[first_tier["板块代码"].eq(board["板块代码"])].head(每条主线股票展示数)
        stock_rows = []
        for _, stock in group.iterrows():
            stock_rows.append(
                f"<tr><td><strong>{html.escape(stock['股票名称'])}</strong><small>{stock['股票代码']} · {html.escape(stock['行业'])}</small></td>"
                f"<td>{html.escape(stock['评价状态'])}</td><td>{stock['第一梯队总分']:.1f}</td>"
                f"<td>{stock['产业地位代理分']:.1f}</td><td>{stock['基本面质量分']:.1f}</td>"
                f"<td>{stock['增长持续性分']:.1f}</td><td>{stock['中长期认可分']:.1f}</td>"
                f"<td>{stock['风险扣分']:.0f}</td><td>{html.escape(stock['角色'])}</td>"
                f"<td>{html.escape(stock['数据置信等级'])} / {百分比(stock['数据覆盖率'])}</td>"
                f"<td>{html.escape(stock['财报期'])}<small class='gap'>{html.escape(stock['产业纯度状态'])}</small></td></tr>"
            )
        tier_sections.append(
            f"<section><div class='section-head'><h2>{html.escape(board['板块名称'])} 第一梯队</h2>"
            f"<span>{html.escape(board['主线阶段'])} · 身份分 {board['主线身份分']:.1f}</span></div>"
            "<div class='table-wrap'><table><thead><tr><th>公司</th><th>状态</th><th>总分</th><th>产业</th>"
            "<th>质量</th><th>增长</th><th>长期认可</th><th>风险扣分</th><th>角色</th><th>置信</th><th>财务依据</th></tr></thead>"
            f"<tbody>{''.join(stock_rows) or '<tr><td colspan=11>暂无足够数据</td></tr>'}</tbody></table></div></section>"
        )

    etf_rows = []
    if not etfs.empty:
        for _, row in etfs.iterrows():
            etf_rows.append(
                f"<tr><td>{html.escape(row['主线'])}</td><td><strong>{html.escape(row['ETF名称'])}</strong><small>{row['ETF代码']}</small></td>"
                f"<td>{金额(row['成交额'])}</td><td>{金额(row['规模代理'])}</td><td>{html.escape(row['评价说明'])}</td></tr>"
            )

    document = f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>A股主线与第一梯队试运行</title>
<style>
:root{{--ink:#20252b;--muted:#68717b;--line:#d9dee3;--paper:#fff;--soft:#f5f7f8;--green:#17734b;--amber:#9a6500;--red:#a63838;--blue:#225f91}}
*{{box-sizing:border-box}}body{{margin:0;color:var(--ink);background:var(--paper);font-family:"Microsoft YaHei","Segoe UI",sans-serif;font-size:14px;letter-spacing:0}}
header{{padding:28px 4vw 22px;border-bottom:1px solid var(--line);background:#f8faf9}}h1{{font-size:26px;margin:0 0 8px}}h2{{font-size:18px;margin:0}}p{{margin:5px 0;color:var(--muted)}}
.summary{{display:grid;grid-template-columns:repeat(4,minmax(150px,1fr));gap:1px;background:var(--line);border-bottom:1px solid var(--line)}}.metric{{background:white;padding:18px 4vw}}.metric b{{display:block;font-size:20px;margin-top:5px}}
section{{padding:24px 4vw;border-bottom:1px solid var(--line)}}.section-head{{display:flex;justify-content:space-between;align-items:end;gap:12px;margin-bottom:12px}}.section-head span{{color:var(--muted)}}
.table-wrap{{width:100%;overflow:auto;border:1px solid var(--line);border-radius:6px}}table{{width:100%;border-collapse:collapse;min-width:980px}}th,td{{padding:10px 11px;border-bottom:1px solid #e8ebee;text-align:left;vertical-align:top}}th{{background:var(--soft);font-weight:600;white-space:nowrap}}tr:last-child td{{border-bottom:0}}small{{display:block;color:var(--muted);margin-top:4px}}.gap{{color:#875f20}}
.phase{{display:inline-block;font-weight:700}}.p-扩散,.p-确认{{color:var(--green)}}.p-拥挤{{color:var(--red)}}.p-形成,.p-萌芽{{color:var(--amber)}}.p-观察{{color:var(--muted)}}
.notice{{border-left:3px solid var(--amber);padding:10px 14px;background:#fffaf0;color:#5e4c2b;margin-top:14px}}footer{{padding:20px 4vw 35px;color:var(--muted)}}
@media(max-width:760px){{.summary{{grid-template-columns:1fr 1fr}}header,section{{padding-left:18px;padding-right:18px}}.section-head{{align-items:start;flex-direction:column}}}}
</style></head><body>
<header><h1>A股主线与第一梯队试运行</h1><p>行情日期 {market_date} · 生成时间 {generated} · 只评价主线和公司身份，不评价买点与当前位置</p></header>
<div class="summary"><div class="metric">市场状态<b>{state}</b><small>{state_reason}</small></div><div class="metric">扫描范围<b>{board_counts['行业']} 行业</b><small>{board_counts['概念']} 个概念板块</small></div><div class="metric">候选主线<b>{len(mainlines)} 条</b><small>行业与概念分别排名后合并</small></div><div class="metric">数据原则<b>逐期可见</b><small>最新财务按公告日读取</small></div></div>
<section><div class="section-head"><h2>主线判断</h2><span>身份与延续分开显示</span></div><div class="table-wrap"><table><thead><tr><th>板块</th><th>阶段</th><th>身份分</th><th>延续</th><th>持续率</th><th>20日广度</th><th>龙头数</th><th>盈利扩散</th><th>证据与反证</th></tr></thead><tbody>{''.join(rows_main)}</tbody></table></div>
<div class="notice">产业催化与主营业务分部收入本次未自动取得，因此不会获得相应分数。门户“主力资金”只用于辅助预筛，不进入最终主线核心分。</div></section>
{''.join(tier_sections)}
<section><div class="section-head"><h2>主线替代工具</h2><span>ETF与个股不混合排名</span></div><div class="table-wrap"><table><thead><tr><th>对应主线</th><th>ETF</th><th>成交额</th><th>规模代理</th><th>评价边界</th></tr></thead><tbody>{''.join(etf_rows) or '<tr><td colspan=5>暂无名称匹配的ETF</td></tr>'}</tbody></table></div></section>
<footer>试运行版本。第一梯队产业分目前包含板块成员关系、市值和收入规模代理；正式版本需要继续补充主营业务分部收入、市场份额、订单与客户验证。所有结果均不构成收益保证或买卖建议。</footer>
</body></html>"""
    (结果目录 / "主线与第一梯队试运行看板.html").write_text(document, encoding="utf-8-sig")


def 生成说明(mainlines: pd.DataFrame, first_tier: pd.DataFrame, etfs: pd.DataFrame) -> None:
    lines = [
        "# 全市场试运行结果说明",
        "",
        f"- 生成时间：{datetime.now():%Y-%m-%d %H:%M:%S}",
        "- 本次结果只评价主线身份与第一梯队身份，不评价当前股价位置。",
        "- 产业催化和主营业务分部收入尚未自动接入，相应证据明确留空。",
        "",
        "## 主线结果",
        "",
        "| 板块 | 类型 | 阶段 | 身份分 | 延续置信度 | 20日超额 | 60日超额 | 20日广度 | 盈利扩散 |",
        "| --- | --- | --- | ---: | --- | ---: | ---: | ---: | ---: |",
    ]
    for _, row in mainlines.iterrows():
        lines.append(
            f"| {row['板块名称']} | {row['类型']} | {row['主线阶段']} | {row['主线身份分']:.1f} | "
            f"{row['延续置信度']} | {百分点(row['二十日实际超额'])} | {百分点(row['六十日实际超额'])} | "
            f"{百分比(row['二十日上涨广度'])} | {百分比(row['盈利扩散比例'])} |"
        )
    lines.extend(["", "## 每条主线最高分公司", ""])
    for _, board in mainlines.head(正式主线展示数).iterrows():
        group = first_tier[first_tier["板块代码"].eq(board["板块代码"])].head(3)
        names = "、".join(f"{row['股票名称']}（{row['第一梯队总分']:.1f}）" for _, row in group.iterrows())
        lines.append(f"- {board['板块名称']}：{names or '暂无足够数据'}")
    lines.extend(
        [
            "",
            "## 本次不能下的结论",
            "",
            "1. 不能把候选主线直接等同于未来会上涨的板块。",
            "2. 不能把第一梯队候选直接等同于当前可以买入。",
            "3. 未核验主营业务分部收入前，不能确认公司对主题的真实收入纯度。",
            "4. ETF费率、跟踪误差和折溢价本次尚未接入。",
        ]
    )
    (结果目录 / "试运行结果说明.md").write_text("\n".join(lines), encoding="utf-8-sig")


def main() -> None:
    print("1/6 获取沪深300与全市场板块...")
    benchmark = 获取腾讯日线("000300", 380)
    industries = 获取板块列表("行业")
    concepts = 获取板块列表("概念")
    all_boards = pd.concat([industries, concepts], ignore_index=True)
    pre_scored = 构造预选分数(all_boards, benchmark)
    preselected = (
        pre_scored.groupby("类型", group_keys=False)
        .head(每类预选板块数)
        .reset_index(drop=True)
    )

    print(f"2/6 补充{len(preselected)}个候选板块的历史结构...")
    board_histories = 并行获取板块日线(preselected)
    structured = 补充主线价格特征(preselected, board_histories, benchmark)
    finalists = (
        structured.groupby("类型", group_keys=False)
        .head(每类最终板块数)
        .reset_index(drop=True)
    )

    print(f"3/6 获取{len(finalists)}个候选板块成分股...")
    board_members: dict[str, pd.DataFrame] = {}
    for _, board in finalists.iterrows():
        try:
            board_members[board["板块代码"]] = 获取板块成分股(board["板块代码"])
        except Exception as exc:
            print(f"成分股缺失 {board['板块名称']}: {exc}")
            board_members[board["板块代码"]] = pd.DataFrame()
    stock_codes = sorted(
        {
            code
            for frame in board_members.values()
            if not frame.empty
            for code in frame["股票代码"].tolist()
        }
    )

    print(f"4/6 获取{len(stock_codes)}只可交易股票的日线和已披露财务摘要...")
    stock_histories, financials = 并行获取股票资料(stock_codes)
    board_names = dict(zip(finalists["板块代码"], finalists["板块名称"]))
    member_table = 构造成分股总表(
        board_members, board_names, stock_histories, financials, benchmark
    )

    print("5/6 计算主线身份、延续置信度和第一梯队...")
    mainline_all = 完成主线评分(finalists, member_table)
    mainlines = 选择去重主线(mainline_all, board_members, 正式主线展示数)
    first_tier = 评价第一梯队(member_table)
    etfs = 获取ETF替代工具(mainlines)

    print("6/6 生成中文静态看板和明细表...")
    mainline_all.to_csv(结果目录 / "全部候选主线明细.csv", index=False, encoding="utf-8-sig")
    mainlines.to_csv(结果目录 / "主线名单.csv", index=False, encoding="utf-8-sig")
    first_tier.to_csv(结果目录 / "第一梯队名单.csv", index=False, encoding="utf-8-sig")
    etfs.to_csv(结果目录 / "ETF替代工具.csv", index=False, encoding="utf-8-sig")
    生成看板(benchmark, mainlines, first_tier, etfs, {"行业": len(industries), "概念": len(concepts)})
    生成说明(mainlines, first_tier, etfs)
    print(f"完成。行情日期：{benchmark.index.max():%Y-%m-%d}")
    print(f"看板：{结果目录 / '主线与第一梯队试运行看板.html'}")


if __name__ == "__main__":
    main()
