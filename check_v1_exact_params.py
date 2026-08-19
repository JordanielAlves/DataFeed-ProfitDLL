import time
import threading
import struct
from ctypes import *
from datetime import datetime
from config import DLL_PATH, PROFIT

dll = WinDLL(DLL_PATH)

class TAssetID(Structure):
    _fields_ = [("ticker", c_wchar_p), ("bolsa", c_wchar_p), ("feed", c_int)]

connected_event = threading.Event()
count = 0

@WINFUNCTYPE(None, c_void_p, c_void_p, c_void_p, c_void_p, c_void_p, c_void_p, c_void_p, c_void_p)
def cb_raw(arg1, arg2, arg3, arg4, arg5, arg6, arg7, arg8):
    global count
    count += 1
    if count <= 5:
        ticker = cast(arg1, POINTER(TAssetID)).contents.ticker
        dt_str = cast(arg2, c_wchar_p).value
        t_num = arg3 & 0xFFFFFFFF
        
        d4 = struct.unpack('<d', struct.pack('<Q', arg4 or 0))[0]
        u4 = arg4 & 0xFFFFFFFF
        
        d5 = struct.unpack('<d', struct.pack('<Q', arg5 or 0))[0]
        u6 = arg6 & 0xFFFFFFFF
        u7 = arg7 & 0xFFFFFFFF
        u8 = arg8 & 0xFFFFFFFF
        
        # Calcular preço a partir de volume/quantidade se arg5 for vol e u6 for qtd
        calc_price = (d5 / u6) if u6 > 0 else 0
        
        print(f"[{ticker}] Data='{dt_str}' TradeNum={t_num} | arg4={u4}(double={d4:.2f}) | Vol(arg5)={d5:.2f} | Qtd(arg6)={u6} | CalcPrice={calc_price:.2f} | arg7={u7} | arg8={u8}")

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
    cb_state, None, None, None, cb_raw,
    None, None, None, None, None, None
)

connected_event.wait(timeout=10)
dll.SubscribeTicker(c_wchar_p("WDOQ26"), c_wchar_p("F"))
time.sleep(3)
dll.DLLFinalize()
