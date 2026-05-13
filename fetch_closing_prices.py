import requests
from bs4 import BeautifulSoup
import re
import datetime
import schedule
import time
import pytz
import pandas as pd

"""
This script fetches closing prices for a list of financial instruments traded on the
Buenos Aires stock exchange (BYMA).  It supports two modes of obtaining USD
prices:

1. **Direct USD quotes** – For instruments that trade directly in dollars (tickers
   ending with a ``D``), the script scrapes the Docta Capital dashboard or other
   defined sources to obtain the latest quoted price in USD.
2. **ARS‐to‐USD conversion** – Many instruments also have a peso‐denominated
   version (the same ticker without the trailing ``D``).  For these tickers, the
   script can fetch the latest price in pesos from the Rava Bursátil website and
   convert it to USD by dividing by the closing value of the ``Dólar MEP`` (a
   widely used dollar exchange rate in Argentina).  If an ARS version is
   available, this conversion is generally more reliable than scraping the USD
   quote directly.

During initialisation below you will find:

* ``TICKER_SOURCES`` – For tickers that must be scraped directly in USD.
* ``CUSTOM_SOURCES`` – Custom sources/regexes for instruments not covered by
  Docta.
* ``ARS_TICKER_MAP`` – Mapping from dollar‐denominated tickers to their
  peso‐denominated counterparts.  When a ticker appears in this map, the
  script will fetch its ARS price and convert it using the Dólar MEP rate
  obtained from Rava.  If a ticker is not present, the script falls back to
  ``TICKER_SOURCES``/``CUSTOM_SOURCES``.
"""
# Mapping of tickers that must be scraped directly in USD (typically via Docta).
# If a ticker requires a different source, specify ``None`` here and provide a
# custom URL/regex in ``CUSTOM_SOURCES`` below.  Tickers not included here
# default to using their ARS counterpart via ``ARS_TICKER_MAP``.
TICKER_SOURCES = {
    "AE38D": "HARD_DOLLAR",
    "AL29D": "HARD_DOLLAR",
    "AL30D": "HARD_DOLLAR",
    "AL35D": "HARD_DOLLAR",
    "AN29D": "HARD_DOLLAR",
    "GD30D": "HARD_DOLLAR",
    "YM40D": "HARD_DOLLAR",
    "YMCID": "HARD_DOLLAR",
    "BA7DD": "SUB_SOBERANO",
    "MSFTD": "CEDEAR",
    "NUD": "CEDEAR",
    "NVDAD": "CEDEAR",
    "SPYD": "CEDEAR",
    "BRKBD": "CEDEAR",
    "DIAD": "CEDEAR",
    "LLYD": "CEDEAR",
    "MELID": "CEDEAR",
    "METAD": "CEDEAR",
    "MSTRD": "CEDEAR",
    "NFLXD": "CEDEAR",
    # Tickers below have no ARS counterpart or require an alternate source
    "GOOGLD": None,
    "IBITD": None,
    "YPFDD": None,
}

# Mapping of USD tickers to their peso‐denominated equivalents on Rava.  When a
# ticker appears in this mapping, the script will fetch the ARS price from
# Rava, fetch the Dólar MEP rate, and divide the two to derive the USD quote.
ARS_TICKER_MAP = {
    "AE38D": "AE38",
    "AL29D": "AL29",
    "AL30D": "AL30",
    "AL35D": "AL35",
    "AN29D": "AN29",
    "GD30D": "GD30",
    "MSFTD": "MSFT",
    "NUD": "NU",
    "NVDAD": "NVDA",
    "BRKBD": "BRKB",
    "DIAD": "DIA",
    "LLYD": "LLY",
    "MELID": "MELI",
    "METAD": "META",
    "MSTRD": "MSTR",
    "NFLXD": "NFLX",
    "SPYD": "SPY",
    "GOOGLD": "GOOGL",
    "IBITD": "IBIT",
    # YPFDD uses YPFD as ARS version
    "YPFDD": "YPFD",
}

# Custom URLs for tickers that need a different source.  The value should be a tuple of (url, regex)
CUSTOM_SOURCES = {
    # The InvertirOnline pages for GOGLD and IBITD include the ticker slug in the path; the pages
    # below reflect the endpoints observed during research.  If they change, update accordingly.
    "GOOGLD": (
        "https://iol.invertironline.com/titulo/cotizacion/BCBA/GOGLD/CEDEAR-GOOGLE-INC.",
        r"Último\s+Operado\s+US\$\s*([0-9.,]+)"  # capture number after "Último Operado US$"
    ),
    "IBITD": (
        "https://iol.invertironline.com/titulo/cotizacion/BCBA/IBITD/CEDEAR-ISHARES-BITCOIN-TR/",
        r"Último\s+Operado\s+US\$\s*([0-9.,]+)"
    ),
    # Rava page for YPFDD shows the price prominently at the top of the page
    "YPFDD": (
        "https://www.rava.com/perfil/YPFDD",
        r"#\s*YPFDD\s+YPF\s+SOCIEDAD\s*\n\s*([0-9.,]+)"  # first numeric price on page
    ),
}


