# Copyright 2025 New Vector Ltd.
# Copyright 2015 OpenMarket Ltd.
#
# SPDX-License-Identifier: AGPL-3.0-only OR LicenseRef-Element-Commercial
# Please see LICENSE files in the repository root for full details.
#
# Originally licensed under the Apache License, Version 2.0:
# <http://www.apache.org/licenses/LICENSE-2.0>.

# Copied and adapted from
# https://raw.githubusercontent.com/matrix-org/pushbaby/master/pushbaby/truncate.py
import json
import sys
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple, Union

if TYPE_CHECKING or sys.version_info < (3, 8, 0):
    from typing_extensions import Literal
else:
    from typing import Literal

Choppable = Union[
    Tuple[Literal["alert", "alert.body"]], Tuple[Literal["alert.loc-args"], int]
]


def json_encode(payload: Dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False).encode()


class BodyTooLongException(Exception):
    pass


def is_too_long(payload: Dict[Any, Any], max_length: int = 2048) -> bool:
    """
    Returns True if the given payload dictionary is too long for a push.
    Note that the maximum is now 2kB "In iOS 8 and later" although in
    practice, payloads over 256 bytes (the old limit) are still
    delivered to iOS 7 or earlier devices.

    Maximum is 4 kiB in the new APNs with the HTTP/2 interface.
    """
    return len(json_encode(payload)) > max_length


def truncate(payload: Dict[str, Any], max_length: int = 2048) -> Dict[str, Any]:
    """
    Truncate APNs fields to make the payload fit within the max length
    specified.
    Only truncates fields that are safe to do so.

    Args:
        payload: nested dict that will be passed to APNs
        max_length: Maximum length, in bytes, that the payload should occupy
            when JSON-encoded.

    Returns:
        Nested dict which should comply with the maximum length restriction.

    """
    payload = payload.copy()
    if "aps" not in payload:
        if is_too_long(payload, max_length):
            raise BodyTooLongException()
        else:
            return payload
    aps = payload["aps"]

    # first ensure all our choppables are str objects.
    # We need them to be for truncating to work and this
    # makes more sense than checking every time.
    for c in _choppables_for_aps(aps):
        val = _choppable_get(aps, c)
        if isinstance(val, bytes):
            _choppable_put(aps, c, val.decode())

    # chop off whole unicode characters until it fits (or we run out of chars)
    while is_too_long(payload, max_length):
        longest = _longest_choppable(aps)
        if longest is None:
            raise BodyTooLongException()

        txt = _choppable_get(aps, longest)
        # Note that python's support for this is actually broken on some OSes
        # (see test_apnstruncate.py)
        txt = txt[:-1]
        _choppable_put(aps, longest, txt)
        payload["aps"] = aps

    return payload


def _choppables_for_aps(aps: Dict[str, Any]) -> List[Choppable]:
    ret: List[Choppable] = []
    if "alert" not in aps:
        return ret

    alert = aps["alert"]
    if isinstance(alert, str):
        ret.append(("alert",))
    elif isinstance(alert, dict):
        if "body" in alert:
            ret.append(("alert.body",))
        if "loc-args" in alert:
            ret.extend([("alert.loc-args", i) for i in range(len(alert["loc-args"]))])

    return ret


def _choppable_get(
    aps: Dict[str, Any],
    choppable: Choppable,
) -> str:
    if choppable[0] == "alert":
        return aps["alert"]
    elif choppable[0] == "alert.body":
        return aps["alert"]["body"]
    elif choppable[0] == "alert.loc-args":
        return aps["alert"]["loc-args"][choppable[1]]


def _choppable_put(
    aps: Dict[str, Any],
    choppable: Choppable,
    val: str,
) -> None:
    if choppable[0] == "alert":
        aps["alert"] = val
    elif choppable[0] == "alert.body":
        aps["alert"]["body"] = val
    elif choppable[0] == "alert.loc-args":
        aps["alert"]["loc-args"][choppable[1]] = val


def _longest_choppable(aps: Dict[str, Any]) -> Optional[Choppable]:
    longest = None
    length_of_longest = 0
    for c in _choppables_for_aps(aps):
        val = _choppable_get(aps, c)
        val_len = len(val.encode())
        if val_len > length_of_longest:
            longest = c
            length_of_longest = val_len
    return longest
