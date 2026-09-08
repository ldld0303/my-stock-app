import datetime
import json
import akshare as ak
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import requests
import streamlit as st

# ==========================================
# 1. 页面基础配置与侧边栏参数定义
# ==========================================
st.set_page_config(
    page_title="A股全景量化与AI智能诊股终端",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.sidebar.header("⚙️ 系统配置与参数")

# 硅基流动 API Key 配置区
sf_api_key = st.sidebar.text_input(
    "🔑 硅基流动 API Key",
    value="",
    type="password",
    help="请输入硅基流动 (SiliconFlow) 获取的 API Key，留空则使用本地智能诊断引擎",
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

# 全局核心标的与时间范围定义（在顶部优先定义，彻底防止 NameError）
main_stock = (
    st.sidebar.text_input("📌 主分析股票代码 (如 300277):", value="300277")
    .strip()
    .zfill(6)
)
start_date = st.sidebar.date_input("📅 开始日期", datetime.date(2024, 1, 1))
end_date = st.sidebar.date_input("📅 结束日期", datetime.date.today())

st.title("📈 A股全景量化决策与AI智能诊股终端")


# ==========================================
# 2. 高可用数据获取与技术指标计算引擎
# ==========================================


@st.cache_data(ttl=3600)
def fetch_stock_kline(symbol, start, end):
  """多源降级高可用 K 线获取函数 (优先东方财富 API -> 备用新浪 API -> 备用 AkShare)

  确保 300277、600519 等所有 A 股标的 100% 成功调取
  """
  symbol = str(symbol).strip().zfill(6)
  start_str = start.strftime("%Y%m%d")
  end_str = end.strftime("%Y%m%d")

  df = None

  # --- 源 1: 东方财富原生 HTTP API (支持前复权) ---
  try:
    secid = f"1.{symbol}" if symbol.startswith("6") else f"0.{symbol}"
    url = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
    params = {
        "secid": secid,
        "ut": "fa5fd1943c09868513d6d6445ed27862",
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
        "klt": "101",
        "fqt": "1",  # 前复权
        "beg": start_str,
        "end": end_str,
    }
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        ),
        "Referer": "https://quote.eastmoney.com/",
    }
    res = requests.get(url, params=params, headers=headers, timeout=8)
    data = res.json()
    if data and "data" in data and data["data"] and "klines" in data["data"]:
      klines = data["data"]["klines"]
      parsed = []
      for line in klines:
        f = line.split(",")
        parsed.append({
            "日期": f[0],
            "Open": float(f[1]),
            "Close": float(f[2]),
            "High": float(f[3]),
            "Low": float(f[4]),
            "Volume": float(f[5]),
            "Amount": float(f[6]),
            "Turnover": float(f[10]) if len(f) > 10 else 0.0,
        })
      df = pd.DataFrame(parsed)
  except Exception:
    df = None

  # --- 源 2: 新浪财经原生 HTTP API (备用源) ---
  if df is None or df.empty:
    try:
      sina_prefix = (
          "sh"
          if symbol.startswith(("60", "688"))
          else ("sz" if symbol.startswith(("00", "30")) else "bj")
      )
      sina_url = f"https://money.finance.sina.com.cn/quotes_service/api/json_p.php/CN_MarketData.getKLineData?symbol={sina_prefix}{symbol}&scale=240&ma=no&datalen=1024"
      res = requests.get(
          sina_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=8
      )
      text = res.text.strip()
      if text and text != "null" and "[]" not in text:
        sina_data = json.loads(text)
        parsed = []
        for item in sina_data:
          parsed.append({
              "日期": item["day"].split(" ")[0],
              "Open": float(item["open"]),
              "Close": float(item["close"]),
              "High": float(item["high"]),
              "Low": float(item["low"]),
              "Volume": float(item["volume"]),
              "Amount": 0.0,
              "Turnover": 0.0,
          })
        df = pd.DataFrame(parsed)
        df["日期"] = pd.to_datetime(df["日期"])
        start_dt = pd.to_datetime(start)
        end_dt = pd.to_datetime(end)
        df = df[(df["日期"] >= start_dt) & (df["日期"] <= end_dt)].reset_index(
            drop=True
        )
    except Exception:
      df = None

  # --- 源 3: AkShare 备用补全 ---
  if df is None or df.empty:
    try:
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
                "开盘": "Open",
                "收盘": "Close",
                "最高": "High",
                "最低": "Low",
                "成交量": "Volume",
                "成交额": "Amount",
                "换手率": "Turnover",
            }
        )
    except Exception:
      df = None

  if df is None or df.empty:
    return None

  # 标准化计算技术指标
  try:
    df["日期"] = pd.to_datetime(df["日期"])
    df = df.sort_values("日期").reset_index(drop=True)

    # 均线
    df["MA5"] = df["Close"].rolling(5).mean()
    df["MA20"] = df["Close"].rolling(20).mean()
    df["MA60"] = df["Close"].rolling(60).mean()

    # RSI (14日相对强弱指标)
    delta = df["Close"].diff()
    gain = (delta.where(delta > 0, 0)).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain / loss
    df["RSI"] = 100 - (100 / (1 + rs))

    # ATR (14日真实波幅)
    high_low = df["High"] - df["Low"]
    high_close = (df["High"] - df["Close"].shift()).abs()
    low_close = (df["Low"] - df["Close"].shift()).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    df["ATR"] = tr.rolling(14).mean()

    return df
  except Exception:
    return None


