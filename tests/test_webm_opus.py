# encoding:utf-8
"""
Unit tests for the WebM -> Ogg Opus remuxer.

Covers:
  - the Ogg stream starts with OpusHead / OpusTags and ends with EOS
  - every page carries a valid CRC and the packets come through unchanged
  - the final granule position is the 48 kHz sample count of all packets
  - unknown-size Segment / Cluster (live MediaRecorder output) are handled
  - long recordings are split across pages within the 255-segment limit
  - a missing OpusHead is synthesized from the track settings
  - inputs without an Opus track are rejected
"""
import os
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from voice import webm_opus

_UNKNOWN_SIZE = b"\x01\xff\xff\xff\xff\xff\xff\xff"
_OPUS_HEAD = struct.pack("<8sBBHIhB", b"OpusHead", 1, 1, 312, 48000, 0, 0)


def _id(eid: int) -> bytes:
    return eid.to_bytes((eid.bit_length() + 7) // 8, "big")


def _el(eid: int, payload: bytes) -> bytes:
    return _id(eid) + b"\x01" + len(payload).to_bytes(7, "big") + payload


def _webm(packets, private=_OPUS_HEAD, codec=b"A_OPUS", truncate=0):
    track = _el(0xAE, _el(0xD7, b"\x01") + _el(0x86, codec)
                + (_el(0x63A2, private) if private else b"")
                + _el(0x56AA, (6500000).to_bytes(4, "big"))
                + _el(0xE1, _el(0x9F, b"\x01") + _el(0xB5, struct.pack(">f", 48000.0))))
    blocks = b"".join(_el(0xA3, b"\x81\x00\x00\x80" + p) for p in packets)
    cluster = _id(0x1F43B675) + _UNKNOWN_SIZE + _el(0xE7, b"\x00") + blocks
    segment = (_id(0x18538067) + _UNKNOWN_SIZE + _el(0x1549A966, b"\x2a\xd7\xb1\x83\x0f\x42\x40")
               + _el(0x1654AE6B, track) + cluster)
    data = _el(0x1A45DFA3, _el(0x4282, b"webm")) + segment
    return data[:len(data) - truncate] if truncate else data


def _read_pages(data):
    pages, pos = [], 0
    while pos < len(data):
        assert data[pos:pos + 4] == b"OggS"
        nseg = data[pos + 26]
        lacing = data[pos + 27:pos + 27 + nseg]
        end = pos + 27 + nseg + sum(lacing)
        raw = bytearray(data[pos:end])
        crc = struct.unpack_from("<I", raw, 22)[0]
        raw[22:26] = b"\x00\x00\x00\x00"
        packets, body, current = [], pos + 27 + nseg, b""
        for n in lacing:
            current += data[body:body + n]
            body += n
            if n < 255:
                packets.append(current)
                current = b""
        pages.append({
            "flags": data[pos + 5],
            "granule": struct.unpack_from("<q", data, pos + 6)[0],
            "seq": struct.unpack_from("<I", data, pos + 18)[0],
            "segments": nseg,
            "crc_ok": crc == webm_opus._ogg_crc(raw),
            "packets": packets,
        })
        pos = end
    return pages


def _remux(webm_bytes):
    with tempfile.TemporaryDirectory() as tmp:
        src, dst = os.path.join(tmp, "a.webm"), os.path.join(tmp, "a.ogg")
        with open(src, "wb") as f:
            f.write(webm_bytes)
        webm_opus.webm_to_ogg(src, dst)
        is_ogg = webm_opus.is_ogg_opus(dst)
        with open(dst, "rb") as f:
            return _read_pages(f.read()), is_ogg


# 20 ms CELT, 20 ms hybrid, and a code-3 packet holding three 20 ms frames.
_PACKETS = [b"\xf8" + b"a" * 40, b"\x78" + b"b" * 600, b"\xfb\x03" + b"c" * 90]


class TestWebmToOgg(unittest.TestCase):
    def test_header_pages_and_packets(self):
        pages, is_ogg = _remux(_webm(_PACKETS))
        self.assertTrue(is_ogg)
        self.assertTrue(all(p["crc_ok"] for p in pages))
        self.assertEqual(pages[0]["packets"], [_OPUS_HEAD])
        self.assertEqual(pages[0]["flags"], 0x02)
        self.assertTrue(pages[1]["packets"][0].startswith(b"OpusTags"))
        self.assertEqual([p["seq"] for p in pages], list(range(len(pages))))
        data = [pkt for p in pages[2:] for pkt in p["packets"]]
        self.assertEqual(data, _PACKETS)
        self.assertEqual(pages[-1]["flags"], 0x04)
        self.assertEqual(pages[-1]["granule"], 960 + 960 + 2880)

    def test_long_recording_spans_pages(self):
        packets = [b"\xf8" + bytes([i % 256]) * 3 for i in range(600)]
        pages, _ = _remux(_webm(packets))
        data_pages = pages[2:]
        self.assertGreater(len(data_pages), 1)
        self.assertTrue(all(p["segments"] <= 255 for p in pages))
        self.assertTrue(all(p["crc_ok"] for p in pages))
        self.assertEqual([pkt for p in data_pages for pkt in p["packets"]], packets)
        granules = [p["granule"] for p in data_pages]
        self.assertEqual(granules, sorted(granules))
        self.assertEqual(granules[-1], 600 * 960)

    def test_cut_off_recording_keeps_complete_blocks(self):
        pages, _ = _remux(_webm(_PACKETS, truncate=10))
        self.assertEqual([pkt for p in pages[2:] for pkt in p["packets"]], _PACKETS[:2])

    def test_missing_opus_head_is_synthesized(self):
        pages, _ = _remux(_webm(_PACKETS, private=b""))
        head = pages[0]["packets"][0]
        magic, version, channels, pre_skip, rate, _, _ = struct.unpack("<8sBBHIhB", head)
        self.assertEqual((magic, version, channels, rate), (b"OpusHead", 1, 1, 48000))
        self.assertEqual(pre_skip, 312)

    def test_non_opus_track_is_rejected(self):
        with self.assertRaises(ValueError):
            _remux(_webm(_PACKETS, codec=b"A_VORBIS"))

    def test_non_webm_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "a.webm")
            with open(src, "wb") as f:
                f.write(b"not webm")
            self.assertFalse(webm_opus.is_webm(src))
            with self.assertRaises(ValueError):
                webm_opus.webm_to_ogg(src, os.path.join(tmp, "a.ogg"))


if __name__ == "__main__":
    unittest.main()
