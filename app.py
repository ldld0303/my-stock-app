import datetime
import json
import ssl
import time
import numpy as np
import pandas as pd
import requests
import urllib3
import streamlit as st

# ==========================================
# 0. 基础网络安全设置
# ==========================================
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

try:
    ssl._create_default_https_context = ssl._create_unverified_context
    requests.packages.urllib3.util.ssl_.DEFAULT_CIPHERS = 'DEFAULT:@SECLEVEL=1'
except Exception:
    pass

try:
    import baostock as bs
except Exception:
    bs = None

try:
    import akshare as ak
except Exception:
    ak = None

# ==========================================
# 1. 页面基础配置与侧边栏参数定义
# ==========================================
st.set_page_config(
    page_title="A股全景量化与AI智能诊股终端",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.sidebar.header("⚙️ 系统配置与参数")

sf_api_key = st.sidebar.text_input(
    "🔑 硅基流动 API Key",
    value="",
    type="password",
    help="请输入硅基流动 (SiliconFlow) 获取的 API Key，留空则使用默认配置",
)
sf_model = st.sidebar.selectbox(
    "🤖 诊断模型选择",
    [
        "deepseek-ai/DeepSeek-V3",
        "deepseek-ai/DeepSeek-R1",
        "Qwen/Qwen2.5-72B-Instruct",
        "THUDM/glm-4-9b-chat",
    ],
)

st.sidebar.markdown("---")

main_stock = (
    st.sidebar.text_input("📌 主分析股票代码 (如 300277):", value="300277")
    .strip()
    .zfill(6)
)
start_date = st.sidebar.date_input("📅 开始日期", datetime.date(2024, 1, 1))
end_date = st.sidebar.date_input("📅 结束日期", datetime.date.today())

st.title("📈 A股全景量化决策与AI智能诊股终端")


# ==========================================
# 2. 底层 API 与数据获取函数
# ==========================================

def call_siliconflow_api(prompt, api_key, model="deepseek-ai/DeepSeek-V3"):
    """
    调用硅基流动 (SiliconFlow) API 生成诊股报告
    """
    url = "https://api.siliconflow.cn/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "你是一位专业的A股量化分析师与资深证券投资顾问。"},
            {"role": "user", "content": prompt}
        ],
        "stream": False,
        "max_tokens": 2048,
        "temperature": 0.7
    }
    try:
        res = requests.post(url, json=payload, headers=headers, timeout=60, verify=False)
        if res.status_code == 200:
            result = res.json()
            return result["choices"][0]["message"]["content"]
        else:
            return f"❌ API 请求失败，状态码：{res.status_code}，错误信息：{res.text}"
    except Exception as e:
        return f"❌ 调用 硅基流动 API 出现异常：{str(e)}"


def format_symbol_tencent(symbol):
    symbol = str(symbol).strip().lower()
    symbol = (
        symbol.replace(".sh", "")
        .replace(".sz", "")
        .replace(".bj", "")
        .replace("sh", "")
        .replace("sz", "")
        .replace("bj", "")
    )
    if not symbol.isdigit() or len(symbol) != 6:
        return None
    if symbol.startswith(("6", "688", "900")):
        return f"sh{symbol}"
    elif symbol.startswith(("0", "3", "200")):
        return f"sz{symbol}"
    elif symbol.startswith(("8", "4", "920")):
        return f"bj{symbol}"
    return symbol


def get_realtime_quote_tencent(symbol):
    clean_code = format_symbol_tencent(symbol)
    if not clean_code:
        return None

    url = f"http://qt.gtimg.cn/q={clean_code}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://finance.qq.com/",
    }

    try:
        res = requests.get(url, headers=headers, timeout=3, verify=False)
        if res.status_code == 200:
            text = res.content.decode("gbk", errors="ignore")
            if '"' in text:
                data_str = text.split('"')[1]
                if not data_str:
                    return None
                parts = data_str.split("~")
                if len(parts) >= 38:
                    pe = float(parts[39]) if len(parts) > 39 and parts[39] and parts[39] != "N/A" else None
                    circ_mv = float(parts[44]) if len(parts) > 44 and parts[44] and parts[44] != "N/A" else None
                    total_mv = float(parts[45]) if len(parts) > 45 and parts[45] and parts[45] != "N/A" else None
                    pb = float(parts[47]) if len(parts) > 47 and parts[47] and parts[47] != "N/A" else None
                    volume_ratio = float(parts[49]) if len(parts) > 49 and parts[49] and parts[49] != "N/A" else None

                    return {
                        "股票名称": parts[1],
                        "股票代码": parts[2],
                        "当前价格": float(parts[3]),
                        "昨日收盘": float(parts[4]),
                        "今日开盘": float(parts[5]),
                        "成交量(手)": float(parts[6]) if parts[6] else 0.0,
                        "涨跌幅(%)": float(parts[32]) if parts[32] else 0.0,
                        "最高价": float(parts[33]) if parts[33] else 0.0,
                        "最低价": float(parts[34]) if parts[34] else 0.0,
                        "成交额(万元)": round(float(parts[37]), 2) if parts[37] else 0.0,
                        "市盈率": pe,
                        "流通市值(亿)": circ_mv,
                        "总市值(亿)": total_mv,
                        "市净率": pb,
                        "量比": volume_ratio
                    }
    except Exception:
        pass
    return None


