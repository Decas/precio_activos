import requests
from bs4 import BeautifulSoup
import re
import datetime
import pytz
import pandas as pd


BOND_USD_TICKERS = [
    "AE38D",
    "AL29D",
    "AL30D",
    "AL35D",
    "AN29D",
    "BA7DD",
    "GD30D",
    "YM40D",
    "YMCID",
]


ARS_TO_USD_TICKERS = [
    "BRKB",
    "BYMA",
    "DIA",
    "GOOGL",
    "IBIT",
    "LLY",
    "MELI",
    "META",
    "MSFT",
    "MSTR",
    "NFLX",
    "NU",
    "NVDA",
    "SPY",
    "YPFD",
]


BOND_USD_SOURCES = {
    "AE38D": "https://app.doctacapital.com.ar/dashboard/market/HARD_DOLLAR/ticker/AE38D",
    "AL29D": "https://app.doctacapital.com.ar/dashboard/market/HARD_DOLLAR/ticker/AL29D",
    "AL30D": "https://app.doctacapital.com.ar/dashboard/market/HARD_DOLLAR/ticker/AL30D",
    "AL35D": "https://app.doctacapital.com.ar/dashboard/market/HARD_DOLLAR/ticker/AL35D",
    "AN29D": "https://app.doctacapital.com.ar/dashboard/market/HARD_DOLLAR/ticker/AN29D",
    "BA7DD": "https://app.doctacapital.com.ar/dashboard/market/SUB_SOBERANO/ticker/BA7DD",
    "GD30D": "https://app.doctacapital.com.ar/dashboard/market/HARD_DOLLAR/ticker/GD30D",
    "YM40D": "https://app.doctacapital.com.ar/dashboard/market/HARD_DOLLAR/ticker/YM40D",
    "YMCID": "https://app.doctacapital.com.ar/dashboard/market/HARD_DOLLAR/ticker/YMCID",
}


HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"
}


PRICE_RE = re.compile(r"^\d{1,3}(?:\.\d{3})*,\d{2}$|^\d+,\d{2}$")


def parse_argentine_number(text):
    clean = str(text).strip().replace("\xa0", " ").replace(".", "").replace(",", ".")
    return float(clean)


def fetch_html(url):
    response = requests.get(url, headers=HEADERS, timeout=30)
    response.raise_for_status()
    return response.text


def get_visible_lines(html):
    soup = BeautifulSoup(html, "html.parser")

    for tag in soup(["script", "style", "noscript", "title", "meta", "svg"]):
        tag.decompose()

    return [
        line.strip().replace("\xa0", " ")
        for line in soup.get_text("\n").splitlines()
        if line.strip()
    ]


def is_clean_price_line(line):
    line = line.strip().replace("\xa0", " ")

    if "%" in line:
        return False

    if "/" in line or ":" in line:
        return False

    if "$" in line or "USD" in line:
        return False

    return bool(PRICE_RE.match(line))


def extract_rava_main_price(html, ticker):
    lines = get_visible_lines(html)
    ticker_upper = ticker.upper()

    for i, line in enumerate(lines):
        line_upper = line.upper()

        ticker_header_found = (
            line_upper == ticker_upper
            or line_upper.startswith("#  " + ticker_upper + " ")
            or line_upper.startswith(ticker_upper + " ")
        )

        if not ticker_header_found:
            continue

        nearby = lines[i + 1:i + 12]

        for candidate in nearby:
            if is_clean_price_line(candidate):
                price = parse_argentine_number(candidate)

                if price > 0:
                    return price, candidate

    raise ValueError(f"No se encontró precio principal en Rava para {ticker}")


def fetch_rava_price_ars(ticker):
    url = f"https://www.rava.com/perfil/{ticker}"
    html = fetch_html(url)
    price, raw_text = extract_rava_main_price(html, ticker)

    return price, raw_text, url


def fetch_mep_price():
    url = "https://www.rava.com/perfil/DOLAR%20MEP"
    html = fetch_html(url)
    price, raw_text = extract_rava_main_price(html, "DOLAR MEP")

    if price < 500:
        raise ValueError(f"Dólar MEP sospechosamente bajo: {price} desde texto '{raw_text}'")

    return price, raw_text, url


def extract_usd_price_from_docta(html):
    lines = get_visible_lines(html)

    for i, line in enumerate(lines):
        if "Último Precio" in line or "Ú. Precio" in line:
            nearby_text = " ".join(lines[i:i + 5]).replace("\xa0", " ")
            match = re.search(r"USD\s*([0-9]{1,3}(?:\.[0-9]{3})*,[0-9]{2}|[0-9]+,[0-9]{2})", nearby_text)

            if match:
                return parse_argentine_number(match.group(1)), match.group(1)

    text = " ".join(lines).replace("\xa0", " ")
    match = re.search(r"Ú\. Precio:\s+USD\s*([0-9]{1,3}(?:\.[0-9]{3})*,[0-9]{2}|[0-9]+,[0-9]{2})", text)

    if match:
        return parse_argentine_number(match.group(1)), match.group(1)

    raise ValueError("No se encontró precio USD en Docta")


