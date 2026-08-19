import time
import threading
import struct
from ctypes import *
from config import DLL_PATH, PROFIT

dll = WinDLL(DLL_PATH)

class TAssetID(Structure):
    _fields_ = [("ticker", c_wchar_p), ("bolsa", c_wchar_p), ("feed", c_int)]

connected_event = threading.Event()
count = 0

# Vamos testar inspecionar os argumentos brutos de ponteiros / ints / doubles
@WINFUNCTYPE(None, c_void_p, c_void_p, c_void_p, c_void_p, c_void_p, c_void_p, c_void_p, c_void_p)
def cb_raw(arg1, arg2, arg3, arg4, arg5, arg6, arg7, arg8):
    global count
    count += 1
    if count <= 5:
        print(f"[RAW {count}] {arg1:#x} {arg2:#x} {arg3:#x} {arg4:#x} {arg5:#x} {arg6:#x} {arg7:#x} {arg8:#x}")
        # Tentar ler como TAssetID em arg1
        try:
            p = cast(arg1, POINTER(TAssetID)).contents
            print(f"  se arg1 é POINTER(TAssetID): ticker={p.ticker} bolsa={p.bolsa} feed={p.feed}")
        except Exception:
            pass
        
        # Tentar ler float de arg2 ou arg3 ou arg4
        try:
            # Em x64 chamadas cdecl/stdcall passadas com doubles em XMM regs ou stack. Mas no Python ctypes com c_void_p recebemos como int de 64 bits.
            # Vamos desempacotar como double se for 64-bit int
            d2 = struct.unpack('<d', struct.pack('<Q', arg2 or 0))[0]
            d3 = struct.unpack('<d', struct.pack('<Q', arg3 or 0))[0]
            d4 = struct.unpack('<d', struct.pack('<Q', arg4 or 0))[0]
            print(f"  doubles (arg2, arg3, arg4): {d2:.2f}, {d3:.2f}, {d4:.2f}")
        except Exception:
            pass

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