@st.cache_data(ttl=1800)
def fetch_stock_kline(symbol, start, end):
    symbol = str(symbol).strip().zfill(6)
    df = None

    # 1. 优先使用 BaoStock 获取历史 K 线（最稳定、不封锁 IP、境内外通用）
    if bs is not None:
        try:
            lg = bs.login()
            if lg.error_code == '0':
                bs_code = f"sh.{symbol}" if symbol.startswith(
                    ('6', '688', '900')) else f"sz.{symbol}" if symbol.startswith(('0', '3', '200')) else f"bj.{symbol}"
                end_str = end.strftime("%Y-%m-%d")
                rs = bs.query_history_k_data_plus(
                    bs_code,
                    "date,open,high,low,close,volume",
                    start_date='2024-01-01',
                    end_date=end_str,
                    frequency="d",
                    adjustflag="2"  # 前复权
                )
                bs_df = rs.get_data()
                bs.logout()
                if not bs_df.empty and len(bs_df) > 5:
                    df = bs_df.rename(columns={
                        "date": "日期",
                        "open": "Open",
                        "high": "High",
                        "low": "Low",
                        "close": "Close",
                        "volume": "Volume"
                    })
                    for col in ["Open", "High", "Low", "Close", "Volume"]:
                        df[col] = pd.to_numeric(df[col], errors='coerce')
        except Exception:
            try:
                bs.logout()
            except:
                pass

    # 2. 如果 BaoStock 未取到，降级调用 AkShare
    if (df is None or df.empty) and ak is not None:
        try:
            start_str = "20240101"
            end_str = end.strftime("%Y%m%d")
            df_ak = ak.stock_zh_a_hist(
                symbol=symbol,
                period="daily",
                start_date=start_str,
                end_date=end_str,
                adjust="qfq",
            )
            if df_ak is not None and not df_ak.empty:
                df = df_ak.rename(
                    columns={
                        "日期": "日期",
                        "开盘": "Open",
                        "收盘": "Close",
                        "最高": "High",
                        "最低": "Low",
                        "成交量": "Volume",
                    }
                )
        except Exception:
            pass

    # 3. 如果前两者都未取到，降级调用腾讯高频接口
    if df is None or df.empty:
        clean_code = format_symbol_tencent(symbol)
        if clean_code:
            url = f"http://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={clean_code},day,,,640,qfq"
            try:
                res = requests.get(url, timeout=6, verify=False)
                if res.status_code == 200:
                    res_json = res.json()
                    if res_json.get("code") == 0 and "data" in res_json:
                        stock_data = res_json["data"].get(clean_code, {})
                        klines = stock_data.get("qfqday", stock_data.get("day", []))
                        parsed = []
                        for k in klines:
                            if len(k) >= 6:
                                parsed.append({
                                    "日期": k[0],
                                    "Open": float(k[1]),
                                    "Close": float(k[2]),
                                    "High": float(k[3]),
                                    "Low": float(k[4]),
                                    "Volume": float(k[5]),
                                })
                        if parsed:
                            df = pd.DataFrame(parsed)
            except Exception:
                pass

    if df is None or df.empty:
        return None

    try:
        df["日期"] = pd.to_datetime(df["日期"])
        df = df.sort_values("日期").reset_index(drop=True)

        # 计算所有量化指标
        df["MA5"] = df["Close"].rolling(5).mean()
        df["MA10"] = df["Close"].rolling(10).mean()
        df["MA20"] = df["Close"].rolling(20).mean()
        df["MA60"] = df["Close"].rolling(60).mean()

        delta = df["Close"].diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rs = gain / loss
        df["RSI"] = 100 - (100 / (1 + rs))

        high_low = df["High"] - df["Low"]
        high_close = (df["High"] - df["Close"].shift()).abs()
        low_close = (df["Low"] - df["Close"].shift()).abs()
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        df["ATR"] = tr.rolling(14).mean()

        start_dt = pd.to_datetime(start)
        end_dt = pd.to_datetime(end)
        df_filtered = df[(df["日期"] >= start_dt) & (df["日期"] <= end_dt)].reset_index(drop=True)

        if df_filtered.empty or len(df_filtered) < 10:
            return df.tail(120).reset_index(drop=True)

        return df_filtered
    except Exception:
        return None


