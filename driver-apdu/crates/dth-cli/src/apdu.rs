//! `dth apdu`: talk to a DTH30 series unit's B-CAS card through the
//! firmware's own command 28 (not a vendor command): query the card's
//! status and ATR, and exchange one APDU with it.
//!
//! The unit is brought up with the firmware built into this program
//! (or the one `--firmware` names), the CAS object is opened and the
//! card reset, as for a device-mode tune; the exchange itself runs in
//! the card's job queue in the firmware, alongside the ECMs. With
//! `--channel`, a device-mode stream of that channel runs while the
//! exchange is made, and what the exchange did to the stream (its
//! packets, and how many stayed scrambled) is reported.
//!
//! With `--socket` (or `--connect`) the unit is not opened here at
//! all: a running `dth serve` is asked instead, and the exchange runs
//! in the daemon's card session, so it works while the daemon streams
//! (a recorder's stream is not disturbed). The daemon's answer carries
//! the card's response; what is shown here is still only the length,
//! the status word and a SHA-256 fingerprint.
//!
//! Card material is never printed or saved: of the ATR and of an
//! answer only the length, the status word and a SHA-256 fingerprint
//! are shown.

use std::error::Error;
use std::io::{BufRead, BufReader, Read, Write};
use std::path::PathBuf;
use std::sync::Arc;
use std::sync::atomic::{AtomicBool, AtomicU32, Ordering};
use std::thread::JoinHandle;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use clap::Args;
use dth_common::{Channel, System};
use dth_proto::ipc::{Conn, Target};
use dth_proto::proto::{
    ApduError, ApduOp, ApduRequest, MAX_LINE, Reply, Request, parse_apdu_error, parse_apdu_exchange, parse_apdu_query,
};
use dth30_core::device::{Config as DevConfig, Dth30, StreamInfo};
use dth30_core::psi::ProgramScanner;
use dth30_core::vixs::Options;
use dth30_core::vixs::cmd::{self, ApduDoneSlot};
use dth30_core::vixs::stream::{StreamKind, card_state, parse_generic_block};
use dth30_usb::{Net2280Usb, StreamReader};
use sha2::{Digest, Sha256};

use crate::{DeviceArgs, default_state_dir};

/// How long the card may take to report itself activated after the
/// reset (it takes about a second).
const CARD_WAIT: Duration = Duration::from_secs(5);
/// How long the completion of an exchange is waited for.
const APDU_WAIT: Duration = Duration::from_secs(10);
/// Bulk reads in flight per stream (as `tune`'s default on Linux).
const READ_DEPTH: usize = 16;

#[derive(Args)]
pub struct ApduArgs {
    #[command(flatten)]
    dev: DeviceArgs,
    /// The APDU to exchange, as hex (9030000000 is the card's
    /// INITIAL_SETTING). Without it only the card is queried.
    #[arg(value_name = "HEX")]
    apdu: Option<String>,
    /// Also tune this terrestrial channel and stream it (device mode)
    /// while the exchange runs, and report the exchange's effect on
    /// the stream.
    #[arg(long, value_name = "NAME")]
    channel: Option<String>,
    /// Exchange the APDU over and over until the process is stopped,
    /// logging every attempt with a timestamp. For watching what an
    /// exchange does when the card is pulled mid-flight (N-064): the
    /// firmware must end a queued or running APDU with completion
    /// code 1, and the host must not hang. Without --channel.
    #[arg(long = "loop")]
    loop_mode: bool,
    /// Ask a running `dth serve` instead of opening the unit (the
    /// daemon's card session is used, so this works while it streams):
    /// the socket file of the daemon (default: $DTH_SOCKET, else
    /// /run/dth/dth.sock on Linux, %TEMP%\dth-<hash of this
    /// executable's folder>.sock on Windows). --serial names the unit
    /// then. Without --channel or --loop.
    #[arg(long, value_name = "PATH")]
    socket: Option<PathBuf>,
    /// The TCP address of `dth serve` instead (e.g. 127.0.0.1:40780; $DTH_LISTEN).
    #[arg(long, value_name = "ADDR", conflicts_with = "socket")]
    connect: Option<String>,
}

fn parse_hex(s: &str) -> Result<Vec<u8>, String> {
    let s: String = s.chars().filter(|c| !c.is_whitespace()).collect();
    if s.len() % 2 != 0 {
        return Err(format!("odd number of hex digits in {s:?}"));
    }
    (0..s.len())
        .step_by(2)
        .map(|i| u8::from_str_radix(&s[i..i + 2], 16).map_err(|e| format!("bad hex {s:?}: {e}")))
        .collect()
}

