// Talks to the Vectiq referee over the app's realtime channel. JSON in, JSON out.
(function () {
  const enc = new TextEncoder(), dec = new TextDecoder();
  const addr = (window.webxdc && window.webxdc.selfAddr) || "anon-" + Math.random().toString(36).slice(2);
  let ch = null, seen = false, last = null, tries = 0;

  function send(obj, isRetry) {
    obj.addr = addr;
    if (!isRetry) { last = obj; tries = 0; }
    if (ch) ch.send(enc.encode(JSON.stringify(obj)));
  }

  // onState(state) for the whole-game snapshots, onError(text) for refusals meant for this player.
  function start(onState, onError) {
    if (!window.webxdc || !window.webxdc.joinRealtimeChannel) {
      onError && onError("This messenger doesn't support live Mini Apps.");
      return;
    }
    ch = window.webxdc.joinRealtimeChannel();
    ch.setListener((data) => {
      let m;
      try { m = JSON.parse(dec.decode(data)); } catch (e) { return; }
      if (m.t === "error") {
        if (m.for && m.for !== addr) return;
        // "verifying your identity": the referee needs a moment to learn who we are, so ask again quietly.
        if (m.retry && last && tries < 8) { tries++; setTimeout(() => send(last, true), 1200); return; }
        onError && onError(m.msg);
        return;
      }
      if (m.t === "state") { seen = true; onState(m); }
    });
    const hello = () => send({ t: "hello" });
    hello();
    // The channel is ephemeral: keep saying hello until the referee answers.
    const retry = setInterval(() => (seen ? clearInterval(retry) : hello()), 2000);
  }

  window.net = { addr, send, start, mine: (m) => !m.for || m.for === addr };
})();