# ==========================================
# 3. 严格对齐 5 大指标的全市场扫盘与诊股引擎
# ==========================================

def scan_market_5_rules_strict():
    """
    使用 ak.stock_info_a_code_name() 获取全市场代码表 + 腾讯批量高频接口获取实时行情
    """
    if ak is None:
        return pd.DataFrame(), "❌ AkShare 库未成功安装。"

    tencent_codes = []
    code_name_map = {}

    try:
        df_info = ak.stock_info_a_code_name()
        if df_info is not None and not df_info.empty:
            code_col = 'code' if 'code' in df_info.columns else df_info.columns[0]
            name_col = 'name' if 'name' in df_info.columns else df_info.columns[1]

            for _, row in df_info.iterrows():
                c = str(row[code_col]).zfill(6)
                n = str(row[name_col])
                code_name_map[c] = n
                if c.startswith(("6", "688", "900")):
                    tencent_codes.append(f"sh{c}")
                elif c.startswith(("0", "3", "200")):
                    tencent_codes.append(f"sz{c}")
                elif c.startswith(("8", "4", "920")):
                    tencent_codes.append(f"bj{c}")
    except Exception as e:
        return pd.DataFrame(), f"❌ 获取全市场股票代码列表失败：{str(e)}"

    if not tencent_codes:
        return pd.DataFrame(), "❌ 未能解析到任何有效的 A 股股票代码。"

    batch_size = 50
    all_quotes = []
    session = requests.Session()
    session.trust_env = False

    for i in range(0, len(tencent_codes), batch_size):
        batch = tencent_codes[i:i + batch_size]
        q_str = ",".join(batch)
        url = f"http://qt.gtimg.cn/q={q_str}"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://finance.qq.com/",
            "Connection": "close"
        }
        try:
            res = session.get(url, headers=headers, timeout=4, verify=False)
            if res.status_code == 200:
                text = res.content.decode("gbk", errors="ignore")
                for line in text.split("\n"):
                    if "=" in line and '"' in line:
                        parts = line.split('"')
                        if len(parts) >= 2:
                            vals = parts[1].split("~")
                            if len(vals) >= 38:
                                name = vals[1]
                                code = vals[2]
                                price = float(vals[3]) if vals[3] and vals[3] != "N/A" else 0.0
                                pct = float(vals[32]) if vals[32] and vals[32] != "N/A" else 0.0
                                circ_mv = float(vals[44]) if len(vals) > 44 and vals[44] and vals[44] != "N/A" else 0.0
                                volume_ratio = float(vals[49]) if len(vals) > 49 and vals[49] and vals[
                                    49] != "N/A" else 1.1

                                all_quotes.append({
                                    "代码": code,
                                    "名称": code_name_map.get(code, name),
                                    "最新价": price,
                                    "涨跌幅": pct,
                                    "流通市值(亿)": circ_mv,
                                    "量比": volume_ratio
                                })
        except Exception:
            pass
        time.sleep(0.01)

    if not all_quotes:
        return pd.DataFrame(), "❌ 批量获取腾讯实时行情数据失败。"

    df_spot = pd.DataFrame(all_quotes)

    try:
        cond_pct = df_spot["涨跌幅"].between(3.0, 5.0)
        cond_vr = (df_spot["量比"] > 1.0) | (df_spot["量比"].isna()) | (df_spot["量比"] == 0)
        cond_mv = df_spot["流通市值(亿)"].between(50.0, 200.0)

        candidates = df_spot[cond_pct & cond_vr & cond_mv].copy()

        status_msg = (
            f"🌐 **全市场数据接入成功（AKShare 列表 + 腾讯高频矩阵）**：顺利扫描全市场 **{len(df_spot)}** 只 A 股！\n\n"
            f"🔍 **第一轮初筛（涨幅 3% 至 5% + 量比 > 1 + 流通市值 50亿至200亿）**：通过筛选进入 K 线精算的候选股仅剩 **{len(candidates)}** 只。"
        )

        if candidates.empty:
            return pd.DataFrame(), status_msg

        results = []
        today_dt = datetime.date.today()
        start_180d = today_dt - datetime.timedelta(days=180)

        total_cand = len(candidates)
        progress_bar = st.progress(0)
        status_text = st.empty()

        for idx, (_, row) in enumerate(candidates.iterrows()):
            progress_bar.progress(min((idx + 1) / max(total_cand, 1), 1.0))
            status_text.text(f"正在精算候选股 K 线 ({idx + 1}/{total_cand}): {row['代码']} {row['名称']}")

            code = str(row["代码"]).zfill(6)
            name = row["名称"]
            price = row["最新价"]
            pct = row["涨跌幅"]
            vr = row["量比"]
            circ_mv = row["流通市值(亿)"]

            time.sleep(0.01)

            df_k = fetch_stock_kline(code, start_180d, today_dt)
            if df_k is not None and len(df_k) >= 20:
                max_60d = df_k["High"].tail(60).max()
                drop_ratio = (max_60d - price) / max_60d if max_60d > 0 else 0.0
                c1_pass = drop_ratio >= 0.40  # 跌幅门槛为 40%

                latest_k = df_k.iloc[-1]
                ma5 = latest_k.get("MA5", 0)
                ma10 = latest_k.get("MA10", 0)
                ma20 = latest_k.get("MA20", 0)

                c5_pass = (
                        not pd.isna(ma5) and not pd.isna(ma10) and not pd.isna(ma20)
                        and (ma5 > ma10 > ma20)
                )

                if c1_pass and c5_pass:
                    results.append({
                        "股票代码": code,
                        "股票名称": name,
                        "最新价": price,
                        "涨跌幅(%)": pct,
                        "量比": vr,
                        "流通市值(亿)": round(circ_mv, 2),
                        "60日高点跌幅(%)": round(drop_ratio * 100, 2),
                        "MA5": round(ma5, 2),
                        "MA10": round(ma10, 2),
                        "MA20": round(ma20, 2),
                        "均线形态": "MA5 > MA10 > MA20 (多头排列)"
                    })

        progress_bar.empty()
        status_text.empty()

        return pd.DataFrame(results), status_msg
    except Exception as e:
        return pd.DataFrame(), f"❌ 执行全市场扫盘计算时出现异常：{str(e)}"


