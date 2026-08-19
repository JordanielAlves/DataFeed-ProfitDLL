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
    if count <= 6:
        asset = cast(arg1, POINTER(TAssetID)).contents.ticker
        # arg2 como string ansi (char*)
        try:
            dt_str = cast(arg2, c_char_p).value.decode('latin-1')
        except Exception:
            dt_str = str(arg2)
        
        # arg3 é uint ou double?
        u3 = arg3 & 0xFFFFFFFF
        d3 = struct.unpack('<d', struct.pack('<Q', arg3 or 0))[0]
        
        # arg4 é uint ou double?
        u4 = arg4 & 0xFFFFFFFF
        d4 = struct.unpack('<d', struct.pack('<Q', arg4 or 0))[0]
        
        # arg5 é double?
        d5 = struct.unpack('<d', struct.pack('<Q', arg5 or 0))[0]
        
        # arg6 é int ou double?
        u6 = arg6 & 0xFFFFFFFF
        d6 = struct.unpack('<d', struct.pack('<Q', arg6 or 0))[0]
        
        # arg7 e arg8 como ints
        u7 = arg7 & 0xFFFFFFFF
        u8 = arg8 & 0xFFFFFFFF
        
        print(f"[{asset}] Date='{dt_str}' | arg3(u={u3}, d={d3:.2f}) | arg4(u={u4}, d={d4:.2f}) | arg5(d={d5:.2f}) | arg6(u={u6}, d={d6:.2f}) | arg7={u7} | arg8={u8}")

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
