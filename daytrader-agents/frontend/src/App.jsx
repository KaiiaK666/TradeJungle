import React, { useEffect, useMemo, useState } from "react";
import { getConfig, getState, getPnL, getResearch, getMarkets } from "./api.js";
import "./App.css";

export default function App() {
  const [config, setConfig] = useState(null);
  const [state, setState] = useState(null);
  const [pnl, setPnl] = useState([]);
  const [research, setResearch] = useState([]);
  const [markets, setMarkets] = useState({ commodities: [], cryptos: [], updated_ts: 0 });
  const [priceHistory, setPriceHistory] = useState([]);

  useEffect(() => {
    (async () => {
      setConfig(await getConfig());
    })();
  }, []);

  useEffect(() => {
    let active = true;
    const tick = async () => {
      const [nextState, nextPnl, nextResearch, nextMarkets] = await Promise.all([
        getState(),
        getPnL(),
        getResearch(),
        getMarkets(),
      ]);
      if (!active) return;
      setState(nextState);
      setPnl(nextPnl);
      setResearch(nextResearch);
      setMarkets(nextMarkets);
    };
    tick();
    const t = setInterval(tick, 2000);
    return () => {
      active = false;
      clearInterval(t);
    };
  }, []);

  const price = state?.price ?? 0;
  const posts = useMemo(() => (state?.posts ?? []).slice().reverse(), [state]);
  const trades = useMemo(() => (state?.trades ?? []).slice().reverse(), [state]);
  const threads = useMemo(() => buildThreads(state?.posts ?? []), [state]);

  useEffect(() => {
    if (!state?.price) return;
    setPriceHistory((prev) => {
      const next = prev.concat(state.price);
      if (next.length > 48) next.shift();
      return next;
    });
  }, [state?.price]);

  const priceStats = useMemo(() => computePriceStats(priceHistory, price), [priceHistory, price]);
  const sentiment = useMemo(() => computeSentiment(posts), [posts]);
  const mood = useMemo(() => computeMood(sentiment), [sentiment]);
  const activity = useMemo(() => computeActivity(posts), [posts]);
  const mentions = useMemo(() => computeMentions(posts, research), [posts, research]);
  const sparkPoints = useMemo(() => buildSparkPoints(priceHistory), [priceHistory]);
  const researchHighlights = useMemo(() => (research ?? []).slice(0, 8), [research]);
  const mentionsTop = useMemo(() => mentions.slice(0, 8), [mentions]);
  const commodityList = useMemo(() => (markets?.commodities ?? []).slice(0, 6), [markets]);
  const cryptoList = useMemo(() => {
    const limit = commodityList.length || 4;
    return (markets?.cryptos ?? []).slice(0, limit);
  }, [markets, commodityList]);

  return (
    <div className="app">
      <header className="hero">
        <div className="hero__intro">
          <div className="kicker">Daytrader Agents</div>
          <h1>Agent Forum + Paper Trading Sandbox</h1>
          <p className="subtitle">
            Real-time agent chatter, paper trades, and research radar built for fast market takes.
          </p>
          <div className="badges">
            <span className="badge">Agents: {config?.agent_count ?? "-"}</span>
            <span className="badge">Tick: {config?.tick_seconds ?? "-"}s</span>
            <span className="badge">Model: {config?.model_name ?? "-"}</span>
            <span className={`badge ${config?.using_claude_api ? "badge--live" : "badge--muted"}`}>
              Claude: {String(config?.using_claude_api ?? false)}
            </span>
          </div>
        </div>
        <div className={`hero__panel ${priceStats.trend}`}>
          <div className="panel__title">Market Pulse</div>
          <div className="panel__price">{price.toFixed(2)}</div>
          <div className="panel__delta">
            <span className="delta">
              {formatSigned(priceStats.change)} ({formatSigned(priceStats.pct)}%)
            </span>
            <span className="delta__note">local session</span>
          </div>
          <div className="sparkline">
            {sparkPoints.map((point, idx) => (
              <span
                key={`${point.value}-${idx}`}
                className={point.isUp ? "spark spark--up" : "spark spark--down"}
                style={{ height: `${point.height}%` }}
              />
            ))}
          </div>
          <div className="panel__meta">
            <span>Low {priceStats.low.toFixed(2)}</span>
            <span>High {priceStats.high.toFixed(2)}</span>
            <span>Vol {priceStats.vol.toFixed(2)}</span>
          </div>
        </div>
      </header>

      <section className="grid">
        <Card title="Hot Mentions" className="span-12">
          <div className="chip-row">
            {mentionsTop.map((item) => (
              <div key={item.label} className="chip">
                <span className="chip__label">{item.label}</span>
                <span className="chip__value">{item.count}</span>
              </div>
            ))}
          </div>
          {!mentionsTop.length ? <div className="empty">No mention data yet.</div> : null}
        </Card>

        <Card title="Commodity Watch" className="span-6">
          {commodityList.length === 0 ? (
            <div className="empty">Waiting for commodity data...</div>
          ) : (
            <div className="market-list">
              {commodityList.map((item) => (
                <div key={item.id} className="market-row">
                  <div>
                    <div className="market-row__label">{item.label}</div>
                    <div className="market-row__symbol">{item.symbol}</div>
                  </div>
                  <div className="market-row__price">{item.price.toFixed(2)}</div>
                  <div
                    className={`market-row__change ${
                      item.change_pct >= 0 ? "market-row__change--up" : "market-row__change--down"
                    }`}
                  >
                    {item.change_pct >= 0 ? "?" : "?"} {item.change_pct.toFixed(2)}%
                  </div>
                </div>
              ))}
            </div>
          )}
        </Card>

        <Card title="Top Cryptos" className="span-6">
          {cryptoList.length === 0 ? (
            <div className="empty">Waiting for crypto data...</div>
          ) : (
            <div className="market-list">
              {cryptoList.map((item) => (
                <div key={item.id} className="market-row">
                  <div>
                    <div className="market-row__label">{item.label}</div>
                    <div className="market-row__symbol">{item.symbol}</div>
                  </div>
                  <div className="market-row__price">{item.price.toFixed(2)}</div>
                  <div
                    className={`market-row__change ${
                      item.change_pct >= 0 ? "market-row__change--up" : "market-row__change--down"
                    }`}
                  >
                    {item.change_pct >= 0 ? "?" : "?"} {item.change_pct.toFixed(2)}%
                  </div>
                </div>
              ))}
            </div>
          )}
        </Card>

        <Card title="Bull vs Dying" className="span-3">
          <div className="mood">
            <div className="mood__row">
              <span>Bull</span>
              <span>{mood.bullPct}%</span>
            </div>
            <div className="mood__bar">
              <span style={{ width: `${mood.bullPct}%` }} />
            </div>
            <div className="mood__row">
              <span>Dying</span>
              <span>{mood.dyingPct}%</span>
            </div>
            <div className="mood__bar mood__bar--danger">
              <span style={{ width: `${mood.dyingPct}%` }} />
            </div>
            <div className="mood__row muted">Neutral {mood.neutralPct}%</div>
          </div>
        </Card>

        <Card title="Top Equity (Paper)" className="span-3">
          <div className="table">
            {pnl.slice(0, 7).map((row) => (
              <div key={row.agent} className="table__row">
                <span>{row.agent}</span>
                <span className="mono">{row.equity.toFixed(2)}</span>
              </div>
            ))}
          </div>
          {!pnl.length ? <div className="empty">No PnL data yet.</div> : null}
        </Card>

        <Card title="Agent Activity" className="span-3">
          <div className="stat">
            <div className="stat__value">{activity.activeCount}</div>
            <div className="stat__label">Agents active (5m)</div>
          </div>
          <div className="stat__meta">
            Most active: <strong>{activity.mostActive ?? "-"}</strong>
          </div>
          <div className="pill-row">
            {activity.topAgents.map((agent) => (
              <span key={agent} className="pill">
                {agent}
              </span>
            ))}
          </div>
        </Card>

        <Card title="Research Radar" className="span-3">
          {researchHighlights.length === 0 ? (
            <div className="empty">Waiting for Reddit highlights...</div>
          ) : (
            <div className="list">
              {researchHighlights.map((item) => (
                <a key={item.id} className="list__item" href={item.url} target="_blank" rel="noreferrer">
                  <div className="list__title">{item.title}</div>
                  <div className="list__meta">
                    r/{item.subreddit} • score {item.score ?? "n/a"}
                  </div>
                </a>
              ))}
            </div>
          )}
        </Card>

        <Card title="Forum Feed (Threaded)" className="span-8">
          <div className="feed">
            {!threads.length ? <div className="empty">Waiting on agent chatter...</div> : null}
            {threads.slice(0, 8).map((thread) => (
              <ThreadNode key={thread.id} node={thread} depth={0} />
            ))}
          </div>
        </Card>

        <Card title="Recent Paper Trades" className="span-4">
          <div className="list">
            {!trades.length ? <div className="empty">No trades yet.</div> : null}
            {trades.slice(0, 14).map((t) => (
              <div key={t.id} className="list__item no-link">
                <div className="list__title">
                  {t.agent} {t.side} {t.qty}
                </div>
                <div className="list__meta">
                  @ {t.price.toFixed(2)} • {new Date(t.ts * 1000).toLocaleTimeString()}
                </div>
              </div>
            ))}
          </div>
        </Card>

        <Card title="Conversation Threads" className="span-12">
          <div className="thread-list">
            {!threads.length ? <div className="empty">No chat threads yet.</div> : null}
            {threads.slice(0, 10).map((thread) => (
              <div key={`summary-${thread.id}`} className="thread-summary">
                <div className="thread-summary__title">{extractHeadline(thread.text)}</div>
                <div className="thread-summary__meta">
                  {thread.agent} • {thread.replyCount} replies • {new Date(thread.latestTs * 1000).toLocaleTimeString()}
                </div>
              </div>
            ))}
          </div>
        </Card>
      </section>

      <footer className="footer">
        Safety note: this is a simulation/paper sandbox. It is not financial advice and does not execute real trades.
      </footer>
    </div>
  );
}

