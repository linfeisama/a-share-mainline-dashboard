from __future__ import annotations

import html
import importlib.util
import math
import os
import re
import sys
import time
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlencode

import akshare as ak
import numpy as np
import pandas as pd
import requests


根目录 = Path(__file__).resolve().parent
缓存目录 = 根目录 / "缓存"
结果目录 = 根目录 / "结果"
在线站点目录 = 根目录 / "在线站点"
缓存目录.mkdir(parents=True, exist_ok=True)
结果目录.mkdir(parents=True, exist_ok=True)
在线站点目录.mkdir(parents=True, exist_ok=True)

本地公共工具 = 根目录 / "公共工具.py"
旧脚本路径 = 本地公共工具 if 本地公共工具.exists() else 根目录.parent / "全市场试运行" / "运行一次.py"
模块规格 = importlib.util.spec_from_file_location("全市场旧工具", 旧脚本路径)
if 模块规格 is None or 模块规格.loader is None:
    raise RuntimeError(f"无法加载旧版公共工具：{旧脚本路径}")
旧工具 = importlib.util.module_from_spec(模块规格)
sys.modules[模块规格.name] = 旧工具
模块规格.loader.exec_module(旧工具)
旧工具.缓存目录 = 缓存目录
旧工具.结果目录 = 结果目录
旧工具.每板块研究股票数 = 10000
原获取腾讯日线 = 旧工具.获取腾讯日线

申万成分接口 = "https://www.swsresearch.com/institute-sw/api/index_publish/details/component_stocks/"
东方财富列表接口 = "https://push2.eastmoney.com/api/qt/clist/get"
腾讯批量行情接口 = "https://qt.gtimg.cn/q="
申万叶子成分映射文件 = 根目录 / "基础数据" / "申万叶子成分映射.csv"
请求头 = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36",
    "Referer": "https://www.swsresearch.com/",
}

一级方向展示数 = 6
每个一级二级候选数 = 2
细分主线展示数 = 8
每条主线个股展示数 = 8
概念历史候选数 = 24
概念确认展示数 = 12

warnings.filterwarnings("ignore", message="Unverified HTTPS request")

申万代理成分 = pd.DataFrame()
申万代理行情 = pd.DataFrame()


def 获取腾讯日线稳健(code: str, limit: int = 380) -> pd.DataFrame:
    try:
        return 原获取腾讯日线(code, limit)
    except Exception as exc:
        cache = 缓存目录 / f"股票_{code}.csv"
        if cache.exists():
            print(f"腾讯日线 {code} 更新失败，使用缓存：{exc}")
            return pd.read_csv(cache, parse_dates=["日期"]).set_index("日期").sort_index()
        try:
            end_date = datetime.now().strftime("%Y%m%d")
            start_date = (pd.Timestamp.now() - pd.Timedelta(days=max(limit * 2, 800))).strftime("%Y%m%d")
            frame = ak.stock_zh_a_hist(
                symbol=code, period="daily", start_date=start_date, end_date=end_date, adjust="qfq"
            )
            frame = frame.rename(
                columns={"日期": "日期", "开盘": "开盘", "收盘": "收盘", "最高": "最高", "最低": "最低", "成交量": "成交量"}
            )
            frame["日期"] = pd.to_datetime(frame["日期"])
            frame = frame.set_index("日期").sort_index().tail(limit)
            frame.to_csv(cache, encoding="utf-8-sig")
            return frame
        except Exception as fallback_exc:
            raise RuntimeError(f"{code} 两个股票日线源均失败：{exc}；{fallback_exc}") from fallback_exc


旧工具.获取腾讯日线 = 获取腾讯日线稳健


def 获取沪深300日线(limit: int = 420) -> pd.DataFrame:
    cache = 缓存目录 / "股票_000300.csv"
    try:
        frame = ak.stock_zh_index_daily_em(symbol="sh000300").tail(limit).copy()
        frame = frame.rename(
            columns={
                "date": "日期", "open": "开盘", "close": "收盘", "high": "最高",
                "low": "最低", "volume": "成交量", "amount": "成交额",
            }
        )
        frame["日期"] = pd.to_datetime(frame["日期"])
        frame = frame.set_index("日期").sort_index()
        frame.to_csv(cache, encoding="utf-8-sig")
        return frame
    except Exception as exc:
        if cache.exists():
            print(f"沪深300指数更新失败，使用缓存：{exc}")
            return pd.read_csv(cache, parse_dates=["日期"]).set_index("日期").sort_index()
        return 获取腾讯日线稳健("000300", limit)


def 数值(value: Any, default: float = np.nan) -> float:
    return 旧工具.数值(value, default)


def 百分比(value: Any, digits: int = 1) -> str:
    return 旧工具.百分比(value, digits)


def 百分点(value: Any, digits: int = 1) -> str:
    return 旧工具.百分点(value, digits)


def 收益(frame: pd.DataFrame, days: int, offset: int = 0) -> float:
    return 旧工具.收益(frame, days, offset)


def 年内收益(frame: pd.DataFrame) -> float:
    return 旧工具.年内收益(frame)


def 排名分(series: pd.Series) -> pd.Series:
    return series.rank(pct=True, method="average").fillna(0.0)


def 读取或下载层级(filename: str, loader: Callable[[], pd.DataFrame]) -> pd.DataFrame:
    cache = 缓存目录 / filename
    try:
        frame = loader()
        frame.to_csv(cache, index=False, encoding="utf-8-sig")
        return frame
    except Exception as exc:
        if cache.exists():
            print(f"层级接口暂不可用，读取缓存 {filename}：{exc}")
            return pd.read_csv(cache, dtype=str)
        raise


def 获取申万层级() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    first = 读取或下载层级("申万一级行业.csv", ak.sw_index_first_info)
    second = 读取或下载层级("申万二级行业.csv", ak.sw_index_second_info)
    third = 读取或下载层级("申万三级行业.csv", ak.sw_index_third_info)
    for frame in (first, second, third):
        frame["行业代码"] = frame["行业代码"].astype(str)
        frame["行业名称"] = frame["行业名称"].astype(str)
        frame["成份个数"] = pd.to_numeric(frame["成份个数"], errors="coerce").fillna(0).astype(int)
    second["上级行业"] = second["上级行业"].astype(str)
    third["上级行业"] = third["上级行业"].astype(str)

    二级到一级 = dict(zip(second["行业名称"], second["上级行业"]))
    有三级的二级 = set(third["上级行业"])
    records: list[dict[str, Any]] = []
    for _, row in third.iterrows():
        二级 = row["上级行业"]
        records.append(
            {
                "叶子代码": row["行业代码"].replace(".SI", ""),
                "叶子行业": row["行业名称"],
                "叶子层级": "三级",
                "二级行业": 二级,
                "一级行业": 二级到一级[二级],
                "成份个数": int(row["成份个数"]),
            }
        )
    for _, row in second[~second["行业名称"].isin(有三级的二级)].iterrows():
        records.append(
            {
                "叶子代码": row["行业代码"].replace(".SI", ""),
                "叶子行业": row["行业名称"],
                "叶子层级": "二级叶子",
                "二级行业": row["行业名称"],
                "一级行业": row["上级行业"],
                "成份个数": int(row["成份个数"]),
            }
        )
    leaves = pd.DataFrame(records).sort_values(["一级行业", "二级行业", "叶子行业"]).reset_index(drop=True)
    leaves.to_csv(缓存目录 / "申万叶子行业层级.csv", index=False, encoding="utf-8-sig")
    return first, second, third, leaves


def 获取腾讯批量行情(codes: list[str]) -> pd.DataFrame:
    records: list[dict[str, Any]] = []
    batches = [codes[index:index + 80] for index in range(0, len(codes), 80)]

    def 请求批次(batch: list[str]) -> list[dict[str, Any]]:
        symbols = [
            ("sh" if code.startswith(("5", "6", "9")) else "sz") + code
            for code in batch
        ]
        response = requests.get(
            腾讯批量行情接口 + ",".join(symbols),
            headers={"User-Agent": 请求头["User-Agent"], "Referer": "https://gu.qq.com/"},
            timeout=12,
        )
        response.raise_for_status()
        rows: list[dict[str, Any]] = []
        for line in response.content.decode("gbk", errors="ignore").splitlines():
            match = re.match(r'v_[a-z]+(\d{6})="(.*)";', line)
            if not match:
                continue
            fields = match.group(2).split("~")
            if len(fields) < 38:
                continue
            rows.append(
                {
                    "股票代码": match.group(1),
                    "现价": 数值(fields[3]),
                    "昨收": 数值(fields[4]),
                    "今开": 数值(fields[5]),
                    "最高": 数值(fields[33]),
                    "最低": 数值(fields[34]),
                    "成交量": 数值(fields[6]),
                    "成交额": 数值(fields[37]) * 10000,
                }
            )
        return rows

    with ThreadPoolExecutor(max_workers=12) as pool:
        futures = [pool.submit(请求批次, batch) for batch in batches]
        for future in as_completed(futures):
            try:
                records.extend(future.result())
            except Exception as exc:
                print(f"腾讯批量行情分组缺失：{exc}")
    return pd.DataFrame(records).drop_duplicates("股票代码") if records else pd.DataFrame()


def 准备申万当日代理行情() -> None:
    global 申万代理成分, 申万代理行情
    if not 申万叶子成分映射文件.exists():
        return
    申万代理成分 = pd.read_csv(
        申万叶子成分映射文件,
        dtype={"叶子代码": str, "股票代码": str},
    )
    codes = sorted(申万代理成分["股票代码"].dropna().astype(str).unique())
    申万代理行情 = 获取腾讯批量行情(codes)
    print(f"  云端代理行情覆盖 {len(申万代理行情)}/{len(codes)} 只成分股")