def fetch_bond_price_usd(ticker):
    if ticker not in BOND_USD_SOURCES:
        raise ValueError(f"No hay fuente directa definida para el bono {ticker}")

    url = BOND_USD_SOURCES[ticker]
    html = fetch_html(url)
    usd_price, raw_price_text = extract_usd_price_from_docta(html)

    return {
        "ticker": ticker,
        "asset_type": "BONO",
        "source_ticker": ticker,
        "price_ars": "",
        "mep_price": "",
        "price_usd": round(usd_price, 6),
        "raw_price_text": raw_price_text,
        "source_url": url,
        "method": "Direct USD",
        "status": "OK",
        "error": "",
    }


def validate_ars_asset_price(ticker, ars_price, mep_price, usd_price, raw_price_text):
    # 1. Lista de acciones locales que pueden valer menos de $1000 ARS
    activos_locales = ["BYMA", "YPFD"]
    
    if ticker in activos_locales:
        if ars_price < 10:
            raise ValueError(
                f"Precio ARS sospechosamente bajo para acción local {ticker}: {ars_price} "
                f"desde texto '{raw_price_text}'"
            )
        return  # Sale de la función y no evalúa la regla del USD ni de los $1000

    # 2. Reglas estándar para CEDEARs
    if ars_price < 1000:
        raise ValueError(
            f"Precio ARS sospechosamente bajo para {ticker}: {ars_price} "
            f"desde texto '{raw_price_text}'"
        )

    if usd_price < 1:
        raise ValueError(
            f"Precio USD sospechosamente bajo para {ticker}: {usd_price} "
            f"(ARS {ars_price} / MEP {mep_price}, texto '{raw_price_text}')"
        )


def fetch_ars_asset_price_usd(ticker, mep_price):
    ars_price, raw_price_text, url = fetch_rava_price_ars(ticker)
    usd_price = ars_price / mep_price

    validate_ars_asset_price(ticker, ars_price, mep_price, usd_price, raw_price_text)

    return {
        "ticker": ticker,
        "asset_type": "CEDEAR/ACCION",
        "source_ticker": ticker,
        "price_ars": round(ars_price, 6),
        "mep_price": round(mep_price, 6),
        "price_usd": round(usd_price, 6),
        "raw_price_text": raw_price_text,
        "source_url": url,
        "method": "ARS / MEP",
        "status": "OK",
        "error": "",
    }


def error_row(ticker, asset_type, method, error, timestamp, mep_price="", source_url=""):
    return {
        "ticker": ticker,
        "asset_type": asset_type,
        "source_ticker": ticker,
        "price_ars": "",
        "mep_price": mep_price,
        "price_usd": "",
        "raw_price_text": "",
        "source_url": source_url,  # Ahora se registra la URL en el Excel si hay error
        "method": method,
        "status": "ERROR",
        "error": str(error),
        "timestamp_argentina": timestamp,
    }


def fetch_all_prices():
    argentina_tz = pytz.timezone("America/Argentina/Buenos_Aires")
    timestamp = datetime.datetime.now(argentina_tz).strftime("%Y-%m-%d %H:%M:%S")

    rows = []

    try:
        mep_price, mep_raw_text, mep_url = fetch_mep_price()
        print(f"MEP OK: {mep_price} desde '{mep_raw_text}'")
    except Exception as e:
        mep_price = None
        mep_error = str(e)
        print(f"MEP ERROR: {mep_error}")
    else:
        mep_error = ""

    for ticker in BOND_USD_TICKERS:
        try:
            result = fetch_bond_price_usd(ticker)
            result["timestamp_argentina"] = timestamp
            rows.append(result)
            print(f"{ticker} OK: USD {result['price_usd']} desde '{result['raw_price_text']}'")
        except Exception as e:
            url = BOND_USD_SOURCES.get(ticker, "")
            rows.append(error_row(ticker, "BONO", "Direct USD", e, timestamp, source_url=url))

    for ticker in ARS_TO_USD_TICKERS:
        try:
            if mep_price is None:
                raise ValueError(f"No se pudo obtener dólar MEP: {mep_error}")

            result = fetch_ars_asset_price_usd(ticker, mep_price)
            result["timestamp_argentina"] = timestamp
            rows.append(result)
            print(
                f"{ticker} OK: ARS {result['price_ars']} / MEP {result['mep_price']} "
                f"= USD {result['price_usd']} desde '{result['raw_price_text']}'"
            )
        except Exception as e:
            url = f"https://www.rava.com/perfil/{ticker}"
            rows.append(error_row(
                ticker,
                "CEDEAR/ACCION",
                "ARS / MEP",
                e,
                timestamp,
                mep_price if mep_price is not None else "",
                source_url=url
            ))
            print(f"{ticker} ERROR: {e}")

    return pd.DataFrame(rows)


def job():
    df = fetch_all_prices()
    filename = "closing_prices.csv"
    df.to_csv(filename, index=False)
    print(f"Saved closing prices to {filename}")


if __name__ == "__main__":
    job()
