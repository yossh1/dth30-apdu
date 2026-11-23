//! [`Session`]: what the daemon and the command ask of an opened unit,
//! whichever family it is (`dth10-backend`, `dth30-backend`).

use crate::{Error, Result};
use crate::channels::{Channel, System};
use crate::queue::TsQueue;
use crate::stream::{DeviceProgram, StreamModeCfg};

/// A unit's B-CAS card as a card query reports it.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CardInfo {
    /// The card status word (bit 0 = a card is in the slot, bit 1 = it is
    /// active).
    pub status: u32,
    /// The ATR as received; empty until the card has been activated.
    pub atr: Vec<u8>,
}

/// How one APDU exchange with a unit's B-CAS card ended.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ApduOutcome {
    /// The exchange ran to its end: the firmware's completion code
    /// (0 = the exchange went through, 1 = the card went away, 2 = the
    /// exchange failed, 3 = a reset or power cycle overtook it,
    /// 4 = a chained answer, not supported) and, for code 0, the answer
    /// (its data and SW1 SW2).
    Completed { code: u32, response: Vec<u8> },
    /// The firmware refused the APDU at submission, with its reason
    /// (1 = no active card, 2 = busy: an APDU is outstanding, or the
    /// queue is full, 3 = bad length, 4 = wrong handle or no CAS object).
    Refused(u32),
}

/// One opened unit: tuners 0 (terrestrial) and 1 (satellite, or a second
/// terrestrial tuner), each streaming into its own [`TsQueue`].
pub trait Session: Send {
    /// Where one tuner's TS goes.
    fn set_queue(&mut self, tuner: usize, queue: TsQueue);
    /// Whether tuner #1 is a second terrestrial tuner.
    fn has_second_terrestrial(&self) -> bool;
    /// Whether the unit has a satellite (BS/CS) tuner.
    fn has_satellite(&self) -> bool;
    fn set_stream_mode(&mut self, mode: StreamModeCfg);
    fn set_device_program(&mut self, program: DeviceProgram);
    /// Antenna supply for BS/CS (units without one ignore it).
    fn set_lnb(&mut self, _volt: u32) {}
    fn set_attenuator(&mut self, _on: bool) {}
    fn set_booster(&mut self, _on: bool) {}
    fn set_lock_wait_ms(&mut self, system: System, ms: u64);
    /// Tune tuner `tuner` to `ch` and start streaming into its queue.
    fn set_channel_on(&mut self, tuner: usize, ch: &Channel) -> Result<()>;
    /// C/N in dB of one tuner (0.0 when unavailable).
    fn signal_level_of(&mut self, tuner: usize) -> f32;
    /// Stop one tuner's stream.
    fn release(&mut self, tuner: usize);
    /// One tuner's stream gave itself up (the device is gone).
    fn stream_failed(&self, tuner: usize) -> bool;
    /// The C/N of every tuner tuned to a channel (about once a second while
    /// streaming).
    fn poll_status(&mut self) -> [Option<f32>; 2];
    /// Query the unit's B-CAS card (its status and ATR). The card session
    /// the unit keeps for its device-mode streams is the one used, so a
    /// query does not disturb a running stream. Units with no card
    /// facility refuse.
    fn card_query(&mut self) -> Result<CardInfo> {
        Err(Error::Unsupported("this unit has no card to query".into()))
    }
    /// Exchange one APDU with the unit's B-CAS card, in the card session
    /// the unit keeps (queued with the card's own work, so a stream's
    /// descrambling goes on). One exchange at a time per unit. Units with
    /// no card facility refuse.
    fn apdu_exchange(&mut self, _apdu: &[u8]) -> Result<ApduOutcome> {
        Err(Error::Unsupported("this unit cannot exchange APDUs with a card".into()))
    }
    /// Stop everything and put the device to rest.
    fn close(&mut self);
}
