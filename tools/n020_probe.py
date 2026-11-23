#!/usr/bin/env python3
"""N-020: read-only probe of the candidate ctx/obj in the EXISTING field-2 dumps.

Runs on 検証ホスト against ~/dth30-lab/*.bin (already-collected dumps only;
no device access). Candidate ctx phys 0x1088DC -> field-2 offset 0x88DC;
obj = ctx + 0x1408 -> field-2 offset 0x9CE4 (per N-017/N-018).
Also probes the alternative base hypothesis (task base = ctx+0x4B18,
obj2 offset 0xE7FC) to confirm it is unrelated static data.
"""
import struct, os

OBJ = 0x9CE4
CTX = OBJ - 0x1408
OBJ_OFFS = [0x4, 0x8, 0x38, 0x80, 0x84, 0x94, 0x98, 0x9C, 0xA4, 0xB8, 0xE8,
            0xEC, 0xF0, 0x110, 0x118, 0x124, 0x15C, 0x160, 0x164, 0x180, 0x2CC,
            0x300, 0x334, 0x690, 0x6AC, 0x6D8, 0x70C, 0x7F8, 0x7FA, 0x7FC,
            0x808, 0x80C, 0x830, 0x834, 0x85C, 0x88C, 0x8C, 0x90, 0x960,
            0xFF0, 0xFF8, 0x1000, 0x116C, 0x1170]
CTX_OFFS = [0x30, 0x9C, 0x2F8, 0x318, 0x324, 0x1488, 0x14C0, 0x14C8, 0x1C90,
            0x1C94, 0x1E38, 0x2600, 0x2604, 0x2608, 0x2614, 0x2618, 0x261C,
            0x2620, 0x2628, 0x263C, 0x2640, 0x2660]
OBJ2 = 0xE7FC  # ctx+0x4B18+0x1408 (alternative-base control probe)
FILES = ["pre_f2_065716.bin", "preB_f2_071344.bin", "postB_f2_071533.bin",
         "postB2_f2_071813.bin", "f2_001547.bin", "f2_001814.bin",
         "f2_002616.bin"]


def u32(d, off):
    return struct.unpack_from("<I", d, off)[0]


def main():
    for fn in FILES:
        d = open(os.path.expanduser("~/dth30-lab/" + fn), "rb").read()
        nz_obj = {hex(o): hex(u32(d, OBJ + o)) for o in OBJ_OFFS if u32(d, OBJ + o)}
        nz_ctx = {hex(o): hex(u32(d, CTX + o)) for o in CTX_OFFS if u32(d, CTX + o)}
        print(fn, "obj nonzero:", nz_obj or "NONE", "| ctx nonzero:", nz_ctx or "NONE")
        print("   obj2(+0xFF0/+0x334/+0x834) =", hex(u32(d, OBJ2 + 0xFF0)),
              hex(u32(d, OBJ2 + 0x334)), hex(u32(d, OBJ2 + 0x834)),
              "(static halfword table, identical in all states)")


if __name__ == "__main__":
    main()
