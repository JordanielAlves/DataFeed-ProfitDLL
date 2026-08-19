import struct
from config import DLL_PATH

def get_exports(dll_path):
    with open(dll_path, "rb") as f:
        data = f.read()
    
    # DOS header e e_lfanew
    e_lfanew = struct.unpack_from("<I", data, 0x3C)[0]
    # Signature "PE\0\0"
    if data[e_lfanew:e_lfanew+4] != b"PE\0\0":
        return []
    
    # FileHeader (20 bytes), OptionalHeader magic
    opt_header_offset = e_lfanew + 4 + 20
    magic = struct.unpack_from("<H", data, opt_header_offset)[0]
    is_64 = (magic == 0x20b)
    
    # DataDirectories offset na OptionalHeader
    data_dir_offset = opt_header_offset + (112 if is_64 else 96)
    export_dir_rva, export_dir_size = struct.unpack_from("<II", data, data_dir_offset)
    if not export_dir_rva:
        return []

    # Parse Sections to convert RVA to file offset
    sections_offset = opt_header_offset + struct.unpack_from("<H", data, e_lfanew + 4 + 16)[0]
    num_sections = struct.unpack_from("<H", data, e_lfanew + 4 + 2)[0]
    
    def rva_to_offset(rva):
        for i in range(num_sections):
            sec_off = sections_offset + i * 40
            name, vsize, vaddr, rawsize, rawoff = struct.unpack_from("<8sIIII", data, sec_off)
            if vaddr <= rva < vaddr + max(vsize, rawsize):
                return rawoff + (rva - vaddr)
        return rva

    exp_off = rva_to_offset(export_dir_rva)
    # IMAGE_EXPORT_DIRECTORY
    num_names, names_rva = struct.unpack_from("<I xxxx I", data, exp_off + 24)
    names_off = rva_to_offset(names_rva)
    
    exports = []
    for i in range(num_names):
        name_rva = struct.unpack_from("<I", data, names_off + i * 4)[0]
        name_off = rva_to_offset(name_rva)
        end_off = data.find(b"\0", name_off)
        name = data[name_off:end_off].decode("ascii", errors="ignore")
        exports.append(name)
    return exports

exports = get_exports(DLL_PATH)
print(f"TOTAL DE EXPORTS DA DLL: {len(exports)}")
relevant = [e for e in exports if any(w in e for w in ['Trade', 'Book', 'Subscribe', 'Callback', 'Set', 'Get', 'Price', 'Ticker', 'DLL'])]
for e in sorted(relevant):
    print(" ", e)