function Card({ title, children, className = "" }) {
  return (
    <div className={`card ${className}`}>
      <div className="card__title">{title}</div>
      {children}
    </div>
  );
}

function ThreadNode({ node, depth }) {
  return (
    <div className="thread-node" style={{ marginLeft: depth * 16 }}>
      <div className="thread-node__header">
        <span className="thread-node__agent">{node.agent}</span>
        <span className="thread-node__time">{new Date(node.ts * 1000).toLocaleTimeString()}</span>
      </div>
      <div className="thread-node__text">{node.text}</div>
      {node.replies.map((reply) => (
        <ThreadNode key={reply.id} node={reply} depth={depth + 1} />
      ))}
    </div>
  );
}

function extractHeadline(text) {
  if (!text) return "";
  const lines = text.split("\n");
  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed) continue;
    if (trimmed.toLowerCase().startsWith("headline:")) {
      return trimmed.split(":").slice(1).join(":").trim();
    }
    return trimmed;
  }
  return "";
}

function formatSigned(value) {
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(2)}`;
}

function computePriceStats(history, fallback) {
  if (!history.length) {
    return {
      change: 0,
      pct: 0,
      low: fallback,
      high: fallback,
      vol: 0,
      range: 0,
      rangePct: 0,
      trend: "flat",
    };
  }
  const first = history[0];
  const last = history[history.length - 1];
  const low = Math.min(...history);
  const high = Math.max(...history);
  const change = last - first;
  const pct = first ? (change / first) * 100 : 0;
  const mean = history.reduce((acc, v) => acc + v, 0) / history.length;
  const variance = history.reduce((acc, v) => acc + (v - mean) ** 2, 0) / history.length;
  const vol = Math.sqrt(variance);
  const range = high - low;
  const rangePct = last ? (range / last) * 100 : 0;
  const trend = change > 0.02 ? "up" : change < -0.02 ? "down" : "flat";
  return { change, pct, low, high, vol, range, rangePct, trend };
}

function buildSparkPoints(history) {
  if (!history.length) return [];
  const low = Math.min(...history);
  const high = Math.max(...history);
  const span = Math.max(high - low, 0.0001);
  return history.map((value, idx) => {
    const next = history[idx + 1] ?? value;
    const height = 20 + ((value - low) / span) * 70;
    return {
      value,
      height,
      isUp: next >= value,
    };
  });
}

function extractBias(text) {
  if (!text) return null;
  const lower = text.toLowerCase();
  if (lower.includes("bias: long")) return "Long";
  if (lower.includes("bias: short")) return "Short";
  if (lower.includes("bias: neutral")) return "Neutral";
  return null;
}

function computeSentiment(posts) {
  const counts = { Long: 0, Short: 0, Neutral: 0 };
  posts.forEach((post) => {
    const bias = extractBias(post.text);
    if (bias) counts[bias] += 1;
  });
  const total = counts.Long + counts.Short + counts.Neutral;
  return { ...counts, total };
}

function computeMood(sentiment) {
  if (!sentiment.total) {
    return { bullPct: 0, dyingPct: 0, neutralPct: 0 };
  }
  const bullPct = Math.round((sentiment.Long / sentiment.total) * 100);
  const dyingPct = Math.round((sentiment.Short / sentiment.total) * 100);
  const neutralPct = Math.max(0, 100 - bullPct - dyingPct);
  return { bullPct, dyingPct, neutralPct };
}

function computeActivity(posts) {
  const cutoff = Date.now() / 1000 - 300;
  const counts = new Map();
  posts.forEach((post) => {
    if (post.ts < cutoff) return;
    counts.set(post.agent, (counts.get(post.agent) || 0) + 1);
  });
  let mostActive = null;
  let mostCount = 0;
  counts.forEach((value, key) => {
    if (value > mostCount) {
      mostCount = value;
      mostActive = key;
    }
  });
  const topAgents = Array.from(counts.entries())
    .sort((a, b) => b[1] - a[1])
    .slice(0, 8)
    .map(([agent]) => agent);
  return {
    activeCount: counts.size,
    mostActive,
    topAgents,
  };
}

function computeMentions(posts, research) {
  const keywords = [
    { label: "Gold", terms: ["gold", "xau"] },
    { label: "Silver", terms: ["silver", "xag"] },
    { label: "Oil", terms: ["oil", "wti", "brent", "crude"] },
    { label: "Cobalt", terms: ["cobalt"] },
    { label: "BTC", terms: ["btc", "bitcoin"] },
    { label: "NVDA", terms: ["nvda", "nvidia"] },
  ];
  const text = [...posts.map((p) => p.text || ""), ...research.map((r) => r.title || "")]
    .join(" ")
    .toLowerCase();
  return keywords
    .map((entry) => {
      const count = entry.terms.reduce((acc, term) => acc + countTerm(text, term), 0);
      return { label: entry.label, count };
    })
    .sort((a, b) => b.count - a.count);
}

function countTerm(text, term) {
  if (!text) return 0;
  const regex = new RegExp(`\\b${term}\\b`, "g");
  const matches = text.match(regex);
  return matches ? matches.length : 0;
}

function buildThreads(posts) {
  const nodes = new Map();
  posts.forEach((post) => {
    nodes.set(post.id, { ...post, replies: [] });
  });
  const roots = [];
  nodes.forEach((node) => {
    if (node.reply_to && nodes.has(node.reply_to)) {
      nodes.get(node.reply_to).replies.push(node);
    } else {
      roots.push(node);
    }
  });
  const sortThread = (node) => {
    node.replies.sort((a, b) => a.ts - b.ts);
    node.replies.forEach(sortThread);
  };
  roots.forEach(sortThread);

  const latestTs = (node) => {
    if (!node.replies.length) return node.ts;
    return Math.max(node.ts, ...node.replies.map(latestTs));
  };

  const addMeta = (node) => {
    const latest = latestTs(node);
    const replyCount = countReplies(node);
    return { ...node, latestTs: latest, replyCount };
  };

  const enriched = roots.map(addMeta);
  enriched.sort((a, b) => b.latestTs - a.latestTs);
  return enriched;
}

function countReplies(node) {
  return node.replies.reduce((acc, reply) => acc + 1 + countReplies(reply), 0);
}
