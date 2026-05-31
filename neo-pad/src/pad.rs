//! Virtual gamepad output, behind a `Pad` trait so the platform shim is swappable.
//!
//! Linux: hand-rolled uinput device (mirrors tools/gamepad.py's validated ioctl
//! struct layout exactly — no third-party uinput crate).
//! Windows (Phase 4): add a `#[cfg(windows)]` module backed by vigem-client and
//! return it from `new_pad()`. The mapping/curve logic in main.rs stays unchanged.

use std::io;

/// A virtual pad whose left stick we drive. x, y in [-1.0, 1.0].
pub trait Pad {
    fn set_left_stick(&mut self, x: f32, y: f32);
}

#[cfg(target_os = "linux")]
pub fn new_pad() -> io::Result<Box<dyn Pad>> {
    Ok(Box::new(linux_uinput::UinputPad::new(
        "Neo65 HE Analog Pad",
    )?))
}

#[cfg(windows)]
pub fn new_pad() -> io::Result<Box<dyn Pad>> {
    Ok(Box::new(win_vigem::VigemPad::new()?))
}

#[cfg(not(any(target_os = "linux", windows)))]
pub fn new_pad() -> io::Result<Box<dyn Pad>> {
    Err(io::Error::new(
        io::ErrorKind::Unsupported,
        "no Pad backend for this OS (only Linux uinput + Windows ViGEm are implemented)",
    ))
}

#[cfg(target_os = "linux")]
mod linux_uinput {
    use super::Pad;
    use std::fs::{File, OpenOptions};
    use std::io::{self, Write};
    use std::mem::size_of;
    use std::os::raw::{c_char, c_int, c_ulong};
    use std::os::unix::io::AsRawFd;

    // event types / codes (linux/input-event-codes.h)
    const EV_SYN: u16 = 0x00;
    const EV_KEY: u16 = 0x01;
    const EV_ABS: u16 = 0x03;
    const SYN_REPORT: u16 = 0x00;
    const ABS_AXES: [u16; 6] = [0x00, 0x01, 0x02, 0x03, 0x04, 0x05]; // X Y Z RX RY RZ
    const ABS_X: u16 = 0x00;
    const ABS_Y: u16 = 0x01;
    const BTN_GAMEPAD: u16 = 0x130; // presence makes the kernel classify us a pad
    const BUS_USB: u16 = 0x03;

    const AXIS_MIN: i32 = -32768;
    const AXIS_MAX: i32 = 32767;

    // _IOC bit layout (asm-generic): dir<<30 | size<<16 | type<<8 | nr
    const fn ioc(dir: u32, ty: u8, nr: u32, size: u32) -> c_ulong {
        ((dir << 30) | (size << 16) | ((ty as u32) << 8) | nr) as c_ulong
    }
    const UI_DEV_CREATE: c_ulong = ioc(0, b'U', 1, 0);
    const UI_DEV_DESTROY: c_ulong = ioc(0, b'U', 2, 0);
    const UI_DEV_SETUP: c_ulong = ioc(1, b'U', 3, size_of::<UinputSetup>() as u32);
    const UI_ABS_SETUP: c_ulong = ioc(1, b'U', 4, size_of::<UinputAbsSetup>() as u32);
    const UI_SET_EVBIT: c_ulong = ioc(1, b'U', 100, 4);
    const UI_SET_KEYBIT: c_ulong = ioc(1, b'U', 101, 4);
    const UI_SET_ABSBIT: c_ulong = ioc(1, b'U', 103, 4);

    #[repr(C)]
    struct InputId {
        bustype: u16,
        vendor: u16,
        product: u16,
        version: u16,
    }
    #[repr(C)]
    struct UinputSetup {
        id: InputId,
        name: [c_char; 80],
        ff_effects_max: u32,
    }
    #[repr(C)]
    struct InputAbsinfo {
        value: i32,
        minimum: i32,
        maximum: i32,
        fuzz: i32,
        flat: i32,
        resolution: i32,
    }
    #[repr(C)]
    struct UinputAbsSetup {
        code: u16,
        absinfo: InputAbsinfo,
    }
    #[repr(C)]
    struct InputEvent {
        tv_sec: i64,
        tv_usec: i64,
        type_: u16,
        code: u16,
        value: i32,
    }

    fn xioctl(fd: c_int, req: c_ulong, arg: c_ulong) -> io::Result<()> {
        // SAFETY: req/arg correspond to the uinput contract above; arg holds
        // either an int bit or a pointer-as-ulong, as the kernel expects.
        let r = unsafe { libc::ioctl(fd, req, arg) };
        if r < 0 {
            Err(io::Error::last_os_error())
        } else {
            Ok(())
        }
    }

    pub struct UinputPad {
        file: File,
    }