def 追加申万当日代理(code: str, cached: pd.DataFrame, market_date: pd.Timestamp) -> pd.DataFrame | None:
    if cached.empty or 申万代理成分.empty or 申万代理行情.empty:
        return None
    members = 申万代理成分[申万代理成分["叶子代码"] == code].copy()
    if members.empty:
        return None
    merged = members.merge(申万代理行情, on="股票代码", how="inner")
    merged = merged[(merged["现价"] > 0) & (merged["昨收"] > 0)]
    if len(merged) < max(2, math.ceil(len(members) * 0.60)):
        return None
    weights = pd.to_numeric(merged["最新权重"], errors="coerce")
    if weights.isna().all() or weights.fillna(0).sum() <= 0:
        weights = pd.Series(1.0, index=merged.index)
    weights = weights.fillna(0)

    def 加权涨幅(column: str) -> float:
        valid = merged[column].gt(0) & merged["昨收"].gt(0) & weights.gt(0)
        if not valid.any():
            return 0.0
        returns = merged.loc[valid, column].div(merged.loc[valid, "昨收"]).sub(1)
        return float(np.average(returns, weights=weights.loc[valid]))

    previous = cached.iloc[-1]
    row = {
        "收盘": float(previous["收盘"]) * (1 + 加权涨幅("现价")),
        "开盘": float(previous["收盘"]) * (1 + 加权涨幅("今开")),
        "最高": float(previous["收盘"]) * (1 + 加权涨幅("最高")),
        "最低": float(previous["收盘"]) * (1 + 加权涨幅("最低")),
        "成交量": 数值(previous.get("成交量")),
        "成交额": 数值(previous.get("成交额")),
    }
    result = pd.concat([cached, pd.DataFrame([row], index=[market_date])]).sort_index()
    result = result[~result.index.duplicated(keep="last")].tail(420)
    result.index.name = "日期"
    result.to_csv(缓存目录 / f"申万指数代理_{code}.csv", encoding="utf-8-sig")
    return result


def 获取申万指数日线(code: str, market_date: pd.Timestamp) -> pd.DataFrame:
    cache = 缓存目录 / f"申万指数_{code}.csv"
    proxy_cache = 缓存目录 / f"申万指数代理_{code}.csv"
    proxy: pd.DataFrame | None = None
    if proxy_cache.exists():
        try:
            proxy = pd.read_csv(proxy_cache, parse_dates=["日期"]).set_index("日期").sort_index()
            if not proxy.empty and proxy.index.max() >= market_date:
                return proxy
        except Exception:
            pass
    cached: pd.DataFrame | None = None
    if cache.exists():
        try:
            cached = pd.read_csv(cache, parse_dates=["日期"]).set_index("日期").sort_index()
            if not cached.empty and cached.index.max() >= market_date:
                return cached
        except Exception:
            cached = None
    baseline = cached
    if proxy is not None and not proxy.empty and (baseline is None or proxy.index.max() > baseline.index.max()):
        baseline = proxy
    if os.environ.get("GITHUB_ACTIONS", "").lower() == "true" and baseline is not None:
        synthetic = 追加申万当日代理(code, baseline, market_date)
        if synthetic is not None:
            return synthetic
    try:
        frame = ak.index_hist_sw(symbol=code, period="day").copy()
        frame["日期"] = pd.to_datetime(frame["日期"])
        for column in ("收盘", "开盘", "最高", "最低", "成交量", "成交额"):
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
        frame = frame.set_index("日期").sort_index().tail(420)
        frame.to_csv(cache, encoding="utf-8-sig")
        return frame
    except Exception as exc:
        if baseline is not None and not baseline.empty:
            synthetic = 追加申万当日代理(code, baseline, market_date)
            if synthetic is not None:
                return synthetic
            print(f"申万指数 {code} 更新失败，使用缓存：{exc}")
            return baseline
        raise


def 并行获取叶子日线(leaves: pd.DataFrame, market_date: pd.Timestamp) -> dict[str, pd.DataFrame]:
    result: dict[str, pd.DataFrame] = {}
    total = len(leaves)
    completed = 0
    with ThreadPoolExecutor(max_workers=12) as pool:
        futures = {
            pool.submit(获取申万指数日线, str(row["叶子代码"]), market_date): str(row["叶子代码"])
            for _, row in leaves.iterrows()
        }
        for future in as_completed(futures):
            code = futures[future]
            completed += 1
            try:
                result[code] = future.result()
            except Exception as exc:
                print(f"申万叶子行业日线缺失 {code}：{exc}")
            if completed % 50 == 0 or completed == total:
                print(f"  已完成 {completed}/{total}")
    return result


def 合成成分加权日线(
    code: str,
    components: pd.DataFrame,
    stock_histories: dict[str, pd.DataFrame],
) -> pd.DataFrame:
    weights = pd.to_numeric(components.get("最新权重"), errors="coerce")
    if weights.isna().all() or weights.sum() <= 0:
        weights = pd.Series(1.0, index=components.index)
    weight_map = dict(zip(components["证券代码"].astype(str), weights.fillna(0)))
    returns: dict[str, pd.Series] = {}
    volumes: dict[str, pd.Series] = {}
    for stock_code, weight in weight_map.items():
        frame = stock_histories.get(stock_code)
        if frame is None or frame.empty or weight <= 0:
            continue
        returns[stock_code] = frame["收盘"].pct_change()
        volumes[stock_code] = frame["成交量"]
    if not returns:
        raise RuntimeError(f"{code} 没有可用于合成的成分股日线")
    return_frame = pd.DataFrame(returns).sort_index()
    weight_series = pd.Series({stock_code: weight_map[stock_code] for stock_code in return_frame.columns})
    valid_weight = return_frame.notna().mul(weight_series, axis=1).sum(axis=1)
    weighted_return = return_frame.mul(weight_series, axis=1).sum(axis=1).div(valid_weight.replace(0, np.nan))
    close = (1 + weighted_return.fillna(0)).cumprod() * 1000
    volume = pd.DataFrame(volumes).reindex(close.index).sum(axis=1, min_count=1)
    synthetic = pd.DataFrame(
        {"收盘": close, "开盘": close, "最高": close, "最低": close, "成交量": volume, "成交额": volume},
        index=close.index,
    ).dropna(subset=["收盘"])
    synthetic.index.name = "日期"
    synthetic.to_csv(缓存目录 / f"申万指数代理_{code}.csv", encoding="utf-8-sig")
    return synthetic


def 补齐过期叶子日线(
    histories: dict[str, pd.DataFrame],
    market_date: pd.Timestamp,
) -> tuple[dict[str, pd.DataFrame], dict[str, str]]:
    source = {
        code: (
            "申万当前成分加权代理"
            if (缓存目录 / f"申万指数代理_{code}.csv").exists()
            and not frame.empty and frame.index.max() >= market_date
            else "申万官方指数"
        )
        for code, frame in histories.items()
    }
    stale = [
        code for code, frame in histories.items()
        if frame.empty or frame.index.max() < market_date - pd.Timedelta(days=10)
    ]
    if not stale:
        return histories, source
    print(f"  {len(stale)} 个叶子指数已停止更新，按当前成分权重合成代理日线...")
    components: dict[str, pd.DataFrame] = {}
    with ThreadPoolExecutor(max_workers=10) as pool:
        futures = {pool.submit(请求申万成分, code): code for code in stale}
        for future in as_completed(futures):
            code = futures[future]
            try:
                components[code] = future.result()
            except Exception as exc:
                print(f"代理成分缺失 {code}：{exc}")
    stock_codes = sorted(
        {
            stock_code
            for frame in components.values()
            for stock_code in frame["证券代码"].dropna().astype(str)
        }
    )
    stock_histories: dict[str, pd.DataFrame] = {}
    with ThreadPoolExecutor(max_workers=12) as pool:
        futures = {pool.submit(旧工具.获取腾讯日线, code, 420): code for code in stock_codes}
        for future in as_completed(futures):
            code = futures[future]
            try:
                stock_histories[code] = future.result()
            except Exception as exc:
                print(f"代理成分日线缺失 {code}：{exc}")
    for code in stale:
        try:
            histories[code] = 合成成分加权日线(code, components[code], stock_histories)
            source[code] = "申万当前成分加权代理"
        except Exception as exc:
            print(f"叶子行业代理合成失败 {code}：{exc}")
    return histories, source


def 计算叶子行业特征(
    leaves: pd.DataFrame,
    histories: dict[str, pd.DataFrame],
    benchmark: pd.DataFrame,
    data_sources: dict[str, str],
) -> pd.DataFrame:
    bench20 = benchmark["收盘"].pct_change(20)
    relative_series: dict[str, pd.Series] = {}
    for code, frame in histories.items():
        common = frame.index.intersection(benchmark.index)
        if len(common) >= 30:
            relative_series[code] = frame.loc[common, "收盘"].pct_change(20) - bench20.reindex(common)
    relative = pd.DataFrame(relative_series).sort_index()
    ranks = relative.rank(axis=1, ascending=False, pct=True, method="average")
    persistence = {
        code: float((ranks[code].dropna().tail(10) <= 0.30).mean())
        for code in relative.columns
    }

    records = []
    for _, leaf in leaves.iterrows():
        code = str(leaf["叶子代码"])
        frame = histories.get(code)
        if frame is None or frame.empty:
            continue
        common = frame.index.intersection(benchmark.index)
        if len(common) < 65:
            continue
        aligned = frame.loc[common]
        bench = benchmark.loc[common]
        close = aligned["收盘"].dropna()
        amount = aligned["成交额"].dropna()
        trend = (
            int(len(close) >= 60 and close.iloc[-1] > close.tail(20).mean() > close.tail(60).mean())
            + int(收益(aligned, 20) > 0)
            + int(收益(aligned, 60) > 0)
        ) / 3
        recent_amount = amount.tail(5).mean()
        base_amount = amount.tail(20).mean()
        records.append(
            {
                **leaf.to_dict(),
                "五日超额": (收益(aligned, 5) - 收益(bench, 5)) * 100,
                "二十日超额": (收益(aligned, 20) - 收益(bench, 20)) * 100,
                "六十日超额": (收益(aligned, 60) - 收益(bench, 60)) * 100,
                "年内超额": (年内收益(aligned) - 年内收益(bench)) * 100,
                "十日排名持续率": persistence.get(code, 0.0),
                "趋势完整度": trend,
                "量能比": recent_amount / base_amount if base_amount else np.nan,
                "行情日期": aligned.index.max().strftime("%Y-%m-%d"),
                "行情数据源": data_sources.get(code, "未知"),
            }
        )
    result = pd.DataFrame(records)
    result["样本置信系数"] = 0.88 + 0.12 * np.minimum(result["成份个数"] / 10, 1)
    result["叶子强度原分"] = (
        排名分(result["二十日超额"]) * 25
        + 排名分(result["六十日超额"]) * 20
        + result["十日排名持续率"].fillna(0) * 20
        + result["趋势完整度"].fillna(0) * 15
        + 排名分(result["量能比"]) * 10
        + 排名分(result["年内超额"]) * 10
    )
    result["叶子强度分"] = result["叶子强度原分"] * result["样本置信系数"]
    result["小样本提示"] = np.where(result["成份个数"] < 5, "成分少于5只，需人工复核", "")
    return result.sort_values("叶子强度分", ascending=False).reset_index(drop=True)