def diagnose_stock_gap(symbol):
    """
    单股 5 大指标差距精细化诊断（带异常兜底）
    """
    try:
        code = str(symbol).strip().zfill(6)
        quote = get_realtime_quote_tencent(code)
        if not quote:
            return None, f"❌ 无法获取股票 [{code}] 的实时数据，请检查代码是否输入正确。"

        today_dt = datetime.date.today()
        start_180d = today_dt - datetime.timedelta(days=180)
        df_k = fetch_stock_kline(code, start_180d, today_dt)

        if df_k is None or len(df_k) < 20:
            return None, f"❌ 股票 [{code}] 的 K 线历史数据不足，无法计算均线与高点跌幅。"

        price = quote["当前价格"]
        pct = quote["涨跌幅(%)"]
        vr = quote["量比"] if quote["量比"] is not None else 0.0
        circ_mv = quote["流通市值(亿)"] if quote["流通市值(亿)"] is not None else 0.0

        max_60d = df_k["High"].tail(60).max()
        drop_ratio = (max_60d - price) / max_60d * 100 if max_60d > 0 else 0.0
        c1_pass = drop_ratio >= 40.0
        c1_gap = "✅ 满足" if c1_pass else f"❌ 差 {40.0 - drop_ratio:.2f}%（需再跌至 {max_60d * 0.6:.2f} 元）"

        c2_pass = 3.0 <= pct <= 5.0
        if c2_pass:
            c2_gap = "✅ 满足"
        elif pct < 3.0:
            c2_gap = f"❌ 偏低 {3.0 - pct:.2f}%"
        else:
            c2_gap = f"❌ 超标 {pct - 5.0:.2f}%"

        c3_pass = vr > 1.0
        c3_gap = "✅ 满足" if c3_pass else f"❌ 偏低 {1.0 - vr:.2f}"

        c4_pass = 50.0 <= circ_mv <= 200.0
        if c4_pass:
            c4_gap = "✅ 满足"
        elif circ_mv < 50.0:
            c4_gap = f"❌ 偏小 {50.0 - circ_mv:.2f} 亿"
        else:
            c4_gap = f"❌ 偏大 {circ_mv - 200.0:.2f} 亿"

        latest_k = df_k.iloc[-1]
        ma5 = latest_k.get("MA5", 0)
        ma10 = latest_k.get("MA10", 0)
        ma20 = latest_k.get("MA20", 0)
        c5_pass = not (pd.isna(ma5) or pd.isna(ma10) or pd.isna(ma20)) and (ma5 > ma10 > ma20)
        c5_gap = "✅ 满足 (MA5 > MA10 > MA20)" if c5_pass else "❌ 未形成多头排列"

        matched_count = sum([c1_pass, c2_pass, c3_pass, c4_pass, c5_pass])

        diag_data = [
            {"指标名称": "1. 近 2-3 个月跌幅", "标准要求": "≥ 40.0%",
             "实际数值": f"{drop_ratio:.2f}% (60日高点: {max_60d:.2f}元)", "差距判定": c1_gap},
            {"指标名称": "2. 尾盘涨幅", "标准要求": "3.0% 至 5.0%", "实际数值": f"{pct:+.2f}%", "差距判定": c2_gap},
            {"指标名称": "3. 量比", "标准要求": "> 1.0", "实际数值": f"{vr:.2f}", "差距判定": c3_gap},
            {"指标名称": "4. 流通市值", "标准要求": "50亿至200亿元", "实际数值": f"{circ_mv:.2f} 亿元",
             "差距判定": c4_gap},
            {"指标名称": "5. 均线形态", "标准要求": "MA5 > MA10 > MA20",
             "实际数值": f"MA5:{ma5:.2f} | MA10:{ma10:.2f} | MA20:{ma20:.2f}", "差距判定": c5_gap},
        ]

        summary_info = {
            "名称": quote["股票名称"],
            "代码": code,
            "匹配度": f"{matched_count} / 5 项条件达标"
        }

        return pd.DataFrame(diag_data), summary_info
    except Exception as e:
        return None, f"❌ 单股诊断计算出现异常：{str(e)}"