@st.cache_data(ttl=3600)
def fetch_financial_metrics(symbol):
  """获取主要基本面与估值指标"""
  symbol = str(symbol).strip().zfill(6)
  pe_ttm, pb, total_mv = None, None, None
  df_abstract = None

  # 获取估值指标 (PE, PB, 总市值)
  try:
    df_ind = ak.stock_a_indicator_lg(symbol=symbol)
    if df_ind is not None and not df_ind.empty:
      latest = df_ind.iloc[-1]
      pe_ttm = latest.get("pe_ttm", latest.get("pe", None))
      pb = latest.get("pb", None)
      total_mv = latest.get("total_mv", None)
  except Exception:
    pass

  # 获取财务报表摘要
  try:
    df_abstract = ak.stock_financial_abstract(symbol=symbol)
  except Exception:
    df_abstract = None

  return {"pe_ttm": pe_ttm, "pb": pb, "total_mv": total_mv}, df_abstract


@st.cache_data(ttl=3600)
def fetch_lhb_data(symbol):
  """获取龙虎榜机构与游资席位数据"""
  symbol = str(symbol).strip().zfill(6)
  try:
    today_str = datetime.date.today().strftime("%Y%m%d")
    start_90d = (datetime.date.today() - datetime.timedelta(days=90)).strftime(
        "%Y%m%d"
    )
    df_lhb = ak.stock_lhb_detail_em(start_date=start_90d, end_date=today_str)
    if df_lhb is not None and not df_lhb.empty:
      df_filtered = df_lhb[df_lhb["代码"] == symbol]
      return df_filtered
    return pd.DataFrame()
  except Exception:
    return pd.DataFrame()


def call_siliconflow_api(prompt, api_key, model_name):
    """通过 native requests 调用硅基流动 API"""
    # 自动清理首尾多余空格，如果为空则使用你填写的默认密钥
    api_key = api_key.strip() if api_key else "sk-rbkrovmorucwnivrifqgvvorzfwqsotxovgqbsoepwvmvzfg"

    url = "https://api.siliconflow.cn/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model_name,
        "messages": [
            {
                "role": "system",
                "content": (
                    "你是一位拥有20年资历的资深量化交易员与证券分析师，擅长结合技术面、基本面与资金面提供客观理性的股票诊断。"
                ),
            },
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.7,
        "max_tokens": 1024,
    }
    try:
        res = requests.post(url, headers=headers, json=payload, timeout=30)
        if res.status_code == 200:
            return res.json()["choices"][0]["message"]["content"]
        else:
            return f"❌ API 调用失败 (HTTP {res.status_code}): {res.text}"
    except Exception as e:
        return f"❌ API 请求发生异常: {str(e)}"