def 加权平均(group: pd.DataFrame, column: str) -> float:
    valid = group[column].notna()
    if not valid.any():
        return np.nan
    weights = np.sqrt(group.loc[valid, "成份个数"].clip(lower=1))
    return float(np.average(group.loc[valid, column], weights=weights))


def 汇总行业方向(leaves: pd.DataFrame, column: str, level_name: str) -> pd.DataFrame:
    records = []
    for name, group in leaves.groupby(column):
        weights = np.sqrt(group["成份个数"].clip(lower=1))
        weight_total = weights.sum()
        records.append(
            {
                level_name: name,
                "子叶子数量": len(group),
                "覆盖成分数": int(group["成份个数"].sum()),
                "二十日超额": 加权平均(group, "二十日超额"),
                "六十日超额": 加权平均(group, "六十日超额"),
                "年内超额": 加权平均(group, "年内超额"),
                "十日排名持续率": 加权平均(group, "十日排名持续率"),
                "趋势完整度": 加权平均(group, "趋势完整度"),
                "量能比": 加权平均(group, "量能比"),
                "二十日正超额广度": float(weights[group["二十日超额"] > 0].sum() / weight_total),
                "六十日正超额广度": float(weights[group["六十日超额"] > 0].sum() / weight_total),
            }
        )
    result = pd.DataFrame(records)
    result["方向得分"] = (
        排名分(result["二十日超额"]) * 20
        + 排名分(result["六十日超额"]) * 20
        + result["十日排名持续率"].fillna(0) * 20
        + result["二十日正超额广度"].fillna(0) * 15
        + result["六十日正超额广度"].fillna(0) * 10
        + result["趋势完整度"].fillna(0) * 10
        + 排名分(result["量能比"]) * 5
    )
    result["主线阶段"] = result.apply(判断阶段, axis=1)
    return result.sort_values("方向得分", ascending=False).reset_index(drop=True)


def 判断阶段(row: pd.Series) -> str:
    score = 数值(row.get("方向得分"), 0)
    breadth20 = 数值(row.get("二十日正超额广度"), 0)
    breadth60 = 数值(row.get("六十日正超额广度"), 0)
    persistence = 数值(row.get("十日排名持续率"), 0)
    if score >= 76 and breadth20 >= 0.65 and breadth60 >= 0.55:
        return "扩散"
    if score >= 70 and breadth20 >= 0.55 and persistence >= 0.50:
        return "确认"
    if score >= 62 and breadth20 >= 0.45:
        return "形成"
    if score >= 54:
        return "萌芽"
    return "观察"


def 选择细分主线(
    first_summary: pd.DataFrame,
    second_summary: pd.DataFrame,
    leaf_detail: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    first_selected = first_summary.head(一级方向展示数).copy()
    second_candidates = []
    for first_name in first_selected["一级行业"]:
        group = second_summary[second_summary["一级行业"].eq(first_name)].head(每个一级二级候选数)
        second_candidates.append(group)
    second_selected = pd.concat(second_candidates, ignore_index=True).sort_values("方向得分", ascending=False)

    leaf_candidates = []
    for _, second in second_selected.iterrows():
        group = leaf_detail[
            leaf_detail["一级行业"].eq(second["一级行业"])
            & leaf_detail["二级行业"].eq(second["二级行业"])
        ].head(2)
        leaf_candidates.append(group)
    selected = (
        pd.concat(leaf_candidates, ignore_index=True)
        .drop_duplicates("叶子代码")
        .sort_values("叶子强度分", ascending=False)
        .head(细分主线展示数)
        .reset_index(drop=True)
    )
    selected["板块代码"] = selected["叶子代码"]
    selected["板块名称"] = selected["叶子行业"]
    selected["类型"] = "申万叶子行业"
    selected["主线阶段"] = selected.apply(
        lambda row: "确认" if row["叶子强度分"] >= 72 and row["十日排名持续率"] >= 0.5
        else "形成" if row["叶子强度分"] >= 62
        else "萌芽" if row["叶子强度分"] >= 54
        else "观察",
        axis=1,
    )
    return first_selected, second_selected.reset_index(drop=True), selected


def 请求申万成分(code: str) -> pd.DataFrame:
    cache = 缓存目录 / f"申万成分_{code}.csv"
    if cache.exists() and time.time() - cache.stat().st_mtime < 7 * 24 * 3600:
        return pd.read_csv(cache, dtype={"证券代码": str})
    last_error: Exception | None = None
    try:
        frame = pd.DataFrame()
        for attempt in range(3):
            try:
                response = requests.get(
                    申万成分接口,
                    params={"swindexcode": code, "page": 1, "page_size": 10000},
                    headers=请求头,
                    timeout=20,
                    verify=False,
                )
                response.raise_for_status()
                payload = response.json()
                rows = payload.get("data") or []
                if isinstance(rows, dict):
                    rows = rows.get("results") or rows.get("list") or rows.get("data") or []
                frame = pd.DataFrame(rows)
                if not frame.empty:
                    rename = {
                        "stockcode": "证券代码", "stockname": "证券名称", "newweight": "最新权重",
                        "in_date": "计入日期", "indate": "计入日期",
                    }
                    frame = frame.rename(columns=rename)
                    break
            except Exception as exc:
                last_error = exc
                time.sleep(0.8 + attempt * 1.2)
        if frame.empty or "证券代码" not in frame.columns:
            frame = ak.index_component_sw(symbol=code)
        if "证券代码" not in frame.columns:
            raise RuntimeError(f"申万成分字段缺失：{list(frame.columns)}")
        frame["证券代码"] = frame["证券代码"].astype(str).str.extract(r"(\d{6})", expand=False)
        frame.to_csv(cache, index=False, encoding="utf-8-sig")
        return frame
    except Exception as exc:
        if cache.exists():
            print(f"申万成分 {code} 更新失败，使用缓存：{last_error or exc}")
            return pd.read_csv(cache, dtype={"证券代码": str})
        raise


def 获取沪深股票快照() -> pd.DataFrame:
    cache = 缓存目录 / "沪深股票快照.csv"
    fields = 旧工具.成分股字段
    records: list[dict[str, Any]] = []
    try:
        page = 1
        while page <= 70:
            payload = 旧工具.请求_json(
                东方财富列表接口,
                {
                    "pn": page, "pz": 100, "po": 1, "np": 1, "ut": 旧工具.接口令牌,
                    "fltt": 2, "invt": 2, "fid": "f6",
                    "fs": "m:1+t:2,m:1+t:23,m:0+t:6,m:0+t:80", "fields": fields,
                },
            )
            data = payload.get("data") or {}
            rows = data.get("diff") or []
            if isinstance(rows, dict):
                rows = list(rows.values())
            records.extend(rows)
            total = int(data.get("total") or len(records))
            if len(records) >= total or not rows:
                break
            page += 1
        parsed = []
        for row in records:
            code = str(row.get("f12") or "")
            name = str(row.get("f14") or "")
            if not code.startswith(("60", "00")) or "ST" in name.upper() or "退" in name:
                continue
            parsed.append(
                {
                    "股票代码": code, "股票名称": name, "现价": 数值(row.get("f2")),
                    "当日涨幅": 数值(row.get("f3")), "成交额": 数值(row.get("f6"), 0),
                    "换手率": 数值(row.get("f8")), "总市值": 数值(row.get("f20"), 0),
                    "流通市值": 数值(row.get("f21"), 0), "市盈率": 数值(row.get("f9")),
                    "市净率": 数值(row.get("f23")), "行业": str(row.get("f100") or ""),
                    "五日涨幅": 数值(row.get("f109")), "六十日涨幅": 数值(row.get("f24")),
                    "年内涨幅": 数值(row.get("f25")),
                }
            )
        frame = pd.DataFrame(parsed).drop_duplicates("股票代码")
        frame.to_csv(cache, index=False, encoding="utf-8-sig")
        return frame
    except Exception as exc:
        if cache.exists():
            print(f"沪深快照更新失败，使用缓存：{exc}")
            return pd.read_csv(cache, dtype={"股票代码": str})
        raise


def 最近完整报告期(reference_date: pd.Timestamp) -> str:
    year = reference_date.year
    month_day = reference_date.month * 100 + reference_date.day
    if month_day >= 1031:
        return f"{year}0930"
    if month_day >= 831:
        return f"{year}0630"
    if month_day >= 430:
        return f"{year}0331"
    return f"{year - 1}1231"


def 读取或下载批量表(filename: str, loader: Callable[[], pd.DataFrame]) -> pd.DataFrame:
    cache = 缓存目录 / filename
    if cache.exists() and time.time() - cache.stat().st_mtime < 6 * 3600:
        return pd.read_csv(cache, dtype={"股票代码": str})
    try:
        frame = loader()
        frame["股票代码"] = frame["股票代码"].astype(str).str.zfill(6)
        frame.to_csv(cache, index=False, encoding="utf-8-sig")
        return frame
    except Exception as exc:
        if cache.exists():
            print(f"批量财务表 {filename} 更新失败，使用缓存：{exc}")
            return pd.read_csv(cache, dtype={"股票代码": str})
        raise


def 获取全市场财务快照(reference_date: pd.Timestamp) -> tuple[pd.DataFrame, str]:
    report_date = 最近完整报告期(reference_date)
    performance = 读取或下载批量表(
        f"全市场业绩_{report_date}.csv", lambda: ak.stock_yjbb_em(date=report_date)
    )
    balance = 读取或下载批量表(
        f"全市场资产负债_{report_date}.csv", lambda: ak.stock_zcfz_em(date=report_date)
    )
    cashflow = 读取或下载批量表(
        f"全市场现金流_{report_date}.csv", lambda: ak.stock_xjll_em(date=report_date)
    )
    base = performance.rename(
        columns={
            "营业总收入-营业总收入": "营业收入",
            "营业总收入-同比增长": "营收增长",
            "净利润-净利润": "归母净利润",
            "净利润-同比增长": "利润增长",
            "净资产收益率": "净资产收益率",
            "销售毛利率": "毛利率",
            "最新公告日期": "公告日期",
        }
    )
    base_columns = [
        "股票代码", "营业收入", "营收增长", "归母净利润", "利润增长",
        "净资产收益率", "毛利率", "公告日期",
    ]
    result = base[base_columns].drop_duplicates("股票代码")
    result = result.merge(
        balance[["股票代码", "资产负债率"]].drop_duplicates("股票代码"),
        on="股票代码", how="left",
    )
    result = result.merge(
        cashflow[["股票代码", "经营性现金流-现金流量净额"]].drop_duplicates("股票代码"),
        on="股票代码", how="left",
    )
    result["经营现金利润比"] = (
        pd.to_numeric(result["经营性现金流-现金流量净额"], errors="coerce")
        / pd.to_numeric(result["归母净利润"], errors="coerce").replace(0, np.nan)
    )
    return result, report_date


def 构造成分股批量表(
    leaf_members: dict[str, pd.DataFrame],
    board_names: dict[str, str],
    financials: pd.DataFrame,
    report_date: str,
    benchmark: pd.DataFrame,
) -> pd.DataFrame:
    benchmark_5 = 收益(benchmark, 5) * 100
    benchmark_60 = 收益(benchmark, 60) * 100
    benchmark_ytd = 年内收益(benchmark) * 100
    records = []
    financial_index = financials.set_index("股票代码", drop=False)
    for board_code, members in leaf_members.items():
        for _, member in members.iterrows():
            stock_code = str(member["股票代码"])
            finance = financial_index.loc[stock_code] if stock_code in financial_index.index else pd.Series(dtype=object)
            if isinstance(finance, pd.DataFrame):
                finance = finance.iloc[0]
            profit = 数值(finance.get("归母净利润"))
            long_term = np.nanmean(
                [
                    数值(member.get("六十日涨幅")) - benchmark_60,
                    数值(member.get("年内涨幅")) - benchmark_ytd,
                ]
            )
            records.append(
                {
                    **member.to_dict(),
                    "板块代码": board_code, "板块名称": board_names[board_code],
                    "二十日股票超额": 数值(member.get("五日涨幅")) - benchmark_5,
                    "六十日股票超额": 数值(member.get("六十日涨幅")) - benchmark_60,
                    "长期认可原值": long_term,
                    "财报期": f"{report_date[:4]}-{report_date[4:6]}-{report_date[6:]}",
                    "公告日期": str(finance.get("公告日期") or "")[:10],
                    "营业收入": 数值(finance.get("营业收入")),
                    "归母净利润": profit,
                    "营收增长": 数值(finance.get("营收增长")),
                    "利润增长": 数值(finance.get("利润增长")),
                    "扣非利润增长": np.nan,
                    "净资产收益率": 数值(finance.get("净资产收益率")),
                    "投入资本回报率": np.nan,
                    "毛利率": 数值(finance.get("毛利率")),
                    "资产负债率": 数值(finance.get("资产负债率")),
                    "经营现金利润比": 数值(finance.get("经营现金利润比")),
                    "不良率": np.nan, "拨备覆盖": np.nan, "资本充足率": np.nan,
                    "近四期盈利为正比例": 1.0 if not math.isnan(profit) and profit > 0 else 0.0,
                }
            )
    return pd.DataFrame(records)


def 获取细分行业成分(
    selected: pd.DataFrame,
    snapshot: pd.DataFrame,
) -> dict[str, pd.DataFrame]:
    result: dict[str, pd.DataFrame] = {}
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(请求申万成分, str(row["叶子代码"])): str(row["叶子代码"]) for _, row in selected.iterrows()}
        for future in as_completed(futures):
            code = futures[future]
            try:
                components = future.result()
                merged = components[["证券代码"]].rename(columns={"证券代码": "股票代码"}).merge(
                    snapshot, on="股票代码", how="inner"
                )
                result[code] = merged.drop_duplicates("股票代码")
            except Exception as exc:
                print(f"细分行业成分缺失 {code}：{exc}")
                result[code] = pd.DataFrame()
    return result