    impl UinputPad {
        pub fn new(name: &str) -> io::Result<Self> {
            // These must match the kernel structs or every ioctl silently misreads.
            assert_eq!(size_of::<UinputSetup>(), 92);
            assert_eq!(size_of::<UinputAbsSetup>(), 28);
            assert_eq!(size_of::<InputEvent>(), 24);

            let file = OpenOptions::new().write(true).open("/dev/uinput")?;
            let fd = file.as_raw_fd();

            xioctl(fd, UI_SET_EVBIT, EV_KEY as c_ulong)?;
            xioctl(fd, UI_SET_EVBIT, EV_ABS as c_ulong)?;
            for btn in BTN_GAMEPAD..BTN_GAMEPAD + 11 {
                xioctl(fd, UI_SET_KEYBIT, btn as c_ulong)?;
            }
            for &axis in ABS_AXES.iter() {
                xioctl(fd, UI_SET_ABSBIT, axis as c_ulong)?;
                let abs = UinputAbsSetup {
                    code: axis,
                    absinfo: InputAbsinfo {
                        value: 0,
                        minimum: AXIS_MIN,
                        maximum: AXIS_MAX,
                        fuzz: 0,
                        flat: 0,
                        resolution: 0,
                    },
                };
                xioctl(fd, UI_ABS_SETUP, &abs as *const _ as c_ulong)?;
            }

            let mut setup = UinputSetup {
                id: InputId {
                    bustype: BUS_USB,
                    vendor: crate::protocol::VID,
                    product: crate::protocol::PID,
                    version: 1,
                },
                name: [0; 80],
                ff_effects_max: 0,
            };
            for (i, &b) in name.as_bytes().iter().take(79).enumerate() {
                setup.name[i] = b as c_char;
            }
            xioctl(fd, UI_DEV_SETUP, &setup as *const _ as c_ulong)?;
            xioctl(fd, UI_DEV_CREATE, 0)?;
            std::thread::sleep(std::time::Duration::from_millis(200)); // let udev settle
            Ok(UinputPad { file })
        }

        fn emit(&mut self, type_: u16, code: u16, value: i32) {
            let ev = InputEvent {
                tv_sec: 0,
                tv_usec: 0,
                type_,
                code,
                value,
            };
            // SAFETY: InputEvent is #[repr(C)] POD; viewing it as its own bytes is sound.
            let bytes = unsafe {
                std::slice::from_raw_parts(&ev as *const _ as *const u8, size_of::<InputEvent>())
            };
            let _ = self.file.write_all(bytes);
        }
    }

    impl Pad for UinputPad {
        fn set_left_stick(&mut self, x: f32, y: f32) {
            let scale = |v: f32| -> i32 {
                let r = if v >= 0.0 {
                    v * AXIS_MAX as f32
                } else {
                    -v * AXIS_MIN as f32
                };
                r.round() as i32
            };
            self.emit(EV_ABS, ABS_X, scale(x));
            self.emit(EV_ABS, ABS_Y, scale(y));
            self.emit(EV_SYN, SYN_REPORT, 0);
        }
    }

    impl Drop for UinputPad {
        fn drop(&mut self) {
            self.set_left_stick(0.0, 0.0); // recenter before teardown
            let _ = xioctl(self.file.as_raw_fd(), UI_DEV_DESTROY, 0);
        }
    }
}

#[cfg(windows)]
mod win_vigem {
    //! Windows backend: emulate a wired Xbox 360 pad through ViGEmBus. Requires the
    //! ViGEmBus driver (pinned to 1.22.0) installed, or `Client::connect()` fails.
    //! Only the left stick is driven; everything else stays neutral.
    use super::Pad;
    use std::io;
    use vigem_client::{Client, TargetId, XGamepad, Xbox360Wired};

    pub struct VigemPad {
        target: Xbox360Wired<Client>,
        gp: XGamepad,
    }

    impl VigemPad {
        pub fn new() -> io::Result<Self> {
            let client = Client::connect().map_err(|e| {
                io::Error::other(format!(
                    "ViGEmBus connect failed (is the ViGEmBus 1.22.0 driver installed and running?): {e}"
                ))
            })?;
            let mut target = Xbox360Wired::new(client, TargetId::XBOX360_WIRED);
            target
                .plugin()
                .map_err(|e| io::Error::other(format!("ViGEm plugin: {e}")))?;
            target
                .wait_ready()
                .map_err(|e| io::Error::other(format!("ViGEm wait_ready: {e}")))?;
            Ok(Self {
                target,
                gp: XGamepad::default(),
            })
        }
    }

    impl Pad for VigemPad {
        fn set_left_stick(&mut self, x: f32, y: f32) {
            // main.rs supplies x,y in [-1,1] with Y screen-down-positive. XInput
            // thumb axes are i16 with +Y = up, so negate Y here (the one platform
            // difference vs the Linux uinput backend, which is ABS down-positive).
            let s = |v: f32| (v.clamp(-1.0, 1.0) * 32767.0).round() as i16;
            self.gp.thumb_lx = s(x);
            self.gp.thumb_ly = s(-y);
            let _ = self.target.update(&self.gp);
        }
    }

    impl Drop for VigemPad {
        fn drop(&mut self) {
            self.set_left_stick(0.0, 0.0); // recenter; target unplugs on its own drop
        }
    }
}