fn fingerprint(b: &[u8]) -> String {
    Sha256::digest(b).iter().map(|x| format!("{x:02x}")).collect()
}

fn reason_text(reason: u32) -> &'static str {
    match reason {
        0 => "taken",
        1 => "no active card",
        2 => "busy (an APDU is outstanding, or the queue is full)",
        3 => "bad length (0, or over 60 bytes)",
        4 => "wrong handle or no CAS object",
        _ => "unknown reason",
    }
}

fn code_text(code: u32) -> &'static str {
    match code {
        0 => "ok",
        1 => "the card went away",
        2 => "the exchange failed",
        3 => "a reset or power cycle overtook it",
        4 => "a chained answer (not supported)",
        _ => "unknown code",
    }
}

/// The CAS endpoint read in the background while the object is open
/// (an unread FIFO may stall the firmware), keeping the card's
/// reported state (the backend's `CasWatch`, reduced to the flags).
struct CasWatch {
    card: Arc<AtomicU32>,
    activated: Arc<AtomicBool>,
    stop: Arc<AtomicBool>,
    thread: JoinHandle<StreamReader>,
}

impl CasWatch {
    fn start(mut r: StreamReader) -> Self {
        let card = Arc::new(AtomicU32::new(0));
        let activated = Arc::new(AtomicBool::new(false));
        let stop = Arc::new(AtomicBool::new(false));
        let (c, a, s) = (card.clone(), activated.clone(), stop.clone());
        let thread = std::thread::spawn(move || {
            while !s.load(Ordering::Relaxed) {
                match r.next(Duration::from_millis(100)) {
                    Ok(Some(b)) => {
                        let Some((h, _)) = parse_generic_block(&b) else { continue };
                        if h.card & card_state::REMOVED != 0 {
                            a.store(false, Ordering::Relaxed);
                        } else if h.card & card_state::ACTIVATED != 0 {
                            a.store(true, Ordering::Relaxed);
                        }
                        c.store(h.card, Ordering::Relaxed);
                    }
                    Ok(None) => {}
                    Err(_) => std::thread::sleep(Duration::from_millis(100)),
                }
            }
            r
        });
        Self { card, activated, stop, thread }
    }

    fn stop(self) -> StreamReader {
        self.stop.store(true, Ordering::Relaxed);
        self.thread.join().expect("CAS reader thread")
    }
}

/// A Program stream read in the background, counting its packets and
/// how many are scrambled, in two phases (0 = before and during the
/// exchange, 1 = after it, once the caller flips the phase).
struct StreamStats {
    phase: Arc<AtomicU32>,
    counts: Arc<std::sync::Mutex<[(u64, u64); 2]>>,
    stop: Arc<AtomicBool>,
    thread: JoinHandle<StreamReader>,
}

impl StreamStats {
    fn start(mut r: StreamReader) -> Self {
        let phase = Arc::new(AtomicU32::new(0));
        let counts = Arc::new(std::sync::Mutex::new([(0, 0); 2]));
        let stop = Arc::new(AtomicBool::new(false));
        let (p, c, s) = (phase.clone(), counts.clone(), stop.clone());
        let thread = std::thread::spawn(move || {
            let mut carry: Vec<u8> = Vec::new();
            while !s.load(Ordering::Relaxed) {
                match r.next(Duration::from_millis(100)) {
                    Ok(Some(b)) => {
                        carry.extend_from_slice(&b);
                        let ph = p.load(Ordering::Relaxed) as usize;
                        let mut n = 0;
                        while n + 188 <= carry.len() {
                            let pkt = &carry[n..n + 188];
                            if pkt[0] == 0x47 {
                                let mut counts = c.lock().unwrap();
                                counts[ph].0 += 1;
                                if pkt[3] & 0xC0 != 0 {
                                    counts[ph].1 += 1;
                                }
                            }
                            n += 188;
                        }
                        carry.drain(..n);
                    }
                    Ok(None) => {}
                    Err(_) => std::thread::sleep(Duration::from_millis(100)),
                }
            }
            r
        });
        Self { phase, counts, stop, thread }
    }

    fn counts(&self) -> [(u64, u64); 2] {
        *self.counts.lock().unwrap()
    }

    fn stop(self) -> StreamReader {
        self.stop.store(true, Ordering::Relaxed);
        self.thread.join().expect("stream reader thread")
    }
}

