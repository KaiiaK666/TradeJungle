import os
import time
import random
import asyncio
from typing import Dict, List, Optional, Tuple

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel


def parse_bool(value: str, default: bool = False) -> bool:
    if value is None:
        return default
    lowered = value.strip().lower()
    if lowered in ("1", "true", "yes", "y", "on"):
        return True
    if lowered in ("0", "false", "no", "n", "off"):
        return False
    return default


MODE = os.getenv("MODE", "hub").strip().lower()
if MODE not in ("hub", "agent"):
    MODE = "hub"
IS_HUB = MODE == "hub"
IS_AGENT = MODE == "agent"

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "").strip()
MODEL_NAME = os.getenv("MODEL_NAME", "claude-3-5-sonnet-latest").strip()

AGENT_COUNT = int(os.getenv("AGENT_COUNT", "33"))
AGENT_LIST_ENV = os.getenv("AGENT_LIST", "").strip()

TICK_SECONDS = float(os.getenv("TICK_SECONDS", "3"))
PRICE_TICK_SECONDS = float(os.getenv("PRICE_TICK_SECONDS", str(TICK_SECONDS)))
AGENT_TICK_SECONDS = float(os.getenv("AGENT_TICK_SECONDS", str(TICK_SECONDS)))
AGENT_POST_CHANCE = float(os.getenv("AGENT_POST_CHANCE", "1.0"))
REPLY_CHANCE = float(os.getenv("REPLY_CHANCE", "0.35"))
AGENT_JITTER_SECONDS = float(os.getenv("AGENT_JITTER_SECONDS", "0.6"))
TRADE_CHANCE = float(os.getenv("TRADE_CHANCE", "0.25"))

MAX_POSTS = int(os.getenv("MAX_POSTS", "2000"))
MAX_TRADES = int(os.getenv("MAX_TRADES", "2000"))

START_PRICE = float(os.getenv("START_PRICE", "100"))
START_CASH = float(os.getenv("START_CASH", "100000"))

HUB_URL = os.getenv("HUB_URL", "http://hub:8000").rstrip("/")
AGENT_NAME = os.getenv("AGENT_NAME", "").strip()
if IS_AGENT and not AGENT_NAME:
    AGENT_NAME = os.getenv("HOSTNAME", "Agent_00").strip() or "Agent_00"

RESEARCH_ENABLED = parse_bool(os.getenv("RESEARCH_ENABLED", "1"), default=True)
RESEARCH_TICK_SECONDS = float(os.getenv("RESEARCH_TICK_SECONDS", "120"))
RESEARCH_MAX_ITEMS = int(os.getenv("RESEARCH_MAX_ITEMS", "80"))
RESEARCH_SNAPSHOT_LIMIT = int(os.getenv("RESEARCH_SNAPSHOT_LIMIT", "12"))
RESEARCH_ALLOW_NSFW = parse_bool(os.getenv("RESEARCH_ALLOW_NSFW", "0"), default=False)
RESEARCH_USER_AGENT = os.getenv("RESEARCH_USER_AGENT", "daytrader-agents/0.1").strip()

MARKET_FEED_ENABLED = parse_bool(os.getenv("MARKET_FEED_ENABLED", "1"), default=True)
MARKET_REFRESH_SECONDS = float(os.getenv("MARKET_REFRESH_SECONDS", "120"))
COMMODITY_SYMBOLS = [
    s.strip()
    for s in os.getenv("COMMODITY_SYMBOLS", "GC=F,SI=F,CL=F,HG=F").split(",")
    if s.strip()
]
CRYPTO_LIMIT_ENV = int(os.getenv("CRYPTO_LIMIT", "0"))
CRYPTO_LIMIT = CRYPTO_LIMIT_ENV if CRYPTO_LIMIT_ENV > 0 else max(len(COMMODITY_SYMBOLS), 4)
COINGECKO_API_KEY = os.getenv("COINGECKO_API_KEY", "").strip()
COINGECKO_API_HEADER = os.getenv("COINGECKO_API_HEADER", "x-cg-demo-api-key").strip()

REDDIT_MODE = os.getenv("REDDIT_MODE", "hot").strip().lower()
if REDDIT_MODE not in ("hot", "new", "top"):
    REDDIT_MODE = "hot"
