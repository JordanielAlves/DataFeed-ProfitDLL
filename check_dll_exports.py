import ctypes
import os
from config import DLL_PATH

dll = ctypes.WinDLL(DLL_PATH)

known_callbacks = [
    "SetTradeCallback",
    "SetTradeCallbackV2",
    "SetNewTradeCallback",
    "SetNewTradeCallbackV2",
    "SetOfferBookCallback",
    "SetOfferBookCallbackV2",
    "SetPriceDepthCallback",
    "SetPriceBookCallback",
    "SetPriceBookCallbackV2",
    "SetHistoryTradeCallback",
    "SubscribeTicker",
    "SubscribeOfferBook",
    "SubscribePriceDepth",
    "SubscribePriceBook",
]

print("CHECHANDO FUNÇÕES NA DLL:")
for name in known_callbacks:
    exists = hasattr(dll, name)
    print(f"  {name:<25}: {'SIM' if exists else 'NÃO'}")