fn reader(dev: &mut Dth30<Net2280Usb>, info: &StreamInfo) -> Result<StreamReader, Box<dyn Error>> {
    let mut r = dev.vixs_mut().bus().stream_reader(info.endpoint, info.transfer_len, READ_DEPTH)?;
    r.start();
    Ok(r)
}

/// Close one stream the vendor's way: the firmware side first (the
/// reads stay pending), then cancel the reads and empty the FIFO.
fn close_stream(dev: &mut Dth30<Net2280Usb>, info: &StreamInfo, mut r: StreamReader) {
    let closed = match info.kind {
        StreamKind::Program => dev.close_program(),
        StreamKind::Raw => dev.close_raw(),
        StreamKind::Generic => dev.close_cas(),
    };
    if let Err(e) = closed {
        log::warn!("closing the {:?} stream: {e}", info.kind);
    }
    r.stop();
    let _ = dev.flush_endpoint_fifo(info.endpoint);
}

/// Wait for the front end's lock, up to about four seconds.
fn wait_lock(dev: &mut Dth30<Net2280Usb>) -> Result<bool, Box<dyn Error>> {
    let deadline = Instant::now() + Duration::from_secs(4);
    loop {
        if dev.status()?.locked {
            return Ok(true);
        }
        if Instant::now() >= deadline {
            return Ok(false);
        }
        std::thread::sleep(Duration::from_millis(100));
    }
}

/// Exchange `apdu` (when given) and report the outcome. The tag is
/// fixed: a one-shot process has no other exchange outstanding.
fn exchange(
    dev: &mut Dth30<Net2280Usb>,
    cas: &dth30_core::vixs::stream::StreamHandle,
    slot: &ApduDoneSlot,
    apdu: &[u8],
) -> Result<(), Box<dyn Error>> {
    let tag = 1;
    let reason = dev.vixs_mut().apdu_submit(cas, apdu, tag)?;
    if reason != 0 {
        return Err(format!("the APDU was refused at submission: reason {reason} ({})", reason_text(reason)).into());
    }
    let Some(done) = dev.vixs_mut().wait_apdu_done(slot, tag, APDU_WAIT)? else {
        return Err("no APDU completion within 10 s".into());
    };
    if done.code != 0 {
        println!(
            "APDU {} -> completion code {} ({})",
            apdu.iter().map(|b| format!("{b:02x}")).collect::<String>(),
            done.code,
            code_text(done.code)
        );
        return Err(format!("the APDU exchange ended with code {}", done.code).into());
    }
    let resp = &done.response;
    let sw = if resp.len() >= 2 {
        format!("{:02x}{:02x}", resp[resp.len() - 2], resp[resp.len() - 1])
    } else {
        "----".into()
    };
    println!(
        "APDU {} -> {} bytes, SW {}, sha256 {}",
        apdu.iter().map(|b| format!("{b:02x}")).collect::<String>(),
        resp.len(),
        sw,
        fingerprint(resp)
    );
    Ok(())
}

/// UTC now as an ISO-8601 string with milliseconds, for the loop log.
fn stamp() -> String {
    let dur = SystemTime::now().duration_since(UNIX_EPOCH).unwrap_or_default();
    let secs = dur.as_secs() as i64;
    let ms = dur.subsec_millis();
    let days = secs.div_euclid(86_400);
    let tod = secs.rem_euclid(86_400);
    // Civil date from the day count (Howard Hinnant's algorithm).
    let z = days + 719_468;
    let era = z.div_euclid(146_097);
    let doe = z.rem_euclid(146_097);
    let yoe = (doe - doe / 1460 + doe / 36_524 - doe / 146_096) / 365;
    let y = yoe + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let d = doy - (153 * mp + 2) / 5 + 1;
    let m = if mp < 10 { mp + 3 } else { mp - 9 };
    let y = if m <= 2 { y + 1 } else { y };
    format!(
        "{y:04}-{m:02}-{d:02}T{:02}:{:02}:{:02}.{ms:03}Z",
        tod / 3600,
        tod / 60 % 60,
        tod % 60
    )
}