def 获取概念确认(
    benchmark: pd.DataFrame,
    selected: pd.DataFrame,
    leaf_members: dict[str, pd.DataFrame],
) -> pd.DataFrame:
    concepts = 旧工具.获取板块列表("概念")
    pre_scored = 旧工具.构造预选分数(concepts, benchmark)
    candidates = pre_scored.head(概念历史候选数).reset_index(drop=True)
    histories = 旧工具.并行获取板块日线(candidates)
    structured = 旧工具.补充主线价格特征(candidates, histories, benchmark)
    structured["概念得分"] = (
        排名分(structured["二十日实际超额"]) * 30
        + 排名分(structured["六十日实际超额"]) * 25
        + structured["十日排名持续率"].fillna(0) * 25
        + 排名分(structured["板块量能比"]) * 10
        + 排名分(structured["当日上涨广度"]) * 10
    )
    rows = []
    selected_sets = {
        str(row["叶子行业"]): set(leaf_members.get(str(row["叶子代码"]), pd.DataFrame()).get("股票代码", []))
        for _, row in selected.iterrows()
    }
    for _, concept in structured.sort_values("概念得分", ascending=False).head(概念确认展示数).iterrows():
        try:
            members = 旧工具.获取板块成分股(concept["板块代码"], limit=10000)
            concept_set = set(members.get("股票代码", []))
        except Exception:
            concept_set = set()
        best_name = "未与入选细分主线形成明显交叉"
        best_overlap = 0.0
        best_count = 0
        for leaf_name, leaf_set in selected_sets.items():
            denominator = min(len(concept_set), len(leaf_set))
            overlap_count = len(concept_set & leaf_set)
            overlap = overlap_count / denominator if denominator else 0.0
            if overlap > best_overlap:
                best_name, best_overlap, best_count = leaf_name, overlap, overlap_count
        confirm = "强确认" if best_overlap >= 0.35 and best_count >= 3 else "弱确认" if best_overlap >= 0.15 and best_count >= 2 else "独立观察"
        rows.append(
            {
                "概念代码": concept["板块代码"], "概念名称": concept["板块名称"],
                "概念得分": concept["概念得分"], "二十日超额": concept["二十日实际超额"],
                "六十日超额": concept["六十日实际超额"], "十日排名持续率": concept["十日排名持续率"],
                "最相关细分主线": best_name, "成分交叉比例": best_overlap,
                "交叉股票数": best_count, "确认状态": confirm,
            }
        )
    return pd.DataFrame(rows)


def 证据文本(row: pd.Series) -> str:
    return (
        f"20日超额 {百分点(row['二十日超额'])}；60日超额 {百分点(row['六十日超额'])}；"
        f"20日扩散 {百分比(row['二十日正超额广度'])}；持续率 {百分比(row['十日排名持续率'])}"
    )


def TradingView链接(code: str) -> str:
    exchange = "SSE" if str(code).startswith(("5", "6")) else "SZSE"
    return f"https://cn.tradingview.com/chart/?symbol={exchange}%3A{code}"


def 新浪行情链接(code: str) -> str:
    market = "sh" if str(code).startswith(("5", "6")) else "sz"
    return f"https://quotes.sina.cn/hs/company/quotes/view/{market}{code}"


def 申万指数链接(code: str, name: str) -> str:
    query = urlencode({"code": str(code).replace(".SI", ""), "name": str(name)})
    return (
        "https://www.swsresearch.com/institute_sw/allIndex/"
        f"releasedIndex/releasedetail?{query}"
    )


def 行业名称链接(name: Any, code: Any, strong: bool = True) -> str:
    escaped_name = html.escape(str(name))
    label = f"<strong>{escaped_name}</strong>" if strong else escaped_name
    if pd.isna(code) or not str(code).strip():
        return label
    url = html.escape(申万指数链接(str(code), str(name)), quote=True)
    return (
        f"<a class='industry-link' href='{url}' target='_blank' rel='noopener noreferrer' "
        f"title='查看{escaped_name}申万指数K线'>{label}</a>"
    )


def 行业表格行(frame: pd.DataFrame, name_column: str, code_column: str) -> str:
    rows = []
    for _, row in frame.iterrows():
        rows.append(
            f"<tr><td>{行业名称链接(row[name_column], row[code_column])}</td>"
            f"<td><span class='phase p-{row['主线阶段']}'>{row['主线阶段']}</span></td>"
            f"<td>{row['方向得分']:.1f}</td><td>{百分点(row['二十日超额'])}</td>"
            f"<td>{百分点(row['六十日超额'])}</td><td>{百分比(row['二十日正超额广度'])}</td>"
            f"<td>{百分比(row['六十日正超额广度'])}</td><td>{百分比(row['十日排名持续率'])}</td>"
            f"<td>{int(row['子叶子数量'])}</td><td>{int(row['覆盖成分数'])}</td></tr>"
        )
    return "".join(rows)


