// Vectiq verification page. Collects an age (when asked), runs the CAPTCHA and a
// light browser fingerprint, and posts them once. Ported from GateBot's flow.
(function () {
  "use strict";
  var root = document.getElementById("verify");
  var cfg = JSON.parse(root.dataset.config);
  var form = document.getElementById("form");
  var status = document.getElementById("status");
  var button = document.getElementById("go");
  var ageInput = document.getElementById("age");
  var token = "";

  function say(text, kind) {
    status.textContent = text;
    status.className = "status " + (kind || "");
  }

  function hash(text) {
    var h = 2166136261;
    for (var i = 0; i < text.length; i++) { h ^= text.charCodeAt(i); h = Math.imul(h, 16777619); }
    return (h >>> 0).toString(16);
  }

  // Eleven short strings. Not proof of identity: just enough to notice one device
  // verifying many accounts. Works without canvas and without cookies.
  function fingerprint() {
    var n = navigator, s = screen || {};
    var canvas = "";
    try {
      var c = document.createElement("canvas"), x = c.getContext("2d");
      if (x) { x.fillRect(2, 2, 40, 12); x.fillText("vectiq ✓", 4, 12); canvas = hash(c.toDataURL()); }
    } catch (e) { canvas = ""; }
    var tz = "";
    try { tz = Intl.DateTimeFormat().resolvedOptions().timeZone || ""; } catch (e) { tz = ""; }
    return JSON.stringify(["v1", String(n.userAgent || "").slice(0, 500), String(n.platform || ""),
      String((n.languages || []).join(",")).slice(0, 200), tz, (s.width || 0) + "x" + (s.height || 0),
      String(s.colorDepth || ""), String(n.hardwareConcurrency || ""), String(n.deviceMemory || ""),
      canvas, String(n.maxTouchPoints || 0)]);
  }

  function ready() {
    button.disabled = !(token && (!ageInput || ageInput.value));
  }

  function render() {
    var api = window.turnstile || window.hcaptcha || window.grecaptcha;
    if (!api || !api.render) { return setTimeout(render, 150); }
    try {
      api.render(document.getElementById("captcha"), {
        sitekey: cfg.siteKey,
        callback: function (t) { token = t; ready(); },
        "expired-callback": function () { token = ""; ready(); }
      });
    } catch (e) { say("The CAPTCHA couldn't load. Reload the page to try again.", "bad"); }
  }

  var s = document.createElement("script");
  s.src = cfg.scriptUrl; s.async = true;
  s.onerror = function () { say("The CAPTCHA couldn't load. Check your connection or turn off blockers for this page.", "bad"); };
  document.head.appendChild(s);
  render();
  if (ageInput) { ageInput.addEventListener("input", ready); }

  form.addEventListener("submit", function (e) {
    e.preventDefault();
    button.disabled = true;
    say("Checking…");
    var body = { captcha: token, fingerprint: fingerprint() };
    if (ageInput) { body.age = parseInt(ageInput.value, 10); }
    fetch(location.pathname, {
      method: "POST", credentials: "same-origin",
      headers: { "Content-Type": "application/json" }, body: JSON.stringify(body)
    }).then(function (r) { return r.json().then(function (d) { return [r.ok, d]; }); })
      .then(function (res) {
        if (res[0]) { form.hidden = true; say(res[1].message, "good"); }
        else {
          say(res[1].message || "That didn't work. Try again.", "bad");
          token = "";
          var api = window.turnstile || window.hcaptcha || window.grecaptcha;
          try { api && api.reset && api.reset(); } catch (err) { /* nothing to reset */ }
          ready();
        }
      })
      .catch(function () { say("Couldn't reach the server. Try again in a moment.", "bad"); ready(); });
  });
})();
