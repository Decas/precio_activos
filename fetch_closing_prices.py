import requests
from bs4 import BeautifulSoup
import re
import datetime
import pytz
import pandas as pd


# Bonos: se buscan directamente en dólares.
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


# CEDEARs y acciones: se buscan en pesos y se dividen por dólar MEP.
ARS_TO_USD_TICKERS = [
    "BRKB",
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


# Fuente directa en dólares para bonos.
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
    "User-Agent": "Mozilla/5.0"
}


def parse_argentine_number(text):
    """
    Convierte números con formato argentino:
    '1.423,81' -> 1423.81
    '90.850,00' -> 90850.00
    '63,90' -> 63.90
    """
    clean = text.strip().replace(".", "").replace(",", ".")
    return float(clean)


def fetch_html(url):
    response = requests.get(url, headers=HEADERS, timeout=30)
    response.raise_for_status()
    return response.text


def extract_first_price_from_rava(html):
    """
    Extrae el primer precio visible desde una página de Rava.
    Para CEDEARs y acciones suele coincidir con la cotización principal en pesos.
    """
    match = re.search(r"([0-9]{1,3}(?:\.[0-9]{3})*,[0-9]{2})", html)
    if not match:
        raise ValueError("No se encontró precio en la página de Rava")
    return parse_argentine_number(match.group(1))


def fetch_rava_price_ars(ticker):
    """
    Obtiene el precio en pesos de un CEDEAR, acción o ETF desde Rava.
    """
    url = f"https://www.rava.com/perfil/{ticker}"
    html = fetch_html(url)
    return extract_first_price_from_rava(html)


def fetch_mep_price():
    """
    Obtiene el valor del dólar MEP desde Rava.
    """
    url = "https://www.rava.com/perfil/DOLAR MEP"
    html = fetch_html(url)
    return extract_first_price_from_rava(html)


def extract_usd_price_from_docta(html):
    """
    Extrae el precio en dólares desde una página de Docta Capital.
    Busca expresiones como:
    'Último Precio USD 63,90'
    'Ú. Precio: USD 63,90'
    """
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(" ", strip=True)

    patterns = [
        r"Último Precio\s+USD\s*([0-9.,]+)",
        r"Ú\. Precio:\s+USD\s*([0-9.,]+)",
        r"USD\s*([0-9.,]+)",
    ]

    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return parse_argentine_number(match.group(1))

    raise ValueError("No se encontró precio USD en Docta")


def fetch_bond_price_usd(ticker):
    """
    Obtiene la cotización directa en dólares de un bono.
    No divide por MEP.
    """
    if ticker not in BOND_USD_SOURCES:
        raise ValueError(f"No hay fuente directa definida para el bono {ticker}")

    url = BOND_USD_SOURCES[ticker]
    html = fetch_html(url)
    usd_price = extract_usd_price_from_docta(html)

    return {
        "ticker": ticker,
        "asset_type": "BONO",
        "source_ticker": ticker,
        "price_ars": "",
        "mep_price": "",
        "price_usd": usd_price,
        "method": "Direct USD",
        "status": "OK",
        "error": "",
    }


def fetch_ars_asset_price_usd(ticker, mep_price):
    """
    Obtiene el precio en pesos y lo convierte a dólares usando dólar MEP.
    """
    ars_price = fetch_rava_price_ars(ticker)
    usd_price = ars_price / mep_price

    return {
        "ticker": ticker,
        "asset_type": "CEDEAR/ACCION",
        "source_ticker": ticker,
        "price_ars": ars_price,
        "mep_price": mep_price,
        "price_usd": usd_price,
        "method": "ARS / MEP",
        "status": "OK",
        "error": "",
    }


def fetch_all_prices():
    """
    Obtiene todos los precios y devuelve una tabla.
    """
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

    # Primero bonos: cotización directa en dólares.
    for ticker in BOND_USD_TICKERS:
        try:
            result = fetch_bond_price_usd(ticker)
            result["timestamp_argentina"] = timestamp
            rows.append(result)

        except Exception as e:
            rows.append({
                "ticker": ticker,
                "asset_type": "BONO",
                "source_ticker": ticker,
                "price_ars": "",
                "mep_price": "",
                "price_usd": "",
                "method": "Direct USD",
                "status": "ERROR",
                "error": str(e),
                "timestamp_argentina": timestamp,
            })

    # Luego CEDEARs/acciones: precio en pesos dividido por MEP.
    for ticker in ARS_TO_USD_TICKERS:
        try:
            if mep_price is None:
                raise ValueError(f"No se pudo obtener dólar MEP: {mep_error}")

            result = fetch_ars_asset_price_usd(ticker, mep_price)
            result["timestamp_argentina"] = timestamp
            rows.append(result)

        except Exception as e:
            rows.append({
                "ticker": ticker,
                "asset_type": "CEDEAR/ACCION",
                "source_ticker": ticker,
                "price_ars": "",
                "mep_price": mep_price if mep_price is not None else "",
                "price_usd": "",
                "method": "ARS / MEP",
                "status": "ERROR",
                "error": str(e),
                "timestamp_argentina": timestamp,
            })

    return pd.DataFrame(rows)


def job():
    """
    Ejecuta la actualización y guarda siempre el mismo archivo.
    El archivo anterior queda reemplazado.
    """
    df = fetch_all_prices()
    filename = "closing_prices.csv"
    df.to_csv(filename, index=False)
    print(f"Saved closing prices to {filename}")


if __name__ == "__main__":
    job()
