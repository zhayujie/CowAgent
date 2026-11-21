# encoding:utf-8
"""
Remux WebM (Matroska) Opus audio into Ogg Opus without decoding.

Browsers record voice with MediaRecorder as WebM carrying Opus, while some
speech APIs only accept Ogg Opus. Both containers hold the same Opus packets,
so moving them across needs no codec, no ffmpeg and no third-party package.

References: RFC 7845 (Ogg Opus), RFC 6716 section 3.1 (TOC byte),
RFC 3533 (Ogg), RFC 9559 (Matroska).
"""
import random
import struct

_EBML_MAGIC = b"\x1a\x45\xdf\xa3"

_ID_SEGMENT = 0x18538067
_ID_CLUSTER = 0x1F43B675
_ID_TRACKS = 0x1654AE6B
_ID_TRACK_ENTRY = 0xAE
_ID_AUDIO = 0xE1
_ID_BLOCK_GROUP = 0xA0
_ID_TRACK_NUMBER = 0xD7
_ID_CODEC_ID = 0x86
_ID_CODEC_PRIVATE = 0x63A2
_ID_CODEC_DELAY = 0x56AA
_ID_CHANNELS = 0x9F
_ID_SAMPLING_FREQUENCY = 0xB5
_ID_SIMPLE_BLOCK = 0xA3
_ID_BLOCK = 0xA1

# Containers whose children matter; every other element is skipped whole.
_MASTER_IDS = {_ID_SEGMENT, _ID_CLUSTER, _ID_TRACKS, _ID_TRACK_ENTRY, _ID_AUDIO, _ID_BLOCK_GROUP}

_OGG_BOS = 0x02
_OGG_EOS = 0x04
_MAX_PAGE_SEGMENTS = 255
_DEFAULT_PRE_SKIP = 312  # libopus encoder delay at 48 kHz


def _build_crc_table():
    table = []
    for i in range(256):
        r = i << 24
        for _ in range(8):
            r = ((r << 1) ^ 0x04C11DB7) if r & 0x80000000 else (r << 1)
        table.append(r & 0xFFFFFFFF)
    return table


_CRC_TABLE = _build_crc_table()


def _ogg_crc(data) -> int:
    crc = 0
    for b in data:
        crc = ((crc << 8) & 0xFFFFFFFF) ^ _CRC_TABLE[((crc >> 24) & 0xFF) ^ b]
    return crc


def is_webm(path: str) -> bool:
    try:
        with open(path, "rb") as f:
            return f.read(4) == _EBML_MAGIC
    except OSError:
        return False


def is_ogg_opus(path: str) -> bool:
    try:
        with open(path, "rb") as f:
            head = f.read(64)
    except OSError:
        return False
    return head[:4] == b"OggS" and b"OpusHead" in head


def _read_vint(buf, pos: int, keep_marker: bool):
    """Return (value, length, is_unknown_size) of the EBML varint at pos."""
    if pos >= len(buf):
        raise ValueError("truncated EBML data")
    first = buf[pos]
    length, mask = 1, 0x80
    while length <= 8 and not first & mask:
        mask >>= 1
        length += 1
    if length > 8:
        raise ValueError("invalid EBML varint")
    if pos + length > len(buf):
        raise ValueError("truncated EBML data")
    value = first if keep_marker else first & (mask - 1)
    for b in buf[pos + 1:pos + length]:
        value = (value << 8) | b
    unknown = not keep_marker and value == (1 << (7 * length)) - 1
    return value, length, unknown


def _uint(data) -> int:
    return int.from_bytes(data, "big") if data else 0


def _float(data) -> float:
    if len(data) == 4:
        return struct.unpack(">f", data)[0]
    if len(data) == 8:
        return struct.unpack(">d", data)[0]
    return 0.0


def _parse_block(data):
    track, length, _ = _read_vint(data, 0, keep_marker=False)
    header = length + 3  # track number, int16 timecode, flags
    if len(data) < header:
        raise ValueError("truncated block")
    if data[length + 2] & 0x06:
        raise ValueError("laced blocks are not supported")
    return track, bytes(data[header:])