/// One exchange for the loop: log the attempt and its outcome with
/// timestamps, and say how it ended instead of failing. Returns true
/// when a completion was reported (whatever its code).
fn exchange_logged(
    dev: &mut Dth30<Net2280Usb>,
    cas: &dth30_core::vixs::stream::StreamHandle,
    slot: &ApduDoneSlot,
    apdu: &[u8],
    n: u64,
) -> bool {
    let tag = 1;
    println!("[{}] #{n} submit", stamp());
    let t0 = Instant::now();
    let reason = match dev.vixs_mut().apdu_submit(cas, apdu, tag) {
        Ok(r) => r,
        Err(e) => {
            println!("[{}] #{n} submit error: {e} (after {} ms)", stamp(), t0.elapsed().as_millis());
            return false;
        }
    };
    if reason != 0 {
        println!(
            "[{}] #{n} refused reason={reason} ({}) after {} ms",
            stamp(),
            reason_text(reason),
            t0.elapsed().as_millis()
        );
        return false;
    }
    match dev.vixs_mut().wait_apdu_done(slot, tag, APDU_WAIT) {
        Ok(Some(done)) => {
            let dur = t0.elapsed().as_millis();
            if done.code == 0 {
                let resp = &done.response;
                let sw = if resp.len() >= 2 {
                    format!("{:02x}{:02x}", resp[resp.len() - 2], resp[resp.len() - 1])
                } else {
                    "----".into()
                };
                println!(
                    "[{}] #{n} done code=0 len={} sw={} sha256={} dur={} ms",
                    stamp(),
                    resp.len(),
                    sw,
                    fingerprint(resp),
                    dur
                );
            } else {
                println!(
                    "[{}] #{n} done code={} ({}) dur={} ms",
                    stamp(),
                    done.code,
                    code_text(done.code),
                    dur
                );
            }
            true
        }
        Ok(None) => {
            println!("[{}] #{n} timeout: no completion within {} s", stamp(), APDU_WAIT.as_secs());
            false
        }
        Err(e) => {
            println!("[{}] #{n} wait error: {e}", stamp());
            false
        }
    }
}

/// `--loop`: keep an APDU outstanding at (nearly) all times, so that
/// pulling the card lands inside a queued or running exchange, and
/// log every attempt. Attempts that never reach the card (refusals,
/// timeouts) pause briefly so the log stays readable; a reported
/// completion is followed by the next submission at once.
fn loop_exchange(
    dev: &mut Dth30<Net2280Usb>,
    cas: &dth30_core::vixs::stream::StreamHandle,
    slot: &ApduDoneSlot,
    apdu: &[u8],
) -> ! {
    println!(
        "[{}] loop start: an APDU is kept outstanding; pulling the card must end it with code 1",
        stamp()
    );
    let mut n: u64 = 0;
    loop {
        n += 1;
        if !exchange_logged(dev, cas, slot, apdu, n) {
            std::thread::sleep(Duration::from_millis(250));
        }
    }
}

/// `--socket` / `--connect`: ask a running `dth serve` for the query
/// and the exchange (one connection each; the daemon ends it after
/// the reply). The output is the direct mode's: the card's status and
/// the ATR's length and fingerprint, then the exchange's length,
/// status word and fingerprint.
fn run_client(a: &ApduArgs, apdu: Option<&[u8]>) -> Result<(), Box<dyn Error>> {
    let target = Target::resolve(a.socket.as_deref(), a.connect.as_deref());
    let ask = |op: ApduOp| -> Result<Reply, Box<dyn Error>> {
        let req = Request::Apdu(ApduRequest { unit: a.dev.serial.clone(), op });
        let conn = Conn::connect(&target).map_err(|e| format!("cannot reach dth serve at {target}: {e}"))?;
        // Opening the unit and activating its card can take seconds.
        conn.set_read_timeout(Some(Duration::from_secs(60)))?;
        (&conn).write_all(format!("{}\n", req.to_line()).as_bytes())?;
        let mut line = String::new();
        (&mut BufReader::new(&conn))
            .take(MAX_LINE as u64)
            .read_line(&mut line)
            .map_err(|e| format!("no reply from dth serve: {e}"))?;
        Ok(Reply::parse(&line))
    };
    match ask(ApduOp::Query)? {
        Reply::Ok(info) => {
            let (status, atr) =
                parse_apdu_query(&info).ok_or("the daemon's reply is not an apdu query answer")?;
            println!(
                "card status: 0x{status:02x} ({}present, {}active)",
                if status & 1 != 0 { "" } else { "not " },
                if status & 2 != 0 { "" } else { "not " }
            );
            if atr.is_empty() {
                println!("ATR: not available (the card has not been activated)");
            } else {
                println!("ATR: {} bytes, sha256 {}", atr.len(), fingerprint(&atr));
            }
        }
        Reply::Busy(why) | Reply::Error(why) => return Err(why.into()),
    }
    let Some(apdu) = apdu else { return Ok(()) };
    let hex: String = apdu.iter().map(|b| format!("{b:02x}")).collect();
    match ask(ApduOp::Exchange(apdu.to_vec()))? {
        Reply::Ok(info) => {
            let resp = parse_apdu_exchange(&info).ok_or("the daemon's reply is not an apdu exchange answer")?;
            let sw = if resp.len() >= 2 {
                format!("{:02x}{:02x}", resp[resp.len() - 2], resp[resp.len() - 1])
            } else {
                "----".into()
            };
            println!("APDU {hex} -> {} bytes, SW {}, sha256 {}", resp.len(), sw, fingerprint(&resp));
            Ok(())
        }
        Reply::Busy(why) => Err(why.into()),
        Reply::Error(why) => match parse_apdu_error(&why) {
            Some(ApduError::Refused(reason)) => {
                println!("APDU {hex} -> refused at submission: reason {reason} ({})", reason_text(reason));
                Err(format!("the APDU was refused at submission: reason {reason}").into())
            }
            Some(ApduError::Completed(code)) => {
                println!("APDU {hex} -> completion code {code} ({})", code_text(code));
                Err(format!("the APDU exchange ended with code {code}").into())
            }
            None => Err(why.into()),
        },
    }
}

