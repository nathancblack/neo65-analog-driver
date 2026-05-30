// Neo65 NeoFlux sniffer v2 — opcode-collapsing, context-window-friendly.
//
// WHY v2: the §9 sniffer dedupes by full payload, so live depth reports (which
// change every frame) flood the console. v2 collapses everything by OPCODE
// SIGNATURE and only tracks which byte offsets ever move. Output stays tiny no
// matter how long you capture.
//
// GOAL OF THIS CAPTURE: open NeoFlux's FULL per-key matrix / Switch-Calibration
// view (the screen showing ALL keys at once, not the WASD picker), press W then
// D. We are looking for ANY out opcode other than `d0 b0` (heartbeat) and
// `d0 ad 00 00` (aggregate depth). A new opcode = per-key data is reachable.
//
// USAGE:
//   1. Paste this whole file into the DevTools Console on he.qwertykeys.com.
//   2. If nothing logs "active", unplug/replug the board so the wrap catches it.
//   3. Open the full per-key matrix / calibration view. Press W slowly, release.
//      Press D slowly, release.
//   4. Run  neoSummary()  -> prints a SHORT summary. Paste that back.
//   5. (backup) Run  neoSave()  -> downloads neo65-sniff.json to ~/Downloads.
//      Tell me the filename and I'll read it directly — no pasting needed.

(() => {
  const toHex = (d) => {
    const b = new Uint8Array(d.buffer ?? d);
    return [...b].map((x) => x.toString(16).padStart(2, "0")).join(" ");
  };
  const bytesOf = (d) => [...new Uint8Array(d.buffer ?? d)];

  // sig = first 4 bytes -> distinguishes opcodes AND their immediate args
  const sigOf = (bytes) =>
    bytes.slice(0, 4).map((x) => x.toString(16).padStart(2, "0")).join(" ");

  // Per-channel store keyed by "TAG|sig". Tracks count, an example payload, and
  // a varyMask: the set of byte offsets whose value ever differed from the first
  // sample (so we can see live data move without logging every frame).
  const store = new Map();
  const record = (tag, id, data) => {
    const bytes = bytesOf(data);
    const key = tag + "|" + sigOf(bytes);
    let e = store.get(key);
    if (!e) {
      e = {
        tag,
        id,
        sig: sigOf(bytes),
        len: bytes.length,
        count: 0,
        first: bytes.slice(),
        vary: new Set(),
        minByte: bytes.slice(),
        maxByte: bytes.slice(),
      };
      store.set(key, e);
    }
    e.count++;
    for (let i = 0; i < bytes.length; i++) {
      if (bytes[i] !== e.first[i]) e.vary.add(i);
      if (bytes[i] < e.minByte[i]) e.minByte[i] = bytes[i];
      if (bytes[i] > e.maxByte[i]) e.maxByte[i] = bytes[i];
    }
  };

  const P = HIDDevice.prototype;
  const wrap = (name, kind) => {
    const orig = P[name];
    if (!orig || orig.__snf) return;
    P[name] = function (id, data) {
      try {
        record(kind, id, data ?? new Uint8Array());
      } catch (e) {}
      return orig.apply(this, arguments);
    };
    P[name].__snf = true;
  };
  wrap("sendReport", "OUT");
  wrap("sendFeatureReport", "FEAT-SET");

  const recv = P.receiveFeatureReport;
  if (recv && !recv.__snf) {
    P.receiveFeatureReport = function (id) {
      return recv.apply(this, arguments).then((dv) => {
        try {
          record("FEAT-GET", id, dv);
        } catch (e) {}
        return dv;
      });
    };
    P.receiveFeatureReport.__snf = true;
  }

  const addEL = P.addEventListener;
  if (!addEL.__snf) {
    P.addEventListener = function (type, listener, opts) {
      if (type === "inputreport")
        addEL.call(this, "inputreport", (e) => record("IN", e.reportId, e.data), {});
      return addEL.call(this, type, listener, opts);
    };
    P.addEventListener.__snf = true;
  }
  navigator.hid.getDevices().then((ds) =>
    ds.forEach((d) => {
      try {
        d.addEventListener("inputreport", (e) => record("IN", e.reportId, e.data));
      } catch (e) {}
    })
  );

  const hx = (arr) => arr.map((x) => x.toString(16).padStart(2, "0")).join(" ");

  window.neoSummary = () => {
    const rows = [...store.values()].sort(
      (a, b) => a.tag.localeCompare(b.tag) || a.sig.localeCompare(b.sig)
    );
    console.log(
      "%c=== Neo65 sniff summary ===  (looking for OUT opcodes besides 'd0 b0' / 'd0 ad 00 00')",
      "color:#0f0;font-weight:bold"
    );
    for (const e of rows) {
      const vary = [...e.vary].sort((a, b) => a - b);
      const varyStr = vary.length ? `bytes[${vary.join(",")}] move` : "static";
      console.log(
        `%c${e.tag.padEnd(9)}%c sig='${e.sig}' len=${e.len} count=${e.count} | ${varyStr}`,
        "color:#0bf;font-weight:bold",
        "color:inherit"
      );
      console.log(`   first: ${hx(e.first)}`);
      if (vary.length) {
        console.log(`   min:   ${hx(e.minByte)}`);
        console.log(`   max:   ${hx(e.maxByte)}`);
      }
    }
    console.log(
      "%cDistinct OUT signatures: " +
        rows.filter((r) => r.tag === "OUT").map((r) => r.sig).join("  |  "),
      "color:#ff0"
    );
    return `${rows.length} distinct signatures captured`;
  };

  window.neoSave = () => {
    const dump = [...store.values()].map((e) => ({
      tag: e.tag,
      id: e.id,
      sig: e.sig,
      len: e.len,
      count: e.count,
      varyBytes: [...e.vary].sort((a, b) => a - b),
      first: hx(e.first),
      min: hx(e.minByte),
      max: hx(e.maxByte),
    }));
    const blob = new Blob([JSON.stringify(dump, null, 2)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "neo65-sniff.json";
    a.click();
    console.log("%cSaved neo65-sniff.json to ~/Downloads", "color:#0f0;font-weight:bold");
  };

  window.neoReset = () => {
    store.clear();
    console.log("sniff store cleared.");
  };

  console.log(
    "%cNeo65 sniffer v2 active. Open the FULL per-key matrix view, press W then D.\n" +
      "Then run  neoSummary()  (short) or  neoSave()  (downloads a file).",
    "color:#0f0;font-weight:bold"
  );
})();