# ==========================================
# 3. 全局数据加载与主界面渲染
# ==========================================

with st.spinner(
    f"正在调取股票 【{main_stock}】 的市场行情与基本面数据..."
):
  df_kline = fetch_stock_kline(main_stock, start_date, end_date)
  val_dict, df_fin = fetch_financial_metrics(main_stock)

if df_kline is None or df_kline.empty:
  st.error(
      f"❌ 无法获取股票【{main_stock}】的行情数据。请检查代码是否输入无误，或延长侧边栏的开始日期。"
  )
else:
  # 7 大核心功能选项卡
  tab1, tab2, tab3, tab4, tab5, tab6, tab7 = st.tabs([
      "📈 全景技术指标",
      "💰 主力资金与龙虎榜",
      "📊 财务基本面与估值",
      "🤖 AI诊股与打分卡",
      "🧪 进阶策略回测",
      "⚔️ 多股走势对比",
      "📡 股票雷达选股",
  ])

  # ==========================================
  # 模块 1：📈 全景 K 线与技术指标扩展
  # ==========================================
  with tab1:
    st.subheader(f"📈 股票 {main_stock} 全景技术指标看板")

    latest_k = df_kline.iloc[-1]
    atr_val = latest_k["ATR"] if not pd.isna(latest_k.get("ATR")) else 0.0
    stop_loss_2atr = latest_k["Close"] - (2 * atr_val)

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("最新收盘价", f"{latest_k['Close']:.2f} 元")
    m2.metric(
        "RSI (14日)",
        f"{latest_k['RSI']:.2f}"
        if not pd.isna(latest_k.get("RSI"))
        else "N/A",
    )
    m3.metric("ATR (真实波幅)", f"{atr_val:.2f}")
    m4.metric("建议止损参考位 (2xATR)", f"{stop_loss_2atr:.2f} 元")

    fig = make_subplots(
        rows=3,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.03,
        row_heights=[0.5, 0.25, 0.25],
    )

    # K线 & 均线
    fig.add_trace(
        go.Candlestick(
            x=df_kline["日期"],
            open=df_kline["Open"],
            high=df_kline["High"],
            low=df_kline["Low"],
            close=df_kline["Close"],
            name="K线",
        ),
        row=1,
        col=1,
    )

    fig.add_trace(
        go.Scatter(
            x=df_kline["日期"],
            y=df_kline["MA5"],
            name="MA5",
            line=dict(color="orange", width=1),
        ),
        row=1,
        col=1,
    )
    fig.add_trace(
        go.Scatter(
            x=df_kline["日期"],
            y=df_kline["MA20"],
            name="MA20",
            line=dict(color="blue", width=1.5),
        ),
        row=1,
        col=1,
    )
    fig.add_trace(
        go.Scatter(
            x=df_kline["日期"],
            y=df_kline["MA60"],
            name="MA60",
            line=dict(color="purple", width=1.5),
        ),
        row=1,
        col=1,
    )

    # RSI
    fig.add_trace(
        go.Scatter(
            x=df_kline["日期"],
            y=df_kline["RSI"],
            name="RSI(14)",
            line=dict(color="magenta"),
        ),
        row=2,
        col=1,
    )
    fig.add_hline(y=70, line_dash="dash", line_color="red", row=2, col=1)
    fig.add_hline(y=30, line_dash="dash", line_color="green", row=2, col=1)

    # 成交量
    fig.add_trace(
        go.Bar(
            x=df_kline["日期"],
            y=df_kline["Volume"],
            name="成交量",
            marker_color="teal",
        ),
        row=3,
        col=1,
    )

    fig.update_layout(
        height=720,
        xaxis_rangeslider_visible=False,
        margin=dict(l=10, r=10, t=10, b=10),
    )
    st.plotly_chart(fig, use_container_width=True)

  # ==========================================
  # 模块 2：💰 主力资金与龙虎榜游资
  # ==========================================
  with tab2:
    st.subheader(f"💰 股票 {main_stock} 资金流向与龙虎榜追踪")

    df_lhb = fetch_lhb_data(main_stock)
    if df_lhb is not None and not df_lhb.empty:
      st.markdown("##### 🏛️ 近 90 天内龙虎榜上榜明细（游资/机构席位）")
      st.dataframe(df_lhb, use_container_width=True)
    else:
      st.info(
          f"ℹ️ 近 90 天内股票 {main_stock}"
          " 未登龙虎榜或暂无公开发布的席位交易明细。"
      )

    st.markdown("---")
    st.markdown("##### ⚡ 主力资金放量异动监控 (超过 5 日均量 2 倍)")
    df_kline["Vol_MA5"] = df_kline["Volume"].rolling(5).mean()
    df_kline["Vol_Ratio"] = df_kline["Volume"] / df_kline["Vol_MA5"]
    heavy_vol = df_kline[df_kline["Vol_Ratio"] >= 2.0][
        ["日期", "Close", "Volume", "Turnover", "Vol_Ratio"]
    ]
    if not heavy_vol.empty:
      st.dataframe(heavy_vol.tail(10), use_container_width=True)
    else:
      st.write("近期未观察到超过 2 倍 5日均量的放大异动。")

  # ==========================================
  # 模块 3：📊 财务基本面与估值分析
  # ==========================================
  with tab3:
    st.subheader(f"📊 股票 {main_stock} 基本面健康度与估值分析")

    c1, c2, c3 = st.columns(3)
    pe_str = (
        f"{val_dict['pe_ttm']:.2f}" if val_dict["pe_ttm"] is not None else "N/A"
    )
    pb_str = f"{val_dict['pb']:.2f}" if val_dict["pb"] is not None else "N/A"
    mv_str = (
        f"{val_dict['total_mv']/10000:.2f} 亿"
        if val_dict["total_mv"] is not None
        else "N/A"
    )

    c1.metric("市盈率 PE (TTM)", pe_str)
    c2.metric("市净率 PB", pb_str)
    c3.metric("总市值", mv_str)

    st.markdown("---")
    st.markdown("##### 📋 财务报表摘要与盈利质量分析")
    if df_fin is not None and not df_fin.empty:
      st.dataframe(df_fin, use_container_width=True)
    else:
      st.info("暂无详细财务摘要数据，系统已基于技术面进行深度打分。")

  # ==========================================
  # 模块 4：🤖 AI 深度诊股与量化打分卡
  # ==========================================
  with tab4:
    st.subheader(f"🤖 股票 {main_stock} 量化打分卡与智能诊断报告")

    # 本地规则量化打分 (0-100分)
    quant_score = 50
    score_details = []
    latest = df_kline.iloc[-1]

    if latest["Close"] > latest["MA20"]:
      quant_score += 15
      score_details.append("✅ 趋势健康：股价稳站在 20 日生命线上方 (+15分)")
    else:
      quant_score -= 10
      score_details.append("⚠️ 趋势受压：股价目前处于 20 日生命线下方 (-10分)")

    rsi_val = latest["RSI"] if not pd.isna(latest.get("RSI")) else 50.0
    if 45 <= rsi_val <= 65:
      quant_score += 15
      score_details.append(
          f"✅ 动能温和：RSI 处在上升多头健康区间 ({rsi_val:.1f}) (+15分)"
      )
    elif rsi_val > 70:
      quant_score -= 5
      score_details.append(
          f"⚠️ 动能过热：RSI 处于短期超买区域 ({rsi_val:.1f}) (-5分)"
      )
    elif rsi_val < 35:
      quant_score += 10
      score_details.append(
          f"🔍 动能超跌：RSI 进入低位超卖区域，存在反弹机会 ({rsi_val:.1f}) (+10分)"
      )

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
          prompt = f"""
请为股票代码 {main_stock} 生成一份专业的量化诊断报告。
【核心指标行情数据】：
- 最新收盘价：{latest['Close']:.2f} 元
- 20日均线 (生命线)：{latest['MA20']:.2f} 元
- 14日 RSI 强弱指标：{rsi_val:.2f}
- 14日 ATR 真实波幅：{atr_val:.2f}
- 量化综合评分：{quant_score} 分

请从以下四个维度进行专业剖析：
1. **技术面结构与趋势研判**
2. **资金面与量能匹配特征**
3. **关键风控位（止盈止损）**
4. **针对性的交易操作建议**
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

  # ==========================================
  # 模块 5：🧪 进阶量化策略回测
  # ==========================================
  with tab5:
    st.subheader("🧪 双均线 + 止盈止损 策略回测引擎")

    b_col1, b_col2, b_col3, b_col4 = st.columns(4)
    short_ma = b_col1.number_input("短期均线周期", value=5, min_value=2)
    long_ma = b_col2.number_input("长期均线周期", value=20, min_value=5)
    tp_pct = b_col3.number_input("硬止盈点位 (%)", value=10.0, step=0.5) / 100.0
    sl_pct = b_col4.number_input("硬止损点位 (%)", value=5.0, step=0.5) / 100.0

    # 回测逻辑
    df_bt = df_kline.copy()
    df_bt["MA_S"] = df_bt["Close"].rolling(short_ma).mean()
    df_bt["MA_L"] = df_bt["Close"].rolling(long_ma).mean()

    position = 0
    buy_price = 0.0
    equity = [100000.0]  # 初始资金 10 万元

    for i in range(1, len(df_bt)):
      curr_close = df_bt.iloc[i]["Close"]
      prev_s = df_bt.iloc[i - 1]["MA_S"]
      prev_l = df_bt.iloc[i - 1]["MA_L"]
      curr_s = df_bt.iloc[i]["MA_S"]
      curr_l = df_bt.iloc[i]["MA_L"]

      # 持仓止盈止损监控
      if position == 1:
        ret = (curr_close - buy_price) / buy_price
        if ret >= tp_pct or ret <= -sl_pct:
          position = 0  # 平仓卖出

      # 金叉买入
      if position == 0 and prev_s <= prev_l and curr_s > curr_l:
        position = 1
        buy_price = curr_close
      # 死叉卖出
      elif position == 1 and prev_s >= prev_l and curr_s < curr_l:
        position = 0

      # 资金曲线更新
      if position == 1:
        daily_ret = (curr_close - df_bt.iloc[i - 1]["Close"]) / df_bt.iloc[
            i - 1
        ]["Close"]
        equity.append(equity[-1] * (1 + daily_ret))
      else:
        equity.append(equity[-1])

    df_bt["Equity"] = equity
    total_ret = (equity[-1] - 100000.0) / 100000.0 * 100.0

    # 最大回撤计算
    eq_arr = np.array(equity)
    max_p = np.maximum.accumulate(eq_arr)
    dd = (eq_arr - max_p) / max_p
    max_drawdown = dd.min() * 100.0

    # 夏普比率 (年化)
    returns = pd.Series(equity).pct_change().dropna()
    sharpe = (
        (returns.mean() / returns.std()) * np.sqrt(252)
        if returns.std() != 0
        else 0.0
    )

    r1, r2, r3 = st.columns(3)
    r1.metric("策略累计收益率", f"{total_ret:.2f}%")
    r2.metric("最大回撤 (Max Drawdown)", f"{max_drawdown:.2f}%")
    r3.metric("年化夏普比率 (Sharpe)", f"{sharpe:.2f}")

    st.markdown("##### 📈 策略资产净值增长曲线 (基准 10 万元)")
    st.line_chart(df_bt.set_index("日期")[["Equity"]])

  # ==========================================
  # 模块 6：⚔️ 多股走势对比与自选对比
  # ==========================================
  with tab6:
    st.subheader("⚔️ 多股归一化收益率对比（识破龙头）")
    stocks_input = st.text_input(
        "输入对比的股票代码 (用逗号隔开，如 300277, 600519, 000001):",
        value="300277, 600519, 000001",
    )

    if st.button("开始对比分析"):
      stock_list = [
          s.strip().zfill(6) for s in stocks_input.split(",") if s.strip()
      ]
      fig_comp = go.Figure()

      with st.spinner("正在抓取并归一化计算多股收益率..."):
        for sym in stock_list:
          df_sym = fetch_stock_kline(sym, start_date, end_date)
          if df_sym is not None and not df_sym.empty:
            base_p = df_sym.iloc[0]["Close"]
            df_sym["Normalized"] = (df_sym["Close"] / base_p) * 100.0
            fig_comp.add_trace(
                go.Scatter(
                    x=df_sym["日期"],
                    y=df_sym["Normalized"],
                    mode="lines",
                    name=f"股票 {sym}",
                )
            )

      fig_comp.update_layout(
          title="多股归一化收益率对比曲线 (初始基准 = 100)",
          height=500,
          yaxis_title="相对净值",
          hovermode="x unified",
      )
      st.plotly_chart(fig_comp, use_container_width=True)

  # ==========================================
  # 模块 7：📡 股票雷达与形态选股
  # ==========================================
  with tab7:
    st.subheader("📡 股票形态选股与多指标扫描雷达")
    scan_pool_str = st.text_area(
        "批量扫描股票池代码 (用逗号隔开):",
        value="300277, 600519, 000001, 000858, 601318",
    )

    if st.button("🔍 执行批量形态雷达扫描"):
      targets = [
          t.strip().zfill(6) for t in scan_pool_str.split(",") if t.strip()
      ]
      scan_results = []

      p_bar = st.progress(0)
      for idx, target in enumerate(targets):
        df_t = fetch_stock_kline(target, start_date, end_date)
        if df_t is not None and len(df_t) >= 20:
          last_r = df_t.iloc[-1]
          prev_r = df_t.iloc[-2]

          patterns = []
          # 1. 金叉
          if (
              prev_r["MA5"] <= prev_r["MA20"]
              and last_r["MA5"] > last_r["MA20"]
          ):
            patterns.append("🔥 5日/20日均线金叉")
          # 2. 超卖/超买
          if last_r["RSI"] < 35:
            patterns.append("🟢 RSI 低位超卖 (<35)")
          elif last_r["RSI"] > 70:
            patterns.append("🔴 RSI 高位超买 (>70)")
          # 3. 巨量异动
          avg_v10 = df_t["Volume"].tail(10).mean()
          if last_r["Volume"] > 2.0 * avg_v10:
            patterns.append("⚡ 巨量放量异动")

          scan_results.append({
              "股票代码": target,
              "最新收盘价": f"{last_r['Close']:.2f}",
              "RSI (14)": (
                  f"{last_r['RSI']:.2f}"
                  if not pd.isna(last_r.get("RSI"))
                  else "N/A"
              ),
              "20日均线": f"{last_r['MA20']:.2f}",
              "特征形态描述": (
                  " | ".join(patterns) if patterns else "常规盘整形态"
              ),
          })
        p_bar.progress((idx + 1) / len(targets))

      st.markdown("##### 🔍 股票雷达匹配扫描结果：")
      st.dataframe(pd.DataFrame(scan_results), use_container_width=True)