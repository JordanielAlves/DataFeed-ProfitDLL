import sys
with open('profit_bridge.py', 'r', encoding='utf-8') as f:
    text = f.read()

text = text.replace('self._safe_setup_func("GetPriceDepthSideCount", restype=c_int, argtypes=[POINTER(TConnectorAssetIdentifier), c_int])', 'self._safe_setup_func("GetPriceDepthSideCount", restype=c_int, argtypes=[TConnectorAssetIdentifier, c_int])')
text = text.replace('self._safe_setup_func("GetPriceGroup", restype=c_int, argtypes=[POINTER(TConnectorAssetIdentifier), c_int, c_int, POINTER(TConnectorPriceGroup)])', 'self._safe_setup_func("GetPriceGroup", restype=c_int, argtypes=[TConnectorAssetIdentifier, c_int, c_int, POINTER(TConnectorPriceGroup)])')
text = text.replace('total = self._dll.GetPriceDepthSideCount(byref(asset), side_int)', 'total = self._dll.GetPriceDepthSideCount(asset, side_int)')
text = text.replace('ret = self._dll.GetPriceGroup(byref(asset), side_int, pos, byref(grupo))', 'ret = self._dll.GetPriceGroup(asset, side_int, pos, byref(grupo))')
text = text.replace('self._safe_setup_func("SubscribePriceDepth", restype=c_int, argtypes=[POINTER(TConnectorAssetIdentifier)])', 'self._safe_setup_func("SubscribePriceDepth", restype=c_int, argtypes=[TConnectorAssetIdentifier])')
text = text.replace('self._safe_setup_func("UnsubscribePriceDepth", restype=c_int, argtypes=[POINTER(TConnectorAssetIdentifier)])', 'self._safe_setup_func("UnsubscribePriceDepth", restype=c_int, argtypes=[TConnectorAssetIdentifier])')
text = text.replace('ret = self._dll.SubscribePriceDepth(byref(asset))', 'ret = self._dll.SubscribePriceDepth(asset)')
text = text.replace('self._dll.UnsubscribePriceDepth(byref(asset))', 'self._dll.UnsubscribePriceDepth(asset)')

with open('profit_bridge.py', 'w', encoding='utf-8') as f:
    f.write(text)

print('Feito!')
