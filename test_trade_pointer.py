import time
import threading
from ctypes import *
from config import DLL_PATH, PROFIT

dll = WinDLL(DLL_PATH)

class TAssetID(Structure):
    _fields_ = [("ticker", c_wchar_p), ("bolsa", c_wchar_p), ("feed", c_int)]

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

dll.TranslateTrade.argtypes = [c_void_p, c_void_p]
dll.TranslateTrade.restype = c_int

connected_event = threading.Event()
count = 0

@WINFUNCTYPE(None, c_void_p, c_void_p, c_void_p, c_void_p, c_void_p, c_void_p, c_void_p, c_void_p)
def cb_test(arg1, arg2, arg3, arg4, arg5, arg6, arg7, arg8):
    global count
    count += 1
    if count <= 5:
        p_asset = cast(arg1, POINTER(TAssetID)).contents
        ticker = p_asset.ticker
        
        # Teste 1: TranslateTrade(arg2, byref(t1))
        t1 = TConnectorTrade(Version=0)
        res1 = dll.TranslateTrade(arg2, byref(t1))
        
        # Teste 2: ler diretamente TConnectorTrade do ponteiro arg2
        try:
            t2 = cast(arg2, POINTER(TConnectorTrade)).contents
            p2 = t2.Price
            q2 = t2.Quantity
            tt2 = t2.TradeType
        except Exception:
            p2, q2, tt2 = -1, -1, -1
            
        print(f"[TRADE #{count}] {ticker} | TranslateTrade(res={res1}): Price={t1.Price} Qtd={t1.Quantity} Vol={t1.Volume} Type={t1.TradeType} | DirectCast: Price={p2} Qtd={q2} Type={tt2}")

@WINFUNCTYPE(None, c_int, c_int)
def cb_state(state_type, result):
    if state_type == 2 and result == 4:
        connected_event.set()

dll.DLLInitializeLogin.argtypes = [
    c_wchar_p, c_wchar_p, c_wchar_p,
    c_void_p, c_void_p, c_void_p, c_void_p, c_void_p,
    c_void_p, c_void_p, c_void_p, c_void_p, c_void_p, c_void_p
]
dll.DLLInitializeLogin.restype = c_int

dll.DLLInitializeLogin(
    c_wchar_p(PROFIT["key"]), c_wchar_p(PROFIT["user"]), c_wchar_p(PROFIT["password"]),
    cb_state, None, None, None, cb_test,
    None, None, None, None, None, None
)

connected_event.wait(timeout=10)
dll.SubscribeTicker(c_wchar_p("WDOQ26"), c_wchar_p("F"))
time.sleep(3)
dll.DLLFinalize()