def parse_price_from_docta(html: str) -> float:
    """Extract the latest USD price from a Docta instrument page.

    The Docta pages contain a section with heading 'Último Precio' followed by a value like
    'USD 63,90'.  This function searches for that pattern and returns the numeric value.
    """
    soup = BeautifulSoup(html, "html.parser")
    # Search for the label 'Último Precio'
    labels = soup.find_all(text=re.compile("Último Precio"))
    for label in labels:
        # Look for the next element that contains the price (e.g., a sibling span)
        parent = label.parent
        # find the next element that includes 'USD'
        price_text = None
        # search in next few siblings
        for sibling in parent.next_elements:
            text = getattr(sibling, 'text', '') or ''
            if 'USD' in text:
                price_text = text
                break
        if price_text:
            # Extract number (comma as decimal separator)
            match = re.search(r"USD\s*([0-9.,]+)", price_text)
            if match:
                # Replace comma with dot and remove thousands separators
                number_str = match.group(1).replace(".", "").replace(",", ".")
                try:
                    return float(number_str)
                except ValueError:
                    pass
    # Fallback: try to find any number prefaced by USD in the whole page
    match = re.search(r"USD\s*([0-9.,]+)", html)
    if match:
        number_str = match.group(1).replace(".", "").replace(",", ".")
        return float(number_str)
    raise ValueError("No price found on Docta page")


def parse_custom_price(html: str, pattern: str) -> float:
    """Parse price from custom source page using provided regex pattern."""
    match = re.search(pattern, html)
    if not match:
        raise ValueError("Price pattern not found in custom page")
    number_str = match.group(1).replace(".", "").replace(",", ".")
    return float(number_str)


def fetch_price(ticker: str) -> float:
    """Fetch the USD closing price for a given ticker.

    The resolution order is as follows:

    1. If the ticker has a peso counterpart (``ARS_TICKER_MAP``), fetch the ARS
       price from Rava, obtain the latest Dólar MEP rate, and convert.
    2. Otherwise, if ``TICKER_SOURCES[ticker]`` is not ``None``, scrape the
       Docta Capital dashboard for a direct USD quote.
    3. If the ticker appears in ``CUSTOM_SOURCES``, scrape the specified page
       using the provided regex pattern.
    4. If none of the above apply, raise an error.
    """
    # Case 1: use ARS conversion if available
    if ticker in ARS_TICKER_MAP:
        ars_ticker = ARS_TICKER_MAP[ticker]
        try:
            ars_price = fetch_rava_price(ars_ticker)
            mep_rate = fetch_mep_price()
            return ars_price / mep_rate
        except Exception as e:
            # If ARS conversion fails, fall back to direct source (if available)
            pass
    # Case 2: direct USD quote via Docta
    source_category = TICKER_SOURCES.get(ticker)
    if source_category:
        url = f"https://app.doctacapital.com.ar/dashboard/market/{source_category}/ticker/{ticker}"
        resp = requests.get(url)
        resp.raise_for_status()
        return parse_price_from_docta(resp.text)
    # Case 3: custom source
    if ticker in CUSTOM_SOURCES:
        url, pattern = CUSTOM_SOURCES[ticker]
        resp = requests.get(url)
        resp.raise_for_status()
        return parse_custom_price(resp.text, pattern)
    raise ValueError(f"No source defined for ticker {ticker}")


def fetch_rava_price(ars_ticker: str) -> float:
    """Fetch the latest price in pesos from the Rava Bursátil page for a given ticker.

    The Rava profile pages display the current price prominently near the top.  We
    locate the first occurrence of a number with thousands separators and a
    comma as the decimal separator (e.g., ``32.580,00``) and convert it to a
    floating‐point value.
    """
    url = f"https://www.rava.com/perfil/{ars_ticker}"
    resp = requests.get(url)
    resp.raise_for_status()
    html = resp.text
    # Look for the first occurrence of a formatted number (e.g. 32.580,00)
    match = re.search(r"([0-9]{1,3}(?:\.[0-9]{3})*,[0-9]{2})", html)
    if not match:
        raise ValueError(f"No price found on Rava page for {ars_ticker}")
    number_str = match.group(1)
    # Remove thousands separators (.) and replace comma with decimal point
    number_str = number_str.replace(".", "").replace(",", ".")
    return float(number_str)


def fetch_mep_price() -> float:
    """Fetch the latest Dólar MEP rate from Rava Bursátil.

    The Dólar MEP page displays the current exchange rate.  We parse the first
    formatted number on the page and convert it to a float.
    """
    url = "https://www.rava.com/perfil/DOLAR MEP"
    resp = requests.get(url)
    resp.raise_for_status()
    html = resp.text
    match = re.search(r"([0-9]{1,3}(?:\.[0-9]{3})*,[0-9]{2})", html)
    if not match:
        raise ValueError("No MEP rate found on Rava page")
    number_str = match.group(1).replace(".", "").replace(",", ".")
    return float(number_str)


def fetch_all_prices() -> pd.DataFrame:
    """Fetch closing prices for all tickers and return a DataFrame."""
    data = []
    for ticker in TICKER_SOURCES.keys():
        try:
            price = fetch_price(ticker)
            data.append({"Ticker": ticker, "Price_USD": price, "Timestamp": datetime.datetime.now(pytz.timezone('America/Argentina/Buenos_Aires'))})
        except Exception as e:
            data.append({"Ticker": ticker, "Price_USD": None, "Error": str(e)})
    return pd.DataFrame(data)


def job():
    """Scheduled job to fetch prices and save them to a CSV file."""
    df = fetch_all_prices()
    # Save to CSV with date stamp
    date_str = datetime.datetime.now(pytz.timezone('America/Argentina/Buenos_Aires')).strftime('%Y-%m-%d')
    filename = f"closing_prices_{date_str}.csv"
    df.to_csv(filename, index=False)
    print(f"Saved closing prices to {filename}")


if __name__ == "__main__":
    # Schedule the job to run daily at 17:00 Argentina time
    schedule.every().day.at("17:00").do(job)

    print("Scheduler initialized. Waiting for scheduled tasks...")
    while True:
        schedule.run_pending()
        time.sleep(60)
