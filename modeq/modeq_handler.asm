; =====================================================================
; Mode Q handler (variant B) for DT-H30/U2 stock firmware — STREAM build
; =====================================================================
; All addresses below are STREAM-build values, measured from the recorded
; stock-driver replay stream (replay_base.json.gz) on 2026-11-23:
;
;   submit API   0xA0121700  (signature match 27/27 @ stream 0x21700)
;   pool alloc   0xA0154854  (file 0xA01548D4, shift -0x80)
;   pool free    0xA0154C1C  (file 0xA0154C9C, shift -0x80)
;   memcpy       0xA01FE680  (file 0xA01FE8A0, shift -0x220; also the
;                             stream stub's own jal target — cross-checked)
;   worker exit  0xA015373C  (file 0xA01537BC, shift -0x80; $v0==0 -> slot+0x10=1,
;                             else 2, then poster notifies the host)
;   state-ptr global  0x80227050  ($gp_stream 0x8022DBC0 - 0x6B70, from stream
;                                  submit's first instruction. Stored value =
;                                  state struct KSEG1 VA 0xA0237ED8, written
;                                  by init @0xA012B0A0, memset size 0x190)
;   pool-ptr global   0x8022700C  ($gp_stream 0x8022DBC0 - 0x6BB4. Stored
;                                  value = pool descriptor KSEG1 VA
;                                  0xA022F254, written @0xA01524FC)
;   ctx list anchor   0x80253308  (stream reset fn @0x25938: lui 0x8025/lw 0x3308;
;                                  head = *anchor, sentinel = anchor itself,
;                                  node+0x00 = next, node+0x30 bit 0x10 = card ctx)
;   $gp (stream)      0x8022DBC0  (lui 0x8023 / addiu -0x2440 at stream
;                                  0x8584 / 0x201B0; the 0x201B0 site is the
;                                  card-task entry trampoline, which sets
;                                  $gp right before jalr into the module.
;                                  CORRECTION 2026-11-23: the first revision
;                                  read 0x8023DBC0 by OR-ing the lui/addiu
;                                  halves instead of sign-extending the
;                                  addiu immediate (0xDBC0 = -0x2440). That
;                                  put both globals 0x10000 too high and
;                                  killed the worker in the first device
;                                  trial. Full derivation: GLOBALS-FIX.md)
;   Func 0x04 stub    stream off 0x534D0 (VA 0xA01534D0), 0xCC bytes
;   code cave         stream off 0x1E238 (VA 0xA011E238 KSEG1 / 0x8011E238 KSEG0),
;                     6596 bytes, C1-proven (N-053)
;
; Cache policy: everything WE own (trampoline target, callback pointer,
; pending-state data) uses KSEG1 (uncached) addresses — cave execution is
; unproven and DMA-loaded bytes must not depend on I-cache maintenance.
; Firmware globals are read via their KSEG0 addresses (same alias the
; firmware itself uses). The T=1 state struct is reached through the
; state-ptr global, exactly like the stock callbacks (its stored pointer
; is already a KSEG1 VA: phys + 0xA0000000).
;
; Host contract (slot byte array, offsets from slot base):
;   +0x40  u16 LE  IN: APDU length L (4..0x80)   OUT: response length
;   +0x42  u16 LE  status: host writes 0 before issue.
;                  0x8000 = in flight (set by handler on acceptance)
;                  0x0000 = done, response valid at +0x44
;                  1..5   = error (mapping as implemented here; note it
;                           deviates from APDU-DESIGN.md sec.6: here 3 =
;                           bad length / callback total out of bounds and
;                           5 = request-pool alloc failure)
;   +0x44  bytes   IN: APDU (CLA INS P1 P2 [Lc data] [Le]); OUT: response
;                  (INF field of the T=1 response block = data + SW1 SW2)
; Func 0x04 returns immediately: slot+0x10 = 1 (accepted) or 2 (rejected,
; error code at +0x42). The host polls +0x42 until != 0x8000.
;
; v1 scope: single in-flight request, APDU <= 0x80 bytes, one T=1 I-block
; round trip. Splitting longer APDUs is a documented future extension.
; Known v1 limitation: if the job queue is purged, the completion callback
; is never called and PEND stays busy; every later Func 0x04 then returns
; error 4 until the device is rebooted. The host must use a timeout.
; =====================================================================

; ---- build-time constants (substituted by build_modeq.py, pass 2) ----
; CB_OFF   = offset of mq_callback from cave base   (@@CB_OFF@@)
; DATA_OFF = offset of pending-state area           (@@DATA_OFF@@)
; PEND_ADDR = 0xA011E238 + DATA_OFF, formed as lui 0xA012 / addiu @@PEND_LO@@

; =====================================================================
; Trampoline — replaces the first 8 bytes of the Func 0x04 stub body
; at stream offset 0x534D0 (VA 0xA01534D0). The remaining 0xC4 bytes of
; the stub are unreachable and left untouched (minimal diff).
; Assembled separately at VA 0xA01534D0.
; =====================================================================
; mq_trampoline:
;     j     0xA011E238          ; cave handler (KSEG1)
;     nop

; =====================================================================
; Cave code — assembled at VA 0xA011E238 (KSEG1)
; =====================================================================

; ---------------------------------------------------------------------
; mq_handler — worker case entry for Func 0x04.
;   IN : $s0 = slot VA (worker ABI; preserved — worker exit uses it)
;   OUT: branches to worker exit 0xA015373C with $v0 = 0 (accepted,
;        slot+0x10 := 1) or $v0 = 1 (rejected, slot+0x10 := 2)
; ---------------------------------------------------------------------
mq_handler:
    addiu $sp, $sp, -0x20
    sw    $ra, 0x1C($sp)
    sw    $s1, 0x18($sp)
    sw    $s2, 0x14($sp)
    sw    $s3, 0x10($sp)
    ; L = slot[0x40] | slot[0x41] << 8   (byte access: no alignment assumption)
    lbu   $s3, 0x40($s0)
    lbu   $t1, 0x41($s0)
    sll   $t1, $t1, 8
    or    $s3, $s3, $t1
    ; validate 4 <= L <= 0x80
    sltiu $t1, $s3, 4
    bnez  $t1, mq_err3
    nop
    sltiu $t1, $s3, 0x81
    beqz  $t1, mq_err3
    nop
    ; busy check: PEND_SLOT != 0 -> error 4
    lui   $t2, 0xA012
    addiu $t2, $t2, @@PEND_LO@@
    lw    $t3, 0($t2)
    bnez  $t3, mq_err4
    nop
    ; gate: state = *0x80227050; (state[0x118] & 2) == 0 -> error 4
    ; sanity guard: state must be a KSEG0/KSEG1 VA (>>29 == 4 or 5) before
    ; dereferencing — a bad deref here is what killed the worker in the
    ; first device trial, so fail clean with error 4 instead. This guard
    ; block is additive and can be dropped without other changes.
    lui   $t4, 0x8022
    lw    $t4, 0x7050($t4)
    srl   $t5, $t4, 29
    addiu $t5, $t5, -4
    sltiu $t5, $t5, 2
    beqz  $t5, mq_err4
    nop
    lw    $t5, 0x118($t4)
    andi  $t5, $t5, 2
    beqz  $t5, mq_err4
    nop
    ; find ctx: walk list at anchor 0x80253308 (idiom copied from the
    ; stock card-reset function, stream @0xA0125938/0xA0125D2C)
    lui   $t6, 0x8025
    lw    $s1, 0x3308($t6)
    addiu $t6, $t6, 0x3308
mq_find:
    beq   $s1, $t6, mq_err4
    nop
    lw    $t7, 0x30($s1)
    andi  $t7, $t7, 0x10
    bnez  $t7, mq_found
    nop
    lw    $s1, 0($s1)
    b     mq_find
    nop
mq_found:
    ; Canonicalize ctx to its KSEG1 form before any use (SECOND-ISSUE
    ; candidate 1): the job-list machinery stores job+0x1C = ctx+0xC
    ; verbatim, and the unlink consistency check recomputes the head as
    ; 0xA0000000 + (ctx & 0x1FFFFFFF) + 0xC. A KSEG0 ctx (as found by
    ; walking the 0x80253308 anchor list) fails that check at teardown
    ; and parks the card task (observed in exp2 as the #2 wedge, fired
    ; during #1's teardown). The anchor list itself is KSEG0-linked, so
    ; $s1 is known to be 0x80xxxxxx here and a plain OR with 0xA0000000
    ; is the exact conversion. The scan above must stay KSEG0, so the
    ; conversion happens only here, after the node is found.
    lui   $t7, 0xA000
    or    $s1, $s1, $t7
    ; req = alloc(*0x8022700C); NULL -> error 5
    lui   $a0, 0x8022
    lw    $a0, 0x700C($a0)
    jal   0xA0154854
    nop
    beqz  $v0, mq_err5
    nop
    or    $s2, $v0, $zero
    ; memcpy(req + 0, slot + 0x44, L)
    or    $a0, $s2, $zero
    addiu $a1, $s0, 0x44
    or    $a2, $s3, $zero
    jal   0xA01FE680
    nop
    ; request fields (fill idiom = stock 0xA0122C9C):
    ;   +0x80 = INS byte (APDU[1]), +0x84 = L, +0x88 = 0 (I-block), +0x8C = ctx
    lbu   $t1, 0x45($s0)
    sw    $t1, 0x80($s2)
    sw    $s3, 0x84($s2)
    sw    $zero, 0x88($s2)
    sw    $s1, 0x8C($s2)
    ; stash pending state (KSEG1 cave data), then mark slot busy.
    ; Order matters: all slot/pending writes precede the submit call, so a
    ; callback that fires early can only overwrite with the final state.
    lui   $t2, 0xA012
    addiu $t2, $t2, @@PEND_LO@@
    sw    $s0, 0($t2)
    sw    $s2, 4($t2)
    sb    $zero, 0x42($s0)
    addiu $t1, $zero, 0x80
    sb    $t1, 0x43($s0)
    ; submit(ctx, req, aux = mq_callback KSEG1 VA)
    or    $a0, $s1, $zero
    or    $a1, $s2, $zero
    lui   $a2, 0xA012
    addiu $a2, $a2, @@CB_LO@@
    jal   0xA0121700
    nop
    beqz  $v0, mq_ok
    nop
    ; submit rejected (gate raced): free req, clear pending, error 4
    lui   $a0, 0x8022
    lw    $a0, 0x700C($a0)
    or    $a1, $s2, $zero
    jal   0xA0154C1C
    nop
    lui   $t2, 0xA012
    addiu $t2, $t2, @@PEND_LO@@
    sw    $zero, 0($t2)
    sw    $zero, 4($t2)
    b     mq_err4
    nop
mq_ok:
    addiu $v0, $zero, 0
    b     mq_exit
    nop
mq_err3:
    addiu $t9, $zero, 3
    b     mq_fail
    nop
mq_err4:
    addiu $t9, $zero, 4
    b     mq_fail
    nop
mq_err5:
    addiu $t9, $zero, 5
    b     mq_fail
    nop
mq_fail:
    ; length := 0, status := error code
    sb    $zero, 0x40($s0)
    sb    $zero, 0x41($s0)
    sb    $t9, 0x42($s0)
    sb    $zero, 0x43($s0)
    addiu $v0, $zero, 1
mq_exit:
    lw    $ra, 0x1C($sp)
    lw    $s1, 0x18($sp)
    lw    $s2, 0x14($sp)
    lw    $s3, 0x10($sp)
    addiu $sp, $sp, 0x20
    j     0xA015373C
    addiu $v1, $zero, 2     ; worker-exit convention: the exit writes $v1 to
                            ; slot+0x10 unless $v0==0 (movz then forces 1).
                            ; Stock cases preset $v1=2 in this delay slot;
                            ; without it the rejection path would leak the
                            ; dispatcher's leftover $v1 (0x801FF180).

; ---------------------------------------------------------------------
; mq_callback — completion callback (aux of the submit API).
;   Called by the T=1 state machine at receive completion with
;   $a0 = 0, $a1 = req, return value ignored (stream @0xA0124860:
;   state+0x134 is already set to the received total before the call).
;   Copies the response INF (state buffer +3, length = total - 4)
;   into the pending slot and clears the busy status.
;   NOTE: runs in the card-task context; standard function conventions.
; ---------------------------------------------------------------------
mq_callback:
    addiu $sp, $sp, -0x18
    sw    $ra, 0x14($sp)
    sw    $s0, 0x10($sp)
    lui   $t2, 0xA012
    addiu $t2, $t2, @@PEND_LO@@
    lw    $s0, 0($t2)
    beqz  $s0, mq_cb_ret
    nop
    lw    $t3, 4($t2)
    bne   $t3, $a1, mq_cb_ret
    nop
    ; state = *0x80227050; total = state[0x134]; resp_len = total - 4
    ; sanity guard (same rationale as in mq_handler): state must be a
    ; KSEG0/KSEG1 VA before dereferencing; fail with error 3 instead of
    ; faulting in the card-task context. Additive, droppable block.
    ; bounds next: a T=1 block total is 6..0x102 (INF 2..254 bytes);
    ; anything else means the completion is not a usable response -> error 3
    lui   $t4, 0x8022
    lw    $t4, 0x7050($t4)
    srl   $t6, $t4, 29
    addiu $t6, $t6, -4
    sltiu $t6, $t6, 2
    beqz  $t6, mq_cb_err3
    nop
    lw    $t5, 0x134($t4)
    sltiu $t6, $t5, 6
    bnez  $t6, mq_cb_err3
    nop
    sltiu $t6, $t5, 0x103
    beqz  $t6, mq_cb_err3
    nop
    addiu $t5, $t5, -4
    ; memcpy(slot + 0x44, state + 3, resp_len)
    addiu $a0, $s0, 0x44
    addiu $a1, $t4, 3
    or    $a2, $t5, $zero
    sw    $t5, 0x08($sp)
    jal   0xA01FE680
    nop
    lw    $t5, 0x08($sp)
    ; length := resp_len (LE bytes), status := 0 (done)
    sb    $t5, 0x40($s0)
    srl   $t6, $t5, 8
    sb    $t6, 0x41($s0)
    sb    $zero, 0x42($s0)
    sb    $zero, 0x43($s0)
    b     mq_cb_done
    nop
mq_cb_err3:
    sb    $zero, 0x40($s0)
    sb    $zero, 0x41($s0)
    addiu $t6, $zero, 3
    sb    $t6, 0x42($s0)
    sb    $zero, 0x43($s0)
mq_cb_done:
    lui   $t2, 0xA012
    addiu $t2, $t2, @@PEND_LO@@
    sw    $zero, 0($t2)
    sw    $zero, 4($t2)
mq_cb_ret:
    lw    $ra, 0x14($sp)
    lw    $s0, 0x10($sp)
    addiu $sp, $sp, 0x18
    jr    $ra
    nop

; pending-state area (in the image: zero-filled, DATA_OFF from cave base)
;   +0  PEND_SLOT  (word) slot VA of the in-flight request, 0 = idle
;   +4  PEND_REQ   (word) request object of the in-flight job
