import struct

vals = [
    (0x3a0af9f784, 0x1873afdede0, 0x28feb0, 0x30002f00340031, 0x40e8e34000000000, 0x1, 0x3a00000003, 0x3),
    (0x3a0af9f784, 0x1873afe0820, 0x28feba, 0x30002f00340031, 0x40f8e34000000000, 0x2, 0x3a00000003, 0x3),
    (0x3a0af9f784, 0x1873afdfb00, 0x28fece, 0x30002f00340031, 0x4115c76400000000, 0x7, 0x3a00000093, 0x27)
]

for idx, row in enumerate(vals):
    print(f"\n--- LINHA {idx+1} ---")
    for i, v in enumerate(row):
        d = struct.unpack('<d', struct.pack('<Q', v))[0]
        i32_lo = v & 0xFFFFFFFF
        i32_hi = (v >> 32) & 0xFFFFFFFF
        print(f"  arg{i+1}: hex={v:#018x} | int64={v} | double={d:.4f} | lo32={i32_lo} hi32={i32_hi}")