def 生成看板(
    benchmark: pd.DataFrame,
    first_all: pd.DataFrame,
    second_all: pd.DataFrame,
    leaf_all: pd.DataFrame,
    first_selected: pd.DataFrame,
    second_selected: pd.DataFrame,
    selected: pd.DataFrame,
    concept_confirm: pd.DataFrame,
    first_tier: pd.DataFrame,
    etfs: pd.DataFrame,
) -> None:
    state, state_reason = 旧工具.市场状态(benchmark)
    generated = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    market_date = benchmark.index.max().strftime("%Y-%m-%d")

    一级代码映射 = dict(zip(first_all["一级行业"], first_all["一级代码"]))
    二级代码映射 = dict(zip(second_all["二级行业"], second_all["二级代码"]))
    细分代码映射 = dict(zip(selected["叶子行业"], selected["叶子代码"]))
    first_rows = 行业表格行(first_all, "一级行业", "一级代码")
    second_rows = 行业表格行(second_selected, "二级行业", "二级代码")
    leaf_rows = []
    for _, row in selected.iterrows():
        parent_links = (
            f"{行业名称链接(row['一级行业'], 一级代码映射.get(row['一级行业']), False)} / "
            f"{行业名称链接(row['二级行业'], 二级代码映射.get(row['二级行业']), False)}"
        )
        leaf_rows.append(
            f"<tr><td>{行业名称链接(row['叶子行业'], row['叶子代码'])}<small>{parent_links}</small></td>"
            f"<td><span class='phase p-{row['主线阶段']}'>{row['主线阶段']}</span></td><td>{row['叶子强度分']:.1f}</td>"
            f"<td>{百分点(row['二十日超额'])}</td><td>{百分点(row['六十日超额'])}</td>"
            f"<td>{百分比(row['十日排名持续率'])}</td><td>{百分比(row['趋势完整度'])}</td>"
            f"<td>{row['量能比']:.2f}</td><td>{int(row['成份个数'])}</td><td>{html.escape(row['行情数据源'])}</td>"
            f"<td>{html.escape(row['小样本提示']) or '-'}</td></tr>"
        )

    concept_rows = []
    for _, row in concept_confirm.iterrows():
        related_name = str(row["最相关细分主线"])
        related_code = 细分代码映射.get(related_name)
        related_html = (
            行业名称链接(related_name, related_code, False)
            if related_code
            else html.escape(related_name)
        )
        concept_rows.append(
            f"<tr><td><strong>{html.escape(row['概念名称'])}</strong></td><td>{row['概念得分']:.1f}</td>"
            f"<td>{百分点(row['二十日超额'])}</td><td>{百分点(row['六十日超额'])}</td>"
            f"<td>{百分比(row['十日排名持续率'])}</td><td>{html.escape(row['确认状态'])}</td>"
            f"<td>{related_html}</td><td>{百分比(row['成分交叉比例'])} / {int(row['交叉股票数'])}只</td></tr>"
        )

    stock_sections = []
    for _, line in selected.iterrows():
        group = first_tier[first_tier["板块代码"].eq(line["叶子代码"])].head(每条主线个股展示数)
        stock_rows = []
        for _, stock in group.iterrows():
            chart_url = TradingView链接(str(stock["股票代码"]))
            mobile_url = 新浪行情链接(str(stock["股票代码"]))
            stock_rows.append(
                f"<tr><td><a class='stock-link' href='{chart_url}' data-desktop-url='{chart_url}' data-mobile-url='{mobile_url}' "
                "target='_blank' rel='noopener noreferrer' title='在 TradingView 打开'>"
                f"<strong>{html.escape(stock['股票名称'])}</strong><small>{stock['股票代码']} · {html.escape(stock['行业'])} · "
                "<span class='stock-link-source'>TradingView图表</span></small></a></td>"
                f"<td>{html.escape(stock['评价状态'])}</td><td>{stock['第一梯队总分']:.1f}</td>"
                f"<td>{stock['产业地位代理分']:.1f}</td><td>{stock['基本面质量分']:.1f}</td>"
                f"<td>{stock['增长持续性分']:.1f}</td><td>{stock['中长期认可分']:.1f}</td>"
                f"<td>{html.escape(stock['角色'])}</td><td>{html.escape(stock['数据置信等级'])}</td>"
                f"<td>{html.escape(stock['风险说明'])}</td></tr>"
            )
        parent_links = (
            f"{行业名称链接(line['一级行业'], 一级代码映射.get(line['一级行业']), False)} / "
            f"{行业名称链接(line['二级行业'], 二级代码映射.get(line['二级行业']), False)}"
        )
        stock_sections.append(
            f"<section><div class='section-head'><h2>{行业名称链接(line['叶子行业'], line['叶子代码'])} 第一梯队</h2>"
            f"<span>{parent_links} · 仅评价公司身份</span></div>"
            "<div class='table-wrap' data-collapse-limit='3'><table><thead><tr><th>公司</th><th>状态</th><th>总分</th><th>产业</th><th>质量</th>"
            "<th>增长</th><th>长期认可</th><th>角色</th><th>置信</th><th>风险</th></tr></thead>"
            f"<tbody>{''.join(stock_rows) or '<tr><td colspan=10>暂无符合交易范围且数据足够的公司</td></tr>'}</tbody></table></div></section>"
        )

    etf_rows = []
    if not etfs.empty:
        for _, row in etfs.iterrows():
            etf_code = str(row["ETF代码"])
            chart_url = TradingView链接(etf_code)
            mobile_url = 新浪行情链接(etf_code)
            etf_rows.append(
                f"<tr><td>{行业名称链接(row['主线'], 细分代码映射.get(row['主线']), False)}</td>"
                f"<td><a class='stock-link etf-link' href='{chart_url}' "
                f"data-desktop-url='{chart_url}' data-mobile-url='{mobile_url}' target='_blank' rel='noopener noreferrer' "
                f"title='在 TradingView 打开'><strong>{html.escape(row['ETF名称'])}</strong>"
                f"<small>{etf_code} · <span class='stock-link-source'>TradingView图表</span></small></a></td>"
                f"<td>{旧工具.金额(row['成交额'])}</td><td>{旧工具.金额(row['规模代理'])}</td><td>{html.escape(row['评价说明'])}</td></tr>"
            )

    指标说明 = """
<div id="metric-help" class="help-popover" role="tooltip">
  <div class="help-heading">指标口径说明</div>
  <div class="help-grid">
    <div class="help-group">
      <h3>行业与概念</h3>
      <dl>
        <div><dt>阶段</dt><dd>按方向分、扩散和持续率划分为扩散、确认、形成、萌芽或观察。</dd></div>
        <div><dt>方向分</dt><dd>同层相对综合分：20日超额20%、60日超额20%、持续率20%、20日扩散15%、60日扩散10%、趋势10%、量能5%。</dd></div>
        <div><dt>20/60日超额</dt><dd>行业同期收益减去沪深300同期收益。</dd></div>
        <div><dt>20/60日扩散</dt><dd>下属叶子行业中取得正超额收益的加权占比，权重为成分数量的平方根。</dd></div>
        <div><dt>持续率</dt><dd>近10个交易日进入同层20日超额排名前30%的天数比例。</dd></div>
        <div><dt>趋势完整度</dt><dd>收盘高于20日均线且20日均线高于60日均线、20日收益为正、60日收益为正，各占三分之一。</dd></div>
        <div><dt>量能比</dt><dd>近5日平均成交额除以近20日平均成交额。</dd></div>
        <div><dt>强度分</dt><dd>叶子行业的20/60日超额、持续率、趋势、量能和年内超额综合分，并对小样本降权。</dd></div>
        <div><dt>概念分</dt><dd>概念的20/60日超额、持续率、量能和当日上涨广度综合分。</dd></div>
        <div><dt>交叉</dt><dd>概念与相关细分主线的成分重合比例，以及实际重合股票数量。</dd></div>
      </dl>
    </div>
    <div class="help-group">
      <h3>个股</h3>
      <dl>
        <div><dt>总分</dt><dd>产业30分、质量30分、增长20分、长期认可15分、可投资性5分，减去风险扣分。</dd></div>
        <div><dt>产业</dt><dd>同一细分行业内的总市值和营业收入相对位置，作为产业地位代理。</dd></div>
        <div><dt>质量</dt><dd>非金融股综合ROE、ROIC、现金质量、毛利率和负债；金融股综合ROE、利润增长、不良率和拨备覆盖。</dd></div>
        <div><dt>增长</dt><dd>同业营收增长、利润增长相对位置，并结合近四期盈利为正比例。</dd></div>
        <div><dt>长期认可</dt><dd>相对沪深300的6个月和12个月超额收益，经年化波动率调整后的同业相对位置。</dd></div>
        <div><dt>角色</dt><dd>依据产业、业绩和长期市场认可，标记产业核心、业绩核心或市场核心。</dd></div>
        <div><dt>置信</dt><dd>核心财务和价格字段覆盖率：A不低于85%，B不低于65%，其余为C。</dd></div>
        <div><dt>风险</dt><dd>利润为负、现金利润背离、高负债或营收利润快速下降等量化风险提示。</dd></div>
      </dl>
    </div>
  </div>
  <p class="help-footnote">所有分数用于同层比较，不评价当前价格位置，也不构成买卖建议。</p>
</div>"""

    document = f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>申万分层主线与第一梯队看板</title>
