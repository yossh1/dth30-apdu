//! The CAS object: what the host opens to follow the B-CAS card and to
//! ask for a card reset.
//!
//! The firmware reports to the host in blocks sent to the object's
//! endpoint: a 0x1EC-byte header, then nothing of interest up to the block
//! size the host gave (0x8000). Header words used:
//!
//! | offset | meaning                                                        |
//! |--------|----------------------------------------------------------------|
//! | +0x00  | the host's own handle (two words), as given in the open        |
//! | +0x30  | 0x10000 = card event                                           |
//! | +0x48  | 1                                                              |
//! | +0x84  | number of the block, counting through the host's buffers       |
//! | +0x88  | 1 \| 0x2000 inserted \| 0x4000 removed \| 0x8000 activated \| 0x800000 INIT done |
//! | +0x8C  | 1 with INIT done                                               |
//! | +0x1BC | with INIT done: the card's return code                         |
//!
//! The end of a reset request is told by message 0x0F ("input done").
//!
//! Command 28 is this project's own addition (not a vendor command):
//! the host hands the object an APDU to exchange with the card, or asks
//! for the card's status and ATR. An exchange runs in the card's job
//! queue alongside the ECMs and its end is told by message 0x10.

use crate::card::{self, Card, Output};
use crate::dma::{Dma, SRC_LOCAL};
use crate::host::{FAILED, Host, OK, UNSUPPORTED};
use crate::hw::{fb_r, fb_w};

/// The handle returned to the host.
const HANDLE: u32 = 0xA006_2A40;
/// Where blocks are put together (SDRAM, above the firmware's other areas).
const BLOCK: u32 = 0x0006_8000;
const BLOCK_MAX: u32 = 0x8000;
const HEADER: u32 = 0x1EC;

const MSG_INPUT_DONE: u32 = 0x0F;
/// The completion of a host APDU exchange (command 28).
const MSG_APDU_DONE: u32 = 0x10;
/// Input type (+0xA0) and request flag (+0xB8) of a card request.
const INPUT_CAS: u32 = 1 << 16;
const REQUEST_CARD: u32 = 1 << 4;

const EV_INSERTED: u32 = 0x2000;
const EV_REMOVED: u32 = 0x4000;
const EV_ACTIVATED: u32 = 0x8000;
const EV_INIT: u32 = 0x80_0000;

struct Object {
    cookie: [u32; 2],
    /// The host's buffers for event blocks: how many, their size, the PCI
    /// address (all the same endpoint FIFO).
    buffers: u32,
    size: u32,
    dest: u32,
    next: u32,
    /// The card status last reported.
    reported: u8,
    /// Words of the last request, repeated in "input done".
    request: [u32; 3],
}

/// A host APDU completion waiting for a free message body, with the
/// answer copied out of the card at the moment it ended.
#[derive(Clone, Copy)]
struct ApduPend {
    cookie: [u32; 2],
    tag: u32,
    code: u32,
    len: usize,
}

pub struct Cas {
    object: Option<Object>,
    /// Events waiting for the DMA engine: +0x88 and +0x1BC.
    events: [(u32, u32); 8],
    count: usize,
    apdu_pend: Option<ApduPend>,
    apdu_snap: [u8; card::APDU_RX_MAX],
}

/// Read bytes out of the payload (words, little-endian).
fn fb_read_bytes(at: u32, out: &mut [u8]) {
    for (i, chunk) in out.chunks_mut(4).enumerate() {
        let w = fb_r(at + 4 * i as u32).to_le_bytes();
        chunk.copy_from_slice(&w[..chunk.len()]);
    }
}

/// Write bytes into the payload (whole words; the rest of the last word
/// is zeroed).
fn fb_write_bytes(at: u32, data: &[u8]) {
    for (i, chunk) in data.chunks(4).enumerate() {
        let mut w = [0u8; 4];
        w[..chunk.len()].copy_from_slice(chunk);
        fb_w(at + 4 * i as u32, u32::from_le_bytes(w));
    }
}

impl Cas {
    pub fn new() -> Self {
        Self { object: None, events: [(0, 0); 8], count: 0, apdu_pend: None, apdu_snap: [0; card::APDU_RX_MAX] }
    }