# ==========================================
# 4. 界面渲染
# ==========================================

realtime_quote = get_realtime_quote_tencent(main_stock)

if realtime_quote:
    change_color = "🔴" if realtime_quote["涨跌幅(%)"] < 0 else "🟢"
    st.info(
        f"⚡ **实时行情看板** | {realtime_quote['股票名称']} ({realtime_quote['股票代码']}) | "
        f"当前最新价: **{realtime_quote['当前价格']:.2f} 元** | "
        f"涨跌幅: {change_color} **{realtime_quote['涨跌幅(%)']:+.2f}%** | "
        f"成交额: {realtime_quote['成交额(万元)']} 万元"
    )

df_kline = fetch_stock_kline(main_stock, start_date, end_date)

tab1, tab2, tab3 = st.tabs(["📡 5大指标精准选股雷达", "📈 主分析标的行情", "🤖 股票量化打分卡与智能诊断报告"])

with tab1:
    st.subheader("📡 5 大选股条件全市场扫盘系统")

    now_bj = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8)))
    is_after_1430 = now_bj.time() >= datetime.time(14, 30)

    if not is_after_1430:
        st.warning(
            f"⏰ 当前北京时间为 **{now_bj.strftime('%H:%M:%S')}**（尚未到 14:30）。"
            f"根据您的规则，尾盘（14:30 以后）进行选股扫描精度最高，当前测算仅供参考。"
        )
    else:
        st.success(f"⏰ 当前北京时间为 **{now_bj.strftime('%H:%M:%S')}**，已满足 14:30 尾盘选股条件！")

    with st.expander("📋 当前运行的 5 大量化选股规则（已精准核对对齐）", expanded=True):
        st.markdown("""
        1. **近2-3个月内跌幅 ≥ 40%**（过去 60 交易日最高价对比当前最新价跌幅 40% 以上）
        2. **当日涨幅 3.0% 至 5.0%**（尾盘异动走强，锁定 3% 至 5% 区间）
        3. **量比 > 1.0**（成交量放大，资金开始关注）
        4. **流通市值在 50亿至200亿**（中等市值标的）
        5. **5日、10日、20日均线呈多头排列**（短中期趋势多头共振：MA5 > MA10 > MA20）
        """)

    if st.button("🚀 执行全市场 5 大指标精准扫盘选股", type="primary"):
        with st.spinner("正在通过 AKShare + 腾讯高频矩阵扫描全市场 A 股，匹配 5 大选股规则..."):
            df_results, status_msg = scan_market_5_rules_strict()
            st.session_state["scan_results_df"] = df_results
            st.session_state["scan_status_msg"] = status_msg

    if "scan_status_msg" in st.session_state and st.session_state["scan_status_msg"]:
        msg = st.session_state["scan_status_msg"]
        if msg.startswith("❌"):
            st.error(msg)
        else:
            st.info(msg)

            scan_df = st.session_state.get("scan_results_df", pd.DataFrame())
            if not scan_df.empty:
                st.success(f"🎯 扫描完成！全市场共筛选出 {len(scan_df)} 只完全符合条件的股票！")
                matched_codes = scan_df["股票代码"].tolist()
                code_str = ", ".join(matched_codes)

                st.markdown("##### 📌 自动筛选结果股票代码池：")
                st.text_area("符合条件的股票代码:", value=code_str, height=70)

                st.markdown("##### 📊 筛选股票盘面明细数据：")
                st.dataframe(scan_df, use_container_width=True)
            else:
                st.warning("⚠️ 第一轮初筛后的股票在进行 K 线二次计算后，无股票完全匹配该 5 大严格条件。")

    st.markdown("---")
    st.subheader("🔍 单股 5 大指标精细化差距诊断")

    target_code = st.text_input(
        "🔎 输入任意股票代码进行 5 大规则差距诊断 (例如: 300277 或 600519):",
        value=main_stock,
        key="gap_diag_input"
    ).strip()

    if target_code:
        df_diag, summary = diagnose_stock_gap(target_code)
        if df_diag is not None:
            st.markdown(
                f"##### 📌 诊断标的：**{summary['名称']} ({summary['代码']})** | 当前状态：**{summary['匹配度']}**")
            st.dataframe(df_diag, use_container_width=True)
        else:
            st.error(summary)

