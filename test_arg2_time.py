import time
import threading
from ctypes import *
from datetime import datetime
from config import DLL_PATH, PROFIT

dll = WinDLL(DLL_PATH)

class TAssetID(Structure):
    _fields_ = [("ticker", c_wchar_p), ("bolsa", c_wchar_p), ("feed", c_int)]

class SystemTime(Structure):
    _fields_ = [
        ("wYear", c_ushort), ("wMonth", c_ushort), ("wDayOfWeek", c_ushort), ("wDay", c_ushort),
        ("wHour", c_ushort), ("wMinute", c_ushort), ("wSecond", c_ushort), ("wMilliseconds", c_ushort)
    ]

connected_event = threading.Event()
count = 0

@WINFUNCTYPE(None, c_void_p, c_void_p, c_void_p, c_void_p, c_void_p, c_void_p, c_void_p, c_void_p)
def cb_test(arg1, arg2, arg3, arg4, arg5, arg6, arg7, arg8):
    global count
    count += 1
    if count <= 4:
        p_asset = cast(arg1, POINTER(TAssetID)).contents
        ticker = p_asset.ticker
        
        # Tentar ler arg2 como POINTER(SystemTime) ou string
        try:
            st = cast(arg2, POINTER(SystemTime)).contents
            dt_str = f"{st.wYear}-{st.wMonth:02d}-{st.wDay:02d} {st.wHour:02d}:{st.wMinute:02d}:{st.wSecond:02d}.{st.wMilliseconds:03d}"
        except Exception as e:
            dt_str = f"erro: {e}"
            
        print(f"[TRADE #{count}] {ticker} | Data={dt_str}")

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
