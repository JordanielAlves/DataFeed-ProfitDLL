import time
import threading
from ctypes import *
from datetime import datetime
from config import DLL_PATH, PROFIT

dll = WinDLL(DLL_PATH)

# Estruturas V1
class TAssetID(Structure):
    _fields_ = [("ticker", c_wchar_p), ("bolsa", c_wchar_p), ("feed", c_int)]

# Estruturas V2
class TConnectorAssetIdentifier(Structure):
    _fields_ = [("Version", c_ubyte), ("Ticker", c_wchar_p), ("Exchange", c_wchar_p), ("FeedType", c_ubyte)]

class SystemTime(Structure):
    _fields_ = [
        ("wYear", c_ushort), ("wMonth", c_ushort), ("wDayOfWeek", c_ushort), ("wDay", c_ushort),
        ("wHour", c_ushort), ("wMinute", c_ushort), ("wSecond", c_ushort), ("wMilliseconds", c_ushort)
    ]

class TConnectorTrade(Structure):
    _fields_ = [
        ("Version", c_ubyte), ("TradeDate", SystemTime), ("TradeNumber", c_uint),
        ("Price", c_double), ("Quantity", c_longlong), ("Volume", c_double),
        ("BuyAgent", c_int), ("SellAgent", c_int), ("TradeType", c_ubyte)
    ]

trade_v1_count = 0
trade_v2_count = 0
book_v1_count = 0
book_v2_count = 0
daily_count = 0

connected_event = threading.Event()

@WINFUNCTYPE(None, TConnectorAssetIdentifier, c_size_t, c_uint)
def cb_trade_v2(assetId, pTrade, flags):
    global trade_v2_count
    trade_v2_count += 1
    if trade_v2_count <= 5:
        trade_struct = TConnectorTrade(Version=0)
        dll.TranslateTrade(pTrade, byref(trade_struct))
        print(f"[V2 TRADE] {assetId.Ticker} Preço={trade_struct.Price} Qtd={trade_struct.Quantity} Tipo={trade_struct.TradeType}")

@WINFUNCTYPE(None, TAssetID, c_double, c_int, c_int, c_double, c_int, c_int, c_int)
def cb_trade_v1_8args(assetId, price, qtd, side, vol, buy_agent, sell_agent, trade_type):
    global trade_v1_count
    trade_v1_count += 1
    if trade_v1_count <= 5:
        print(f"[V1 TRADE (8 args)] {assetId.ticker} Preço={price} Qtd={qtd} Lado={side}")

@WINFUNCTYPE(None,
             TAssetID, c_int, c_int, c_int, c_int, c_int,
             c_longlong, c_double,
             c_int, c_int, c_int, c_int, c_int,
             c_wchar_p, POINTER(c_ubyte), POINTER(c_ubyte))
def cb_book_v2(assetId, nAction, nPosition, side, nQtd, nAgent,
               nOfferID, sPrice, bHasPrice, bHasQtd, bHasDate, bHasOfferID, bHasAgent,
               date, pArraySell, pArrayBuy):
    global book_v2_count
    book_v2_count += 1
    if book_v2_count <= 3:
        print(f"[V2 BOOK] {assetId.ticker} Preço={sPrice} Qtd={nQtd} Ação={nAction}")

@WINFUNCTYPE(None, TAssetID, c_wchar_p, c_double, c_double, c_double, c_double, c_double, c_double, c_double, c_double, c_double, c_double, c_double, c_double)
def cb_daily(assetId, date, open_, high, low, close, vol, qty_buyer, qty_seller, neg_buyer, neg_seller, vol_buyer, vol_seller, contracts_open):
    global daily_count
    daily_count += 1
    if daily_count <= 3:
        print(f"[DAILY] {assetId.ticker} Close={close} Vol={vol}")

@WINFUNCTYPE(None, c_int, c_int)
def cb_state(state_type, result):
    print(f"[STATE] Type={state_type} Result={result}")
    if state_type == 2 and result == 4: # MARKET_DATA_READY
        connected_event.set()

dll.SetTradeCallbackV2(cb_trade_v2)
dll.SetOfferBookCallbackV2(cb_book_v2)
dll.SetDailyCallback(cb_daily)

dll.DLLInitializeLogin.argtypes = [
    c_wchar_p, c_wchar_p, c_wchar_p,
    c_void_p, c_void_p, c_void_p, c_void_p, c_void_p,
    c_void_p, c_void_p, c_void_p, c_void_p, c_void_p, c_void_p
]
dll.DLLInitializeLogin.restype = c_int

print("Conectando...")
res = dll.DLLInitializeLogin(
    c_wchar_p(PROFIT["key"]), c_wchar_p(PROFIT["user"]), c_wchar_p(PROFIT["password"]),
    cb_state, None, None, None, cb_trade_v1_8args,
    cb_daily, cb_book_v2, None, None, None, None
)
print(f"Resultado login: {res}")

print("Aguardando MARKET_DATA_READY (Type=2 Result=4)...")
if not connected_event.wait(timeout=15):
    print("Timeout esperando MARKET_DATA_READY!")

tickers = ["WDOQ26", "WDON26", "WDOFUT", "DOLPRO", "DOLQ26"]
for t in tickers:
    dll.SubscribeTicker(c_wchar_p(t), c_wchar_p("F"))
    dll.SubscribeOfferBook(c_wchar_p(t), c_wchar_p("F"))
    print(f"Inscrito em {t} (F)")

print("Aguardando dados por 10 segundos...")
for i in range(10):
    time.sleep(1)
    if trade_v2_count > 0 or book_v2_count > 0 or trade_v1_count > 0:
        print(f"  [{i+1}s] Trades V1={trade_v1_count}, V2={trade_v2_count}, Book V2={book_v2_count}, Daily={daily_count}")

print(f"\nRESULTADO FINAL:")
print(f"  Trades V1: {trade_v1_count}")
print(f"  Trades V2: {trade_v2_count}")
print(f"  Book V2:   {book_v2_count}")
print(f"  Daily:     {daily_count}")
dll.DLLFinalize()