    /// Command 25: open the object.
    ///
    /// Payload: +0x00 the host's handle (two words, replaced by the
    /// firmware's), +0x08 mode (bit 4 = B-CAS, bit 5 = B-CAS with the
    /// vendor's re-encryption, which is not supported and treated as bit
    /// 4), +0x0C number of event buffers, +0x10 their size, +0x14.. their
    /// PCI addresses.
    pub fn open(&mut self, p: u32) -> u32 {
        let (mode, buffers, size, dest) = (fb_r(p + 0x08), fb_r(p + 0x0C), fb_r(p + 0x10), fb_r(p + 0x14));
        if self.object.is_some()
            || mode & 0x30 == 0
            || !(1..=64).contains(&buffers)
            || !(HEADER..=BLOCK_MAX).contains(&size)
        {
            return FAILED;
        }
        for off in (0..BLOCK_MAX).step_by(4) {
            fb_w(BLOCK + off, 0);
        }
        self.object =
            Some(Object { cookie: [fb_r(p), fb_r(p + 4)], buffers, size, dest, next: 0, reported: 0, request: [0; 3] });
        self.count = 0;
        fb_w(p, HANDLE);
        fb_w(p + 4, 0);
        OK
    }

    /// Command 26: close the object. The card stays as it is.
    pub fn close(&mut self, handle: u32) -> u32 {
        if handle != HANDLE || self.object.is_none() {
            return FAILED;
        }
        self.object = None;
        self.count = 0;
        OK
    }

    /// Command 11: a request to the object. Only the card reset is
    /// supported (+0xA0 bit 16, +0xB8 bit 4, +0x1BC bit 0); the host always
    /// gets "done" for the command itself and the outcome in message 0x0F.
    pub fn input(&mut self, p: u32, card: &mut Card) -> u32 {
        fb_w(p + 0xA4, 0);
        let Some(o) = self.object.as_mut() else { return OK };
        let (kind, flags, what) = (fb_r(p + 0xA0), fb_r(p + 0xB8), fb_r(p + 0x1BC));
        if fb_r(p) != HANDLE || kind & INPUT_CAS == 0 || flags & REQUEST_CARD == 0 {
            return OK;
        }
        o.request = [kind, fb_r(p + 0xAC), flags];
        if what & 1 != 0 {
            card.request_reset();
        }
        OK
    }

    /// Command 28: a host APDU exchange, or a query of the card, on the
    /// object.
    ///
    /// Payload: +0x00 the object's handle, +0x04 the operation (0 =
    /// EXCHANGE, 1 = QUERY). Unlike command 11, a request that cannot be
    /// taken is refused with its reason, so the host can tell what this
    /// firmware can do.
    ///
    /// EXCHANGE: +0x08 the APDU's length, +0x0C a tag the host picks,
    /// +0x10.. the APDU itself. The reason code of
    /// [`Card::submit_apdu`] (or 4 for a wrong handle or no object) is
    /// written back at +0x08 and the command fails unless the APDU was
    /// taken; the exchange itself ends with message 0x10.
    ///
    /// QUERY is answered in the payload at once: +0x08 0, +0x0C the
    /// card's status ([`Card::status`]), +0x10 the ATR's length and
    /// +0x14.. the ATR as received (length 0 until the card has been
    /// activated).
    ///
    /// An unknown operation is UNSUPPORTED. A firmware without this
    /// command fails command 28 outright, which is how the host tells
    /// the two apart.
    pub fn apdu(&mut self, p: u32, card: &mut Card) -> u32 {
        if self.object.is_none() || fb_r(p) != HANDLE {
            fb_w(p + 0x08, 4);
            return FAILED;
        }
        match fb_r(p + 0x04) {
            0 => {
                let len = fb_r(p + 0x08) as usize;
                let tag = fb_r(p + 0x0C);
                let mut buf = [0u8; card::APDU_MAX];
                let n = len.min(card::APDU_MAX);
                fb_read_bytes(p + 0x10, &mut buf[..n]);
                let reason = card.submit_apdu(&buf[..n], len, tag);
                fb_w(p + 0x08, reason);
                if reason == 0 { OK } else { FAILED }
            }
            1 => {
                fb_w(p + 0x08, 0);
                fb_w(p + 0x0C, u32::from(card.status()));
                let atr = card.atr();
                fb_w(p + 0x10, atr.len() as u32);
                fb_write_bytes(p + 0x14, atr);
                OK
            }
            _ => UNSUPPORTED,
        }
    }