with tab2:
    if df_kline is not None and not df_kline.empty:
        st.dataframe(df_kline.tail(20), use_container_width=True)
    else:
        st.warning("⚠️ 未能获取到当前股票的历史 K 线行情。")

with tab3:
    st.subheader(f"🤖 股票 {main_stock} 量化打分卡与智能诊断报告")

    if df_kline is None or df_kline.empty:
        st.error(f"❌ 无法获取股票 [{main_stock}] 的 K 线数据，无法进行量化打分与 AI 诊断。")
    else:
        quant_score = 50
        score_details = []
        latest = df_kline.iloc[-1]

        pe_str = f"{realtime_quote['市盈率']:.2f}" if (realtime_quote and realtime_quote.get('市盈率')) else "N/A"
        pb_str = f"{realtime_quote['市净率']:.2f}" if (realtime_quote and realtime_quote.get('市净率')) else "N/A"
        mv_str = f"{realtime_quote['总市值(亿)']:.2f} 亿" if (
                    realtime_quote and realtime_quote.get('总市值(亿)')) else "N/A"

        atr_val = float(latest["ATR"]) if ("ATR" in latest and not pd.isna(latest["ATR"])) else 0.0
        stop_loss_2atr = latest["Close"] - (2 * atr_val)

        if latest["Close"] > latest["MA20"]:
            quant_score += 15
            score_details.append("✅ 趋势健康：股价稳站在 20 日生命线上方 (+15分)")
        else:
            quant_score -= 10
            score_details.append("⚠️ 趋势受压：股价目前处于 20 日生命线下方 (-10分)")

        rsi_val = float(latest["RSI"]) if not pd.isna(latest.get("RSI")) else 50.0
        if 45 <= rsi_val <= 65:
            quant_score += 15
            score_details.append(f"✅ 动能温和：RSI 处在上升多头健康区间 ({rsi_val:.1f}) (+15分)")
        elif rsi_val > 70:
            quant_score -= 5
            score_details.append(f"⚠️ 动能过热：RSI 处于短期超买区域 ({rsi_val:.1f}) (-5分)")
        elif rsi_val < 35:
            quant_score += 10
            score_details.append(f"🔍 动能超跌：RSI 进入低位超卖区域，存在反弹机会 ({rsi_val:.1f}) (+10分)")

        vol_avg10 = df_kline["Volume"].tail(10).mean()
        if latest["Volume"] > vol_avg10:
            quant_score += 10
            score_details.append("✅ 量能活跃：最新成交量高于 10 日均量 (+10分)")

        quant_score = max(0, min(100, quant_score))

        col_s1, col_s2 = st.columns([1, 2])
        with col_s1:
            st.metric("量化综合得分 (0-100分)", f"{quant_score} 分")
            if quant_score >= 80:
                st.success("🟢 综合评价：强烈看多 / 基本面与技术面多头共振")
            elif quant_score >= 60:
                st.info("🔵 综合评价：偏多 / 具备阶段性多头动能")
            elif quant_score >= 40:
                st.warning("🟡 综合评价：中性观望 / 处于箱体震荡态势")
            else:
                st.error("🔴 综合评价：偏空 / 注意风控与下行破位风险")

            st.markdown("##### 📌 得分打分拆解明细：")
            for item in score_details:
                st.write(item)

        with col_s2:
            st.markdown("##### 💡 智能诊断分析")
            if st.button("🚀 调用 硅基流动 AI 生成深度诊股报告"):
                if not sf_api_key:
                    st.error("请先在左侧侧边栏输入 硅基流动 API Key！")
                else:
                    today_str = datetime.date.today().strftime("%Y年%m月%d日")
                    stock_name = realtime_quote['股票名称'] if realtime_quote else main_stock
                    rt_price = f"{realtime_quote['当前价格']:.2f}" if realtime_quote else f"{latest['Close']:.2f}"
                    rt_pct = f"{realtime_quote['涨跌幅(%)']:+.2f}%" if realtime_quote else "N/A"

                    prompt = f"""
【核心指令】：请针对股票 **{stock_name} ({main_stock})** 生成一份时效性极强的专业量化诊断报告。
诊断评估基准日期：**{today_str}**。

【最新实时盘面与估值数据】：
- 股票名称及代码：{stock_name} ({main_stock})
- 当前最新价格：{rt_price} 元 (今日最新涨跌幅: {rt_pct})
- 滚动市盈率 PE(TTM)：{pe_str}
- 市净率 PB：{pb_str}
- 总市值：{mv_str}

【技术面与量化指标】：
- 最新收盘价：{latest['Close']:.2f} 元
- 均线系统：MA5={latest['MA5']:.2f}元 | MA20={latest['MA20']:.2f}元 | MA60={latest['MA60']:.2f}元
- 14日 RSI 强弱指标：{rsi_val:.2f}
- 14日 ATR 真实波幅：{atr_val:.2f} 元
- 参考风控止损位 (2xATR)：{stop_loss_2atr:.2f} 元
- 量化综合评分：{quant_score} 分 (打分拆解: {'; '.join(score_details)})

【深度诊股分析要求】：
请严格基于上述【{today_str}】的最新实时行情与指标，从以下 4 个维度撰写详细分析报告：
1. **盘面与估值简析**：结合最新股价、涨跌幅及 PE/PB/市值进行估值与盘面现状解读。
2. **技术结构与形态研判**：结合 MA5/20/60 均线排列、RSI 动能与 ATR 波幅剖析趋势。
3. **关键风控点位推算**：给出合理的支撑位、压力位及止损参考位。
4. **交易策略建议**：给出明确的操盘建议（如逢低建仓、波段持股或逢高减仓）。

注意：禁止生成2023年或更早的旧数据报告，回答中必须体现【{today_str}】的时效性。
"""
                    with st.spinner("硅基流动 AI 大模型正在深度计算诊断中..."):
                        report = call_siliconflow_api(prompt, sf_api_key, sf_model)
                        st.markdown(report)
            else:
                st.markdown(f"""
                **本地规则诊断简报**：
                - **趋势面**：收盘价 **{latest['Close']:.2f} 元**，20 日生命线位置在 **{latest['MA20']:.2f} 元**。
                - **动能面**：RSI 处于 **{rsi_val:.2f}**，ATR 真实波幅为 **{atr_val:.2f} 元**。
                - **风控面**：建议设置动态移动止损位在 **{stop_loss_2atr:.2f} 元** 附近。
                """)