REDDIT_LIMIT = int(os.getenv("REDDIT_LIMIT", "6"))
REDDIT_SUBREDDITS = [
    s.strip()
    for s in os.getenv(
        "REDDIT_SUBREDDITS",
        "stocks,investing,wallstreetbets,options,futures,commodities,gold,silverbugs,oil,energy,news",
    ).split(",")
    if s.strip()
]


# -----------------------------------------
# App + CORS
# -----------------------------------------
app = FastAPI(title="Agent Forum + Paper Trading Sandbox")

# Allow the Vite frontend (5173) to call the API (8000)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# -----------------------------------------
# Models
# -----------------------------------------
class Post(BaseModel):
    id: int
    ts: float
    agent: str
    text: str
    reply_to: Optional[int] = None


class Trade(BaseModel):
    id: int
    ts: float
    agent: str
    side: str  # BUY / SELL
    qty: float
    price: float


class ResearchItem(BaseModel):
    id: str
    ts: float
    source: str
    title: str
    url: str
    score: Optional[int] = None
    subreddit: Optional[str] = None


class MarketItem(BaseModel):
    id: str
    label: str
    symbol: str
    price: float
    change_pct: float
    change_pct_7d: Optional[float] = None
    sparkline: Optional[List[float]] = None
    source: str


class ConfigOut(BaseModel):
    agent_count: int
    tick_seconds: float
    max_posts_per_tick: int
    model_name: str
    using_claude_api: bool
    mode: str


class StateOut(BaseModel):
    price: float
    posts: List[Post]
    trades: List[Trade]


class AgentPnL(BaseModel):
    agent: str
    cash: float
    position: float
    equity: float


class SnapshotOut(BaseModel):
    price: float
    recent_prices: List[float]
    posts: List[Post]
    position: float
    cash: float
    research: List[ResearchItem] = []


class MarketsOut(BaseModel):
    commodities: List[MarketItem]
    cryptos: List[MarketItem]
    updated_ts: float


class PostIn(BaseModel):
    agent: str
    text: str
    reply_to: Optional[int] = None


# -----------------------------------------
# Agent personas
# -----------------------------------------
ROLE_CYCLE = [
    ("Momentum Scalper", "Trades breakouts/acceleration; tight stops; fast exits."),
    ("Mean Reversion", "Fades extremes; looks for snapback; disciplined sizing."),
    ("Market Microstructure", "Watches liquidity/chop; avoids bad fills; trade quality."),
    ("Risk Manager", "Controls drawdown; enforces stops; reduces size in volatility."),
    ("Macro/News", "Explains regime/catalysts; identifies risk-on/off conditions."),
    ("Technicals", "Key levels, S/R, patterns; defines invalidation zones."),
    ("Volatility", "Vol expansion/contraction; adapts sizing; avoids chop."),
    ("Sentiment", "Crowd behavior; overreaction/underreaction; contrarian setups."),
    ("Trend Follower", "Rides direction; waits for confirmation; uses trailing stops."),
    ("Tape Reader", "Short-term flow; reacts to impulse; avoids false breaks."),
    ("Quant-ish", "Simple rules; measures momentum/mean-rev; avoids narratives."),
]

INTERESTS = [
    "Opening range breakouts and relative volume",
    "VWAP reclaims and mean reversion fades",
    "News catalysts and earnings reactions",
    "Liquidity sweeps and stop runs",
    "Index ETF trends and sector rotation",
    "Volatility compression and expansion",
    "Gap-and-go and gap-fade patterns",
    "Support and resistance laddering",
    "Tape speed and pullback entries",
    "Risk sizing and drawdown control",
    "Pairs and correlation shifts",
]

STYLE_NOTES = [
    "Short sentences, no fluff.",
    "Mentions key levels and invalidation.",
    "Prefers clear if/then statements.",
    "Gives a size range, not a single number.",
    "Calls out liquidity and slippage risk.",
    "Emphasizes patience and confirmation.",
    "Notes when to reduce size in chop.",
    "Highlights triggers and stop placement.",
    "Uses confident but measured tone.",
    "Focuses on trade quality over quantity.",
    "Adds a quick alternate scenario.",
]


def build_agent_list(count: int) -> List[str]:
    if AGENT_LIST_ENV:
        names = [a.strip() for a in AGENT_LIST_ENV.split(",") if a.strip()]
        return names
    return [f"Agent_{i:02d}" for i in range(1, count + 1)]


