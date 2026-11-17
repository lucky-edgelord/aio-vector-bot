"""Picture checks for the image guard: a perceptual hash, and pluggable nudity detectors.

Detectors (``imageguard.detector``):

* ``off``: only the blocklist of known pictures
* ``nudenet``: NudeNet, runs on this computer (``pip install "vectiq[nudenet]"``)
* ``nsfw-detector``: GantMan's nsfw_model through the ``nsfw-detector`` package, runs on this computer
  (``pip install "vectiq[nsfw-detector]"`` plus a downloaded model, see the docs). TensorFlow, GPLv3.
* ``sightengine``: the Sightengine API (an account and two keys)
* ``http``: any web API you run or rent that takes a picture and answers with a score in JSON

Local models are imported the first time a picture is checked, never at start-up, and run in a thread.
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import os
import tempfile
import urllib.request
import uuid
from typing import Any

from PIL import Image

log = logging.getLogger("vectiq.imagecheck")

DETECTORS = ("off", "nudenet", "nsfw-detector", "sightengine", "http")
NUDENET_UNSAFE = {"FEMALE_GENITALIA_EXPOSED", "MALE_GENITALIA_EXPOSED", "FEMALE_BREAST_EXPOSED",
                  "BUTTOCKS_EXPOSED", "ANUS_EXPOSED"}
SIGHTENGINE = "https://api.sightengine.com/1.0/check.json"


class DetectorUnavailable(RuntimeError):
    """The detector can't run: a package or key is missing. The message says how to fix it."""


def open_image(data: bytes) -> Image.Image:
    img = Image.open(io.BytesIO(data))
    img.seek(0)                      # first frame of a GIF / animated WebP
    return img.convert("RGB")


def dhash(data: bytes | Image.Image, size: int = 8) -> str:
    """A 64-bit difference hash as 16 hex digits. Re-encoded, resized or slightly edited copies stay close."""
    img = data if isinstance(data, Image.Image) else open_image(data)
    small = img.convert("L").resize((size + 1, size), Image.Resampling.LANCZOS)
    px = small.tobytes()
    bits = 0
    for row in range(size):
        for col in range(size):
            bits = (bits << 1) | (px[row * (size + 1) + col] > px[row * (size + 1) + col + 1])
    return f"{bits:0{size * size // 4}x}"


def _jpeg(img: Image.Image) -> bytes:
    out = io.BytesIO()
    img.save(out, "JPEG", quality=90)
    return out.getvalue()


class Detector:
    """Turns picture bytes into an (unsafe score 0..1, label) pair."""

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.name = str(cfg.get("detector", "off"))
        self._model: Any = None
        self.cfg_key: Any = None

    # -- local models (loaded once, lazily) ----------------------------------------------

    def _nudenet(self, img: Image.Image) -> tuple[float, str]:
        if self._model is None:
            try:
                from nudenet import NudeDetector
            except ImportError as exc:
                raise DetectorUnavailable('NudeNet isn\'t installed: pip install "vectiq[nudenet]"') from exc
            self._model = NudeDetector()
        with tempfile.NamedTemporaryFile(suffix=".jpg") as f:
            f.write(_jpeg(img))
            f.flush()
            found = self._model.detect(f.name) or []
        hits = [(float(d.get("score", 0)), d.get("class", "")) for d in found if d.get("class") in NUDENET_UNSAFE]
        return max(hits, default=(0.0, "safe"))

    def _nsfw_detector(self, img: Image.Image) -> tuple[float, str]:
        if self._model is None:
            try:
                from nsfw_detector import predict
            except ImportError as exc:
                raise DetectorUnavailable('nsfw-detector isn\'t installed: pip install "vectiq[nsfw-detector]"') from exc
            path = (self.cfg.get("nsfw_detector") or {}).get("model_path", "")
            if not path or not os.path.exists(path):
                raise DetectorUnavailable("nsfw-detector needs a model: set imageguard.nsfw_detector.model_path to the "
                                          "downloaded .h5 file (see the image guard docs)")
            self._model = (predict, predict.load_model(path))
        predict, model = self._model
        with tempfile.NamedTemporaryFile(suffix=".jpg") as f:
            f.write(_jpeg(img))
            f.flush()
            scores = next(iter(predict.classify(model, f.name).values()), {})
        unsafe = ["porn", "hentai"] + (["sexy"] if (self.cfg.get("nsfw_detector") or {}).get("count_sexy") else [])
        label = max(unsafe, key=lambda k: scores.get(k, 0))
        return float(sum(scores.get(k, 0) for k in unsafe)), label

    # -- web APIs -------------------------------------------------------------------------

    def _post(self, url: str, img: Image.Image, fields: dict, headers: dict | None = None) -> dict:
        boundary = uuid.uuid4().hex
        body = io.BytesIO()
        for k, v in fields.items():
            body.write(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
        body.write(f'--{boundary}\r\nContent-Disposition: form-data; name="media"; filename="image.jpg"\r\n'
                   "Content-Type: image/jpeg\r\n\r\n".encode() + _jpeg(img) + f"\r\n--{boundary}--\r\n".encode())
        req = urllib.request.Request(url, data=body.getvalue(), method="POST",
                                     headers={"Content-Type": f"multipart/form-data; boundary={boundary}",
                                              "User-Agent": "Vectiq image guard", **(headers or {})})
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read() or b"{}")

    def _sightengine(self, img: Image.Image) -> tuple[float, str]:
        c = self.cfg.get("sightengine") or {}
        user, secret = os.environ.get(c.get("user_env", "SIGHTENGINE_USER"), ""), \
            os.environ.get(c.get("secret_env", "SIGHTENGINE_SECRET"), "")
        if not user or not secret:
            raise DetectorUnavailable("Sightengine needs SIGHTENGINE_USER and SIGHTENGINE_SECRET in .env")
        out = self._post(SIGHTENGINE, img, {"models": c.get("models", "nudity-2.1"), "api_user": user,
                                            "api_secret": secret})
        if out.get("status") != "success":
            raise RuntimeError((out.get("error") or {}).get("message", "Sightengine refused the picture"))
        nudity = out.get("nudity") or {}
        keys = ["sexual_activity", "sexual_display", "erotica"] + (["very_suggestive"] if c.get("strict") else [])
        label = max(keys, key=lambda k: float(nudity.get(k, 0) or 0))
        return float(nudity.get(label, 0) or 0), label

    def _http(self, img: Image.Image) -> tuple[float, str]:
        c = self.cfg.get("http") or {}
        if not c.get("url"):
            raise DetectorUnavailable("set imageguard.http.url to your API")
        headers = {}
        if c.get("header") and c.get("header_env"):
            headers[c["header"]] = os.environ.get(c["header_env"], "")
        node: Any = self._post(c["url"], img, {}, headers)
        for part in str(c.get("score_field", "score")).split("."):
            node = node.get(part, 0) if isinstance(node, dict) else 0
        return float(node or 0), str(c.get("score_field", "score"))

    # -- entry point ----------------------------------------------------------------------

    def _run(self, img: Image.Image) -> tuple[float, str]:
        fn = {"nudenet": self._nudenet, "nsfw-detector": self._nsfw_detector, "sightengine": self._sightengine,
              "http": self._http}.get(self.name)
        return fn(img) if fn else (0.0, "off")

    async def score(self, img: Image.Image) -> tuple[float, str]:
        return await asyncio.to_thread(self._run, img)