def _parse_webm(buf):
    tracks, packets = [], []
    pos, size_total = 0, len(buf)
    while pos < size_total:
        try:
            eid, id_len, _ = _read_vint(buf, pos, keep_marker=True)
            size, size_len, unknown = _read_vint(buf, pos + id_len, keep_marker=False)
        except ValueError:
            if packets:
                break  # trailing bytes of a recording that was cut off
            raise
        pos += id_len + size_len
        if eid in _MASTER_IDS:
            # Descend by reading on; this also covers the unknown-size
            # Segment / Cluster that live recordings are written with.
            if eid == _ID_TRACK_ENTRY:
                tracks.append({})
            continue
        if unknown:
            raise ValueError(f"unknown-size element 0x{eid:X}")
        end = pos + size
        if end > size_total:
            break
        data = buf[pos:end]
        pos = end
        if eid in (_ID_SIMPLE_BLOCK, _ID_BLOCK):
            packets.append(_parse_block(data))
        elif tracks:
            track = tracks[-1]
            if eid == _ID_TRACK_NUMBER:
                track["number"] = _uint(data)
            elif eid == _ID_CODEC_ID:
                track["codec"] = bytes(data).decode("ascii", "replace").rstrip("\x00")
            elif eid == _ID_CODEC_PRIVATE:
                track["private"] = bytes(data)
            elif eid == _ID_CODEC_DELAY:
                track["codec_delay"] = _uint(data)
            elif eid == _ID_CHANNELS:
                track["channels"] = _uint(data)
            elif eid == _ID_SAMPLING_FREQUENCY:
                track["rate"] = _float(data)
    return tracks, packets


def _opus_samples(packet: bytes) -> int:
    """Samples at 48 kHz carried by one Opus packet (RFC 6716 3.1)."""
    if not packet:
        return 0
    toc = packet[0]
    config = toc >> 3
    if config < 12:
        frame = (480, 960, 1920, 2880)[config & 3]
    elif config < 16:
        frame = (480, 960)[config & 1]
    else:
        frame = (120, 240, 480, 960)[config & 3]
    code = toc & 3
    if code == 0:
        count = 1
    elif code in (1, 2):
        count = 2
    else:
        count = packet[1] & 0x3F if len(packet) > 1 else 0
    return frame * count


def _opus_head(track) -> bytes:
    private = track.get("private") or b""
    if private[:8] == b"OpusHead" and len(private) >= 19:
        return private
    channels = track.get("channels") or 1
    if channels > 2:
        raise ValueError("multichannel Opus needs a channel mapping table")
    pre_skip = track.get("codec_delay", 0) * 48000 // 1_000_000_000 or _DEFAULT_PRE_SKIP
    rate = int(track.get("rate") or 48000)
    return struct.pack("<8sBBHIhB", b"OpusHead", 1, channels, pre_skip, rate, 0, 0)


def _opus_tags() -> bytes:
    vendor = b"webm-opus-remux"
    return b"OpusTags" + struct.pack("<I", len(vendor)) + vendor + struct.pack("<I", 0)


def _ogg_page(packets, granule: int, serial: int, seq: int, flags: int) -> bytes:
    lacing = bytearray()
    for p in packets:
        lacing.extend(b"\xff" * (len(p) // 255))
        lacing.append(len(p) % 255)
    header = struct.pack("<4sBBqIIIB", b"OggS", 0, flags, granule, serial, seq, 0, len(lacing))
    page = bytearray(header)
    page += lacing
    for p in packets:
        page += p
    struct.pack_into("<I", page, 22, _ogg_crc(page))
    return bytes(page)


def webm_to_ogg(src: str, dst: str) -> None:
    """Rewrite the Opus track of a WebM file as an Ogg Opus file.

    Raises ValueError when the input holds no usable Opus track.
    """
    with open(src, "rb") as f:
        buf = f.read()
    if buf[:4] != _EBML_MAGIC:
        raise ValueError("not a WebM/Matroska file")
    tracks, blocks = _parse_webm(buf)
    track = next((t for t in tracks if t.get("codec") == "A_OPUS"), None)
    if track is None:
        raise ValueError("no Opus audio track")
    number = track.get("number", 1)
    packets = [p for t, p in blocks if t == number and p]
    if not packets:
        raise ValueError("no Opus packets")

    serial = random.getrandbits(32)
    pages = [
        _ogg_page([_opus_head(track)], 0, serial, 0, _OGG_BOS),
        _ogg_page([_opus_tags()], 0, serial, 1, 0),
    ]
    seq, granule, batch, segments = 2, 0, [], 0
    for packet in packets:
        need = len(packet) // 255 + 1
        if batch and segments + need > _MAX_PAGE_SEGMENTS:
            pages.append(_ogg_page(batch, granule, serial, seq, 0))
            seq, batch, segments = seq + 1, [], 0
        batch.append(packet)
        segments += need
        granule += _opus_samples(packet)
    pages.append(_ogg_page(batch, granule, serial, seq, _OGG_EOS))

    with open(dst, "wb") as f:
        for page in pages:
            f.write(page)