def agent_index_from_name(name: str, total: int) -> int:
    digits = "".join(ch for ch in name if ch.isdigit())
    if digits:
        try:
            idx = int(digits)
            if 1 <= idx <= total:
                return idx - 1
        except ValueError:
            pass
    return abs(hash(name)) % max(total, 1)


def profile_for_agent(name: str) -> Dict[str, str]:
    idx = agent_index_from_name(name, max(AGENT_COUNT, 1))
    role, focus = ROLE_CYCLE[idx % len(ROLE_CYCLE)]
    interests = INTERESTS[(idx * 3) % len(INTERESTS)]
    style = STYLE_NOTES[(idx * 5) % len(STYLE_NOTES)]
    return {
        "role": role,
        "focus": focus,
        "interests": interests,
        "style": style,
    }


def load_agent_profile(name: str) -> Dict[str, str]:
    profile = profile_for_agent(name)
    overrides = {
        "role": os.getenv("AGENT_ROLE", "").strip(),
        "focus": os.getenv("AGENT_FOCUS", "").strip(),
        "interests": os.getenv("AGENT_INTERESTS", "").strip(),
        "style": os.getenv("AGENT_STYLE", "").strip(),
    }
    for key, value in overrides.items():
        if value:
            profile[key] = value
    return profile


def extract_headline(text: str) -> str:
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.lower().startswith("headline:"):
            line = line.split(":", 1)[1].strip()
        return line[:120]
    text = text.strip()
    return text[:120] if text else "No headline"


