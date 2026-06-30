import json
import requests
from typing import Any, Dict, Optional
from connectors.base import BaseConnector
from security.secrets import get_secret
from utils.logger import get_logger

logger = get_logger("connectors.web_search")


class WebSearchConnector(BaseConnector):
    """
    Web search and financial data connector.

    Provides three tools agents can call:
      web_search.search       — Google search via Serper API (2500 free/month)
      web_search.get_stock    — Real-time stock quote via Alpha Vantage (free tier)
      web_search.scrape_page  — Fetch and extract text from any URL

    API Keys (set as environment variables):
      SERPER_API_KEY      — https://serper.dev  (free, sign up for key)
      ALPHA_VANTAGE_KEY   — https://alphavantage.co (free, sign up for key)

    Both connectors fall back to mock data if no key is set, so you can
    develop and test without credentials.
    """

    def __init__(self, name: str = "web_search", config: Dict[str, Any] = None):
        super().__init__(name, config)
        self.serper_key: Optional[str] = None
        self.alpha_vantage_key: Optional[str] = None

    def authenticate(self) -> None:
        self.serper_key = self.config.get("serper_api_key") or get_secret("SERPER_API_KEY")
        self.alpha_vantage_key = (
            self.config.get("alpha_vantage_key") or get_secret("ALPHA_VANTAGE_KEY")
        )
        if not self.serper_key:
            logger.warning("No SERPER_API_KEY found — web_search.search will return mock results.")
        if not self.alpha_vantage_key:
            logger.warning("No ALPHA_VANTAGE_KEY found — web_search.get_stock will return mock data.")

    # ──────────────────────────────────────────────────────────────────────────
    # Tool 1 — web_search.search
    # ──────────────────────────────────────────────────────────────────────────
    def search(self, query: str, num_results: int = 5) -> str:
        """
        Search the web using Google Search (via Serper API) and return the top
        results as a formatted text summary. Use this to find current news,
        company info, analyst reports, or any real-time information.
        """
        self.authenticate()

        if not self.serper_key:
            # Mock fallback — returns realistic fake data for dev/testing
            return (
                f"[MOCK] Web search results for: '{query}'\n\n"
                "1. Title: Stock Market Overview — Reuters\n"
                "   Link: https://reuters.com/markets\n"
                "   Snippet: Markets showed mixed signals today as tech stocks rallied...\n\n"
                "2. Title: AAPL Stock Analysis — Bloomberg\n"
                "   Link: https://bloomberg.com/quote/AAPL\n"
                "   Snippet: Apple Inc shares climbed 2.3% on strong iPhone sales data...\n\n"
                "3. Title: Analyst Upgrades — MarketWatch\n"
                "   Link: https://marketwatch.com\n"
                "   Snippet: Goldman Sachs upgraded three tech names citing AI tailwinds...\n"
            )

        try:
            response = requests.post(
                "https://google.serper.dev/search",
                headers={
                    "X-API-KEY": self.serper_key,
                    "Content-Type": "application/json",
                },
                json={"q": query, "num": num_results},
                timeout=10,
            )
            response.raise_for_status()
            data = response.json()

            output_lines = [f"Web search results for: '{query}'\n"]

            # Knowledge Graph (if present)
            kg = data.get("knowledgeGraph", {})
            if kg:
                output_lines.append(f"Knowledge Panel: {kg.get('title', '')} — {kg.get('description', '')}\n")

            # Organic results
            organic = data.get("organic", [])
            for i, item in enumerate(organic[:num_results], start=1):
                title = item.get("title", "")
                link = item.get("link", "")
                snippet = item.get("snippet", "")
                output_lines.append(f"{i}. {title}\n   {link}\n   {snippet}\n")

            # Answer box if present (direct answers)
            answer = data.get("answerBox", {})
            if answer:
                output_lines.insert(1, f"Direct Answer: {answer.get('answer') or answer.get('snippet', '')}\n")

            return "\n".join(output_lines)

        except Exception as e:
            logger.error(f"Serper search failed: {e}")
            return f"Web search failed for query '{query}': {e}"

    # ──────────────────────────────────────────────────────────────────────────
    # Tool 2 — web_search.get_stock
    # ──────────────────────────────────────────────────────────────────────────
    def get_stock(self, symbol: str) -> str:
        """
        Fetch the latest stock quote for a ticker symbol (e.g. AAPL, MSFT, TSLA,
        GOOGL). Returns current price, change, volume, 52-week range, and market cap.
        Use this whenever the user asks about a specific stock's current price or
        recent performance.
        """
        self.authenticate()
        symbol = symbol.upper().strip()

        if not self.alpha_vantage_key:
            # Mock fallback
            mock_prices = {
                "AAPL": ("189.45", "+2.30", "+1.23%", "58.2M", "172.10", "199.62"),
                "MSFT": ("415.20", "+5.10", "+1.24%", "22.1M", "309.45", "430.82"),
                "TSLA": ("248.30", "-3.50", "-1.39%", "103.5M", "138.80", "299.29"),
                "GOOGL": ("178.90", "+1.20", "+0.67%", "19.8M", "130.67", "193.31"),
                "NVDA": ("875.40", "+12.30", "+1.42%", "45.2M", "373.85", "974.00"),
            }
            data = mock_prices.get(symbol, ("150.00", "+1.00", "+0.67%", "10M", "100.00", "200.00"))
            return (
                f"[MOCK] Stock Quote: {symbol}\n"
                f"  Price:       ${data[0]}\n"
                f"  Change:      {data[1]} ({data[2]})\n"
                f"  Volume:      {data[3]} shares\n"
                f"  52-wk Low:   ${data[4]}\n"
                f"  52-wk High:  ${data[5]}\n"
            )

        try:
            response = requests.get(
                "https://www.alphavantage.co/query",
                params={
                    "function": "GLOBAL_QUOTE",
                    "symbol": symbol,
                    "apikey": self.alpha_vantage_key,
                },
                timeout=10,
            )
            response.raise_for_status()
            data = response.json()

            quote = data.get("Global Quote", {})
            if not quote:
                return f"No data found for symbol '{symbol}'. Check the ticker is valid."

            price        = quote.get("05. price", "N/A")
            change       = quote.get("09. change", "N/A")
            change_pct   = quote.get("10. change percent", "N/A")
            volume       = quote.get("06. volume", "N/A")
            high_52      = quote.get("03. high", "N/A")
            low_52       = quote.get("04. low", "N/A")
            prev_close   = quote.get("08. previous close", "N/A")
            open_price   = quote.get("02. open", "N/A")
            latest_day   = quote.get("07. latest trading day", "N/A")

            return (
                f"Stock Quote: {symbol} (as of {latest_day})\n"
                f"  Price:          ${price}\n"
                f"  Open:           ${open_price}\n"
                f"  Prev Close:     ${prev_close}\n"
                f"  Change:         {change} ({change_pct})\n"
                f"  Volume:         {volume} shares\n"
                f"  Day High:       ${high_52}\n"
                f"  Day Low:        ${low_52}\n"
            )

        except Exception as e:
            logger.error(f"Alpha Vantage stock fetch failed for {symbol}: {e}")
            return f"Stock data fetch failed for '{symbol}': {e}"

    # ──────────────────────────────────────────────────────────────────────────
    # Tool 3 — web_search.scrape_page
    # ──────────────────────────────────────────────────────────────────────────
    def scrape_page(self, url: str, max_chars: int = 3000) -> str:
        """
        Fetch the content of a webpage and return the extracted plain text.
        Useful for reading articles, press releases, earnings reports, or any
        URL found from a web search. Returns up to max_chars characters of text.
        """
        try:
            headers = {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                )
            }
            response = requests.get(url, headers=headers, timeout=12)
            response.raise_for_status()

            # Strip HTML tags with a simple regex approach (no extra deps needed)
            import re
            text = response.text
            # Remove scripts and styles
            text = re.sub(r"<(script|style)[^>]*>.*?</(script|style)>", " ", text, flags=re.DOTALL | re.IGNORECASE)
            # Remove all remaining tags
            text = re.sub(r"<[^>]+>", " ", text)
            # Collapse whitespace
            text = re.sub(r"\s+", " ", text).strip()

            if len(text) > max_chars:
                text = text[:max_chars] + f"\n\n[... truncated at {max_chars} chars]"

            return f"Content from {url}:\n\n{text}"

        except Exception as e:
            logger.error(f"scrape_page failed for {url}: {e}")
            return f"Failed to fetch page at '{url}': {e}"
