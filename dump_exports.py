import pefile
from config import DLL_PATH

pe = pefile.PE(DLL_PATH)
exports = []
for exp in pe.DIRECTORY_ENTRY_EXPORT.symbols:
    if exp.name:
        name = exp.name.decode('utf-8')
        if any(w in name for w in ['Trade', 'Book', 'Subscribe', 'Callback', 'Set', 'Get', 'Price', 'Ticker']):
            exports.append(name)

print(f"TOTAL DE EXPORTS RELEVANTES ENCONTRADOS: {len(exports)}")
for e in sorted(exports):
    print(" ", e)
