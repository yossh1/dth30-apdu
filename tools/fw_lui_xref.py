import re
lines=open("~/dth30-re/disasm/firmware.asm", errors='ignore').read().splitlines()
# parse: VA: hex  mnemonic operands
pat=re.compile(r'^(0x[0-9a-f]+):\s+[0-9a-f]+\s+(.*)$')
ins=[]
for ln in lines:
    m=pat.match(ln)
    if m: ins.append((int(m.group(1),16), m.group(2).strip()))
targets={0x22d8:"CP APDU Length",0x2f89:"CalcDesKeyAB",0x29f0:"Authenticating CableCARD",0x244c:"CP task init",0x2294:"send_id_to_host",0xf030:"Initializing CableCard",0xf024:"Reinit TSD",0xf1dc:"TSD_FPGA configured",0xf0d0:"No CableCard detected",0x22f0:"CP numLengthByte",0x238c:"CP Received cp_open_req"}
# track lui 0x8020 / 0x8021 / 0x801f per register within window
for i,(va,txt) in enumerate(ins):
    m=re.match(r'addiu\s+(\$\w+),\s*(\$\w+),\s*(-?0x[0-9a-f]+|-?\d+)', txt)
    if m:
        try: imm=int(m.group(3),0)
        except: continue
        if imm in targets or (imm & 0xFFFF) in targets:
            # look back for lui of src reg
            src=m.group(2)
            for j in range(max(0,i-6), i):
                if ins[j][1].startswith('lui') and src in ins[j][1] and ('0x8020' in ins[j][1] or '0x8021' in ins[j][1] or '0x801f' in ins[j][1]):
                    print(f"{targets.get(imm & 0xFFFF)}: xref at VA 0x{va:x} : {txt}  (lui at 0x{ins[j][0]:x}: {ins[j][1]})")
                    break
