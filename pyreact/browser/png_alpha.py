"""Read alpha coverage from non-interlaced, 8-bit PNG font atlases."""

import struct
import zlib
from pathlib import Path


def _paeth(left, above, upper_left):
    estimate = left + above - upper_left
    distances = (abs(estimate - left), abs(estimate - above),
                 abs(estimate - upper_left))
    return (left, above, upper_left)[distances.index(min(distances))]


def read_alpha(path):
    """Return (width, height, alpha bytes), rejecting unsupported/corrupt PNGs."""
    try:
        return _read_alpha(Path(path).read_bytes())
    except (ValueError, zlib.error, struct.error) as exc:
        raise ValueError('Invalid font PNG %s: %s' % (path, exc)) from exc


def _read_alpha(data):
    if data[:8] != b'\x89PNG\r\n\x1a\n':
        raise ValueError('invalid PNG signature')
    offset = 8
    header = None
    palette = None
    transparency = b''
    compressed = bytearray()
    ended = False
    while offset < len(data):
        if offset + 12 > len(data):
            raise ValueError('truncated PNG chunk')
        length = struct.unpack_from('>I', data, offset)[0]
        kind = data[offset + 4:offset + 8]
        end = offset + 8 + length
        if end + 4 > len(data):
            raise ValueError('truncated PNG chunk payload')
        payload = data[offset + 8:end]
        expected_crc = struct.unpack_from('>I', data, end)[0]
        if zlib.crc32(kind + payload) & 0xffffffff != expected_crc:
            raise ValueError('PNG chunk checksum mismatch')
        if header is None and kind != b'IHDR':
            raise ValueError('missing PNG header')
        if kind == b'IHDR':
            if header is not None or length != 13:
                raise ValueError('invalid PNG header')
            header = struct.unpack('>IIBBBBB', payload)
        elif kind == b'PLTE':
            if not length or length % 3 or length > 768:
                raise ValueError('invalid PNG palette')
            palette = payload
        elif kind == b'tRNS':
            transparency = payload
        elif kind == b'IDAT':
            compressed.extend(payload)
        elif kind == b'IEND':
            if length:
                raise ValueError('invalid PNG end chunk')
            ended = True
            break
        elif kind[0] & 32 == 0:
            raise ValueError('unsupported critical PNG chunk %r' % kind)
        offset = end + 4
    if header is None or not ended:
        raise ValueError('incomplete PNG')
    width, height, depth, color, compression, filtering, interlace = header
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}.get(color)
    if depth != 8 or channels is None or compression or filtering or interlace:
        raise ValueError('only non-interlaced 8-bit PNG atlases are supported')
    if not width or not height or width * height > 16777216:
        raise ValueError('invalid or oversized font atlas dimensions')
    if color == 3 and (palette is None or len(transparency) > len(palette) // 3):
        raise ValueError('missing or inconsistent PNG palette')
    if transparency and ((color == 0 and len(transparency) != 2) or
                         (color == 2 and len(transparency) != 6) or color in (4, 6)):
        raise ValueError('invalid PNG transparency')
    stride = width * channels
    expected = height * (stride + 1)
    decompressor = zlib.decompressobj()
    decoded = decompressor.decompress(bytes(compressed), expected + 1)
    if len(decoded) != expected or not decompressor.eof or decompressor.unused_data:
        raise ValueError('invalid PNG scanline length or compressed stream')
    result = bytearray(width * height)
    previous = bytearray(stride)
    transparent_gray = struct.unpack('>H', transparency)[0] if color == 0 and transparency else None
    transparent_rgb = struct.unpack('>HHH', transparency) if color == 2 and transparency else None
    for y in range(height):
        start = y * (stride + 1)
        mode = decoded[start]
        if mode > 4:
            raise ValueError('unsupported PNG row filter %s' % mode)
        row = bytearray(decoded[start + 1:start + 1 + stride])
        for index in range(stride):
            left = row[index - channels] if index >= channels else 0
            above = previous[index]
            upper_left = previous[index - channels] if index >= channels else 0
            predictor = (0, left, above, (left + above) // 2,
                         _paeth(left, above, upper_left))[mode]
            row[index] = (row[index] + predictor) & 255
        for x in range(width):
            index = x * channels
            if color in (4, 6):
                alpha = row[index + channels - 1]
            elif color == 3:
                entry = row[index]
                if entry >= len(palette) // 3:
                    raise ValueError('PNG palette index out of bounds')
                alpha = transparency[entry] if entry < len(transparency) else 255
            elif color == 0:
                alpha = 0 if row[index] == transparent_gray else 255
            else:
                alpha = 0 if tuple(row[index:index + 3]) == transparent_rgb else 255
            result[y * width + x] = alpha
        previous = row
    return width, height, bytes(result)