# -----------------------------------------
# Claude call (agent side)
# -----------------------------------------
async def claude_generate(system: str, user: str, price_hint: float, profile: Dict[str, str]) -> str:
    if not ANTHROPIC_API_KEY:
        return build_stub_note(price_hint, profile)

    url = "https://api.anthropic.com/v1/messages"
    headers = {
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    payload = {
        "model": MODEL_NAME,
        "max_tokens": 420,
        "system": system,
        "messages": [{"role": "user", "content": user}],
    }

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(url, headers=headers, json=payload)
            r.raise_for_status()
            data = r.json()
    except httpx.HTTPStatusError as exc:
        detail = exc.response.text if exc.response is not None else ""
        print(f"[{AGENT_NAME}] Claude HTTP {exc.response.status_code if exc.response else 'error'}: {detail[:500]}")
        return build_stub_note(price_hint, profile)
    except Exception as exc:
        print(f"[{AGENT_NAME}] Claude error: {type(exc).__name__}: {exc}")
        return build_stub_note(price_hint, profile)

    blocks = data.get("content", [])
    text_parts = []
    for b in blocks:
        if b.get("type") == "text":
            text_parts.append(b.get("text", ""))

    return ("\n".join(text_parts)).strip() or "(no text)"


def build_stub_note(price_hint: float, profile: Dict[str, str]) -> str:
    bias = random.choice(["Long", "Short", "Neutral"])
    conf = random.randint(45, 72)
    decision = "Hold (paper): wait for confirmation"
    if bias != "Neutral":
        decision = f"Enter (paper): {bias} ~{random.randint(1, 8)} shares"
    stop = f"{price_hint * (0.995 if bias == 'Long' else 1.005):.2f}"
    headline = f"{profile['role']} watching {price_hint:.2f} for cleaner push"
    setup = f"{profile['interests']} while price drifts; waiting for confirmation."
    risk = f"Invalidate if price breaks {stop}; trim size if chop persists."
    return (
        f"Headline: {headline}\n"
        f"Bias: {bias}\n"
        f"Setup: {setup}\n"
        f"Decision (paper): {decision}\n"
        f"Risk: {risk}\n"
        f"Confidence: {conf}%"
    )


# -----------------------------------------
# Hub state + helpers
# -----------------------------------------
if IS_HUB:
    agents: List[str] = build_agent_list(AGENT_COUNT)
    agent_profiles: Dict[str, Dict[str, str]] = {a: profile_for_agent(a) for a in agents}

    posts: List[Post] = []
    trades: List[Trade] = []
    research_items: List[ResearchItem] = []
    market_commodities: List[MarketItem] = []
    market_cryptos: List[MarketItem] = []
    market_updated_ts: float = 0.0

    price: float = START_PRICE
    positions: Dict[str, float] = {a: 0.0 for a in agents}
    cash: Dict[str, float] = {a: float(START_CASH) for a in agents}

    next_post_id: int = 1
    next_trade_id: int = 1

    price_history: List[Tuple[float, float]] = []  # (ts, price)


    def ensure_agent(name: str) -> None:
        if name in positions:
            return
        agents.append(name)
        positions[name] = 0.0
        cash[name] = float(START_CASH)
        agent_profiles[name] = profile_for_agent(name)


    def trim_list(items: List, max_len: int) -> None:
        if len(items) > max_len:
            del items[: len(items) - max_len]


    def move_price() -> None:
        global price
        drift = 0.01
        shock = random.gauss(0, 0.35)
        price = max(1.0, price * (1 + (drift + shock) / 100.0))
        price_history.append((time.time(), price))
        if len(price_history) > 300:
            del price_history[:100]


    def parse_bias(text: str) -> Optional[str]:
        t = text.lower()
        if "bias: long" in t:
            return "Long"
        if "bias: short" in t:
            return "Short"
        if "bias: neutral" in t:
            return "Neutral"
        return None


    def maybe_paper_trade(agent: str, note_text: str) -> None:
        global next_trade_id
        if random.random() > TRADE_CHANCE:
            return

        bias = parse_bias(note_text)
        if bias in (None, "Neutral"):
            return

        side = "BUY" if bias == "Long" else "SELL"
        qty = round(random.uniform(1, 10), 2)
        p = price

        if side == "BUY":
            cost = qty * p
            if cash[agent] < cost:
                return
            cash[agent] -= cost
            positions[agent] += qty
        else:
            if positions[agent] < qty:
                return
            positions[agent] -= qty
            cash[agent] += qty * p

        trades.append(
            Trade(
                id=next_trade_id,
                ts=time.time(),
                agent=agent,
                side=side,
                qty=qty,
                price=p,
            )
        )
        next_trade_id += 1
        trim_list(trades, MAX_TRADES)

    def normalize_reddit_url(url: str, permalink: str) -> str:
        if url:
            return url
        if permalink:
            return f"https://www.reddit.com{permalink}"
        return "https://www.reddit.com"

    def commodity_label(symbol: str) -> str:
        labels = {
            "GC=F": "Gold",
            "SI=F": "Silver",
            "CL=F": "WTI Crude",
            "BZ=F": "Brent Crude",
            "HG=F": "Copper",
            "NG=F": "Nat Gas",
        }
        return labels.get(symbol, symbol)

    def build_reddit_item(subreddit: str, data: Dict) -> Optional[ResearchItem]:
        if not data:
            return None
        if data.get("over_18") and not RESEARCH_ALLOW_NSFW:
            return None
        title = (data.get("title") or "").strip()
        if not title:
            return None
        permalink = (data.get("permalink") or "").strip()
        url = normalize_reddit_url(
            (data.get("url_overridden_by_dest") or data.get("url") or "").strip(), permalink
        )
        item_id = data.get("name") or data.get("id") or f"{subreddit}:{hash(title)}"
        ts = float(data.get("created_utc") or time.time())
        score = data.get("score")
        return ResearchItem(
            id=f"reddit:{item_id}",
            ts=ts,
            source="reddit",
            title=title,
            url=url,
            score=score,
            subreddit=subreddit,
        )

    async def fetch_reddit_items(client: httpx.AsyncClient) -> List[ResearchItem]:
        if not REDDIT_SUBREDDITS:
            return []
        items: List[ResearchItem] = []
        for subreddit in REDDIT_SUBREDDITS:
            url = f"https://www.reddit.com/r/{subreddit}/{REDDIT_MODE}.json?limit={REDDIT_LIMIT}"
            try:
                r = await client.get(url)
                r.raise_for_status()
                payload = r.json()
            except Exception as exc:
                print(f"[research] reddit fetch failed for r/{subreddit}: {type(exc).__name__}: {exc}")
                continue

            for child in payload.get("data", {}).get("children", []):
                if child.get("kind") != "t3":
                    continue
                item = build_reddit_item(subreddit, child.get("data") or {})
                if item:
                    items.append(item)

        items.sort(key=lambda x: ((x.score or 0), x.ts), reverse=True)
        return items[:RESEARCH_MAX_ITEMS]

    async def fetch_commodities(client: httpx.AsyncClient) -> List[MarketItem]:
        if not COMMODITY_SYMBOLS:
            return []
        url = "https://query1.finance.yahoo.com/v7/finance/quote"
        params = {"symbols": ",".join(COMMODITY_SYMBOLS)}
        r = await client.get(url, params=params)
        r.raise_for_status()
        payload = r.json()
        results = payload.get("quoteResponse", {}).get("result", [])
        items: List[MarketItem] = []
        for row in results:
            symbol = row.get("symbol")
            price = row.get("regularMarketPrice")
            change_pct = row.get("regularMarketChangePercent")
            if symbol is None or price is None or change_pct is None:
                continue
            items.append(
                MarketItem(
                    id=f"yahoo:{symbol}",
                    label=commodity_label(symbol),
                    symbol=symbol,
                    price=float(price),
                    change_pct=float(change_pct),
                    source="yahoo",
                )
            )
        return items

    async def fetch_cryptos(client: httpx.AsyncClient) -> List[MarketItem]:
        url = "https://api.coingecko.com/api/v3/coins/markets"
        params = {
            "vs_currency": "usd",
            "order": "market_cap_desc",
            "per_page": CRYPTO_LIMIT,
            "page": 1,
            "sparkline": "true",
            "price_change_percentage": "24h,7d",
        }
        headers = {}
        if COINGECKO_API_KEY and COINGECKO_API_HEADER:
            headers[COINGECKO_API_HEADER] = COINGECKO_API_KEY
        r = await client.get(url, params=params, headers=headers)
        r.raise_for_status()
        payload = r.json()
        items: List[MarketItem] = []
        for row in payload:
            price = row.get("current_price")
            change_pct = row.get("price_change_percentage_24h")
            change_pct_7d = row.get("price_change_percentage_7d_in_currency")
            sparkline = None
            spark = row.get("sparkline_in_7d")
            if isinstance(spark, dict):
                sparkline = spark.get("price")
            if price is None or change_pct is None:
                continue
            items.append(
                MarketItem(
                    id=f"cg:{row.get('id')}",
                    label=row.get("name") or row.get("symbol", "").upper(),
                    symbol=(row.get("symbol") or "").upper(),
                    price=float(price),
                    change_pct=float(change_pct),
                    change_pct_7d=float(change_pct_7d) if change_pct_7d is not None else None,
                    sparkline=sparkline,
                    source="coingecko",
                )
            )
        return items

    async def research_loop() -> None:
        if not RESEARCH_ENABLED:
            return
        headers = {"User-Agent": RESEARCH_USER_AGENT}
        async with httpx.AsyncClient(timeout=20, headers=headers) as client:
            while True:
                try:
                    new_items = await fetch_reddit_items(client)
                    if new_items:
                        research_items[:] = new_items
                except Exception as exc:
                    print(f"[research] loop error: {type(exc).__name__}: {exc}")
                await asyncio.sleep(RESEARCH_TICK_SECONDS)

    async def market_loop() -> None:
        global market_commodities, market_cryptos, market_updated_ts
        if not MARKET_FEED_ENABLED:
            return
        headers = {"User-Agent": "daytrader-agents/0.1"}
        async with httpx.AsyncClient(timeout=20, headers=headers) as client:
            while True:
                try:
                    commodities = await fetch_commodities(client)
                    cryptos = await fetch_cryptos(client)
                    if commodities:
                        market_commodities = commodities
                    if cryptos:
                        market_cryptos = cryptos
                    if commodities or cryptos:
                        market_updated_ts = time.time()
                except Exception as exc:
                    print(f"[markets] loop error: {type(exc).__name__}: {exc}")
                await asyncio.sleep(MARKET_REFRESH_SECONDS)

    async def price_loop() -> None:
        global next_post_id
        while True:
            try:
                move_price()
            except Exception as e:
                posts.append(
                    Post(
                        id=next_post_id,
                        ts=time.time(),
                        agent="SYSTEM",
                        text=f"Price loop error: {type(e).__name__}: {e}",
                    )
                )
                next_post_id += 1
            await asyncio.sleep(PRICE_TICK_SECONDS)


# -----------------------------------------
# Agent logic
# -----------------------------------------
async def fetch_snapshot(client: httpx.AsyncClient) -> SnapshotOut:
    params = {"agent": AGENT_NAME, "limit_posts": 40, "limit_prices": 20}
    r = await client.get(f"{HUB_URL}/api/snapshot", params=params)
    r.raise_for_status()
    data = r.json()
    return SnapshotOut(**data)


def summarize_posts(posts_in: List[Post], limit: int = 8) -> str:
    if not posts_in:
        return "(none)"
    lines = []
    for p in posts_in[-limit:]:
        headline = extract_headline(p.text)
        lines.append(f"- [{p.id}] {p.agent}: {headline}")
    return "\n".join(lines)

def summarize_research(items: List[ResearchItem], limit: int = 8) -> str:
    if not items:
        return "(no research highlights yet)"
    lines: List[str] = []
    for item in items[:limit]:
        score = f"{item.score}" if item.score is not None else "n/a"
        sub = f"r/{item.subreddit}" if item.subreddit else "reddit"
        lines.append(f"- {sub} ({score}): {item.title}")
    return "\n".join(lines)


def pick_reply_target(posts_in: List[Post]) -> Optional[Post]:
    if not posts_in or random.random() > REPLY_CHANCE:
        return None
    candidates = [p for p in posts_in[-12:] if p.agent != AGENT_NAME]
    if not candidates:
        return None
    return random.choice(candidates)


async def post_note(client: httpx.AsyncClient, text: str, reply_to: Optional[int]) -> None:
    payload = {"agent": AGENT_NAME, "text": text, "reply_to": reply_to}
    r = await client.post(f"{HUB_URL}/api/post", json=payload)
    r.raise_for_status()


async def agent_loop() -> None:
    profile = load_agent_profile(AGENT_NAME)
    async with httpx.AsyncClient(timeout=30) as client:
        while True:
            try:
                if random.random() <= AGENT_POST_CHANCE:
                    snapshot = await fetch_snapshot(client)
                    prices = snapshot.recent_prices or [snapshot.price]
                    change = prices[-1] - prices[0]
                    pct = (change / prices[0]) * 100 if prices[0] else 0.0
                    hi = max(prices)
                    lo = min(prices)

                    reply_target = pick_reply_target(snapshot.posts)
                    recent_posts_text = summarize_posts(snapshot.posts, limit=8)
                    research_text = "(research not enabled)"
                    if snapshot.research:
                        research_text = summarize_research(snapshot.research, limit=8)

                    system = (
                        f"You are {AGENT_NAME}, a day-trading desk agent in a PAPER-trading sandbox.\n"
                        f"ROLE: {profile['role']}\n"
                        f"FOCUS: {profile['focus']}\n"
                        f"INTERESTS: {profile['interests']}\n"
                        f"STYLE: {profile['style']}\n\n"
                        "Rules:\n"
                        "- Paper trading only. Do NOT give real-world advice to a person.\n"
                        "- Use the provided SIM data, recent posts, and research highlights only.\n"
                        "- Speak like a desk note: concise, specific, actionable.\n"
                        "- Always include risk controls: invalidation/stop idea + sizing.\n"
                        "- Do not claim you personally browsed the web; use the highlights only.\n"
                        "- Do NOT mention APIs, models, tokens, or that you are an AI.\n"
                        "Return output in the exact format below, with all fields present."
                    )

                    user_lines = [
                        "SIM MARKET SNAPSHOT:",
                        f"- Current price: {snapshot.price:.2f}",
                        f"- Recent range (last ~{len(prices)} pts): low {lo:.2f} / high {hi:.2f}",
                        f"- Recent change: {change:+.2f} ({pct:+.2f}%)",
                        "",
                        "YOUR BOOK (paper):",
                        f"- Position: {snapshot.position:.2f} shares",
                        f"- Cash: {snapshot.cash:.2f}",
                        "",
                        "RECENT POSTS (newest last):",
                        recent_posts_text,
                        "",
                        "RESEARCH HIGHLIGHTS (public chatter):",
                        research_text,
                    ]

                    if reply_target:
                        user_lines += [
                            "",
                            "REPLY TARGET:",
                            f"Post ID {reply_target.id} by {reply_target.agent}:",
                            reply_target.text,
                            "",
                            "Respond directly to the reply target before adding your own view.",
                        ]
                    else:
                        user_lines += [
                            "",
                            "No required reply target. Add a fresh insight for the group.",
                        ]

                    user_lines += [
                        "",
                        "FORMAT (exact):",
                        "Headline: <8-14 words, market-focused>",
                        "Bias: Long | Short | Neutral",
                        "Setup: <1-2 sentences describing what you see>",
                        "Decision (paper): <Enter/Exit/Hold + side + rough size in shares>",
                        "Risk: <stop/invalidation level idea + what would prove you wrong>",
                        "Confidence: <0-100%>",
                    ]

                    user = "\n".join(user_lines)
                    text = await claude_generate(system, user, snapshot.price, profile)
                    await post_note(client, text, reply_target.id if reply_target else None)
            except Exception as e:
                print(f"[{AGENT_NAME}] error: {type(e).__name__}: {e}")

            sleep_for = max(1.0, AGENT_TICK_SECONDS + random.uniform(-AGENT_JITTER_SECONDS, AGENT_JITTER_SECONDS))
            await asyncio.sleep(sleep_for)


# -----------------------------------------
# Startup
# -----------------------------------------
@app.on_event("startup")
async def on_startup():
    if IS_HUB:
        global next_post_id
        price_history.append((time.time(), price))
        posts.append(
            Post(
                id=next_post_id,
                ts=time.time(),
                agent="SYSTEM",
                text="System online. Agents will begin posting shortly.",
            )
        )
        next_post_id += 1
        asyncio.create_task(price_loop())
        asyncio.create_task(research_loop())
        asyncio.create_task(market_loop())

    if IS_AGENT:
        asyncio.create_task(agent_loop())


# -----------------------------------------
# API routes
# -----------------------------------------
@app.get("/health")
def health():
    return {"mode": MODE}


if IS_HUB:
    @app.get("/api/config", response_model=ConfigOut)
    def get_config():
        return ConfigOut(
            agent_count=len(agents),
            tick_seconds=PRICE_TICK_SECONDS,
            max_posts_per_tick=1,
            model_name=MODEL_NAME,
            using_claude_api=bool(ANTHROPIC_API_KEY),
            mode=MODE,
        )


    @app.get("/api/state", response_model=StateOut)
    def get_state(limit_posts: int = 200, limit_trades: int = 200):
        return StateOut(
            price=price,
            posts=posts[-limit_posts:],
            trades=trades[-limit_trades:],
        )


    @app.get("/api/pnl", response_model=List[AgentPnL])
    def get_pnl():
        out: List[AgentPnL] = []
        for a in agents:
            equity = cash[a] + positions[a] * price
            out.append(AgentPnL(agent=a, cash=cash[a], position=positions[a], equity=equity))

        out.sort(key=lambda x: x.equity, reverse=True)
        return out[:25]


    @app.get("/api/snapshot", response_model=SnapshotOut)
    def get_snapshot(agent: str, limit_posts: int = 40, limit_prices: int = 20):
        if not agent:
            raise HTTPException(status_code=400, detail="agent is required")
        ensure_agent(agent)
        recent_prices = [p for _, p in price_history[-limit_prices:]]
        if not recent_prices:
            recent_prices = [price]
        research_slice = research_items[:RESEARCH_SNAPSHOT_LIMIT]
        return SnapshotOut(
            price=price,
            recent_prices=recent_prices,
            posts=posts[-limit_posts:],
            position=positions[agent],
            cash=cash[agent],
            research=research_slice,
        )

    @app.get("/api/research", response_model=List[ResearchItem])
    def get_research():
        return research_items[:RESEARCH_SNAPSHOT_LIMIT]

    @app.get("/api/markets", response_model=MarketsOut)
    def get_markets():
        return MarketsOut(
            commodities=market_commodities,
            cryptos=market_cryptos,
            updated_ts=market_updated_ts,
        )


    @app.post("/api/post", response_model=Post)
    def post_note(note: PostIn):
        global next_post_id

        agent = note.agent.strip() if note.agent else ""
        text = note.text.strip() if note.text else ""
        if not agent or not text:
            raise HTTPException(status_code=400, detail="agent and text are required")

        ensure_agent(agent)

        reply_to = note.reply_to
        if reply_to is not None and not any(p.id == reply_to for p in posts):
            reply_to = None

        post = Post(id=next_post_id, ts=time.time(), agent=agent, text=text, reply_to=reply_to)
        posts.append(post)
        next_post_id += 1
        trim_list(posts, MAX_POSTS)

        maybe_paper_trade(agent, text)
        return post