pub fn run(a: &ApduArgs) -> Result<(), Box<dyn Error>> {
    let apdu = a.apdu.as_deref().map(parse_hex).transpose()?;
    if a.socket.is_some() || a.connect.is_some() {
        if a.channel.is_some() || a.loop_mode {
            return Err("--socket/--connect do not go with --channel or --loop".into());
        }
        return run_client(a, apdu.as_deref());
    }
    let channel = a
        .channel
        .as_deref()
        .map(|name| {
            let ch = Channel::parse(name).ok_or_else(|| format!("unknown channel {name:?}"))?;
            if ch.system != System::IsdbT {
                return Err("--channel takes a terrestrial channel".into());
            }
            Ok::<Channel, Box<dyn Error>>(ch)
        })
        .transpose()?;

    let (name, found) = dth30_backend::find(a.dev.serial.as_deref())?
        .ok_or_else(|| -> Box<dyn Error> { "no DTH30 series unit found".into() })?;
    let state_dir = default_state_dir();
    let (fw, _) = dth30_backend::firmware(a.dev.firmware.as_deref(), &state_dir)?;
    let t = found.open()?;
    let pid = t.product_id();
    let pipes: Vec<u8> = t.endpoints().iter().map(|e| e.address).collect();
    let mut dev = Dth30::open(t, pid, &pipes, Options::default(), DevConfig::default())?;
    dev.bring_up(&fw)?;
    log::info!("unit {name}: board 0x{:02x}, {} front end", dev.board(), dev.kit().name());

    // The completion handler goes in before the CAS object is opened,
    // so no completion can be missed.
    let slot: ApduDoneSlot = Arc::new(std::sync::Mutex::new(None));
    dev.vixs_mut().set_m2h_handler(cmd::apdu_done_handler(slot.clone()));

    let cas_info = dev.open_cas()?;
    let cas = dev
        .stream(StreamKind::Generic)
        .cloned()
        .ok_or::<Box<dyn Error>>("the CAS object did not stay open".into())?;
    let watch = CasWatch::start(reader(&mut dev, &cas_info)?);

    // The card reports itself activated about a second after the reset.
    let deadline = Instant::now() + CARD_WAIT;
    while !watch.activated.load(Ordering::Relaxed) && Instant::now() < deadline {
        std::thread::sleep(Duration::from_millis(20));
    }
    if watch.activated.load(Ordering::Relaxed) {
        println!("card: activated (last event 0x{:x})", watch.card.load(Ordering::Relaxed));
    } else {
        println!(
            "card: not activated within {} s (last event 0x{:x})",
            CARD_WAIT.as_secs(),
            watch.card.load(Ordering::Relaxed)
        );
    }

    let result = run_open(&mut dev, &cas, &slot, apdu.as_deref(), channel.as_ref(), a.loop_mode, &cas_info, watch);
    result
}