    /// Send a waiting APDU completion (message 0x10) as soon as a
    /// message body is free. Unlike a reset's "input done", an APDU
    /// completion is never dropped: the host waits for it, so it is
    /// held and retried on every turn of the main loop until it goes
    /// out.
    pub fn flush_apdu_done(&mut self, host: &mut Host) {
        let Some(pend) = self.apdu_pend else { return };
        let Some(m) = host.message(MSG_APDU_DONE) else { return };
        let d = Host::descriptor(m);
        fb_w(d, pend.cookie[0]);
        fb_w(d + 0x04, pend.cookie[1]);
        fb_w(d + 0x08, pend.tag);
        fb_w(d + 0x0C, pend.code);
        fb_w(d + 0x10, pend.len as u32);
        fb_write_bytes(d + 0x14, &self.apdu_snap[..pend.len]);
        host.send(m);
        self.apdu_pend = None;
    }

    fn event(&mut self, bits: u32, value: u32) {
        if self.object.is_some() && self.count < self.events.len() {
            self.events[self.count] = (bits | 1, value);
            self.count += 1;
        }
    }

    /// Something the card code reports.
    pub fn card_output(&mut self, out: Output, card: &Card, host: &mut Host) {
        let Some(o) = self.object.as_ref() else { return };
        match out {
            Output::ResetDone(result) => {
                let Some(m) = host.message(MSG_INPUT_DONE) else { return };
                let d = Host::descriptor(m);
                fb_w(d, o.cookie[0]);
                fb_w(d + 0x04, o.cookie[1]);
                fb_w(d + 0x08, o.request[0]);
                fb_w(d + 0x1C, o.request[1]);
                fb_w(d + 0x20, result);
                fb_w(d + 0x24, o.request[2]);
                host.send(m);
            }
            Output::InitDone(ret) => self.event(EV_INIT, ret),
            Output::ApduDone { tag, code } => {
                // The answer is copied out now: the card's buffer is
                // reused by the next exchange, while the message may
                // have to wait for a free body.
                let resp = if code == 0 { card.apdu_response() } else { &[] };
                let n = resp.len();
                self.apdu_snap[..n].copy_from_slice(resp);
                self.apdu_pend = Some(ApduPend { cookie: o.cookie, tag, code, len: n });
                self.flush_apdu_done(host);
            }
            // ECM answers concern the Program stream only.
            Output::Keys { .. } | Output::EcmRefused | Output::EcmLost => {}
        }
    }

    /// Report card status changes and send the next waiting block.
    pub fn poll(&mut self, status: u8, dma: &mut Dma) {
        let Some(o) = self.object.as_mut() else { return };
        if status != o.reported {
            let changed = status ^ o.reported;
            let mut bits = 0;
            if changed & card::PRESENT != 0 {
                bits |= if status & card::PRESENT != 0 { EV_INSERTED } else { EV_REMOVED };
            }
            if changed & status & card::ACTIVE != 0 {
                bits |= EV_ACTIVATED;
            }
            o.reported = status;
            if bits != 0 {
                self.event(bits, 0);
            }
        }
        if self.count == 0 || !dma.idle() {
            return;
        }
        let Some(o) = self.object.as_mut() else { return };
        let (bits, value) = self.events[0];
        self.events.copy_within(1..self.count, 0);
        self.count -= 1;
        for off in (0..HEADER).step_by(4) {
            fb_w(BLOCK + off, 0);
        }
        fb_w(BLOCK, o.cookie[0]);
        fb_w(BLOCK + 0x04, o.cookie[1]);
        fb_w(BLOCK + 0x30, 0x1_0000);
        fb_w(BLOCK + 0x48, 1);
        fb_w(BLOCK + 0x84, o.next);
        fb_w(BLOCK + 0x88, bits);
        if bits & EV_INIT != 0 {
            fb_w(BLOCK + 0x8C, 1);
            fb_w(BLOCK + 0x1BC, value);
        }
        o.next = (o.next + 1) % o.buffers;
        dma.start(BLOCK, o.dest, o.size, SRC_LOCAL);
    }
}