<script>try{{const savedTheme=localStorage.getItem('dashboard-theme');if(savedTheme==='light'||savedTheme==='dark')document.documentElement.dataset.theme=savedTheme;}}catch(_error){{}}</script>
<style>
:root{{--ink:#e9edf0;--strong:#ffffff;--muted:#94a0a8;--line:#343b3f;--paper:#111416;--header:#15191b;--panel:#181c1f;--panel2:#202529;--section-alt:#14181a;--row-line:#2b3236;--row-hover:#20272a;--button:#22282b;--button-border:#4b565c;--notice:#242117;--notice-ink:#d8c596;--footer:#0e1112;--green:#55d68b;--amber:#f0bd5b;--red:#ff7474;--cyan:#63c9da;--tab-active:#17353b;color-scheme:dark}}
:root[data-theme="light"]{{--ink:#263238;--strong:#101719;--muted:#617078;--line:#d3dce0;--paper:#f4f6f7;--header:#ffffff;--panel:#ffffff;--panel2:#eaf0f2;--section-alt:#f9fbfb;--row-line:#e1e7ea;--row-hover:#edf7f8;--button:#f8fafb;--button-border:#b8c4ca;--notice:#fff8e7;--notice-ink:#66501c;--footer:#e9eef0;--green:#137a42;--amber:#9a6500;--red:#c83c3c;--cyan:#087f91;--tab-active:#dff3f5;color-scheme:light}}
*{{box-sizing:border-box}}html,body{{max-width:100%;overflow-x:hidden}}body{{margin:0;color:var(--ink);background:var(--paper);font-family:"Microsoft YaHei","Segoe UI",sans-serif;font-size:14px;letter-spacing:0}}button{{font-family:inherit}}header{{padding:26px 4vw 18px;border-bottom:1px solid var(--line);background:var(--header)}}.header-row{{display:flex;align-items:flex-start;justify-content:space-between;gap:24px}}.header-copy{{min-width:0}}.title-row{{display:flex;align-items:center;gap:10px;position:relative}}h1{{font-size:26px;line-height:1.35;margin:0;color:var(--strong)}}h2{{font-size:18px;margin:0;color:var(--strong)}}p{{margin:5px 0;color:var(--muted);line-height:1.6;overflow-wrap:anywhere}}
.header-actions{{flex:0 0 auto;display:flex;align-items:center;gap:10px;flex-wrap:wrap;justify-content:flex-end}}.icon-button{{display:inline-flex;align-items:center;justify-content:center;width:30px;height:30px;padding:0;border:1px solid var(--button-border);border-radius:50%;background:var(--button);color:var(--ink);font-size:17px;font-weight:800;cursor:pointer}}.icon-button:hover,.icon-button:focus-visible{{border-color:var(--cyan);color:var(--cyan);outline:none}}.help-wrap{{position:relative;flex:0 0 auto}}.help-popover{{position:fixed;left:4vw;top:74px;z-index:30;width:min(680px,92vw);max-height:min(70vh,640px);overflow:auto;padding:18px;border:1px solid var(--line);border-radius:6px;background:var(--panel);box-shadow:0 14px 40px rgba(0,0,0,.28);visibility:hidden;opacity:0;transform:translateY(-5px);pointer-events:none;transition:opacity .14s ease,transform .14s ease,visibility .14s}}.help-wrap:hover .help-popover,.help-wrap:focus-within .help-popover,.help-wrap.is-open .help-popover{{visibility:visible;opacity:1;transform:translateY(0);pointer-events:auto}}.help-heading{{font-size:17px;font-weight:800;color:var(--strong);margin-bottom:12px}}.help-grid{{display:grid;grid-template-columns:1fr 1fr;gap:20px}}.help-group h3{{margin:0 0 8px;font-size:15px;color:var(--cyan)}}.help-group dl{{margin:0}}.help-group dl>div{{display:grid;grid-template-columns:82px 1fr;gap:8px;padding:7px 0;border-top:1px solid var(--row-line)}}.help-group dt{{font-weight:700;color:var(--strong)}}.help-group dd{{margin:0;color:var(--muted);line-height:1.55}}.help-footnote{{margin:12px 0 0;padding-top:10px;border-top:1px solid var(--line);font-size:13px}}
.theme-switch{{display:inline-flex;height:38px;padding:2px;border:1px solid var(--button-border);border-radius:6px;background:var(--button)}}.theme-option{{display:inline-flex;align-items:center;gap:5px;padding:0 10px;border:0;border-radius:4px;background:transparent;color:var(--muted);font:inherit;cursor:pointer}}.theme-option[aria-pressed="true"]{{background:var(--tab-active);color:var(--strong);font-weight:700}}.theme-option:focus-visible{{outline:2px solid var(--cyan);outline-offset:1px}}.theme-icon{{font-size:16px;line-height:1}}.refresh-button{{flex:0 0 auto;display:inline-flex;align-items:center;gap:8px;height:38px;padding:0 14px;border:1px solid var(--button-border);border-radius:6px;background:var(--button);color:var(--ink);font:inherit;font-weight:700;cursor:pointer}}.refresh-button:hover{{border-color:var(--cyan);color:var(--cyan)}}.refresh-button:disabled{{cursor:wait;opacity:.65}}.refresh-icon{{font-size:20px;line-height:1}}.refresh-loading{{flex:0 0 auto;width:22px;height:22px;object-fit:contain}}.refresh-loading[hidden]{{display:none}}.refresh-status{{min-height:20px;margin-top:8px;color:var(--muted);font-size:13px}}.refresh-status.error{{color:var(--red)}}.refresh-status.success{{color:var(--green)}}
.summary{{padding:16px 4vw;background:var(--panel);border-bottom:1px solid var(--line)}}.metric{{min-width:0;display:grid;grid-template-columns:auto auto minmax(0,1fr);align-items:baseline;gap:10px 16px}}.metric-label{{font-weight:700;color:var(--muted)}}.metric b{{font-size:22px;color:var(--strong)}}.metric small{{margin:0}}
.dashboard-tabs{{position:sticky;top:0;z-index:20;display:flex;gap:4px;padding:10px 4vw;border-bottom:1px solid var(--line);background:var(--header);overflow-x:auto}}.tab-button{{flex:0 0 auto;min-width:92px;height:38px;padding:0 16px;border:1px solid transparent;border-radius:6px;background:transparent;color:var(--muted);font:inherit;font-weight:700;cursor:pointer}}.tab-button:hover{{color:var(--strong);background:var(--button)}}.tab-button[aria-selected="true"]{{color:var(--strong);border-color:var(--cyan);background:var(--tab-active)}}.tab-button:focus-visible{{outline:2px solid var(--cyan);outline-offset:1px}}.tab-panel[hidden]{{display:none}}main{{min-height:55vh}}
.tab-panel>section{{padding:24px 4vw;border-bottom:1px solid var(--line)}}.tab-panel>section:nth-child(even){{background:var(--section-alt)}}.section-head{{display:flex;justify-content:space-between;align-items:end;gap:12px;margin-bottom:12px}}.section-head span{{color:var(--muted)}}
.table-wrap{{width:100%;overflow:auto;border:1px solid var(--line);border-radius:6px;background:var(--panel)}}table{{width:100%;border-collapse:collapse;min-width:960px}}th,td{{padding:10px 11px;border-bottom:1px solid var(--row-line);text-align:left;vertical-align:top}}th{{background:var(--panel2);font-weight:600;white-space:nowrap;color:var(--ink)}}tbody tr:hover{{background:var(--row-hover)}}tbody tr.is-collapsed{{display:none}}tr:last-child td{{border-bottom:0}}small{{display:block;color:var(--muted);margin-top:4px}}.table-toggle-row{{display:flex;justify-content:center;margin-top:10px}}.table-toggle{{display:inline-flex;align-items:center;justify-content:center;gap:7px;min-height:34px;padding:0 12px;border:1px solid var(--button-border);border-radius:6px;background:var(--button);color:var(--ink);font:inherit;cursor:pointer}}.table-toggle:hover{{border-color:var(--cyan);color:var(--cyan)}}.table-toggle-icon{{width:16px;font-size:18px;line-height:1;text-align:center}}
.phase{{font-weight:700}}.p-扩散,.p-确认{{color:var(--green)}}.p-形成,.p-萌芽{{color:var(--amber)}}.p-观察{{color:var(--muted)}}.notice{{border-left:3px solid var(--amber);padding:10px 14px;background:var(--notice);color:var(--notice-ink);margin-top:14px}}.industry-link,.stock-link{{color:var(--cyan);text-decoration:none}}.industry-link:hover,.stock-link:hover strong{{text-decoration:underline}}.stock-link{{display:block}}.stock-link small{{color:var(--muted)}}footer{{padding:20px 4vw 35px;color:var(--muted);background:var(--footer)}}
@media(max-width:760px){{header,.tab-panel>section{{padding-left:18px;padding-right:18px}}.header-row{{gap:16px;flex-direction:column}}.header-actions{{justify-content:flex-start}}h1{{font-size:22px}}small{{overflow-wrap:anywhere}}.help-popover{{left:18px;right:18px;top:72px;width:auto;max-height:calc(100dvh - 92px)}}.help-grid{{grid-template-columns:1fr}}.summary{{padding:14px 18px}}.metric{{display:flex;align-items:baseline;flex-wrap:wrap;gap:6px 12px}}.metric small{{flex-basis:100%}}.dashboard-tabs{{padding-left:18px;padding-right:18px}}.tab-button{{min-width:80px;padding:0 13px}}.section-head{{align-items:start;flex-direction:column}}.section-head span{{line-height:1.5}}}}
@media(max-width:430px){{.theme-option{{padding:0 9px}}.refresh-button{{padding:0 11px}}.help-group dl>div{{grid-template-columns:74px 1fr}}}}
</style></head><body>
<header><div class="header-row"><div class="header-copy"><div class="title-row"><h1>申万分层主线与第一梯队看板</h1><div class="help-wrap"><button id="help-button" class="icon-button" type="button" aria-label="查看指标口径说明" aria-expanded="false" aria-controls="metric-help" title="指标口径说明">?</button>{指标说明}</div></div><p>行情日期 {market_date} · 生成时间 {generated} · 不评价当前位置和买卖时点</p></div><div class="header-actions"><div class="theme-switch" role="group" aria-label="界面主题"><button class="theme-option" type="button" data-theme-choice="light" aria-pressed="false" title="切换到明亮模式"><span class="theme-icon" aria-hidden="true">☀</span><span class="theme-label">明亮</span></button><button class="theme-option" type="button" data-theme-choice="dark" aria-pressed="true" title="切换到深色模式"><span class="theme-icon" aria-hidden="true">☾</span><span class="theme-label">深色</span></button></div><button id="refresh-button" class="refresh-button" type="button" onclick="refreshMarket()" title="重新获取行情并生成看板"><span class="refresh-icon" aria-hidden="true">↻</span><span>更新行情</span></button><img id="refresh-loading" class="refresh-loading" src="加载中.gif" alt="加载中" hidden></div></div><div id="refresh-status" class="refresh-status" role="status" aria-live="polite"></div></header>
<div class="summary"><div class="metric"><span class="metric-label">市场状态</span><b>{state}</b><small>{state_reason}</small></div></div>
<nav class="dashboard-tabs" role="tablist" aria-label="看板内容">
  <button id="tab-industry" class="tab-button" type="button" role="tab" aria-selected="true" aria-controls="panel-industry" tabindex="0">行业</button>
  <button id="tab-concept" class="tab-button" type="button" role="tab" aria-selected="false" aria-controls="panel-concept" tabindex="-1">概念</button>
  <button id="tab-stock" class="tab-button" type="button" role="tab" aria-selected="false" aria-controls="panel-stock" tabindex="-1">个股</button>
  <button id="tab-etf" class="tab-button" type="button" role="tab" aria-selected="false" aria-controls="panel-etf" tabindex="-1">ETF</button>
</nav>
<main>
<div id="panel-industry" class="tab-panel" role="tabpanel" aria-labelledby="tab-industry">
  <section><div class="section-head"><h2>一级资金方向</h2><span>共 {len(first_all)} 个一级行业，按方向得分排序</span></div><div class="table-wrap" data-collapse-limit="5"><table><thead><tr><th>一级行业</th><th>阶段</th><th>方向分</th><th>20日超额</th><th>60日超额</th><th>20日扩散</th><th>60日扩散</th><th>持续率</th><th>叶子数</th><th>成分覆盖</th></tr></thead><tbody>{first_rows}</tbody></table></div><div class="notice">这里的“资金方向”由相对收益、行业扩散、排名持续性、趋势和量能共同代理，不把门户估算的“主力净流入”当作真实资金流。</div></section>
  <section><div class="section-head"><h2>二级方向候选</h2><span>从前 {一级方向展示数} 个一级方向中，各取前 {每个一级二级候选数} 个二级行业</span></div><div class="table-wrap" data-collapse-limit="5"><table><thead><tr><th>二级行业</th><th>阶段</th><th>方向分</th><th>20日超额</th><th>60日超额</th><th>20日扩散</th><th>60日扩散</th><th>持续率</th><th>叶子数</th><th>成分覆盖</th></tr></thead><tbody>{second_rows}</tbody></table></div></section>
  <section><div class="section-head"><h2>细分主线</h2><span>由叶子行业强度产生，不与上级行业重复排名</span></div><div class="table-wrap" data-collapse-limit="5"><table><thead><tr><th>叶子行业</th><th>阶段</th><th>强度分</th><th>20日超额</th><th>60日超额</th><th>持续率</th><th>趋势完整度</th><th>量能比</th><th>成分数</th><th>数据源</th><th>提示</th></tr></thead><tbody>{''.join(leaf_rows)}</tbody></table></div><div class="notice">叶子行业用于全覆盖和细分识别；一级、二级结果由其向上聚合。成分少于 5 只的细分只降低置信度，不直接删除。停止更新的申万三级指数使用当前成分权重合成代理走势，并在数据源列明确标注。</div></section>
</div>
<div id="panel-concept" class="tab-panel" role="tabpanel" aria-labelledby="tab-concept" hidden>
  <section><div class="section-head"><h2>概念独立确认</h2><span>概念与申万行业分开评分，仅用成分交叉验证细分主线</span></div><div class="table-wrap" data-collapse-limit="5"><table><thead><tr><th>概念</th><th>概念分</th><th>20日超额</th><th>60日超额</th><th>持续率</th><th>状态</th><th>最相关细分</th><th>交叉</th></tr></thead><tbody>{''.join(concept_rows)}</tbody></table></div></section>
</div>
<div id="panel-stock" class="tab-panel" role="tabpanel" aria-labelledby="tab-stock" hidden>{''.join(stock_sections)}</div>
<div id="panel-etf" class="tab-panel" role="tabpanel" aria-labelledby="tab-etf" hidden>
  <section><div class="section-head"><h2>主线替代工具</h2><span>ETF 与个股不混合排名</span></div><div class="table-wrap" data-collapse-limit="3"><table><thead><tr><th>对应主线</th><th>ETF</th><th>成交额</th><th>规模代理</th><th>边界</th></tr></thead><tbody>{''.join(etf_rows) or '<tr><td colspan=5>暂无名称匹配的 ETF</td></tr>'}</tbody></table></div></section>
</div>
</main>
<footer>本看板解决主线方向和第一梯队身份识别，不给出收益承诺，也不替代买卖时点判断。产业地位目前仍以申万成分关系、市值和收入规模代理衡量，主营收入纯度、市场份额和订单证据需人工核验。</footer>
<script>
function setupCollapsibleTables() {{
  document.querySelectorAll('.table-wrap[data-collapse-limit]').forEach((wrapper, index) => {{
    const limit = Number.parseInt(wrapper.dataset.collapseLimit || '0', 10);
    const tbody = wrapper.querySelector('tbody');
    if (!tbody || limit < 1) return;
    const rows = Array.from(tbody.children).filter((row) => row.tagName === 'TR');
    if (rows.length <= limit) return;

    tbody.id = `collapsible-table-${{index}}`;
    const hiddenCount = rows.length - limit;
    const control = document.createElement('div');
    control.className = 'table-toggle-row';
    control.innerHTML = `<button class="table-toggle" type="button" aria-expanded="false" aria-controls="${{tbody.id}}"><span class="table-toggle-icon" aria-hidden="true">⌄</span><span class="table-toggle-text"></span></button>`;
    wrapper.insertAdjacentElement('afterend', control);

    const button = control.querySelector('.table-toggle');
    const icon = control.querySelector('.table-toggle-icon');
    const label = control.querySelector('.table-toggle-text');
    const setExpanded = (expanded) => {{
      rows.forEach((row, rowIndex) => row.classList.toggle('is-collapsed', !expanded && rowIndex >= limit));
      button.setAttribute('aria-expanded', String(expanded));
      icon.textContent = expanded ? '⌃' : '⌄';
      label.textContent = expanded ? `收起到前 ${{limit}} 条` : `展开其余 ${{hiddenCount}} 条`;
    }};
    button.addEventListener('click', () => setExpanded(button.getAttribute('aria-expanded') !== 'true'));
    setExpanded(false);
  }});
}}

function setupStockLinks() {{
  const userAgent = navigator.userAgent || '';
  const mobileHint = navigator.userAgentData?.mobile === true;
  const mobileUserAgent = /Android|iPhone|iPad|iPod|Mobile/i.test(userAgent);
  const touchIPad = navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1;
  const touchTablet = navigator.maxTouchPoints > 1 && window.matchMedia('(pointer: coarse)').matches;
  const useMobileLinks = mobileHint || mobileUserAgent || touchIPad || touchTablet;

  document.querySelectorAll('.stock-link[data-desktop-url][data-mobile-url]').forEach((link) => {{
    const source = link.querySelector('.stock-link-source');
    link.href = useMobileLinks ? link.dataset.mobileUrl : link.dataset.desktopUrl;
    link.title = useMobileLinks ? '在新浪财经打开' : '在 TradingView 打开';
    if (source) source.textContent = useMobileLinks ? '新浪详情' : 'TradingView图表';
  }});
}}

function setupThemeSwitch() {{
  const root = document.documentElement;
  const buttons = Array.from(document.querySelectorAll('[data-theme-choice]'));
  const applyTheme = (theme, remember = true) => {{
    root.dataset.theme = theme;
    buttons.forEach((button) => button.setAttribute('aria-pressed', String(button.dataset.themeChoice === theme)));
    if (remember) {{
      try {{ localStorage.setItem('dashboard-theme', theme); }} catch (_error) {{}}
    }}
  }};
  const initialTheme = root.dataset.theme === 'light' ? 'light' : 'dark';
  applyTheme(initialTheme, false);
  buttons.forEach((button) => button.addEventListener('click', () => applyTheme(button.dataset.themeChoice)));
}}

function setupHelpPopover() {{
  const button = document.getElementById('help-button');
  const wrapper = button?.closest('.help-wrap');
  if (!button || !wrapper) return;
  const closeHelp = () => {{
    wrapper.classList.remove('is-open');
    button.setAttribute('aria-expanded', 'false');
  }};
  button.addEventListener('click', (event) => {{
    event.stopPropagation();
    const open = !wrapper.classList.contains('is-open');
    wrapper.classList.toggle('is-open', open);
    button.setAttribute('aria-expanded', String(open));
  }});
  wrapper.addEventListener('click', (event) => event.stopPropagation());
  document.addEventListener('click', closeHelp);
  document.addEventListener('keydown', (event) => {{
    if (event.key === 'Escape') {{
      closeHelp();
      button.focus();
    }}
  }});
}}

function setupTabs() {{
  const tabs = Array.from(document.querySelectorAll('[role="tab"]'));
  const panels = Array.from(document.querySelectorAll('[role="tabpanel"]'));
  if (!tabs.length) return;
  const activateTab = (tab, remember = true) => {{
    tabs.forEach((item) => {{
      const active = item === tab;
      item.setAttribute('aria-selected', String(active));
      item.tabIndex = active ? 0 : -1;
    }});
    panels.forEach((panel) => {{
      panel.hidden = panel.id !== tab.getAttribute('aria-controls');
    }});
    if (remember) {{
      try {{ localStorage.setItem('dashboard-tab', tab.id); }} catch (_error) {{}}
    }}
  }};
  tabs.forEach((tab, index) => {{
    tab.addEventListener('click', () => activateTab(tab));
    tab.addEventListener('keydown', (event) => {{
      let targetIndex = index;
      if (event.key === 'ArrowRight') targetIndex = (index + 1) % tabs.length;
      else if (event.key === 'ArrowLeft') targetIndex = (index - 1 + tabs.length) % tabs.length;
      else if (event.key === 'Home') targetIndex = 0;
      else if (event.key === 'End') targetIndex = tabs.length - 1;
      else return;
      event.preventDefault();
      activateTab(tabs[targetIndex]);
      tabs[targetIndex].focus();
    }});
  }});
  let savedId = '';
  try {{ savedId = localStorage.getItem('dashboard-tab') || ''; }} catch (_error) {{}}
  activateTab(tabs.find((tab) => tab.id === savedId) || tabs[0], false);
}}

const cloudUpdateApi = 'https://a-share-dashboard-refresh.linfeisama.workers.dev';
const cloudRunStorageKey = 'dashboard-refresh-run-id';
const cloudPollInterval = 5000;
let cloudPollPromise = null;

function setRefreshLoading(isLoading) {{
  const button = document.getElementById('refresh-button');
  const loading = document.getElementById('refresh-loading');
  button.disabled = isLoading;
  loading.hidden = !isLoading;
}}

function setRefreshStatus(message, state = '') {{
  const status = document.getElementById('refresh-status');
  status.className = `refresh-status ${{state}}`.trim();
  status.textContent = message;
}}

async function readJsonResponse(response) {{
  const contentType = response.headers.get('content-type') || '';
  if (!contentType.includes('application/json')) throw new Error('更新服务返回了无法识别的内容');
  const result = await response.json();
  if (!response.ok || !result.ok) throw new Error(result.message || '更新失败');
  return result;
}}

function rememberCloudRun(runId) {{
  try {{
    if (runId) localStorage.setItem(cloudRunStorageKey, String(runId));
    else localStorage.removeItem(cloudRunStorageKey);
  }} catch (_error) {{}}
}}

function reloadLatestDashboard() {{
  const url = new URL(window.location.href);
  url.searchParams.set('updated', Date.now().toString());
  window.location.replace(url.toString());
}}

async function pollCloudRefresh(runId) {{
  if (cloudPollPromise) return cloudPollPromise;
  cloudPollPromise = (async () => {{
    setRefreshLoading(true);
    rememberCloudRun(runId);
    for (let attempt = 0; attempt < 180; attempt += 1) {{
      const query = runId ? `?run_id=${{encodeURIComponent(runId)}}` : '';
      const response = await fetch(`${{cloudUpdateApi}}/更新状态${{query}}`, {{ cache: 'no-store' }});
      const result = await readJsonResponse(response);
      const run = result.run;
      if (!run) {{
        setRefreshStatus('更新请求已提交，正在等待云端任务开始…');
      }} else if (run.status === 'completed') {{
        rememberCloudRun('');
        if (run.conclusion === 'success') {{
          setRefreshStatus('更新完成，正在载入最新看板…', 'success');
          window.setTimeout(reloadLatestDashboard, 700);
          return;
        }}
        throw new Error(`云端更新未完成（${{run.conclusion || '状态未知'}}）`);
      }} else if (run.status === 'queued' || run.status === 'waiting' || run.status === 'pending') {{
        runId = run.run_id || runId;
        rememberCloudRun(runId);
        setRefreshStatus('更新请求已提交，正在等待云端计算…');
      }} else {{
        runId = run.run_id || runId;
        rememberCloudRun(runId);
        setRefreshStatus('正在获取行情并重新计算，通常需要几分钟…');
      }}
      await new Promise((resolve) => window.setTimeout(resolve, cloudPollInterval));
    }}
    throw new Error('云端更新等待超时，请稍后再点一次更新行情');
  }})().catch((error) => {{
    rememberCloudRun('');
    setRefreshStatus(error.message, 'error');
    setRefreshLoading(false);
  }}).finally(() => {{
    cloudPollPromise = null;
  }});
  return cloudPollPromise;
}}

async function refreshMarket() {{
  if (window.location.protocol === 'file:') {{
    setRefreshStatus('请先运行“启动看板网站.cmd”，再通过本地网站使用更新按钮。', 'error');
    return;
  }}
  const isLocalService = ['127.0.0.1', 'localhost'].includes(window.location.hostname);
  if (!isLocalService) {{
    setRefreshLoading(true);
    setRefreshStatus('正在提交云端更新请求…');
    try {{
      const response = await fetch(`${{cloudUpdateApi}}/更新行情`, {{ method: 'POST', cache: 'no-store' }});
      const result = await readJsonResponse(response);
      await pollCloudRefresh(result.run && result.run.run_id);
    }} catch (error) {{
      setRefreshStatus(error.message, 'error');
      setRefreshLoading(false);
    }}
    return;
  }}
  setRefreshLoading(true);
  setRefreshStatus('正在获取行情并重新计算，请稍候…');
  try {{
    const response = await fetch('/refresh', {{ method: 'POST', cache: 'no-store' }});
    await readJsonResponse(response);
    setRefreshStatus('更新完成，正在载入最新看板…', 'success');
    window.setTimeout(() => window.location.reload(), 400);
  }} catch (error) {{
    setRefreshStatus(`${{error.message}}。请确认“启动看板网站.cmd”正在运行。`, 'error');
    setRefreshLoading(false);
  }}
}}
document.addEventListener('DOMContentLoaded', () => {{
  setupCollapsibleTables();
  setupStockLinks();
  setupThemeSwitch();
  setupHelpPopover();
  setupTabs();
  if (!['127.0.0.1', 'localhost'].includes(window.location.hostname)) {{
    let savedRunId = '';
    try {{ savedRunId = localStorage.getItem(cloudRunStorageKey) || ''; }} catch (_error) {{}}
    if (savedRunId) pollCloudRefresh(savedRunId);
  }}
}});
</script>
</body></html>"""
    (结果目录 / "申万分层主线看板.html").write_text(document, encoding="utf-8-sig")
    (在线站点目录 / "index.html").write_text(document, encoding="utf-8-sig")
    (在线站点目录 / "网站首页.html").write_text(document, encoding="utf-8-sig")


def 生成说明(
    first_selected: pd.DataFrame,
    selected: pd.DataFrame,
    first_tier: pd.DataFrame,
) -> None:
    lines = [
        "# 申万分层试运行说明", "",
        f"- 生成时间：{datetime.now():%Y-%m-%d %H:%M:%S}",
        "- 计算底座：申万 2021 行业分类的当前叶子行业。",
        "- 聚合方式：叶子行业按成分数量平方根加权，向上汇总到二级和一级。",
        "- 概念板块：独立评分，只通过成分交叉验证行业主线，不与行业混排。",
        "- 交易范围：个股仅保留 60、00 开头，排除 ST 和退市标记；ETF 单列。", "",
        "## 当前一级方向", "",
    ]
    for _, row in first_selected.iterrows():
        lines.append(f"- {row['一级行业']}：{row['主线阶段']}，方向分 {row['方向得分']:.1f}；{证据文本(row)}")
    lines.extend(["", "## 当前细分主线与最高分公司", ""])
    for _, row in selected.iterrows():
        group = first_tier[first_tier["板块代码"].eq(row["叶子代码"])].head(3)
        names = "、".join(f"{stock['股票名称']}（{stock['第一梯队总分']:.1f}）" for _, stock in group.iterrows())
        lines.append(f"- {row['叶子行业']}：{names or '暂无足够数据'}")
    lines.extend([
        "", "## 使用边界", "",
        "1. 主线分数反映当前可见市场结构，不等于未来收益预测。",
        "2. 第一梯队只评价公司身份，不评价当前股价位置和入场性价比。",
        "3. 小样本叶子行业可能被少数股票影响，页面会保留提示。",
        "4. 主营收入纯度、市场份额、订单和政策催化仍需人工研究。",
    ])
    (结果目录 / "运行结果说明.md").write_text("\n".join(lines), encoding="utf-8-sig")


def main() -> None:
    print("1/8 获取市场基准和申万行业树...")
    benchmark = 获取沪深300日线(420)
    first, second, third, leaves = 获取申万层级()
    print(f"  层级：一级 {len(first)}，二级 {len(second)}，三级 {len(third)}，叶子 {len(leaves)}")

    print(f"2/8 获取 {len(leaves)} 个叶子行业日线...")
    if os.environ.get("GITHUB_ACTIONS", "").lower() == "true":
        准备申万当日代理行情()
    histories = 并行获取叶子日线(leaves, benchmark.index.max())
    histories, data_sources = 补齐过期叶子日线(histories, benchmark.index.max())

    print("3/8 计算叶子强度并向上聚合...")
    leaf_detail = 计算叶子行业特征(leaves, histories, benchmark, data_sources)
    if len(leaf_detail) < len(leaves) * 0.95:
        raise RuntimeError(f"叶子行业有效行情覆盖不足：{len(leaf_detail)}/{len(leaves)}")
    first_summary = 汇总行业方向(leaf_detail, "一级行业", "一级行业")
    second_summary = 汇总行业方向(leaf_detail, "二级行业", "二级行业")
    一级代码表 = first[["行业名称", "行业代码"]].rename(
        columns={"行业名称": "一级行业", "行业代码": "一级代码"}
    )
    一级代码表["一级代码"] = 一级代码表["一级代码"].str.replace(".SI", "", regex=False)
    二级代码表 = second[["行业名称", "行业代码"]].rename(
        columns={"行业名称": "二级行业", "行业代码": "二级代码"}
    )
    二级代码表["二级代码"] = 二级代码表["二级代码"].str.replace(".SI", "", regex=False)
    first_summary = first_summary.merge(一级代码表, on="一级行业", how="left")
    second_summary = second_summary.merge(二级代码表, on="二级行业", how="left")
    second_to_first = leaves[["二级行业", "一级行业"]].drop_duplicates()
    second_summary = second_summary.merge(second_to_first, on="二级行业", how="left")
    first_selected, second_selected, selected = 选择细分主线(first_summary, second_summary, leaf_detail)

    print("4/8 获取入选细分行业的完整成分和沪深快照...")
    snapshot = 获取沪深股票快照()
    leaf_members = 获取细分行业成分(selected, snapshot)
    stock_codes = sorted({code for frame in leaf_members.values() if not frame.empty for code in frame["股票代码"]})
    print(f"  入选细分 {len(selected)} 个，可交易股票 {len(stock_codes)} 只")

    print("5/8 批量获取全市场财务快照并评价第一梯队...")
    financials, report_date = 获取全市场财务快照(benchmark.index.max())
    board_names = dict(zip(selected["叶子代码"], selected["叶子行业"]))
    member_table = 构造成分股批量表(
        leaf_members, board_names, financials, report_date, benchmark
    )
    first_tier = 旧工具.评价第一梯队(member_table) if not member_table.empty else pd.DataFrame()

    print("6/8 独立计算概念确认...")
    try:
        concept_confirm = 获取概念确认(benchmark, selected, leaf_members)
    except Exception as exc:
        concept_fallback = 根目录 / "基础数据" / "概念独立确认回退.csv"
        if not concept_fallback.exists():
            raise
        print(f"概念更新失败，使用上次成功结果：{exc}")
        concept_confirm = pd.read_csv(concept_fallback)

    print("7/8 匹配 ETF 主线替代工具...")
    try:
        etfs = 旧工具.获取ETF替代工具(selected)
    except Exception as exc:
        etf_fallback = 根目录 / "基础数据" / "ETF主线替代工具回退.csv"
        if not etf_fallback.exists():
            raise
        print(f"ETF 更新失败，使用上次成功结果：{exc}")
        etfs = pd.read_csv(etf_fallback, dtype={"ETF代码": str})

    print("8/8 生成中文静态看板和完整明细...")
    first_summary.to_csv(结果目录 / "一级行业方向_完整31项.csv", index=False, encoding="utf-8-sig")
    second_summary.to_csv(结果目录 / "二级行业方向_完整131项.csv", index=False, encoding="utf-8-sig")
    leaf_detail.to_csv(结果目录 / "叶子行业明细_完整覆盖.csv", index=False, encoding="utf-8-sig")
    selected.to_csv(结果目录 / "细分主线名单.csv", index=False, encoding="utf-8-sig")
    concept_confirm.to_csv(结果目录 / "概念独立确认.csv", index=False, encoding="utf-8-sig")
    member_table.to_csv(结果目录 / "细分行业全部可交易成分.csv", index=False, encoding="utf-8-sig")
    first_tier.to_csv(结果目录 / "第一梯队完整名单.csv", index=False, encoding="utf-8-sig")
    etfs.to_csv(结果目录 / "ETF主线替代工具.csv", index=False, encoding="utf-8-sig")
    生成看板(
        benchmark, first_summary, second_summary, leaf_detail, first_selected,
        second_selected, selected, concept_confirm, first_tier, etfs,
    )
    生成说明(first_selected, selected, first_tier)
    print(f"完成。行情日期：{benchmark.index.max():%Y-%m-%d}")
    print(f"看板：{结果目录 / '申万分层主线看板.html'}")


if __name__ == "__main__":
    main()