fn run_open(
    dev: &mut Dth30<Net2280Usb>,
    cas: &dth30_core::vixs::stream::StreamHandle,
    slot: &ApduDoneSlot,
    apdu: Option<&[u8]>,
    channel: Option<&Channel>,
    loop_mode: bool,
    cas_info: &StreamInfo,
    watch: CasWatch,
) -> Result<(), Box<dyn Error>> {
    // QUERY first: it is also how a firmware without command 28 is
    // told apart (it refuses the query as well).
    let body = (|| -> Result<(), Box<dyn Error>> {
        let (status, atr) = dev.vixs_mut().card_query(cas)?;
        println!(
            "card status: 0x{status:02x} ({}present, {}active)",
            if status & 1 != 0 { "" } else { "not " },
            if status & 2 != 0 { "" } else { "not " }
        );
        if atr.is_empty() {
            println!("ATR: not available (the card has not been activated)");
        } else {
            println!("ATR: {} bytes, sha256 {}", atr.len(), fingerprint(&atr));
        }
        let Some(apdu) = apdu else { return Ok(()) };
        let Some(ch) = channel else {
            if loop_mode {
                loop_exchange(dev, cas, slot, apdu);
            }
            return exchange(dev, cas, slot, apdu);
        };
        // Stream the channel (device mode) across the exchange.
        dev.tune(ch.frequency_hz)?;
        if !wait_lock(dev)? {
            return Err(format!("no lock on {}", ch.name).into());
        }
        let raw_info = dev.open_raw()?;
        let mut raw = reader(dev, &raw_info)?;
        let spec = {
            let mut scan = ProgramScanner::new(None);
            let deadline = Instant::now() + Duration::from_secs(5);
            let found = loop {
                match raw.next(Duration::from_millis(200))? {
                    Some(b) => {
                        if let Some(spec) = scan.push(&b) {
                            break Some(spec);
                        }
                    }
                    None => {}
                }
                if Instant::now() >= deadline {
                    break None;
                }
            };
            match found {
                Some(s) => s,
                None => {
                    close_stream(dev, &raw_info, raw);
                    return Err("no PAT/PMT in the Raw stream within 5 s".into());
                }
            }
        };
        let prog_info = dev.open_program(&spec)?;
        let stats = StreamStats::start(reader(dev, &prog_info)?);
        // Two seconds of stream before the exchange.
        let t0 = Instant::now();
        while t0.elapsed() < Duration::from_secs(2) && stats.counts()[0].0 == 0 {
            std::thread::sleep(Duration::from_millis(50));
        }
        std::thread::sleep(Duration::from_millis(200));
        let outcome = exchange(dev, cas, slot, apdu);
        // A second of grace (packets already descrambled with the
        // previous keys are not the exchange's fault), then count three
        // seconds of stream as the after phase.
        std::thread::sleep(Duration::from_secs(1));
        stats.phase.store(1, Ordering::Relaxed);
        std::thread::sleep(Duration::from_secs(3));
        let counts = stats.counts();
        let prog_reader = stats.stop();
        close_stream(dev, &prog_info, prog_reader);
        close_stream(dev, &raw_info, raw);
        println!(
            "stream {}: before/during the exchange {} packets ({} scrambled); after it {} packets ({} scrambled)",
            ch.name, counts[0].0, counts[0].1, counts[1].0, counts[1].1
        );
        outcome
    })();
    let cas_reader = watch.stop();
    close_stream(dev, cas_info, cas_reader);
    let _ = dev.standby();
    body
}

#[cfg(test)]
mod tests {
    use clap::Parser;

    use crate::{Cli, Cmd};

    fn args(v: &[&str]) -> super::ApduArgs {
        match Cli::parse_from(std::iter::once("dth").chain(v.iter().copied())).cmd {
            Cmd::Apdu(a) => *a,
            _ => panic!("not apdu"),
        }
    }

    #[test]
    fn socket_mode_is_opt_in() {
        let a = args(&["apdu", "9030000000"]);
        assert!(a.socket.is_none() && a.connect.is_none(), "direct mode is the default");
        let a = args(&["apdu", "--socket", "/run/dth/dth.sock", "9030000000"]);
        assert_eq!(a.socket.as_deref(), Some(std::path::Path::new("/run/dth/dth.sock")));
        assert_eq!(a.apdu.as_deref(), Some("9030000000"));
        let a = args(&["apdu", "--connect", "127.0.0.1:40780"]);
        assert_eq!(a.connect.as_deref(), Some("127.0.0.1:40780"));
        assert!(Cli::try_parse_from(["dth", "apdu", "--socket", "/x", "--connect", "127.0.0.1:1"]).is_err());
    }
}
