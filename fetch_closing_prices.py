import requests
import re
import datetime
import pytz
import pandas as pd


TICKERS = [
    "AE38D",
    "AL29D",
    "AL30D",
    "AL35D",
    "AN29D",
    "BA7DD",
    "BRKBD",
    "DIAD",
    "GD30D",
    "GOOGLD",
    "IBITD",
    "LLYD",
    "MELID",
    "METAD",
    "MSFTD",
    "MSTRD",
    "NFLXD",
    "NUD",
    "NVDAD",
    "SPYD",
    "YM40D",
    "YMCID",
    "YPFDD",
]


ARS_TICKER_MAP = {
    "AE38D": "AE38",
    "AL29D": "AL29",
    "AL30D": "AL30",
    "AL35D": "AL35",
    "AN29D": "AN29",
    "BA7DD": "BA37D",
    "BRKBD": "BRKB",
    "DIAD": "DIA",
    "GD30D": "GD30",
    "GOOGLD": "GOOGL",
    "IBITD": "IBIT",
    "LLYD": "LLY",
    "MELID": "MELI",
    "METAD": "META",
    "MSFTD": "MSFT",
    "MSTRD": "MSTR",
    "NFLXD": "NFLX",
    "NUD": "NU",
    "NVDAD": "NVDA",
    "SPYD": "SPY",
    "YM40D": "YM40O",
    "YMCID": "YMCIO",
    "YPFDD": "YPFD",
}


HEADERS = {
    "User-Agent": "Mozilla/5.0"
}


def parse_argentine_number(text):
    clean = text.strip().replace(".", "").replace(",", ".")
    return float(clean)


def fetch_html(url):
    response = requests.get(url, headers=HEADERS, timeout=30)
    response.raise_for_status()
    return response.text


def extract_first_price_from_rava(html):
    match = re.search(r"([0-9]{1,3}(?:\.[0-9]{3})*,[0-9]{2})", html)
    if not match:
        raise ValueError("No se encontró precio en la página de Rava")
    return parse_argentine_number(match.group(1))


def fetch_rava_price(ticker):
    url = f"https://www.rava.com/perfil/{ticker}"
    html = fetch_html(url)
    return extract_first_price_from_rava(html)


def fetch_mep_price():
    url = "https://www.rava.com/perfil/DOLAR MEP"
    html = fetch_html(url)
    return extract_first_price_from_rava(html)


def fetch_price_usd(ticker, mep_price):
    if ticker not in ARS_TICKER_MAP:
        raise ValueError(f"No hay equivalencia en pesos definida para {ticker}")

    ars_ticker = ARS_TICKER_MAP[ticker]
    ars_price = fetch_rava_price(ars_ticker)
    usd_price = ars_price / mep_price

    return {
        "ticker": ticker,
        "source_ticker": ars_ticker,
        "price_ars": ars_price,
        "mep_price": mep_price,
        "price_usd": usd_price,
        "method": "ARS / MEP",
        "status": "OK",
        "error": "",
    }


def fetch_all_prices():
    argentina_tz = pytz.timezone("America/Argentina/Buenos_Aires")
    timestamp = datetime.datetime.now(argentina_tz).strftime("%Y-%m-%d %H:%M:%S")

    rows = []

    try:
        mep_price = fetch_mep_price()
    except Exception as e:
        mep_price = None
        mep_error = str(e)
    else:
        mep_error = ""

    for ticker in TICKERS:
        try:
            if mep_price is None:
                raise ValueError(f"No se pudo obtener dólar MEP: {mep_error}")

            result = fetch_price_usd(ticker, mep_price)
            result["timestamp_argentina"] = timestamp
            rows.append(result)

        except Exception as e:
            rows.append({
                "ticker": ticker,
                "source_ticker": ARS_TICKER_MAP.get(ticker, ticker),
                "price_ars": "",
                "mep_price": mep_price if mep_price is not None else "",
                "price_usd": "",
                "method": "",
                "status": "ERROR",
                "error": str(e),
                "timestamp_argentina": timestamp,
            })

    return pd.DataFrame(rows)


def job():
    df = fetch_all_prices()
    filename = "closing_prices.csv"
    df.to_csv(filename, index=False)
    print(f"Saved closing prices to {filename}")


if __name__ == "__main__":
    job()
