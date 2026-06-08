#!/usr/bin/env python3
"""Convert Composer's Mosaic MOSA documents to MusicXML."""

from __future__ import annotations

import argparse
import dataclasses
import math
import re
import struct
import sys
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from pathlib import Path

def u16(data: bytes, off: int) -> int:
    return struct.unpack_from('>H', data, off)[0]

def s16(data: bytes, off: int) -> int:
    return struct.unpack_from('>h', data, off)[0]

def u32(data: bytes, off: int) -> int:
    return struct.unpack_from('>I', data, off)[0]

def macroman(data: bytes) -> str:
    return data.decode('mac_roman', errors='replace')

@dataclasses.dataclass(frozen=True)
class MusicXmlClef:
    sign: str
    line: int | None = None
    octave_change: int | None = None

@dataclasses.dataclass(frozen=True)
class MusicXmlEnding:
    number: str
    type: str
    text: str = ''

@dataclasses.dataclass(frozen=True)
class MusicXmlBarline:
    location: str
    style: str | None = None
    repeat: str | None = None
    endings: tuple[MusicXmlEnding, ...] = ()
TEXT_SYMBOL_ALIASES = {0: 'metronome-mark', 1: 'system-text', 2: 'rehearsal-mark', 3: 'segno', 4: 'staff-text', 5: 'da-capo', 6: 'dal-segno', 7: 'coda', 65535: 'custom-text'}
HAIRPIN_SYMBOL_ALIASES = {0: 'crescendo', 1: 'diminuendo'}
DYNAMIC_SYMBOL_ALIASES = {0: 'ppp', 1: 'pp', 2: 'p', 3: 'mp', 4: 'mf', 5: 'f', 6: 'ff', 7: 'fff', 8: 'sf', 9: 'fz', 10: 'sfz', 11: 'fp'}

def decode_dynamic_display_control_token(token: bytes) -> int | None:
    if len(token) == 2 and token[0] == 48 and (128 <= token[1] <= 137):
        return token[1] & 127
    if len(token) == 3 and token[0] == 48 and (token[1] == 10) and (token[2] in (138, 139)):
        return token[2] & 127
    return None

def dynamic_display_control_label(symbol: int) -> str:
    alias = DYNAMIC_SYMBOL_ALIASES.get(symbol, f'dynamic-{symbol}')
    return f'dyna-control Dynamics:Dyna/symbol={symbol}/{alias}/tool=133/display-index'
ORNAMENT_SYMBOL_ALIASES = {0: 'mosaic-ornament-0', 1: 'mosaic-ornament-1', 2: 'mosaic-ornament-2', 3: 'mosaic-ornament-3', 4: 'mosaic-ornament-4', 5: 'mosaic-ornament-5', 6: 'mosaic-ornament-6', 7: 'mosaic-ornament-7', 8: 'mosaic-ornament-8', 9: 'mosaic-ornament-9', 10: 'jazz-ornament-10', 11: 'jazz-ornament-11', 12: 'jazz-ornament-12', 13: 'jazz-ornament-13', 14: 'jazz-ornament-14', 15: 'jazz-ornament-15', 16: 'jazz-ornament-16', 17: 'jazz-ornament-17', 18: 'jazz-ornament-18', 19: 'jazz-ornament-19', 20: 'jazz-ornament-20', 21: 'jazz-ornament-21', 22: 'jazz-ornament-22', 23: 'jazz-ornament-23', 24: 'mosaic-ornament-24', 25: 'mosaic-ornament-25', 26: 'mosaic-ornament-26', 27: 'mosaic-ornament-27', 28: 'mosaic-ornament-28', 29: 'mosaic-ornament-29'}
CONTROL_KIND_BY_SYMBOL_TYPE = {'Acc': 'acc-control', 'CAcc': 'cacc-control', 'BLin': 'blin-control', 'Chrd': 'chrd-control', 'Dyna': 'dyna-control', 'Grup': 'grup-control', 'Hair': 'hair-control', 'MRpt': 'mrpt-control', 'Orna': 'orna-control', 'SBra': 'sbra-control', 'Text': 'text-control', 'Tie': 'tie-control', 'Tupl': 'tupl-control'}
LAYOUT_FINAL_BYTES = frozenset({0, 35, 36, 37, 38, 39, 40, 76, 77, 78, 79, 80, 81, 82, 83, 84, 85, 86, 87, 88, 89, 90, 91, 92, 93, 94, 95, 103, 104, 105, 106, 107, 108, 109, 110, 111, 118, 119, 120, 121, 122, 123, 124, 125, 126, 127, 128, 129, 130, 131, 132, 133, 134, 135, 136, 137, 139, 141, 142, 143, 144, 145, 146, 147, 148, 149, 150, 151, 152, 153, 154, 156, 157, 158, 159, 160, 161, 162, 163, 164, 165, 166, 167, 168, 169, 170, 171, 172, 173, 174, 175, 176, 177, 178, 180, 181, 182, 183, 186, 187, 241, 243, 245, 247, 251, 252})
FINAL_BYTE_TOOL_CONTROLS = {42: ('Grup', 0, 'grouping'), **{43 + index: ('Orna', 10 + index, ORNAMENT_SYMBOL_ALIASES.get(10 + index, f'ornament-{10 + index}')) for index in range(14)}, 101: ('MRpt', 1, 'measure-repeat'), 102: ('MRpt', 2, 'measure-repeat'), 112: ('Grup', 0, 'grouping'), 113: ('Grup', 0, 'grouping'), 114: ('Grup', 0, 'grouping'), 115: ('Text', 4, TEXT_SYMBOL_ALIASES.get(4, 'staff-text')), 116: ('Text', 1, TEXT_SYMBOL_ALIASES.get(1, 'system-text')), 184: ('Chrd', 0, 'chord-symbol'), 185: ('Chrd', 1, 'chord-symbol'), **{188 + index: ('Orna', index, ORNAMENT_SYMBOL_ALIASES.get(index, f'ornament-{index}')) for index in range(10)}, 198: ('Dyna', 2, DYNAMIC_SYMBOL_ALIASES[2]), 199: ('Dyna', 3, DYNAMIC_SYMBOL_ALIASES[3]), 200: ('Dyna', 1, DYNAMIC_SYMBOL_ALIASES[1]), 201: ('Dyna', 0, DYNAMIC_SYMBOL_ALIASES[0]), 202: ('Dyna', 5, DYNAMIC_SYMBOL_ALIASES[5]), 203: ('Dyna', 4, DYNAMIC_SYMBOL_ALIASES[4]), 204: ('Dyna', 6, DYNAMIC_SYMBOL_ALIASES[6]), 205: ('Dyna', 7, DYNAMIC_SYMBOL_ALIASES[7]), 206: ('Dyna', 8, DYNAMIC_SYMBOL_ALIASES[8]), 207: ('Dyna', 9, DYNAMIC_SYMBOL_ALIASES[9]), 208: ('Dyna', 10, DYNAMIC_SYMBOL_ALIASES[10]), 209: ('Dyna', 11, DYNAMIC_SYMBOL_ALIASES[11]), 210: ('Hair', 0, HAIRPIN_SYMBOL_ALIASES[0]), 211: ('Hair', 1, HAIRPIN_SYMBOL_ALIASES[1]), **{212 + index: ('BLin', index, f'barline-{index}') for index in range(10)}, 222: ('BLin', 10, 'barline-10'), 224: ('BLin', 11, 'barline-11'), 225: ('MRpt', 16386, 'measure-repeat'), 226: ('Text', 5, TEXT_SYMBOL_ALIASES.get(5, 'da-capo')), 227: ('Text', 6, TEXT_SYMBOL_ALIASES.get(6, 'dal-segno')), 228: ('Text', 3, TEXT_SYMBOL_ALIASES.get(3, 'segno')), 229: ('Text', 7, TEXT_SYMBOL_ALIASES.get(7, 'coda')), 230: ('Grup', 0, 'grouping'), 231: ('Tie', 0, 'tie'), 232: ('Grup', 0, 'grouping'), 234: ('Tupl', 0, 'tuplet'), 238: ('SBra', 0, 'system-bracket-0'), 239: ('SBra', 1, 'system-bracket-1'), 240: ('Text', 2, TEXT_SYMBOL_ALIASES.get(2, 'rehearsal-mark')), 242: ('Text', 0, TEXT_SYMBOL_ALIASES.get(0, 'metronome-mark')), 244: ('Text', 65535, TEXT_SYMBOL_ALIASES.get(65535, 'custom-text')), 246: ('Text', 65535, TEXT_SYMBOL_ALIASES.get(65535, 'custom-text')), 247: ('Artc', 20, 'articulation-20'), 251: ('Artc', 21, 'articulation-21')}

def has_layout_final_byte(token: bytes) -> bool:
    if not token:
        return False
    final = token[-1]
    return final in LAYOUT_FINAL_BYTES or final in range(128, 141) or final >= 248

def control_palette_label(palette: int) -> str:
    control = FINAL_BYTE_TOOL_CONTROLS.get(palette)
    if control is None:
        return f'palette=0x{palette:02x}'
    symbol_type, symbol, alias = control
    return f'type={symbol_type}/symbol={symbol}/{alias}/palette=0x{palette:02x}'

def decoded_tool_control_label(token: bytes) -> tuple[str, str] | None:
    if not token:
        return None
    if token[0] in (112, 113, 114):
        return ('grouping-span-control', mosaic_category18_control_detail(token))
    if token[0] == 42:
        return ('grouping-span-control', token.hex(' '))
    if token[0] == 96:
        return ('span-control', mosaic_category18_control_detail(token))
    if token[0] in (64, 72, 76, 78):
        return ('note-display-control', token.hex(' '))
    display_control = decoded_display_control_label(token)
    if display_control is not None:
        return display_control
    control = FINAL_BYTE_TOOL_CONTROLS.get(token[-1])
    if control is None:
        return None
    symbol_type, _symbol, _alias = control
    if symbol_type == 'Orna' and token[-1] < 188 and (not (token[0] & 128 and len(token) <= 2)):
        return None
    kind = CONTROL_KIND_BY_SYMBOL_TYPE.get(symbol_type)
    if kind is None:
        return None
    if token[0] & 128 and len(token) <= 2:
        return (kind, control_palette_label(token[-1]))
    if len(token) == 2 and token[0] == 68:
        return (kind, control_palette_label(token[-1]))
    if token[0] < 128:
        return (kind, control_palette_label(token[-1]))
    return None

def parse_time_signature_text(value: str) -> tuple[int, int]:
    match = re.fullmatch('\\s*(\\d+)\\s*/\\s*(\\d+)\\s*', value)
    if match is None:
        raise argparse.ArgumentTypeError('expected a time signature like 4/4 or 6/8')
    beats = int(match.group(1))
    beat_type = int(match.group(2))
    if beats < 1 or beats > 64:
        raise argparse.ArgumentTypeError('beats must be in the range 1..64')
    if beat_type not in {1, 2, 4, 8, 16, 32, 64}:
        raise argparse.ArgumentTypeError('beat type must be 1, 2, 4, 8, 16, 32, or 64')
    return (beats, beat_type)
KEY_FIFTHS_MAJOR = {'Cb': -7, 'Gb': -6, 'Db': -5, 'Ab': -4, 'Eb': -3, 'Bb': -2, 'F': -1, 'C': 0, 'G': 1, 'D': 2, 'A': 3, 'E': 4, 'B': 5, 'F#': 6, 'C#': 7}
KEY_FIFTHS_MINOR = {'Ab': -7, 'Eb': -6, 'Bb': -5, 'F': -4, 'C': -3, 'G': -2, 'D': -1, 'A': 0, 'E': 1, 'B': 2, 'F#': 3, 'C#': 4, 'G#': 5, 'D#': 6, 'A#': 7}
FLAT_SIGN = '♭'
SHARP_SIGN = '♯'

def normalize_key_root(value: str) -> str:
    value = value.strip().replace(FLAT_SIGN, 'b').replace(SHARP_SIGN, '#')
    if not value:
        return value
    return value[0].upper() + value[1:]

def parse_key_signature_text(value: str) -> tuple[int, str]:
    text = value.strip().replace(FLAT_SIGN, 'b').replace(SHARP_SIGN, '#')
    lower = text.lower()
    mode = 'major'
    root_text = text
    for suffix in (' minor', ' min'):
        if lower.endswith(suffix):
            mode = 'minor'
            root_text = text[:-len(suffix)]
            break
    else:
        for suffix in (' major', ' maj'):
            if lower.endswith(suffix):
                mode = 'major'
                root_text = text[:-len(suffix)]
                break
        else:
            if len(text) > 1 and lower.endswith('m') and (not lower.endswith('maj')):
                mode = 'minor'
                root_text = text[:-1]
    root = normalize_key_root(root_text)
    table = KEY_FIFTHS_MINOR if mode == 'minor' else KEY_FIFTHS_MAJOR
    if root not in table:
        raise argparse.ArgumentTypeError('expected a key like C, Bb, F#, Am, or G minor')
    return (table[root], mode)

def printable_strings(data: bytes, start: int, end: int, min_len: int) -> list[tuple[int, int, str]]:
    strings: list[tuple[int, int, str]] = []
    start = max(0, start)
    end = min(len(data), end)
    for match in re.finditer(b'[\\x20-\\x7e]{%d,}' % min_len, data[start:end]):
        off = start + match.start()
        strings.append((off, match.end() - match.start(), macroman(match.group(0))))
    return strings
NOTE_DURATION_CODES = {1: 'whole', 2: 'half', 3: 'quarter', 4: 'eighth', 5: '16th', 6: '32nd', 7: '64th'}
PITCH_STEPS = ['C', 'D', 'E', 'F', 'G', 'A', 'B']
MOSAIC_TOKEN_CATEGORY_RULES: tuple[tuple[int, int], ...] = ((128, 128), (0, 240), (24, 248), (32, 240), (48, 240), (64, 255), (65, 255), (66, 255), (67, 255), (68, 255), (69, 255), (70, 255), (71, 255), (72, 255), (73, 255), (74, 255), (75, 255), (76, 255), (96, 224), (78, 254), (80, 252), (84, 252), (88, 252), (92, 254))

def mosaic_token_category(lead_byte: int) -> int:
    for category in range(len(MOSAIC_TOKEN_CATEGORY_RULES) - 1, -1, -1):
        value, mask = MOSAIC_TOKEN_CATEGORY_RULES[category]
        if lead_byte & mask == value:
            return category
    return -1

@dataclasses.dataclass(frozen=True)
class PreGridSection:
    marker: int
    off: int
    end: int
    name: str
    count: int
    header: bytes
    records: list[bytes]
    extra_count: int | None = None
    extra_records: list[bytes] = dataclasses.field(default_factory=list)

@dataclasses.dataclass(frozen=True)
class MusicCell:
    index: int
    off: int
    length: int
    payload: bytes
    gap_after: bytes
    parts: tuple[int, int, int] = (0, 0, 0)

def music_cell_structural_prefix_len(cell: MusicCell) -> int:
    prefix_len = cell.parts[0] + cell.parts[1]
    if prefix_len <= 0:
        return 0
    if prefix_len >= len(cell.payload):
        return max(0, len(cell.payload) - 1) if cell.payload.endswith(b'M') else len(cell.payload)
    return prefix_len

def music_cell_event_payload(cell: MusicCell) -> bytes:
    prefix_len = music_cell_structural_prefix_len(cell)
    payload = cell.payload[prefix_len:]
    return payload or b'M'

def music_cell_grouping_scale_side_payload(cell: MusicCell) -> bytes:
    if cell.parts[1] <= 0:
        return b''
    start = cell.parts[0]
    end = start + cell.parts[1]
    return cell.payload[start:end]

def mosaic_grouping_side_entry_next_offset(data: bytes, off: int) -> int:
    pos = off
    while pos < len(data):
        value = data[pos]
        pos += 1
        if value & 128:
            break
    if pos < len(data) and (not data[pos] & 120):
        while pos < len(data):
            value = data[pos]
            pos += 1
            if value & 128:
                break
    return pos

def mosaic_grouping_scale_side_entries(data: bytes) -> tuple[MosaicGroupingScaleEntry, ...]:
    entries: list[MosaicGroupingScaleEntry] = []
    off = 0
    while off < len(data):
        payload_fields = mosaic_category18_payload_fields(data[off:])
        if payload_fields is None:
            break
        ratio = mosaic_grouping_scale_ratio_from_payload_fields(payload_fields)
        next_off = mosaic_grouping_side_entry_next_offset(data, off)
        raw = data[off:off + payload_fields['length']]
        if ratio is not None:
            actual_notes, normal_notes = ratio
            entries.append(MosaicGroupingScaleEntry(len(entries), off, raw, actual_notes, normal_notes, payload_fields))
        if next_off <= off:
            break
        off = next_off
    return tuple(entries)

def music_cell_grouping_scale_entries(cell: MusicCell) -> tuple[MosaicGroupingScaleEntry, ...]:
    return mosaic_grouping_scale_side_entries(music_cell_grouping_scale_side_payload(cell))

@dataclasses.dataclass(frozen=True)
class MusicRow:
    index: int
    off: int
    end: int
    header: tuple[int, int, int]
    prefix: bytes
    cells: list[MusicCell]

@dataclasses.dataclass(frozen=True)
class MusicGrid:
    marker_off: int
    end: int
    columns: int
    row_count: int
    rows: list[MusicRow]

@dataclasses.dataclass(frozen=True)
class MusicXmlNotehead:
    value: str
    filled: bool | None = None
    parentheses: bool | None = None

@dataclasses.dataclass(frozen=True)
class MusicEvent:
    kind: str
    duration_name: str
    pitch: str = ''
    alter: int = 0
    raw: str = ''
    text: str = ''
    accidental: str = ''
    accidental_cautionary: bool = False
    articulations: tuple[str, ...] = ()
    ornaments: tuple[str, ...] = ()
    dots: int = 0
    chord: bool = False
    ties: tuple[str, ...] = ()
    slurs: tuple[tuple[str, int], ...] = ()
    mosaic_slur_positions: tuple[tuple[int, int], ...] = ()
    time_modification: tuple[int, int] | None = None
    tuplets: tuple[tuple[str, int], ...] = ()
    mosaic_tuplet_indices: tuple[int, ...] = ()
    display_code: int | None = None
    chromatic_alter: bool = False
    notehead: MusicXmlNotehead | None = None
    duration_divisions: int | None = None
    stem: str = ''

@dataclasses.dataclass(frozen=True)
class ScannedMusicToken:
    kind: str
    off: int
    length: int
    raw: str
    detail: str = ''

@dataclasses.dataclass(frozen=True)
class MosaicMusicTokenGroup:
    index: int
    start: int
    tokens: tuple[ScannedMusicToken, ...]

@dataclasses.dataclass(frozen=True)
class MosaicPartInfo:
    index: int
    off: int
    end: int
    name: str
    name_extra: str
    header: bytes
    name_len: int
    flags: tuple[int, int, int]
    blob_len: int

@dataclasses.dataclass(frozen=True)
class MosaicGroupingScaleEntry:
    index: int
    off: int
    raw: bytes
    actual_notes: int
    normal_notes: int
    payload_fields: dict[str, int]

@dataclasses.dataclass(frozen=True)
class MosaicVoiceInfo:
    index: int
    off: int
    end: int
    name: str
    header: bytes

@dataclasses.dataclass(frozen=True)
class MosaicVoiceLaneRef:
    section: str
    rel_off: int
    list_index: int
    list_secondary: int
    entry_index: int
    lane: int
    voice_ids: tuple[int, ...]
    header: bytes

@dataclasses.dataclass(frozen=True)
class MosaicVoiceLaneList:
    section: str
    rel_off: int
    list_index: int
    declared_count: int
    secondary: int
    entries: tuple[MosaicVoiceLaneRef, ...]

@dataclasses.dataclass(frozen=True)
class MosaicVoiceLaneBlock:
    marker: int
    section: str
    rel_off: int
    declared_count: int
    fields: tuple[int, ...]
    lists: tuple[MosaicVoiceLaneList, ...] = ()
    entries: tuple[MosaicVoiceLaneRef, ...] = ()

@dataclasses.dataclass(frozen=True)
class MosaicStaffVoiceInfo:
    part_index: int
    voice_ids: tuple[int, ...]
    abbreviation: str = ''
    lane_blocks: tuple[MosaicVoiceLaneBlock, ...] = ()

@dataclasses.dataclass(frozen=True)
class MosaicVoiceStreamRef:
    voice_id: int
    source_part_index: int
    source_kind: str = 'direct'

@dataclasses.dataclass(frozen=True)
class MosaicStaffVoicePlan:
    part_index: int
    streams: tuple[MosaicVoiceStreamRef, ...]

@dataclasses.dataclass(frozen=True)
class PostGridSectionSpec:
    marker: int
    name: str
    fixed_record_count: int
    fixed_record_size: int
    entry_size: int
    header_after_count_size: int = 0
    min_version: int = 0
    old_fixed_version_lt: int | None = None
    old_fixed_record_count: int | None = None

@dataclasses.dataclass(frozen=True)
class PostGridSection:
    marker: int
    off: int
    end: int
    count: int
    header_after_count: bytes
    fixed_records: list[bytes]
    entries: list[bytes]
    spec: PostGridSectionSpec | None

@dataclasses.dataclass(frozen=True)
class MosaicTailSection33:
    off: int
    end: int
    records: list[bytes]
    nested_001f: PostGridSection | None

@dataclasses.dataclass(frozen=True)
class MosaicDocumentInfo:
    off: int
    end: int
    fields: list[str]
MOSAIC_DOCUMENT_FIELD_LABELS: tuple[str, ...] = ('title', 'composer', 'arranger', 'copyright', 'user-text-1', 'user-text-2', 'user-text-3', 'user-text-4', 'user-text-5')

@dataclasses.dataclass(frozen=True)
class MosaicLayoutText:
    off: int
    text: str
    default_x: int | None = None
    default_y: int | None = None

@dataclasses.dataclass(frozen=True)
class MosaicIndexedTextRecord:
    index: int
    off: int
    text: str
    default_x: int | None = None
    default_y: int | None = None
    record_start: int | None = None
    record_length: int | None = None
    record_word_1: int | None = None
    record_kind: int | None = None
    record_style: int | None = None

@dataclasses.dataclass(frozen=True)
class MosaicRehearsalMark:
    measure_index: int
    text_index: int
    text: str
    off: int
    default_x: int | None = None
    default_y: int | None = None

@dataclasses.dataclass(frozen=True)
class MosaicStaffText:
    measure_index: int
    part_index: int
    text_index: int
    text: str
    off: int
    default_x: int | None = None
    default_y: int | None = None
    position_divisions: int | None = None
    relative_x: int | None = None
    relative_y: int | None = None

@dataclasses.dataclass(frozen=True)
class MosaicMeasureDirectionText:
    measure_index: int
    text_index: int
    text: str
    off: int
    kind: str
    default_x: int | None = None
    default_y: int | None = None
    position_divisions: int | None = None

@dataclasses.dataclass(frozen=True)
class MosaicEnding:
    start_measure_index: int
    end_measure_index: int
    text_index: int
    text: str
    off: int
    default_x: int | None = None
    default_y: int | None = None
POST_GRID_SECTION_SPECS: dict[int, PostGridSectionSpec] = {26: PostGridSectionSpec(26, 'postgrid-1a', 0, 6, 4, old_fixed_version_lt=39, old_fixed_record_count=4), 25: PostGridSectionSpec(25, 'postgrid-19', 5, 6, 8), 28: PostGridSectionSpec(28, 'postgrid-1c', 3, 6, 4), 27: PostGridSectionSpec(27, 'postgrid-1b/key-index', 3, 6, 4), 30: PostGridSectionSpec(30, 'postgrid-1e/meter-index', 4, 6, 4), 31: PostGridSectionSpec(31, 'postgrid-1f', 0, 0, 16, header_after_count_size=8)}

def mosaic_body_start(data: bytes) -> int:
    magic, tag, length, _version = mosa_header(data)
    if magic == 'MOSA' and tag == 25 and (length == 4):
        return 14
    if len(data) >= 14 and u16(data, 8) == 14 and (u32(data, 0) == u32(data, 4)):
        return 14
    return 0

def parse_pregrid_section_at(data: bytes, off: int) -> PreGridSection | None:
    if off + 2 > len(data):
        return None
    marker = u16(data, off)
    pos = off + 2
    if marker == 47:
        if pos + 6 > len(data):
            return None
        count = u32(data, pos)
        flag = data[pos + 4:pos + 6]
        pos += 6
        if count > 10000:
            return None
        records: list[bytes] = []
        record_size = 2 + 278
        for _index in range(count):
            record = data[pos:pos + record_size]
            if len(record) != record_size:
                return None
            records.append(record)
            pos += record_size
        return PreGridSection(marker, off, pos, 'pregrid-2f', int(count), flag, records)
    if marker == 40:
        if pos + 2 > len(data):
            return None
        count = s16(data, pos)
        pos += 2
        if count < 0 or count > 10000:
            return None
        records = []
        for _index in range(count):
            record = data[pos:pos + 36]
            if len(record) != 36:
                return None
            records.append(record)
            pos += 36
        return PreGridSection(marker, off, pos, 'pregrid-28', count, b'', records)
    if marker == 39:
        if pos + 2 > len(data):
            return None
        count = s16(data, pos)
        pos += 2
        if count < 0 or count > 100000:
            return None
        records = []
        for _index in range(count):
            if pos + 2 > len(data):
                return None
            first_word = s16(data, pos)
            record_size = 14 if first_word >= 0 else 12
            record = data[pos:pos + record_size]
            if len(record) != record_size:
                return None
            records.append(record)
            pos += record_size
        return PreGridSection(marker, off, pos, 'pregrid-27', count, b'', records)
    if marker == 38:
        if pos + 20 > len(data):
            return None
        header = data[pos:pos + 20]
        pos += 20
        count1 = s16(header, 18)
        if count1 < 0 or count1 > 100000:
            return None
        records = []
        for _index in range(count1):
            record = data[pos:pos + 10]
            if len(record) != 10:
                return None
            records.append(record)
            pos += 10
        if pos + 4 > len(data):
            return None
        count2 = u32(data, pos)
        pos += 4
        if count2 > 100000:
            return None
        extra_records = []
        for _index in range(count2):
            record = data[pos:pos + 4]
            if len(record) != 4:
                return None
            extra_records.append(record)
            pos += 4
        return PreGridSection(marker, off, pos, 'pregrid-26', count1, header, records, int(count2), extra_records)
    return None

def parse_pregrid_sections(data: bytes) -> list[PreGridSection]:
    pos = mosaic_body_start(data)
    sections: list[PreGridSection] = []
    for expected_marker in (47, 40, 39, 38):
        section = parse_pregrid_section_at(data, pos)
        if section is None or section.marker != expected_marker:
            break
        sections.append(section)
        pos = section.end
    return sections

def split_raw_music_tokens(data: bytes) -> list[tuple[int, bytes]]:
    tokens: list[tuple[int, bytes]] = []
    off = 0
    while off < len(data):
        if data[off] == 77:
            break
        start = off
        if data[off] & 128 and off + 2 < len(data) and (data[off + 1] == 66) and data[off + 2] & 128:
            tokens.append((start, data[start:start + 1]))
            off += 1
            continue
        if data[off] & 128 and off + 3 < len(data) and (data[off + 1] == 80) and (data[off + 2] < 128) and data[off + 3] & 128 and (decode_rest_token(data[off + 1:off + 4]) is not None):
            tokens.append((start, data[start:start + 1]))
            off += 1
            continue
        if data[off] & 128 and off + 2 < len(data) and data[off + 1] & 128 and (data[off + 1] >> 3 & 7 in NOTE_DURATION_CODES) and (data[off + 2] < 128):
            tokens.append((start, data[start:start + 1]))
            off += 1
            continue
        if off + 1 < len(data) and data[off] == 66 and data[off + 1] & 128:
            tokens.append((start, data[start:start + 2]))
            off += 2
            continue
        off += 1
        while off < len(data) and data[off] < 128:
            off += 1
        if off < len(data):
            off += 1
        tokens.append((start, data[start:off]))
    return tokens

def decode_rest_token(token: bytes) -> str | None:
    if len(token) < 3 or token[0] != 80 or (not token[-1] & 128):
        return None
    duration_code = token[1] >> 3 & 7
    return NOTE_DURATION_CODES.get(duration_code)

def rest_token_hidden(token: bytes) -> bool:
    return bool(token and token[-1] & 64)

def mosaic_rest_dots(token: bytes) -> int:
    if len(token) < 2:
        return 0
    return (token[1] & 6) >> 1

def decode_chord_symbol_token(token: bytes) -> str | None:
    if len(token) < 10 or token[0] != 67 or (not token[-1] & 128):
        return None
    text_bytes = bytearray(token[9:])
    text_bytes[-1] &= 127
    text = macroman(bytes(text_bytes)).strip('\x00')
    if not text or not any((ch.isalnum() for ch in text)):
        return None
    return text
ARTICULATION_SYMBOL_XML = {0: 'staccato', 1: 'accent', 2: 'strong-accent', 3: 'staccatissimo', 5: 'tenuto', 20: 'jazz-scoop', 21: 'jazz-doit'}
JAZZ_PLACED_ARTICULATION_XML: dict[tuple[bytes, bytes], str] = {(b'8\xd5', b'\\\x04D~\x8c'): 'scoop', (b'8\xd4', b'\\\x03\x1c~\xb8'): 'scoop', (b'8\xd7', b'\\\x048\x01\xe0'): 'falloff', (b'8\xd6', b'\\\x03\x0c\x01\xa8'): 'falloff', (b'8\xd5', b'\\\x00`\x01\xb8'): 'doit', (b'8\xd4', b'\\\x00T\x01\x8c'): 'doit', (b'8\xd7', b'\\\x00(~\xb8'): 'plop', (b'8\xd6', b'\\\x00(\x7f\x80'): 'plop', (b'8\xd0', b'\\\x04`~\x80'): 'scoop', (b'8\xce', b'\\\x028~\xc4'): 'scoop', (b'8\xd1', b'\\\x04p\x01\xd4'): 'falloff', (b'8\xcf', b'\\\x02T\x01\xa8'): 'falloff', (b'8\xd0', b'\\\x008\x01\xe0'): 'doit', (b'8\xce', b'\\\x00D\x01\xa8'): 'doit', (b'8\xd1', b'\\\x00(~\xc4'): 'plop', (b'8\xcf', b'\\\x00\x0c\x7f\x80'): 'plop'}
JAZZ_UPWARD_PLACED_GLYPH_TOKENS = frozenset({b'8\xce', b'8\xd0', b'8\xd3', b'8\xd4', b'8\xd5'})
JAZZ_DOWNWARD_PLACED_GLYPH_TOKENS = frozenset({b'8\xcf', b'8\xd1', b'8\xd6', b'8\xd7'})
JAZZ_FALLOFF_FALLBACK_TOKENS = frozenset({b'0\xd1', b'8\xd1'})
JAZZ_PLACEMENT_NEAR_X_THRESHOLD = 128

def decode_category23_xy_placement_token(token: bytes | None) -> tuple[int, int] | None:
    if token is None or len(token) != 5 or mosaic_token_category(token[0]) != 23:
        return None
    if not token[-1] & 128:
        return None
    x = mosaic_sign_extend((token[1] & 127) << 7 | token[2] & 127, 14)
    y = mosaic_sign_extend((token[3] & 127) << 7 | token[4] & 127, 14)
    return (x, y)

def decode_jazz_placed_articulation_token_pair(token: bytes, next_token: bytes | None) -> str | None:
    verified = JAZZ_PLACED_ARTICULATION_XML.get((token, next_token or b''))
    if verified is not None:
        return verified
    placement = decode_category23_xy_placement_token(next_token)
    if placement is None:
        return None
    x, y = placement
    if y == 0:
        return None
    near_note_x = x < JAZZ_PLACEMENT_NEAR_X_THRESHOLD
    if token in JAZZ_UPWARD_PLACED_GLYPH_TOKENS:
        if y < 0 and (not near_note_x):
            return 'scoop'
        if y > 0 and near_note_x:
            return 'doit'
        return 'scoop' if y < 0 else 'doit'
    if token in JAZZ_DOWNWARD_PLACED_GLYPH_TOKENS:
        if y < 0 and near_note_x:
            return 'plop'
        if y > 0 and (not near_note_x):
            return 'falloff'
        return 'plop' if y < 0 else 'falloff'
    return None

def decode_jazz_fallback_articulation_token(token: bytes) -> str | None:
    if token in JAZZ_FALLOFF_FALLBACK_TOKENS:
        return 'falloff'
    return None

def jazz_placement_follower_token(token: bytes | None) -> bool:
    return token is not None and token[:1] == b'\\'
ORNAMENT_ACCIDENTAL_XML: dict[int, tuple[int, str]] = {}
NON_EXPORT_ORNAMENT_SYMBOLS = frozenset({7, 8, 9})
MEASURE_REPEAT_GLYPH_TOKENS = {b'B\x85': ('start', 1, 'one-bar-repeat'), b'B\x87': ('stop', 1, 'one-bar-repeat')}
BARE_MEASURE_REPEAT_CELL_TOKENS = {b'B\x80': ('start', 1, 'one-bar-repeat'), b'B\x82': ('start', 1, 'one-bar-repeat')}

def format_measure_repeat_glyph(repeat_style: tuple[str, int, str]) -> str:
    repeat_type, measures, label = repeat_style
    return f'{label} type={repeat_type} measures={measures}'

def decode_measure_repeat_glyph_token(token: bytes) -> str | None:
    repeat_style = MEASURE_REPEAT_GLYPH_TOKENS.get(token)
    if repeat_style is None:
        return None
    return format_measure_repeat_glyph(repeat_style)

def music_payload_before_end(data: bytes) -> bytes:
    end = data.find(b'M')
    return data[:end] if end >= 0 else data

def decode_bare_measure_repeat_cell(data: bytes) -> str | None:
    repeat_style = BARE_MEASURE_REPEAT_CELL_TOKENS.get(music_payload_before_end(data))
    if repeat_style is None:
        return None
    return format_measure_repeat_glyph(repeat_style)
TIE_GROUPING_SPAN_TOKENS = {b'p\x81': 'start', b'p\x85': 'stop'}

def decode_tie_grouping_span_token(token: bytes) -> str | None:
    fields = mosaic_category18_fields(token)
    if fields is not None and len(token) == 2 and (fields['length'] == 2) and (fields['field_4'] == 1) and (fields['field_5'] == 1) and (fields['field_6'] in (0, 1)):
        return 'start' if fields['field_6'] == 0 else 'stop'
    return TIE_GROUPING_SPAN_TOKENS.get(token)

def decode_mosaic_slur_position_token(token: bytes) -> tuple[int, int] | None:
    fields = mosaic_category18_fields(token)
    if fields is None or len(token) != 2 or fields['length'] != 2 or (fields['field_4'] != 0) or (fields['field_5'] != 1) or (fields['field_6'] != 0):
        return None
    return (fields['field_8'], fields['field_0'])

def decode_mosaic_grouping_scale_token(token: bytes) -> dict[str, int] | None:
    fields = mosaic_category18_fields(token)
    if fields is None or len(token) != fields['length'] or fields['field_5'] != 2:
        return None
    return fields

def mosaic_hairpin_kind_from_side_entry(entry: MosaicGroupingScaleEntry | None) -> str | None:
    if entry is None:
        return None
    fields = entry.payload_fields
    if fields.get('field_0') != 32 or fields.get('field_4') != 65536:
        return None
    if fields.get('field_8') == 0:
        return 'diminuendo'
    if fields.get('field_8') == 1:
        return 'crescendo'
    return None

def decode_mosaic_hairpin_span_token(token: bytes, side_entries_by_index: dict[int, MosaicGroupingScaleEntry]) -> tuple[int, str] | None:
    fields = mosaic_category18_fields(token)
    if fields is None or len(token) != 2 or fields['length'] != 2 or (fields['field_4'] != 0) or (fields['field_5'] != 0) or (fields['field_6'] != 0):
        return None
    index = fields['field_0']
    kind = mosaic_hairpin_kind_from_side_entry(side_entries_by_index.get(index))
    if kind is None:
        return None
    return (index, kind)

def hairpin_span_control_label(kind: str, phase: str, index: int) -> str:
    symbol = 0 if kind == 'crescendo' else 1
    alias = 'stop' if phase == 'stop' else kind
    return f'hair-control Dynamics:Hair/symbol={symbol}/{alias}/tool=1300/kind={kind}/index={index}'
DOT_PALETTE_COUNTS = {123: 1, 122: 2, 121: 3, 120: 1, 119: 2, 118: 3}

def decode_dot_token(token: bytes) -> int | None:
    if len(token) < 2:
        return None
    return DOT_PALETTE_COUNTS.get(token[0])
ACCIDENTAL_PALETTE_XML: dict[int, tuple[int, str, bool]] = {144: (-2, 'flat-flat', False), 142: (-1, 'flat', False), 143: (0, 'natural', False), 141: (1, 'sharp', False), 145: (2, 'double-sharp', False), 108: (-2, 'flat-flat', True), 107: (-1, 'flat', True), 106: (0, 'natural', True), 105: (1, 'sharp', True), 104: (2, 'double-sharp', True)}
ACCIDENTAL_POSITION_XML: dict[tuple[int, bool], tuple[int, str, bool]] = {(24, False): (-2, 'flat-flat', False), (24, True): (-1, 'flat', False), (25, False): (0, 'natural', False), (25, True): (1, 'sharp', False), (26, False): (2, 'double-sharp', False), (26, True): (-2, 'flat-flat', True), (27, False): (-1, 'flat', True), (27, True): (0, 'natural', True), (28, False): (1, 'sharp', True), (28, True): (2, 'double-sharp', True)}

def decode_accidental_control_token(token: bytes) -> tuple[int, str, bool] | None:
    if not token or not token[-1] & 128:
        return None
    if len(token) == 2 and 24 <= token[0] <= 28:
        return ACCIDENTAL_POSITION_XML.get((token[0], bool(token[1] & 64)))
    accidental = ACCIDENTAL_PALETTE_XML.get(token[-1])
    if accidental is None:
        return None
    if 48 <= token[0] <= 63 and len(token) in (2, 3):
        return accidental
    if token[0] == 68 and len(token) == 2:
        return accidental
    return None

def format_accidental_control_detail(accidental: tuple[int, str, bool]) -> str:
    _alter, name, cautionary = accidental
    return f"{name}{(' cautionary=yes' if cautionary else '')}"

def decode_articulation_token(token: bytes) -> str | None:
    if len(token) != 2 or token[0] != 66 or (not token[1] & 128):
        return None
    symbol = (token[1] & 127) >> 2
    return ARTICULATION_SYMBOL_XML.get(symbol, f'mosaic-articulation-{symbol}')
ARTICULATION_DISPLAY_INDEX_BYTES = range(128, 150)

def decode_articulation_display_control_token(token: bytes) -> str | None:
    if len(token) == 3 and token[0] in (48, 56) and (token[1] == 12):
        final = token[2]
    else:
        return None
    if final not in ARTICULATION_DISPLAY_INDEX_BYTES:
        return None
    return ARTICULATION_SYMBOL_XML.get(final & 127)
NOTEHEAD_DISPLAY_FINAL_SYMBOL: dict[int, int] = {**{128 + symbol: symbol for symbol in range(14)}, 168: 40, 169: 41, 170: 42}
NOTEHEAD_SYMBOL_MUSICXML: dict[int, MusicXmlNotehead] = {0: MusicXmlNotehead('normal', True), 1: MusicXmlNotehead('normal', False), 2: MusicXmlNotehead('circle-x'), 3: MusicXmlNotehead('normal', parentheses=True), 4: MusicXmlNotehead('diamond', False), 5: MusicXmlNotehead('diamond', False), 6: MusicXmlNotehead('diamond', True), 7: MusicXmlNotehead('square', True), 8: MusicXmlNotehead('triangle', True), 9: MusicXmlNotehead('square', False), 10: MusicXmlNotehead('triangle', False), 11: MusicXmlNotehead('cross'), 12: MusicXmlNotehead('x'), 13: MusicXmlNotehead('slash'), 40: MusicXmlNotehead('slash'), 41: MusicXmlNotehead('diamond', False), 42: MusicXmlNotehead('none')}

def notehead_symbol_from_display_control_token(token: bytes) -> int | None:
    if len(token) != 4 or token[2] != 0 or (not token[-1] & 128):
        return None
    return NOTEHEAD_DISPLAY_FINAL_SYMBOL.get(token[-1])

def decode_notehead_display_control_token(token: bytes) -> MusicXmlNotehead | None:
    symbol = notehead_symbol_from_display_control_token(token)
    if symbol is None:
        return None
    return NOTEHEAD_SYMBOL_MUSICXML.get(symbol)

def notehead_control_detail(token: bytes) -> str | None:
    symbol = notehead_symbol_from_display_control_token(token)
    if symbol is None:
        return None
    notehead = NOTEHEAD_SYMBOL_MUSICXML.get(symbol)
    parts = [f'symbol={symbol}']
    if notehead is not None:
        parts.append(f'value={notehead.value}')
        if notehead.filled is not None:
            parts.append(f"filled={('yes' if notehead.filled else 'no')}")
        if notehead.parentheses is not None:
            parts.append(f"parentheses={('yes' if notehead.parentheses else 'no')}")
    return ' '.join(parts)

def decode_stem_display_control_token(token: bytes) -> str | None:
    return 'none' if token == b'H\x80' else None

def is_note_like_token(token: bytes) -> bool:
    if len(token) < 3 or not token[0] & 128 or (not token[-1] & 128):
        return False
    duration_code = token[0] >> 3 & 7
    return duration_code in NOTE_DURATION_CODES

def decode_note_token(token: bytes, wrap_low_pitch: bool=False) -> tuple[str, str, int, int] | None:
    if not is_note_like_token(token):
        return None
    pitch_code = pitch_code_from_note_like_token(token, wrap_low_pitch)
    if not 320 <= pitch_code <= 720:
        return None
    duration_code = token[0] >> 3 & 7
    duration = NOTE_DURATION_CODES.get(duration_code)
    if duration is None:
        return None
    pitch_text, alter = pitch_code_to_name(pitch_code)
    return (duration, pitch_text, alter, pitch_code)

def decode_slash_note_token(token: bytes) -> tuple[str, int] | None:
    if not is_note_like_token(token):
        return None
    is_compact_slash = len(token) == 3
    is_display_variant_slash = len(token) == 4 and token[2] in (125, 126, 127)
    if not (is_compact_slash or is_display_variant_slash):
        return None
    duration_code = token[0] >> 3 & 7
    duration = NOTE_DURATION_CODES.get(duration_code)
    if duration is None:
        return None
    pitch_code = pitch_code_from_note_like_token(token)
    if 0 <= pitch_code < 192:
        return (duration, pitch_code)
    return None

def decode_stemless_rhythm_slash_context(token: bytes, following_tokens: tuple[ScannedMusicToken, ...]) -> tuple[str, int] | None:
    slash_note = decode_slash_note_token(token)
    if slash_note is None:
        return None
    if pitch_code_from_note_like_token(token, wrap_low_pitch=False) != 0:
        return None
    for following in following_tokens:
        if following.kind == 'end':
            break
        following_token = bytes.fromhex(following.raw)
        if notehead_symbol_from_display_control_token(following_token) == 40:
            return slash_note
        if is_note_like_token(following_token) or decode_rest_token(following_token) is not None:
            break
    return None

def mosaic_slash_note_dots(token: bytes) -> int:
    return mosaic_note_like_dots(token)

def mosaic_note_like_dots(token: bytes) -> int:
    return (token[0] & 6) >> 1 if token else 0

def mosaic_staff_position_note_dots(token: bytes) -> int:
    return mosaic_note_like_dots(token)

def mosaic_slash_display_pitch(code: int, clef: MusicXmlClef | None=None) -> str:
    if clef is not None:
        pitch = pitch_name_from_staff_position(code >> 3, clef)
        if pitch is not None:
            return pitch
    return pitch_name_from_diatonic_degree(6 + (code >> 3))

def musicxml_unpitched_display_pitch(event: MusicEvent, clef: MusicXmlClef | None=None) -> tuple[str, int]:
    if event.display_code is None:
        pitch = pitch_name_from_staff_position(0, clef) if clef is not None else None
        if pitch is None:
            return ('B', 4)
    else:
        pitch = mosaic_slash_display_pitch(event.display_code, clef)
    return (pitch[0], int(pitch[1:]))

def decode_unpitched_packed_note_token(token: bytes) -> tuple[str, int] | None:
    packed_pitch_set = decode_packed_pitch_set_token(token, wrap_low_pitch=True)
    if packed_pitch_set is None:
        return None
    duration, pitch_codes = packed_pitch_set
    raw_pitch_code = pitch_code_from_note_like_token(token, wrap_low_pitch=False)
    if raw_pitch_code >= 192:
        return None
    return (duration, len(pitch_codes))

def note_like_packed_code_parts(token: bytes) -> tuple[int, tuple[int, ...], int | None]:
    pitch_code = token[0] & 7
    if len(token) < 2:
        return (pitch_code, (), None)
    aux = token[1] & 63
    pos = 1
    if not token[1] & 64 and aux >= 10:
        pos = 2
    shift = 3
    chunks: list[int] = []
    while pos < len(token) and token[pos] < 128:
        pos += 1
        if pos >= len(token):
            break
        chunk = token[pos] & 127
        chunks.append(chunk)
        pitch_code |= chunk << shift
        shift += 7
    return (pitch_code, tuple(chunks), aux)

def mosaic_sign_extend(value: int, bits: int) -> int:
    sign = 1 << bits - 1
    mask = (1 << bits) - 1
    value &= mask
    return value - (1 << bits) if value & sign else value

def bit_mask_range(mb: int, me: int) -> int:
    mask = 0
    for index in range(32):
        bit = 1 << 31 - index
        if mb <= me:
            if mb <= index <= me:
                mask |= bit
        elif index >= mb or index <= me:
            mask |= bit
    return mask

def rotate_left_mask(value: int, shift: int, mb: int, me: int) -> int:
    value &= 4294967295
    rotated = value if shift == 0 else (value << shift | value >> 32 - shift) & 4294967295
    return rotated & bit_mask_range(mb, me)

def mosaic_category0_descriptor_base_offset(token: bytes) -> int | None:
    if len(token) < 3 or mosaic_token_category(token[0]) != 0:
        return None
    offset = 2
    if token[1] & 2:
        offset += 1
        if token[1] & 1:
            offset += 1
    if offset >= len(token):
        return None
    return offset

def mosaic_category0_display_model_payload_offset(token: bytes) -> int | None:
    if len(token) < 3 or mosaic_token_category(token[0]) != 0:
        return None
    offset = 3 if token[0] & 112 == 48 else 2
    if token[1] & 64:
        offset += 1
    if offset >= len(token):
        return None
    return offset

def mosaic_iter_130a44_positions(token: bytes, base_offset: int, payload_offset: int) -> tuple[int, ...]:
    if not 0 <= base_offset < len(token) or not 0 <= payload_offset <= len(token):
        return ()
    position = mosaic_sign_extend(token[base_offset] & 63, 6)
    positions = [position]
    for byte in token[payload_offset:]:
        if byte & 128:
            break
        for mask in (64, 32, 16, 8, 4, 2, 1):
            position -= 1
            if byte & mask:
                positions.append(position)
    return tuple(positions)

def mosaic_category0_descriptor_positions(token: bytes) -> tuple[int, ...]:
    base_offset = mosaic_category0_descriptor_base_offset(token)
    if base_offset is None:
        return ()
    return mosaic_iter_130a44_positions(token, base_offset, base_offset + 1)

def mosaic_category0_display_model_positions(token: bytes) -> tuple[int, ...]:
    payload_offset = mosaic_category0_display_model_payload_offset(token)
    if payload_offset is None:
        return ()
    return mosaic_iter_130a44_positions(token, 1, payload_offset)

def format_int_tuple(values: tuple[int, ...]) -> str:
    return '[' + ','.join((str(value) for value in values)) + ']'

def mosaic_category0_bitstream_debug_text(token: bytes) -> str:
    descriptor_offset = mosaic_category0_descriptor_base_offset(token)
    model_offset = mosaic_category0_display_model_payload_offset(token)
    if descriptor_offset is None and model_offset is None:
        return ''
    parts: list[str] = []
    if descriptor_offset is not None:
        parts.append(f'desc_base={descriptor_offset} desc_pos={format_int_tuple(mosaic_category0_descriptor_positions(token))}')
    if model_offset is not None:
        parts.append(f'model_payload={model_offset} model_pos={format_int_tuple(mosaic_category0_display_model_positions(token))}')
    return ' '.join(parts)

def mosaic_category18_fields(token: bytes) -> dict[str, int] | None:
    if len(token) < 2 or mosaic_token_category(token[0]) != 18:
        return None
    b0 = token[0]
    fields = {'field_0': 0, 'field_2': 0, 'field_3': 0, 'field_4': (b0 & 16) >> 4, 'field_5': 0, 'field_6': 0, 'field_8': 0, 'field_c': 0, 'length': 1}
    if fields['field_4']:
        fields['field_2'] = (b0 & 8) >> 3
        fields['field_3'] = (b0 & 4) >> 2
        b1 = token[1]
        if b1 & 128:
            fields['field_8'] = b0 & 3
            fields['field_0'] = (b1 & 112) >> 4
            fields['field_6'] = (b1 & 12) >> 2
            fields['field_5'] = b1 & 3
            fields['length'] = 2
            return fields
        fields['field_5'] = b0 & 3
        if len(token) < 3:
            return fields
        if b1 & 32:
            fields['field_6'] = b1 & 63
            fields['field_0'] = token[2] & 127
            payload = 3
        else:
            if len(token) < 5:
                return fields
            fields['field_6'] = (b1 << 7 | token[2] & 127) & 65535
            fields['field_0'] = (token[3] << 7 | token[4] & 127) & 65535
            payload = 5
    else:
        fields['field_6'] = 0
        b1 = token[1]
        if b1 & 128:
            fields['field_8'] = b0 & 15
            fields['field_0'] = (b1 & 124) >> 2
            fields['field_5'] = b1 & 3
            fields['length'] = 2
            return fields
        fields['field_5'] = b0 & 3
        if len(token) < 3:
            return fields
        fields['field_0'] = (b1 << 7 | token[2] & 127) & 65535
        payload = 3
    field8 = 0
    fieldc = 0
    bit = 0
    pos = payload
    while pos < len(token):
        value = token[pos]
        pos += 1
        chunk = value & 127
        if bit < 32:
            field8 |= chunk << bit
        else:
            fieldc |= chunk << bit - 32
        bit += 7
        if value & 128:
            break
    fields['field_8'] = field8
    fields['field_c'] = fieldc
    fields['length'] = pos
    return fields

def mosaic_category18_payload_fields(data: bytes) -> dict[str, int] | None:
    if not data:
        return None
    b0 = data[0]
    fields = {'field_0': rotate_left_mask(b0, 0, 25, 28), 'field_2': 0, 'field_4': 65536, 'field_8': 0, 'field_c': 0, 'length': 1}
    if b0 & 128:
        fields['field_8'] = rotate_left_mask(b0, 30, 31, 31)
        fields['field_2'] = b0 & 3
        return fields
    fields['field_8'] = rotate_left_mask(b0, 31, 30, 31)
    has_field4_extension = b0 & 1
    if len(data) < 2:
        return None
    b1 = data[1]
    fields['field_2'] = b1 & 127
    pos = 1
    if b1 & 128:
        fields['length'] = 2
        return fields
    if has_field4_extension:
        pos += 1
        if pos >= len(data):
            return None
        fields['field_4'] = rotate_left_mask(data[pos], 12, 13, 19)
    bit = 2
    while pos < len(data) and (not data[pos] & 128):
        payload_bit = mosaic_sign_extend(bit, 16)
        pos += 1
        if pos >= len(data):
            break
        chunk = data[pos] & 127
        upper_bit = payload_bit - 32
        if mosaic_sign_extend(upper_bit, 16) > 0:
            fields['field_c'] |= chunk << mosaic_sign_extend(upper_bit, 16)
        else:
            fields['field_8'] |= chunk << payload_bit
            upper_bit += 7
            if mosaic_sign_extend(upper_bit, 16) > 0:
                fields['field_c'] |= chunk << mosaic_sign_extend(upper_bit, 16) >> 7
        bit += 7
    fields['length'] = min(pos + 1, len(data))
    return fields

def mosaic_grouping_scale_ratio_from_payload_fields(fields: dict[str, int]) -> tuple[int, int] | None:
    encoded = fields['field_8']
    extension = fields['field_c']
    if extension == 0:
        if rotate_left_mask(encoded, 0, 0, 27) == 0:
            return (3, 2)
        if rotate_left_mask(encoded, 0, 0, 22) == 0:
            actual = rotate_left_mask(encoded, 0, 23, 27)
            if rotate_left_mask(encoded, 0, 23, 23):
                normal = actual // 3 * 3
            else:
                normal = actual // 2 * 2
            return (actual, normal) if actual > 0 and normal > 0 else None
        if rotate_left_mask(encoded, 0, 0, 15) == 0:
            actual = rotate_left_mask(encoded, 28, 26, 31)
            normal = rotate_left_mask(encoded, 22, 26, 31)
            return (actual, normal) if actual > 0 and normal > 0 else None
    actual = rotate_left_mask(encoded, 28, 24, 31)
    normal = rotate_left_mask(encoded, 20, 24, 31)
    return (actual, normal) if actual > 0 and normal > 0 else None

def format_pitch_code_name(pitch_code: int) -> str:
    pitch_text, alter = pitch_code_to_name(pitch_code)
    return pitch_text if alter == 0 else f'{pitch_text}{alter:+d}'

def format_pitch_code_set(pitch_codes: tuple[int, ...]) -> str:
    return '[' + ','.join((format_pitch_code_name(pitch_code) for pitch_code in pitch_codes)) + ']'

def decode_packed_pitch_set_token(token: bytes, wrap_low_pitch: bool=True, lane: int | None=None) -> tuple[str, tuple[int, ...]] | None:
    if len(token) < 4 or not is_note_like_token(token):
        return None
    duration_code = token[0] >> 3 & 7
    duration = NOTE_DURATION_CODES.get(duration_code)
    if duration is None:
        return None
    top_high = token[-2] & 127
    if wrap_low_pitch and top_high < 32:
        top_high += 64
    low_bits = token[0] & 7
    if lane == 2:
        low_bits |= 1
    top_code = low_bits | top_high << 3
    if not 320 <= top_code <= 720:
        return None
    codes = {top_code}
    lower_mask = token[-1] & 127
    for bit in range(7):
        if not lower_mask & 1 << bit:
            continue
        interval = 7 - bit
        lower_code = top_code - interval * 8
        if 320 <= lower_code <= 720:
            codes.add(lower_code)
    if len(codes) <= 1:
        return None
    return (duration, tuple(sorted(codes)))

def pitch_code_from_note_like_token(token: bytes, wrap_low_pitch: bool=False) -> int:
    high = token[-1] & 127
    if wrap_low_pitch and high < 32:
        high += 64
    return token[0] & 7 | high << 3

def pitch_code_to_name(pitch_code: int) -> tuple[str, int]:
    degree = round((pitch_code - 465) / 8)
    natural_code = 465 + degree * 8
    alter = pitch_code - natural_code
    step = PITCH_STEPS[degree % 7]
    octave = 4 + degree // 7
    return (f'{step}{octave}', alter)
MOSAIC_CLEF_REFERENCE_DEGREES = {'G': 4, 'F': -4, 'C': 0}

def pitch_name_from_diatonic_degree(degree: int) -> str:
    step = PITCH_STEPS[degree % 7]
    octave = 4 + degree // 7
    return f'{step}{octave}'

def pitch_name_from_staff_position(position: int, clef: MusicXmlClef) -> str | None:
    if clef.sign not in MOSAIC_CLEF_REFERENCE_DEGREES or clef.line is None:
        return None
    middle_line_degree = MOSAIC_CLEF_REFERENCE_DEGREES[clef.sign] + (3 - clef.line) * 2
    if clef.octave_change is not None:
        middle_line_degree += clef.octave_change * 7
    return pitch_name_from_diatonic_degree(middle_line_degree + position)

def decode_staff_position_note_token(token: bytes, clef: MusicXmlClef | None) -> tuple[str, tuple[str, ...]] | None:
    if clef is None or not is_note_like_token(token) or mosaic_token_category(token[0]) != 0:
        return None
    duration_code = token[0] >> 3 & 7
    duration = NOTE_DURATION_CODES.get(duration_code)
    if duration is None:
        return None
    positions = mosaic_category0_descriptor_positions(token)
    if not positions:
        return None
    pitches: list[str] = []
    for position in sorted(set(positions)):
        pitch = pitch_name_from_staff_position(position, clef)
        if pitch is None:
            return None
        pitches.append(pitch)
    return (duration, tuple(pitches))

def music_control_event_from_token(scanned: ScannedMusicToken) -> MusicEvent:
    return MusicEvent('control', '', raw=scanned.raw, text=scanned_control_label(scanned))

def scanned_control_label(scanned: ScannedMusicToken) -> str:
    label = scanned.kind
    if scanned.detail:
        label += f' {scanned.detail}'
    if scanned.raw:
        label += f' raw={scanned.raw}'
    return label

def decoded_ornament_control_name(scanned: ScannedMusicToken) -> str | None:
    if scanned.kind != 'orna-control':
        return None
    label = scanned_control_label(scanned)
    symbol = musicxml_control_symbol(label)
    if symbol.isdigit() and int(symbol) in NON_EXPORT_ORNAMENT_SYMBOLS:
        return None
    alias = musicxml_control_alias(label)
    if alias:
        return alias
    if symbol:
        return f'mosaic-ornament-{symbol}'
    return f"mosaic-ornament-raw-{scanned.raw.replace(' ', '-')}"

def decoded_ornament_accidental(scanned: ScannedMusicToken) -> tuple[int, str] | None:
    if scanned.kind != 'orna-control':
        return None
    symbol = musicxml_control_symbol(scanned_control_label(scanned))
    if not symbol.isdigit():
        return None
    return ORNAMENT_ACCIDENTAL_XML.get(int(symbol))
SLUR_ATTACH_EVENT_KINDS = {'note', 'slash', 'unpitched'}
GROUPING_SCALE_ATTACH_EVENT_KINDS = {'note', 'rest', 'slash', 'unpitched'}
NOTEHEAD_ATTACH_EVENT_KINDS = {'note', 'slash', 'unpitched'}
TIE_ATTACH_EVENT_KINDS = {'note', 'slash'}

def add_mosaic_slur_position_to_event(event: MusicEvent, level: int, position: int) -> MusicEvent:
    slur_position = (level, position)
    if slur_position in event.mosaic_slur_positions:
        return event
    return dataclasses.replace(event, mosaic_slur_positions=event.mosaic_slur_positions + (slur_position,))

def add_musicxml_slur_to_event(event: MusicEvent, slur_type: str, number: int) -> MusicEvent:
    slur = (slur_type, number)
    if slur in event.slurs:
        return event
    return dataclasses.replace(event, slurs=event.slurs + (slur,))

def add_musicxml_tie_to_event(event: MusicEvent, tie_type: str) -> MusicEvent:
    if tie_type in event.ties:
        return event
    return dataclasses.replace(event, ties=event.ties + (tie_type,))

def add_musicxml_tuplet_to_event(event: MusicEvent, tuplet_type: str, number: int) -> MusicEvent:
    tuplet = (tuplet_type, number)
    if tuplet in event.tuplets:
        return event
    return dataclasses.replace(event, tuplets=event.tuplets + (tuplet,))

def add_grouping_scale_to_event(event: MusicEvent, entry_index: int, actual_notes: int, normal_notes: int) -> MusicEvent:
    if actual_notes <= 0 or normal_notes <= 0:
        return event
    if event.time_modification is None:
        combined_actual = actual_notes
        combined_normal = normal_notes
    else:
        old_actual, old_normal = event.time_modification
        combined_actual = old_actual * actual_notes
        combined_normal = old_normal * normal_notes
    divisor = math.gcd(combined_actual, combined_normal)
    combined_actual //= divisor
    combined_normal //= divisor
    indices = event.mosaic_tuplet_indices
    if entry_index not in indices:
        indices = indices + (entry_index,)
    return dataclasses.replace(event, time_modification=(combined_actual, combined_normal), mosaic_tuplet_indices=indices)

def apply_mosaic_tuplet_spans(events: list[MusicEvent]) -> list[MusicEvent]:
    if not any((event.time_modification for event in events)):
        return events
    adjusted = list(events)
    run: list[int] = []
    run_key: tuple[int, tuple[int, int]] | None = None

    def flush_run() -> None:
        nonlocal run, run_key
        if len(run) >= 2 and run_key is not None:
            index, _time_modification = run_key
            number = index + 1
            adjusted[run[0]] = add_musicxml_tuplet_to_event(adjusted[run[0]], 'start', number)
            adjusted[run[-1]] = add_musicxml_tuplet_to_event(adjusted[run[-1]], 'stop', number)
        run = []
        run_key = None
    for index, event in enumerate(events):
        duration = event_duration_divisions(event)
        if event.chord or duration is None:
            continue
        if event.time_modification is None or not event.mosaic_tuplet_indices:
            flush_run()
            continue
        key = (event.mosaic_tuplet_indices[-1], event.time_modification)
        if run_key is not None and key != run_key:
            flush_run()
        run.append(index)
        run_key = key
    flush_run()
    return adjusted

def apply_mosaic_slur_spans(events: list[MusicEvent]) -> list[MusicEvent]:
    levels = sorted({level for event in events for level, _position in event.mosaic_slur_positions})
    if not levels:
        return events
    adjusted = list(events)
    for level in levels:
        run: list[int] = []
        last_position: int | None = None

        def flush_run() -> None:
            nonlocal run, last_position
            if len(run) >= 2:
                number = level + 1
                adjusted[run[0]] = add_musicxml_slur_to_event(adjusted[run[0]], 'start', number)
                adjusted[run[-1]] = add_musicxml_slur_to_event(adjusted[run[-1]], 'stop', number)
            run = []
            last_position = None
        for index, event in enumerate(events):
            if event.kind not in SLUR_ATTACH_EVENT_KINDS:
                if event_duration_divisions(event) is not None:
                    flush_run()
                continue
            positions = [position for event_level, position in event.mosaic_slur_positions if event_level == level]
            if not positions:
                if event_duration_divisions(event) is not None and (not event.chord):
                    flush_run()
                continue
            position = positions[-1]
            if last_position is not None and position <= last_position:
                flush_run()
            run.append(index)
            last_position = position
        flush_run()
    return adjusted

def musicxml_tie_pitch_key(event: MusicEvent) -> tuple[str, int] | None:
    if event.kind not in TIE_ATTACH_EVENT_KINDS or not event.pitch:
        return None
    return (event.pitch, event.alter)

def apply_mosaic_same_position_tie_spans(events: list[MusicEvent]) -> list[MusicEvent]:
    if not any((event.mosaic_slur_positions for event in events)):
        return events
    adjusted = list(events)
    previous_index: int | None = None
    for index, event in enumerate(events):
        duration = event_duration_divisions(event)
        key = musicxml_tie_pitch_key(event)
        if event.chord:
            continue
        if key is None:
            if duration is not None:
                previous_index = None
            continue
        if previous_index is not None:
            previous = events[previous_index]
            previous_key = musicxml_tie_pitch_key(previous)
            common_positions = set(previous.mosaic_slur_positions).intersection(event.mosaic_slur_positions)
            if previous_key == key and common_positions:
                adjusted[previous_index] = add_musicxml_tie_to_event(adjusted[previous_index], 'start')
                adjusted[index] = add_musicxml_tie_to_event(adjusted[index], 'stop')
        if duration is not None:
            previous_index = index
    return adjusted

def apply_mosaic_semantic_spans(events: list[MusicEvent]) -> list[MusicEvent]:
    return apply_mosaic_tuplet_spans(apply_mosaic_slur_spans(apply_mosaic_same_position_tie_spans(events)))

def music_events_from_cell(payload: bytes, include_controls: bool=False, wrap_low_pitch_notes: bool=False, unpitched_note_like: bool=False, staff_position_clef: MusicXmlClef | None=None, grouping_scale_entries: tuple[MosaicGroupingScaleEntry, ...]=()) -> list[MusicEvent]:
    bare_measure_repeat = decode_bare_measure_repeat_cell(payload)
    if bare_measure_repeat is not None:
        return [MusicEvent('control', '', raw=music_payload_before_end(payload).hex(' '), text=f'mrpt-control {bare_measure_repeat}')]
    events: list[MusicEvent] = []
    pending_articulations: list[str] = []
    pending_note_articulations: list[str] = []
    pending_ornaments: list[str] = []
    pending_notehead: MusicXmlNotehead | None = None
    pending_accidental: tuple[int, str, bool] | None = None
    pending_dots = 0
    pending_stem = ''
    pending_ties: list[str] = []
    pending_slur_positions: list[tuple[int, int]] = []
    pending_grouping_scales: list[MosaicGroupingScaleEntry] = []
    grouping_scale_by_index = {entry.index: entry for entry in grouping_scale_entries}
    active_hairpins: dict[int, str] = {}

    def append_unique(values: tuple[str, ...], value: str) -> tuple[str, ...]:
        return values if value in values else values + (value,)

    def add_event(event: MusicEvent) -> None:
        nonlocal pending_accidental, pending_articulations, pending_note_articulations, pending_ornaments, pending_notehead, pending_dots, pending_stem, pending_ties, pending_slur_positions, pending_grouping_scales
        if pending_accidental is not None and event.kind == 'note':
            alter, accidental, cautionary = pending_accidental
            event = dataclasses.replace(event, alter=alter, accidental=accidental, accidental_cautionary=cautionary)
            pending_accidental = None
        if pending_articulations and event.kind in {'note', 'slash'}:
            event = dataclasses.replace(event, articulations=tuple(pending_articulations) + event.articulations)
            pending_articulations = []
        if pending_note_articulations and event.kind == 'note':
            event = dataclasses.replace(event, articulations=tuple(pending_note_articulations) + event.articulations)
            pending_note_articulations = []
        if pending_ornaments and event.kind in {'note', 'slash'}:
            event = dataclasses.replace(event, ornaments=tuple(pending_ornaments) + event.ornaments)
            pending_ornaments = []
        if pending_notehead is not None and event.kind in NOTEHEAD_ATTACH_EVENT_KINDS:
            event = dataclasses.replace(event, notehead=pending_notehead)
            pending_notehead = None
        if pending_dots and event.kind in {'note', 'rest', 'slash'}:
            event = dataclasses.replace(event, dots=max(event.dots, pending_dots))
            pending_dots = 0
        if pending_stem and event.kind in {'note', 'slash', 'unpitched'}:
            event = dataclasses.replace(event, stem=pending_stem)
            pending_stem = ''
        if pending_ties and event.kind in TIE_ATTACH_EVENT_KINDS:
            ties = event.ties
            for tie in pending_ties:
                ties = append_unique(ties, tie)
            event = dataclasses.replace(event, ties=ties)
            pending_ties = []
        if pending_slur_positions and event.kind in SLUR_ATTACH_EVENT_KINDS:
            for level, position in pending_slur_positions:
                event = add_mosaic_slur_position_to_event(event, level, position)
            pending_slur_positions = []
        if pending_grouping_scales and event.kind in GROUPING_SCALE_ATTACH_EVENT_KINDS:
            for entry in pending_grouping_scales:
                event = add_grouping_scale_to_event(event, entry.index, entry.actual_notes, entry.normal_notes)
            pending_grouping_scales = []
        events.append(event)

    def attach_accidental_to_recent_note(alter: int, accidental: str, cautionary: bool) -> bool:
        for index in range(len(events) - 1, -1, -1):
            event = events[index]
            if event.kind == 'note':
                events[index] = dataclasses.replace(event, alter=alter, accidental=accidental, accidental_cautionary=cautionary)
                return True
            if event_duration_divisions(event) is not None:
                break
        return False

    def attach_stem_to_recent_note_like(stem: str) -> bool:
        for index in range(len(events) - 1, -1, -1):
            event = events[index]
            if event.kind in {'note', 'slash', 'unpitched'}:
                events[index] = dataclasses.replace(event, stem=stem)
                return True
            if event_duration_divisions(event) is not None:
                break
        return False

    def attach_articulation_to_recent_note_like(articulation: str) -> bool:
        for index in range(len(events) - 1, -1, -1):
            event = events[index]
            if event.kind in {'note', 'slash', 'unpitched'}:
                events[index] = dataclasses.replace(event, articulations=append_unique(event.articulations, articulation))
                return True
            if event_duration_divisions(event) is not None:
                break
        return False

    def attach_articulation_to_previous_note_like(articulation: str) -> bool:
        for index in range(len(events) - 1, -1, -1):
            event = events[index]
            if event.kind in {'note', 'slash', 'unpitched'}:
                events[index] = dataclasses.replace(event, articulations=append_unique(event.articulations, articulation))
                return True
        return False

    def attach_jazz_articulation(articulation: str) -> None:
        if articulation in {'falloff', 'doit'} and attach_articulation_to_previous_note_like(articulation):
            return
        if attach_articulation_to_recent_note_like(articulation):
            return
        pending_articulations.append(articulation)

    def insert_event_before_recent_note_like(event_to_insert: MusicEvent) -> bool:
        for index in range(len(events) - 1, -1, -1):
            event = events[index]
            if event.kind in {'note', 'slash', 'unpitched'}:
                events.insert(index, event_to_insert)
                return True
            if event_duration_divisions(event) is not None:
                break
        return False
    scanned_tokens = scanned_music_tokens(payload, wrap_low_pitch_notes, unpitched_note_like)
    skip_scanned_indices: set[int] = set()
    for scanned_index, scanned in enumerate(scanned_tokens):
        if scanned_index in skip_scanned_indices:
            continue
        if scanned.kind == 'end':
            break
        token = bytes.fromhex(scanned.raw)
        next_token = None
        if scanned_index + 1 < len(scanned_tokens):
            next_scanned = scanned_tokens[scanned_index + 1]
            if next_scanned.kind != 'end':
                next_token = bytes.fromhex(next_scanned.raw)
        if is_note_attached_text_control_pair(token, next_token):
            skip_scanned_indices.add(scanned_index + 1)
            continue
        tie = decode_tie_grouping_span_token(token)
        if tie is not None:
            for index in range(len(events) - 1, -1, -1):
                if events[index].kind in TIE_ATTACH_EVENT_KINDS:
                    events[index] = dataclasses.replace(events[index], ties=append_unique(events[index].ties, tie))
                    break
            else:
                pending_ties.append(tie)
            continue
        slur_position = decode_mosaic_slur_position_token(token)
        if slur_position is not None:
            level, position = slur_position
            for index in range(len(events) - 1, -1, -1):
                if events[index].kind in SLUR_ATTACH_EVENT_KINDS:
                    events[index] = add_mosaic_slur_position_to_event(events[index], level, position)
                    break
            else:
                pending_slur_positions.append(slur_position)
            continue
        grouping_scale = decode_mosaic_grouping_scale_token(token)
        if grouping_scale is not None:
            entry = grouping_scale_by_index.get(grouping_scale['field_0'])
            if entry is not None:
                for index in range(len(events) - 1, -1, -1):
                    if events[index].kind in GROUPING_SCALE_ATTACH_EVENT_KINDS:
                        events[index] = add_grouping_scale_to_event(events[index], entry.index, entry.actual_notes, entry.normal_notes)
                        break
                else:
                    pending_grouping_scales.append(entry)
                continue
            if not include_controls:
                continue
        dynamic_symbol = decode_dynamic_display_control_token(token)
        if dynamic_symbol is not None:
            control_event = MusicEvent('control', '', raw=token.hex(' '), text=dynamic_display_control_label(dynamic_symbol))
            if not insert_event_before_recent_note_like(control_event):
                events.append(control_event)
            continue
        hairpin_span = decode_mosaic_hairpin_span_token(token, grouping_scale_by_index)
        if hairpin_span is not None:
            hairpin_index, hairpin_kind = hairpin_span
            if hairpin_index in active_hairpins:
                phase = 'stop'
                hairpin_kind = active_hairpins.pop(hairpin_index)
                control_event = MusicEvent('control', '', raw=token.hex(' '), text=hairpin_span_control_label(hairpin_kind, phase, hairpin_index))
                events.append(control_event)
            else:
                phase = 'start'
                active_hairpins[hairpin_index] = hairpin_kind
                control_event = MusicEvent('control', '', raw=token.hex(' '), text=hairpin_span_control_label(hairpin_kind, phase, hairpin_index))
                if not insert_event_before_recent_note_like(control_event):
                    events.append(control_event)
            continue
        jazz_articulation = decode_jazz_placed_articulation_token_pair(token, next_token)
        if jazz_articulation is not None:
            attach_jazz_articulation(jazz_articulation)
            skip_scanned_indices.add(scanned_index + 1)
            continue
        jazz_articulation = decode_jazz_fallback_articulation_token(token)
        if jazz_articulation is not None:
            attach_jazz_articulation(jazz_articulation)
            if jazz_placement_follower_token(next_token):
                skip_scanned_indices.add(scanned_index + 1)
            continue
        if unpitched_note_like:
            unpitched_packed = decode_unpitched_packed_note_token(token)
            if unpitched_packed is not None:
                duration, head_count = unpitched_packed
                for index in range(head_count):
                    add_event(MusicEvent('unpitched', duration, raw=token.hex(' '), chord=index > 0))
                continue
        stemless_rhythm_slash = decode_stemless_rhythm_slash_context(token, tuple(scanned_tokens[scanned_index + 1:scanned_index + 5]))
        if stemless_rhythm_slash is not None:
            duration, code = stemless_rhythm_slash
            dots = mosaic_slash_note_dots(token)
            pitch = mosaic_slash_display_pitch(code, staff_position_clef) if staff_position_clef is not None else ''
            add_event(MusicEvent('slash', duration, pitch=pitch, raw=token.hex(' '), dots=dots, display_code=code))
            continue
        packed_pitch_set = decode_packed_pitch_set_token(token, wrap_low_pitch_notes)
        if packed_pitch_set is not None:
            duration, pitch_codes = packed_pitch_set
            for index, pitch_code in enumerate(pitch_codes):
                pitch, alter = pitch_code_to_name(pitch_code)
                add_event(MusicEvent('note', duration, pitch, alter, token.hex(' '), chord=index > 0))
            continue
        if staff_position_clef is not None:
            staff_position_note = decode_staff_position_note_token(token, staff_position_clef)
            if staff_position_note is not None:
                duration, pitches = staff_position_note
                dots = mosaic_staff_position_note_dots(token)
                for index, pitch in enumerate(pitches):
                    add_event(MusicEvent('note', duration, pitch, 0, token.hex(' '), chord=index > 0, dots=dots))
                continue
        measure_repeat_glyph = decode_measure_repeat_glyph_token(token)
        if measure_repeat_glyph is not None:
            control_event = music_control_event_from_token(scanned)
            if include_controls or should_export_music_control_by_default(control_event):
                events.append(control_event)
            continue
        articulation = decode_articulation_token(token)
        if articulation is not None:
            for index in range(len(events) - 1, -1, -1):
                if events[index].kind in {'note', 'slash'}:
                    events[index] = dataclasses.replace(events[index], articulations=events[index].articulations + (articulation,))
                    break
            else:
                pending_articulations.append(articulation)
            continue
        articulation = decode_articulation_display_control_token(token)
        if articulation is not None:
            for index in range(len(events) - 1, -1, -1):
                if events[index].kind == 'note':
                    events[index] = dataclasses.replace(events[index], articulations=events[index].articulations + (articulation,))
                    break
            else:
                pending_note_articulations.append(articulation)
            continue
        notehead = decode_notehead_display_control_token(token)
        if notehead is not None:
            for index in range(len(events) - 1, -1, -1):
                if events[index].kind in NOTEHEAD_ATTACH_EVENT_KINDS:
                    events[index] = dataclasses.replace(events[index], notehead=notehead)
                    break
            else:
                pending_notehead = notehead
            continue
        stem = decode_stem_display_control_token(token)
        if stem is not None:
            if not attach_stem_to_recent_note_like(stem):
                pending_stem = stem
            continue
        ornament_accidental = decoded_ornament_accidental(scanned)
        if ornament_accidental is not None:
            alter, name = ornament_accidental
            if not attach_accidental_to_recent_note(alter, name, False):
                pending_accidental = (alter, name, False)
            continue
        ornament = decoded_ornament_control_name(scanned)
        if ornament is not None:
            for index in range(len(events) - 1, -1, -1):
                if events[index].kind in {'note', 'slash'}:
                    events[index] = dataclasses.replace(events[index], ornaments=events[index].ornaments + (ornament,))
                    break
            else:
                pending_ornaments.append(ornament)
            continue
        accidental = decode_accidental_control_token(token)
        if accidental is not None:
            alter, name, cautionary = accidental
            if not attach_accidental_to_recent_note(alter, name, cautionary):
                pending_accidental = accidental
            continue
        dots = decode_dot_token(token)
        if dots is not None:
            for index in range(len(events) - 1, -1, -1):
                if events[index].kind in {'note', 'rest', 'slash'}:
                    events[index] = dataclasses.replace(events[index], dots=max(events[index].dots, dots))
                    break
            else:
                pending_dots = max(pending_dots, dots)
            continue
        rest = decode_rest_token(token)
        if rest is not None:
            add_event(MusicEvent('rest', rest, raw=token.hex(' '), dots=mosaic_rest_dots(token)))
            continue
        chord_symbol = decode_chord_symbol_token(token)
        if chord_symbol is not None:
            add_event(MusicEvent('harmony', '', raw=token.hex(' '), text=chord_symbol))
            continue
        note = decode_note_token(token, wrap_low_pitch_notes)
        if note is not None:
            duration, pitch, alter, _code = note
            add_event(MusicEvent('note', duration, pitch, alter, token.hex(' ')))
            continue
        slash_note = decode_slash_note_token(token)
        if slash_note is not None:
            duration, code = slash_note
            dots = mosaic_slash_note_dots(token)
            is_percussion_notehead = unpitched_note_like and staff_position_clef is not None and (staff_position_clef.sign == 'percussion') and (code >= 8)
            kind = 'unpitched' if is_percussion_notehead else 'slash'
            pitch = ''
            if kind == 'slash' and staff_position_clef is not None:
                pitch = mosaic_slash_display_pitch(code, staff_position_clef)
            add_event(MusicEvent(kind, duration, pitch=pitch, raw=token.hex(' '), dots=dots, display_code=code))
            continue
        if scanned.kind != 'end':
            control_event = music_control_event_from_token(scanned)
            if include_controls or should_export_music_control_by_default(control_event):
                events.append(control_event)
    for articulation in pending_articulations:
        events.append(MusicEvent('articulation', '', raw='', text=articulation))
    for articulation in pending_note_articulations:
        events.append(MusicEvent('articulation', '', raw='', text=articulation))
    for ornament in pending_ornaments:
        events.append(MusicEvent('ornament', '', raw='', text=ornament))
    return apply_mosaic_semantic_spans(events)
EVENT_TOKEN_KINDS = {'note', 'note-chord', 'rest', 'harmony', 'slash', 'unpitched', 'staff-position-note'}
MUSIC_DURATION_TOKEN_KINDS = {'note', 'note-chord', 'rest', 'slash', 'unpitched', 'staff-position-note', 'undecoded-duration'}
KNOWN_NON_DURATION_TOKEN_KINDS = {'accidental', 'articulation', 'dot', 'end', 'note-display-control', 'span-control', 'slur-span-control', 'stem-control', 'tie-span-control', 'grouping-span-control', 'grouping-scale-control', 'tool-palette-control', 'notehead-control', 'acc-control', 'cacc-control', 'orna-control', 'dyna-control', 'hair-control', 'blin-control', 'mrpt-control', 'text-control', 'chrd-control', 'grup-control', 'tie-control', 'tupl-control', 'sbra-control'}

def is_decoded_music_token(token: ScannedMusicToken) -> bool:
    return token.kind in EVENT_TOKEN_KINDS | KNOWN_NON_DURATION_TOKEN_KINDS

def music_token_groups(payload: bytes, wrap_low_pitch_notes: bool=False, unpitched_note_like: bool=False) -> tuple[ScannedMusicToken, tuple[MosaicMusicTokenGroup, ...]]:
    prefix: list[ScannedMusicToken] = []
    groups: list[MosaicMusicTokenGroup] = []
    current: list[ScannedMusicToken] = []
    current_start = 0
    for token in scanned_music_tokens(payload, wrap_low_pitch_notes, unpitched_note_like):
        if token.kind == 'end':
            break
        if token.kind in MUSIC_DURATION_TOKEN_KINDS:
            if current:
                groups.append(MosaicMusicTokenGroup(len(groups), current_start, tuple(current)))
            current = [token]
            current_start = token.off
            continue
        if current:
            current.append(token)
        else:
            prefix.append(token)
    if current:
        groups.append(MosaicMusicTokenGroup(len(groups), current_start, tuple(current)))
    return (ScannedMusicToken('prefix', 0, 0, '', ' '.join((token.raw for token in prefix))), tuple(groups))

def music_token_is_hidden_rest(token: ScannedMusicToken) -> bool:
    if token.kind != 'rest' or not token.raw:
        return False
    return rest_token_hidden(bytes.fromhex(token.raw))

def mosaic_music_group_lane_from_duration_flag(group: MosaicMusicTokenGroup, lanes: set[int]) -> tuple[int | None, str]:
    if not group.tokens or not lanes.issuperset({0, 2}):
        return (None, '')
    duration = group.tokens[0]
    if not duration.raw or duration.kind not in MUSIC_DURATION_TOKEN_KINDS:
        return (None, '')
    token = bytes.fromhex(duration.raw)
    if duration.kind in {'note', 'note-chord', 'slash', 'staff-position-note', 'undecoded-duration'}:
        lane = 0 if token[0] & 1 else 2
        return (lane, f'{duration.kind} lane flag bit={token[0] & 1}')
    if duration.kind == 'rest' and len(token) > 1:
        lane = 0 if token[1] & 1 else 2
        return (lane, f'rest lane flag bit={token[1] & 1}')
    return (None, '')

def mosaic_music_group_lane_hint(group: MosaicMusicTokenGroup, lane_refs: tuple[MosaicVoiceLaneRef, ...]=()) -> tuple[int | None, str]:
    if not group.tokens:
        return (None, '')
    lanes = {ref.lane for ref in lane_refs}
    if len(lanes) == 1:
        lane = next(iter(lanes))
        return (lane, 'single lane ref')
    lane, reason = mosaic_music_group_lane_from_duration_flag(group, lanes)
    if lane is not None:
        return (lane, reason)
    if lane_refs:
        return (None, '')
    duration = group.tokens[0]
    raws = {token.raw for token in group.tokens}
    has_harmony = any((token.kind == 'harmony' for token in group.tokens))
    if duration.kind == 'rest' and music_token_is_hidden_rest(duration) and ('40 81' in raws):
        reason = 'hidden rest + 40 81'
        if '4e 80' in raws:
            reason += ' + 4e 80'
        if has_harmony:
            reason += ' + harmony'
        return (2, reason)
    if duration.kind in MUSIC_DURATION_TOKEN_KINDS and '4c 00 19 33 84' in raws:
        return (0, 'duration event + 4c 00 19 33 84')
    if has_harmony:
        return (2, 'harmony')
    return (None, '')

def music_events_from_token_group(group: MosaicMusicTokenGroup, include_controls: bool=False, wrap_low_pitch_notes: bool=False, unpitched_note_like: bool=False, staff_position_clef: MusicXmlClef | None=None, grouping_scale_entries: tuple[MosaicGroupingScaleEntry, ...]=()) -> list[MusicEvent]:
    payload = b''.join((bytes.fromhex(token.raw) for token in group.tokens if token.raw)) + b'M'
    return music_events_from_cell(payload, include_controls, wrap_low_pitch_notes, unpitched_note_like, staff_position_clef, grouping_scale_entries)

def music_events_from_token_group_for_mosaic_lane(group: MosaicMusicTokenGroup, lane: int | None, include_controls: bool=False, wrap_low_pitch_notes: bool=False, unpitched_note_like: bool=False, staff_position_clef: MusicXmlClef | None=None, grouping_scale_entries: tuple[MosaicGroupingScaleEntry, ...]=()) -> list[MusicEvent]:
    events = music_events_from_token_group(group, include_controls, wrap_low_pitch_notes, unpitched_note_like, staff_position_clef, grouping_scale_entries)
    if lane != 2 or not group.tokens or (not group.tokens[0].raw):
        return events
    duration_token = bytes.fromhex(group.tokens[0].raw)
    if not duration_token or duration_token[0] & 1 or (not is_note_like_token(duration_token)):
        return events
    adjusted_duration = bytes([duration_token[0] | 1]) + duration_token[1:]
    adjusted_payload = adjusted_duration + b''.join((bytes.fromhex(token.raw) for token in group.tokens[1:] if token.raw)) + b'M'
    adjusted_events = music_events_from_cell(adjusted_payload, include_controls, wrap_low_pitch_notes, unpitched_note_like, staff_position_clef, grouping_scale_entries)
    if not events or not adjusted_events:
        return events
    original = events[0]
    adjusted = adjusted_events[0]
    if original.kind == 'note' and adjusted.kind == 'note' and (original.pitch == adjusted.pitch) and (original.alter == -1) and (adjusted.alter == 0):
        adjusted_events[0] = dataclasses.replace(adjusted, raw=group.tokens[0].raw)
        return adjusted_events
    return apply_mosaic_semantic_spans(events)

def music_events_from_cell_with_same_time_chords(payload: bytes, include_controls: bool=False, wrap_low_pitch_notes: bool=False, unpitched_note_like: bool=False, staff_position_clef: MusicXmlClef | None=None, grouping_scale_entries: tuple[MosaicGroupingScaleEntry, ...]=()) -> list[MusicEvent]:
    prefix, groups = music_token_groups(payload, wrap_low_pitch_notes, unpitched_note_like)
    runs = mosaic_music_same_time_runs(groups)
    if not groups or prefix.detail or (not any((len(run) > 1 for run in runs))):
        return music_events_from_cell(payload, include_controls, wrap_low_pitch_notes, unpitched_note_like, staff_position_clef, grouping_scale_entries)
    events: list[MusicEvent] = []
    for run in runs:
        if len(run) == 1:
            events.extend(music_events_from_token_group(run[0], include_controls, wrap_low_pitch_notes, unpitched_note_like, staff_position_clef, grouping_scale_entries))
            continue
        run_events: list[MusicEvent] = []
        nominal_durations: list[int] = []
        for group_index, group in enumerate(run):
            group_events = music_events_from_token_group(group, include_controls, wrap_low_pitch_notes, unpitched_note_like, staff_position_clef, grouping_scale_entries)
            duration_indexes = [index for index, event in enumerate(group_events) if event_nominal_duration_divisions(event) is not None]
            if len(duration_indexes) != 1:
                return music_events_from_cell(payload, include_controls, wrap_low_pitch_notes, unpitched_note_like, staff_position_clef, grouping_scale_entries)
            duration_index = duration_indexes[0]
            duration_event = group_events[duration_index]
            nominal_duration = event_nominal_duration_divisions(duration_event)
            if nominal_duration is None or duration_event.kind != 'note':
                return music_events_from_cell(payload, include_controls, wrap_low_pitch_notes, unpitched_note_like, staff_position_clef, grouping_scale_entries)
            nominal_durations.append(nominal_duration)
            if group_index:
                group_events[duration_index] = dataclasses.replace(duration_event, chord=True)
            run_events.extend(group_events)
        if len(set(nominal_durations)) != 1:
            return music_events_from_cell(payload, include_controls, wrap_low_pitch_notes, unpitched_note_like, staff_position_clef, grouping_scale_entries)
        events.extend(run_events)
    return apply_mosaic_semantic_spans(events)

def mosaic_voice_ids_in_lane_ref_order(lane_refs: tuple[MosaicVoiceLaneRef, ...]) -> tuple[int, ...]:
    voice_ids: list[int] = []
    for ref in lane_refs:
        for voice_id in ref.voice_ids:
            if voice_id not in voice_ids:
                voice_ids.append(voice_id)
    return tuple(voice_ids)

def music_events_by_mosaic_lane(payload: bytes, lane_refs: tuple[MosaicVoiceLaneRef, ...], include_controls: bool=False, wrap_low_pitch_notes: bool=False, unpitched_note_like: bool=False, staff_position_clef: MusicXmlClef | None=None, grouping_scale_entries: tuple[MosaicGroupingScaleEntry, ...]=()) -> list[tuple[int, list[MusicEvent]]] | None:
    lane_order = [ref.lane for ref in lane_refs]
    if len(set(lane_order)) != len(lane_order) or len(lane_order) <= 1:
        return None
    lane_events: dict[int, list[MusicEvent]] = {lane: [] for lane in lane_order}
    _prefix, groups = music_token_groups(payload, wrap_low_pitch_notes, unpitched_note_like)
    if not groups:
        return None
    for group in groups:
        lane, _reason = mosaic_music_group_lane_hint(group, lane_refs)
        if lane not in lane_events:
            return None
        lane_events[lane].extend(music_events_from_token_group_for_mosaic_lane(group, lane, include_controls, wrap_low_pitch_notes, unpitched_note_like, staff_position_clef, grouping_scale_entries))
    result: list[tuple[int, list[MusicEvent]]] = []
    for voice_number, lane in enumerate(lane_order, start=1):
        events = apply_mosaic_semantic_spans(lane_events.get(lane, []))
        if events:
            result.append((voice_number, events))
    return result or None

def music_events_by_mosaic_lane_voice_groups(payload: bytes, lane_refs: tuple[MosaicVoiceLaneRef, ...], marker4: MosaicVoiceLaneBlock | None=None, include_controls: bool=False, wrap_low_pitch_notes: bool=False, unpitched_note_like: bool=False, staff_position_clef: MusicXmlClef | None=None, grouping_scale_entries: tuple[MosaicGroupingScaleEntry, ...]=()) -> list[tuple[int, list[MusicEvent]]] | None:
    lane_groups = mosaic_lane_voice_groups(lane_refs)
    if len(lane_groups) <= 1 or not any((len(voice_ids) > 1 for voice_ids in lane_groups.values())):
        return None
    _prefix, groups = music_token_groups(payload, wrap_low_pitch_notes, unpitched_note_like)
    if not groups:
        return None
    voice_ids = mosaic_voice_ids_in_lane_ref_order(lane_refs)
    voice_events_by_id: dict[int, list[MusicEvent]] = {voice_id: [] for voice_id in voice_ids}
    groups_by_lane: dict[int, list[MosaicMusicTokenGroup]] = {}
    for group in groups:
        lane, _reason = mosaic_music_group_lane_hint(group, lane_refs)
        if lane is None or lane not in lane_groups:
            return None
        groups_by_lane.setdefault(lane, []).append(group)
    for lane, lane_run_groups in groups_by_lane.items():
        lane_voice_ids = lane_groups[lane]
        if len(lane_voice_ids) == 1:
            lane_events = {lane_voice_ids[0]: []}
            for group in lane_run_groups:
                lane_events[lane_voice_ids[0]].extend(music_events_from_token_group_for_mosaic_lane(group, lane, include_controls, wrap_low_pitch_notes, unpitched_note_like, staff_position_clef, grouping_scale_entries))
        else:
            lane_events = mosaic_events_by_same_lane_voice_ids_from_groups(tuple(lane_run_groups), marker4, lane_voice_ids, include_controls, wrap_low_pitch_notes, unpitched_note_like, lane, staff_position_clef, grouping_scale_entries)
            if lane_events is None:
                return None
        for voice_id, events in lane_events.items():
            voice_events_by_id.setdefault(voice_id, []).extend(events)
    result: list[tuple[int, list[MusicEvent]]] = []
    for voice_number, voice_id in enumerate(voice_ids, start=1):
        events = apply_mosaic_semantic_spans(voice_events_by_id.get(voice_id, []))
        if events:
            result.append((voice_number, events))
    return result or None

def duration_name_from_scanned_duration_token(token: ScannedMusicToken) -> str | None:
    if not token.raw or token.kind not in MUSIC_DURATION_TOKEN_KINDS:
        return None
    raw = bytes.fromhex(token.raw)
    if token.kind == 'rest':
        duration = decode_rest_token(raw)
        return duration
    duration_code = raw[0] >> 3 & 7
    return NOTE_DURATION_CODES.get(duration_code)

def music_events_by_same_lane_voice_refs(payload: bytes, lane_refs: tuple[MosaicVoiceLaneRef, ...], marker4: MosaicVoiceLaneBlock | None=None, include_controls: bool=False, wrap_low_pitch_notes: bool=False, unpitched_note_like: bool=False, staff_position_clef: MusicXmlClef | None=None, grouping_scale_entries: tuple[MosaicGroupingScaleEntry, ...]=()) -> list[tuple[int, list[MusicEvent]]] | None:
    lane_groups = mosaic_lane_voice_groups(lane_refs)
    if len(lane_groups) != 1:
        return None
    voice_ids = next(iter(lane_groups.values()))
    if len(voice_ids) <= 1:
        return None
    _prefix, groups = music_token_groups(payload, wrap_low_pitch_notes, unpitched_note_like)
    if not groups:
        return None
    voice_events_by_id = mosaic_events_by_same_lane_voice_ids_from_groups(groups, marker4, voice_ids, include_controls, wrap_low_pitch_notes, unpitched_note_like, next(iter(lane_groups)), staff_position_clef, grouping_scale_entries)
    if voice_events_by_id is None:
        return None
    return [(voice_number, voice_events_by_id[voice_id]) for voice_number, voice_id in enumerate(voice_ids, start=1) if voice_events_by_id.get(voice_id)]

def mosaic_events_by_same_lane_voice_ids_from_groups(groups: tuple[MosaicMusicTokenGroup, ...], marker4: MosaicVoiceLaneBlock | None, voice_ids: tuple[int, ...], include_controls: bool=False, wrap_low_pitch_notes: bool=False, unpitched_note_like: bool=False, lane: int | None=None, staff_position_clef: MusicXmlClef | None=None, grouping_scale_entries: tuple[MosaicGroupingScaleEntry, ...]=()) -> dict[int, list[MusicEvent]] | None:
    voice_events_by_id: dict[int, list[MusicEvent]] = {voice_id: [] for voice_id in voice_ids}
    for run in mosaic_music_same_time_runs(groups):
        assignment = mosaic_same_time_run_voice_assignment(run, marker4, voice_ids)
        if assignment is not None:
            for group, assigned_voice_ids in zip(run, assignment):
                events = music_events_from_token_group_for_mosaic_lane(group, lane, include_controls=False, wrap_low_pitch_notes=wrap_low_pitch_notes, unpitched_note_like=unpitched_note_like, staff_position_clef=staff_position_clef, grouping_scale_entries=grouping_scale_entries)
                for voice_id in assigned_voice_ids:
                    voice_events_by_id.setdefault(voice_id, []).extend(events)
            continue
        if len(run) == 1:
            packed_events = mosaic_packed_pitch_set_voice_events(run[0], marker4, voice_ids, wrap_low_pitch_notes, unpitched_note_like, lane, grouping_scale_entries)
            if packed_events is not None:
                for voice_id, event in packed_events.items():
                    voice_events_by_id.setdefault(voice_id, []).append(event)
                continue
            shared_note_events = mosaic_same_pitch_voice_events(run[0], marker4, voice_ids, wrap_low_pitch_notes, unpitched_note_like, lane, staff_position_clef, grouping_scale_entries)
            if shared_note_events is not None:
                for voice_id, event in shared_note_events.items():
                    voice_events_by_id.setdefault(voice_id, []).append(event)
                continue
        for group in run:
            if not group.tokens:
                return None
            duration_token = group.tokens[0]
            duration_name = duration_name_from_scanned_duration_token(duration_token)
            if duration_name is None:
                return None
            raw_group = ' '.join((token.raw for token in group.tokens if token.raw))
            if duration_token.kind == 'rest':
                raw_token = bytes.fromhex(duration_token.raw) if duration_token.raw else b''
                event = MusicEvent('rest', duration_name, raw=duration_token.raw, dots=mosaic_rest_dots(raw_token))
            else:
                event = MusicEvent('unpitched', duration_name, raw=raw_group)
            for events in voice_events_by_id.values():
                events.append(event)
            if include_controls:
                controls = [music_control_event_from_token(token) for token in group.tokens[1:] if token.kind in KNOWN_NON_DURATION_TOKEN_KINDS and token.raw]
                first_voice_events = voice_events_by_id.get(voice_ids[0]) if voice_ids else None
                if controls and first_voice_events is not None:
                    first_voice_events.extend(controls)
    return {voice_id: apply_mosaic_semantic_spans(events) for voice_id, events in voice_events_by_id.items()}

def mosaic_voice_marker4_block(info: MosaicStaffVoiceInfo | None) -> MosaicVoiceLaneBlock | None:
    if info is None:
        return None
    for block in info.lane_blocks:
        if block.marker == 4:
            return block
    return None

def mosaic_voice_ids_from_lane_list(lane_list: MosaicVoiceLaneList) -> tuple[tuple[int, ...], ...]:
    return tuple((ref.voice_ids for ref in lane_list.entries if ref.voice_ids))

def mosaic_same_time_assignment_from_entries(entries: tuple[tuple[int, ...], ...], run: tuple[MosaicMusicTokenGroup, ...], preferred_voice_ids: tuple[int, ...]) -> tuple[tuple[int, ...], ...] | None:
    preferred_set = set(preferred_voice_ids)
    if any((voice_id not in preferred_set for entry in entries for voice_id in entry)):
        return None
    flattened_entries = tuple(((voice_id,) for entry in entries for voice_id in entry))
    flattened_voice_ids = [voice_id for entry in flattened_entries for voice_id in entry]
    if len(flattened_entries) == len(run) and len(set(flattened_voice_ids)) == len(flattened_voice_ids):
        return flattened_entries
    mutable_entries = list(entries)
    if len(mutable_entries) < len(run):
        assigned = {voice_id for entry in mutable_entries for voice_id in entry}
        for voice_id in preferred_voice_ids:
            if voice_id not in assigned:
                mutable_entries.append((voice_id,))
            if len(mutable_entries) == len(run):
                break
    if len(mutable_entries) != len(run):
        return None
    return tuple(mutable_entries)

def mosaic_same_time_run_voice_assignment(run: tuple[MosaicMusicTokenGroup, ...], marker4: MosaicVoiceLaneBlock | None, preferred_voice_ids: tuple[int, ...]) -> tuple[tuple[int, ...], ...] | None:
    if marker4 is None or len(run) <= 1:
        return None
    for group in run:
        if not group.tokens or group.tokens[0].kind == 'undecoded-duration':
            return None
    selector_indices: list[int] = []
    has_restore = False
    for group in run:
        for _token, op, list_index in mosaic_music_group_voice_list_controls(group):
            if op == 64:
                selector_indices.append(list_index)
            elif op == 78:
                has_restore = True
    if not selector_indices or not has_restore:
        return None
    for list_index in reversed(selector_indices):
        if not 0 <= list_index < len(marker4.lists):
            continue
        entries = mosaic_voice_ids_from_lane_list(marker4.lists[list_index])
        if not entries:
            continue
        assignment = mosaic_same_time_assignment_from_entries(entries, run, preferred_voice_ids)
        if assignment is not None:
            return assignment
    return None

def mosaic_same_pitch_voice_events(group: MosaicMusicTokenGroup, marker4: MosaicVoiceLaneBlock | None, preferred_voice_ids: tuple[int, ...], wrap_low_pitch_notes: bool=True, unpitched_note_like: bool=False, lane: int | None=None, staff_position_clef: MusicXmlClef | None=None, grouping_scale_entries: tuple[MosaicGroupingScaleEntry, ...]=()) -> dict[int, MusicEvent] | None:
    entries = mosaic_music_group_selector_voice_entries(group, marker4)
    if entries is None:
        return None
    selected_voice_ids = tuple((voice_id for entry in entries for voice_id in entry))
    if len(selected_voice_ids) <= 1 or len(set(selected_voice_ids)) != len(selected_voice_ids) or set(selected_voice_ids) != set(preferred_voice_ids):
        return None
    events = music_events_from_token_group_for_mosaic_lane(group, lane, include_controls=False, wrap_low_pitch_notes=wrap_low_pitch_notes, unpitched_note_like=unpitched_note_like, staff_position_clef=staff_position_clef, grouping_scale_entries=grouping_scale_entries)
    if len(events) != 1 or events[0].kind not in {'note', 'rest'}:
        return None
    return {voice_id: events[0] for voice_id in preferred_voice_ids}

def mosaic_music_group_selector_voice_entries(group: MosaicMusicTokenGroup, marker4: MosaicVoiceLaneBlock | None) -> tuple[tuple[int, ...], ...] | None:
    if marker4 is None:
        return None
    selector_indices = [list_index for _token, op, list_index in mosaic_music_group_voice_list_controls(group) if op == 64]
    if not selector_indices:
        return None
    list_index = selector_indices[-1]
    if not 0 <= list_index < len(marker4.lists):
        return None
    entries = mosaic_voice_ids_from_lane_list(marker4.lists[list_index])
    return entries or None

def mosaic_packed_pitch_set_voice_assignment(group: MosaicMusicTokenGroup, marker4: MosaicVoiceLaneBlock | None, preferred_voice_ids: tuple[int, ...], pitch_count: int) -> tuple[int, ...] | None:
    entries = mosaic_music_group_selector_voice_entries(group, marker4)
    if entries is None:
        if pitch_count == len(preferred_voice_ids):
            return preferred_voice_ids
        return None
    if any((len(entry) != 1 for entry in entries)):
        return None
    entry_voice_ids = tuple((entry[0] for entry in entries))
    preferred_set = set(preferred_voice_ids)
    if any((voice_id not in preferred_set for voice_id in entry_voice_ids)):
        return None
    if len(entry_voice_ids) == pitch_count and len(set(entry_voice_ids)) == pitch_count:
        return entry_voice_ids
    if len(entry_voice_ids) == 1 and pitch_count == len(preferred_voice_ids):
        selected_voice_id = entry_voice_ids[0]
        if selected_voice_id not in preferred_voice_ids:
            return None
        assigned: list[int | None] = [None] * pitch_count
        selected_index = preferred_voice_ids.index(selected_voice_id)
        if selected_index >= pitch_count:
            return None
        assigned[selected_index] = selected_voice_id
        for index, voice_id in enumerate(preferred_voice_ids):
            if index >= pitch_count:
                return None
            if assigned[index] is None:
                assigned[index] = voice_id
        if any((voice_id is None for voice_id in assigned)):
            return None
        return tuple((voice_id for voice_id in assigned if voice_id is not None))
    return None

def mosaic_packed_pitch_set_voice_events(group: MosaicMusicTokenGroup, marker4: MosaicVoiceLaneBlock | None, preferred_voice_ids: tuple[int, ...], wrap_low_pitch_notes: bool=True, unpitched_note_like: bool=False, lane: int | None=None, grouping_scale_entries: tuple[MosaicGroupingScaleEntry, ...]=()) -> dict[int, MusicEvent] | None:
    if not group.tokens or not group.tokens[0].raw:
        return None
    token = bytes.fromhex(group.tokens[0].raw)
    pitch_set = decode_packed_pitch_set_token(token, True, lane)
    if pitch_set is None:
        return None
    duration, pitch_codes = pitch_set
    assignment = mosaic_packed_pitch_set_voice_assignment(group, marker4, preferred_voice_ids, len(pitch_codes))
    if assignment is None:
        return None
    scale_by_index = {entry.index: entry for entry in grouping_scale_entries}
    group_scales: list[MosaicGroupingScaleEntry] = []
    for token in group.tokens[1:]:
        if not token.raw:
            continue
        scale = decode_mosaic_grouping_scale_token(bytes.fromhex(token.raw))
        if scale is None:
            continue
        entry = scale_by_index.get(scale['field_0'])
        if entry is not None:
            group_scales.append(entry)

    def with_grouping_scales(event: MusicEvent) -> MusicEvent:
        for entry in group_scales:
            event = add_grouping_scale_to_event(event, entry.index, entry.actual_notes, entry.normal_notes)
        return event
    events: dict[int, MusicEvent] = {}
    for voice_id, pitch_code in zip(assignment, pitch_codes):
        if unpitched_note_like:
            events[voice_id] = with_grouping_scales(MusicEvent('unpitched', duration, raw=group.tokens[0].raw))
        else:
            pitch, alter = pitch_code_to_name(pitch_code)
            events[voice_id] = with_grouping_scales(MusicEvent('note', duration, pitch, alter, raw=group.tokens[0].raw))
    return events
DISPLAY_CONTROL_START_BYTES = frozenset({0, 1, 2, 24, 25, 36, 38, 48, 49, 50, 51, 52, 54, 56, 57, 65, 69, 84, 86, 92, 97, 98, 99, 115, 116})
UNMAPPED_DISPLAY_FINAL_BYTES = {179, 236}

def decoded_display_control_label(token: bytes) -> tuple[str, str] | None:
    if not token:
        return None
    if token[0] & 128:
        if has_layout_final_byte(token):
            return ('note-display-control', token.hex(' '))
        return None
    if token[0] in DISPLAY_CONTROL_START_BYTES and len(token) <= 7 and (has_layout_final_byte(token) or token[-1] in UNMAPPED_DISPLAY_FINAL_BYTES):
        return ('note-display-control', token.hex(' '))
    return None

def classify_scanned_music_token(token: bytes, wrap_low_pitch_notes: bool=False, unpitched_note_like: bool=False) -> tuple[str, str]:
    tie = decode_tie_grouping_span_token(token)
    if tie is not None:
        return ('tie-span-control', tie)
    slur_position = decode_mosaic_slur_position_token(token)
    if slur_position is not None:
        level, position = slur_position
        return ('slur-span-control', f'level={level} position={position}')
    grouping_scale = decode_mosaic_grouping_scale_token(token)
    if grouping_scale is not None:
        return ('grouping-scale-control', ' '.join((f'{key}={grouping_scale[key]}' for key in ('field_0', 'field_4', 'field_6', 'field_8', 'field_c'))))
    measure_repeat_glyph = decode_measure_repeat_glyph_token(token)
    if measure_repeat_glyph is not None:
        return ('mrpt-control', measure_repeat_glyph)
    articulation = decode_articulation_token(token)
    if articulation is not None:
        return ('articulation', articulation)
    notehead_detail = notehead_control_detail(token)
    if notehead_detail is not None:
        return ('notehead-control', notehead_detail)
    stem = decode_stem_display_control_token(token)
    if stem is not None:
        return ('stem-control', f'stem={stem}')
    accidental = decode_accidental_control_token(token)
    if accidental is not None:
        return ('accidental', format_accidental_control_detail(accidental))
    dynamic_symbol = decode_dynamic_display_control_token(token)
    if dynamic_symbol is not None:
        return ('dyna-control', dynamic_display_control_label(dynamic_symbol).removeprefix('dyna-control '))
    articulation = decode_articulation_display_control_token(token)
    if articulation is not None:
        return ('articulation', articulation)
    dots = decode_dot_token(token)
    if dots is not None:
        return ('dot', f'dots={dots}')
    rest = decode_rest_token(token)
    if rest is not None:
        hidden = ' hidden' if rest_token_hidden(token) else ''
        dots = mosaic_rest_dots(token)
        dot_text = '.' * dots
        return ('rest', f'{rest}{dot_text}{hidden}')
    chord_symbol = decode_chord_symbol_token(token)
    if chord_symbol is not None:
        return ('harmony', chord_symbol)
    if unpitched_note_like:
        unpitched_packed = decode_unpitched_packed_note_token(token)
        if unpitched_packed is not None:
            duration, head_count = unpitched_packed
            return ('unpitched', f"{duration} heads={head_count} raw={token.hex(' ')}")
    packed_pitch_set = decode_packed_pitch_set_token(token, wrap_low_pitch_notes)
    if packed_pitch_set is not None:
        duration, pitch_codes = packed_pitch_set
        return ('note-chord', f"{duration} pitches={format_pitch_code_set(pitch_codes)} raw={token.hex(' ')}")
    note = decode_note_token(token)
    if note is not None:
        duration, pitch, alter, code = note
        alter_text = '' if alter == 0 else f' alter={alter:+d}'
        packed_text = ''
        if len(token) > 3:
            packed_code, chunks, aux = note_like_packed_code_parts(token)
            bits = ','.join((str(bit) for bit in range(32) if packed_code & 1 << bit))
            pitch_set = decode_packed_pitch_set_token(token)
            pitch_set_text = ''
            if pitch_set is not None:
                _pitch_set_duration, pitch_codes = pitch_set
                pitch_set_text = ' pitch_set=' + format_pitch_code_set(pitch_codes)
            packed_text = f" packed={packed_code} aux={('' if aux is None else aux)} chunks=[{','.join((str(chunk) for chunk in chunks))}] bits=[{bits}]{pitch_set_text}"
        return ('note', f'{duration} {pitch}{alter_text} code={code}{packed_text}')
    if wrap_low_pitch_notes:
        note = decode_note_token(token, True)
        if note is not None:
            duration, pitch, alter, code = note
            alter_text = '' if alter == 0 else f' alter={alter:+d}'
            packed_text = ''
            if len(token) > 3:
                packed_code, chunks, aux = note_like_packed_code_parts(token)
                bits = ','.join((str(bit) for bit in range(32) if packed_code & 1 << bit))
                packed_text = f" packed={packed_code} aux={('' if aux is None else aux)} chunks=[{','.join((str(chunk) for chunk in chunks))}] bits=[{bits}]"
            return ('note', f'{duration} {pitch}{alter_text} code={code} wrapped-low{packed_text}')
    slash_note = decode_slash_note_token(token)
    if slash_note is not None:
        duration, code = slash_note
        dots = mosaic_slash_note_dots(token)
        dot_text = '.' * dots
        display = mosaic_slash_display_pitch(code)
        return ('slash', f'{duration}{dot_text} code={code} display={display}')
    if is_note_like_token(token):
        duration_code = token[0] >> 3 & 7
        duration = NOTE_DURATION_CODES.get(duration_code, f'code-{duration_code}')
        packed_code, chunks, aux = note_like_packed_code_parts(token)
        bits = ','.join((str(bit) for bit in range(32) if packed_code & 1 << bit))
        bitstream_text = mosaic_category0_bitstream_debug_text(token)
        descriptor_positions = mosaic_category0_descriptor_positions(token)
        if bitstream_text:
            bitstream_text = ' ' + bitstream_text
        pitch_set = decode_packed_pitch_set_token(token)
        pitch_set_text = ''
        if pitch_set is not None:
            _pitch_set_duration, pitch_codes = pitch_set
            pitch_set_text = ' pitch_set=' + format_pitch_code_set(pitch_codes)
        if descriptor_positions:
            return ('staff-position-note', f"{duration} app_cat={mosaic_token_category(token[0])}{bitstream_text} raw={token.hex(' ')}")
        return ('undecoded-duration', f"{duration} app_cat={mosaic_token_category(token[0])} packed={packed_code} aux={('' if aux is None else aux)} chunks=[{','.join((str(chunk) for chunk in chunks))}] bits=[{bits}]{pitch_set_text}{bitstream_text} raw={token.hex(' ')}")
    jazz_articulation = decode_jazz_fallback_articulation_token(token)
    if jazz_articulation is not None:
        return ('articulation', jazz_articulation)
    tool_control = decoded_tool_control_label(token)
    if tool_control is not None:
        return tool_control
    if token and token[0] == 80:
        return ('rest-control', token.hex(' '))
    if token and token[0] == 67:
        return ('harmony-control', token.hex(' '))
    if token and token[0] & 128:
        return ('high-control', token.hex(' '))
    return ('control', token.hex(' '))

def scanned_music_tokens(payload: bytes, wrap_low_pitch_notes: bool=False, unpitched_note_like: bool=False) -> list[ScannedMusicToken]:
    tokens: list[ScannedMusicToken] = []
    for off, token in split_raw_music_tokens(payload):
        kind, detail = classify_scanned_music_token(token, wrap_low_pitch_notes, unpitched_note_like)
        tokens.append(ScannedMusicToken(kind, off, len(token), token.hex(' '), detail))
    end = payload.find(b'M')
    if end >= 0:
        tokens.append(ScannedMusicToken('end', end, 1, '4d'))
    return tokens
DIVISIONS_PER_QUARTER = 480
XML_DURATION_DIVISIONS = {'whole': DIVISIONS_PER_QUARTER * 4, 'half': DIVISIONS_PER_QUARTER * 2, 'quarter': DIVISIONS_PER_QUARTER, 'eighth': DIVISIONS_PER_QUARTER // 2, '16th': DIVISIONS_PER_QUARTER // 4, '32nd': DIVISIONS_PER_QUARTER // 8, '64th': DIVISIONS_PER_QUARTER // 16}
XML_TYPE_NAMES = {'whole': 'whole', 'half': 'half', 'quarter': 'quarter', 'eighth': 'eighth', '16th': '16th', '32nd': '32nd', '64th': '64th'}
MUSICXML_BEAM_LEVELS_BY_DURATION = {'eighth': 1, '16th': 2, '32nd': 3, '64th': 4}
MUSICXML_STEP_SEMITONES = {'C': 0, 'D': 2, 'E': 4, 'F': 5, 'G': 7, 'A': 9, 'B': 11}

def musicxml_midi_number_for_event(event: MusicEvent) -> int | None:
    if event.kind != 'note' or len(event.pitch) < 2:
        return None
    step = event.pitch[0]
    if step not in MUSICXML_STEP_SEMITONES:
        return None
    try:
        octave = int(event.pitch[1:])
    except ValueError:
        return None
    return (octave + 1) * 12 + MUSICXML_STEP_SEMITONES[step] + musicxml_alter_for_event(event)

def musicxml_alter_from_mosaic_alter(alter: int) -> int:
    if alter > 0:
        return 1
    if alter < 0:
        return -1
    return 0
EXPLICIT_ACCIDENTAL_XML_ALTER = {'flat-flat': -2, 'flat': -1, 'natural': 0, 'sharp': 1, 'double-sharp': 2}
EXPLICIT_ACCIDENTAL_MUSICXML_NAME = {'flat-flat': 'flat-flat', 'flat': 'flat', 'natural': 'natural', 'sharp': 'sharp', 'double-sharp': 'double-sharp'}

def musicxml_key_signature_alter(step: str, key_fifths: int) -> int:
    if key_fifths > 0:
        return 1 if step in ('F', 'C', 'G', 'D', 'A', 'E', 'B')[:key_fifths] else 0
    if key_fifths < 0:
        return -1 if step in ('B', 'E', 'A', 'D', 'G', 'C', 'F')[:-key_fifths] else 0
    return 0

def musicxml_alter_for_event(event: MusicEvent, key_fifths: int=0) -> int:
    if event.accidental in EXPLICIT_ACCIDENTAL_XML_ALTER:
        return EXPLICIT_ACCIDENTAL_XML_ALTER[event.accidental]
    if key_fifths and event.pitch:
        key_alter = musicxml_key_signature_alter(event.pitch[0], key_fifths)
        if key_alter and event.alter in (0, key_alter):
            return key_alter
    if event.chromatic_alter:
        return musicxml_alter_from_mosaic_alter(event.alter)
    return musicxml_alter_from_mosaic_alter(event.alter)

def musicxml_accidental_alters_for_measure(event_voices: list[tuple[int, list[MusicEvent]]], key_fifths: int=0, tied_alters: dict[tuple[int, str], int] | None=None) -> dict[tuple[int, int], int]:
    timed_notes: list[tuple[int, int, int, MusicEvent]] = []
    for voice_number, voice_events in event_voices:
        position = 0
        for event_index, event in enumerate(voice_events):
            if event.kind == 'note':
                timed_notes.append((position, voice_number, event_index, event))
            duration = event_duration_divisions(event)
            if duration is not None:
                position += duration
    alters: dict[tuple[int, int], int] = {}
    accidental_state: dict[str, int] = {}
    current_position: int | None = None
    position_notes: list[tuple[int, int, int, MusicEvent]] = []

    def flush_position_notes() -> None:
        if not position_notes:
            return
        for _position, _voice_number, _event_index, event in position_notes:
            if event.accidental in EXPLICIT_ACCIDENTAL_XML_ALTER and event.pitch:
                accidental_state[event.pitch] = EXPLICIT_ACCIDENTAL_XML_ALTER[event.accidental]
            elif 'stop' in event.ties and event.pitch and (tied_alters is not None):
                tied_alter = tied_alters.get((_voice_number, event.pitch))
                if tied_alter is not None:
                    accidental_state[event.pitch] = tied_alter
        for _position, voice_number, event_index, event in position_notes:
            if event.accidental in EXPLICIT_ACCIDENTAL_XML_ALTER:
                alter = EXPLICIT_ACCIDENTAL_XML_ALTER[event.accidental]
            elif 'stop' in event.ties and event.pitch and (tied_alters is not None):
                alter = tied_alters.get((voice_number, event.pitch))
                if alter is None:
                    alter = accidental_state.get(event.pitch)
                    if alter is None:
                        alter = musicxml_alter_for_event(event, key_fifths)
            elif event.pitch in accidental_state:
                alter = accidental_state[event.pitch]
            else:
                alter = musicxml_alter_for_event(event, key_fifths)
            alters[voice_number, event_index] = alter
        position_notes.clear()
    for note_info in sorted(timed_notes, key=lambda item: (item[0], item[1], item[2])):
        position = note_info[0]
        if current_position is None:
            current_position = position
        elif position != current_position:
            flush_position_notes()
            current_position = position
        position_notes.append(note_info)
    flush_position_notes()
    return alters

def musicxml_accidental_name_for_event(event: MusicEvent) -> str | None:
    if event.accidental:
        return EXPLICIT_ACCIDENTAL_MUSICXML_NAME.get(event.accidental)
    return None

def add_musicxml_accidental(note: ET.Element, event: MusicEvent) -> None:
    accidental = musicxml_accidental_name_for_event(event)
    if accidental is None:
        return
    attrs: dict[str, str] = {}
    if event.accidental_cautionary:
        attrs['cautionary'] = 'yes'
    add_text(note, 'accidental', accidental, **attrs)

def infer_mosaic_part_clef(part: MosaicPartInfo | None, rows: list[MusicRow], part_index: int, sample_limit: int=96, wrap_low_pitch_notes: bool=False) -> MusicXmlClef:
    name = mosaic_part_display_name(part, '') if part is not None else ''
    normalized_name = name.lower()
    if any((word in normalized_name for word in ('drum', 'perc', 'percussion'))):
        return MusicXmlClef('percussion', 2)
    if any((word in normalized_name for word in ('bass', 'bone', 'trombone', 'tuba', 'cello'))):
        return MusicXmlClef('F', 4)
    pitches: list[int] = []
    for row in rows:
        if part_index >= len(row.cells):
            continue
        for event in music_events_from_cell(music_cell_event_payload(row.cells[part_index]), wrap_low_pitch_notes=wrap_low_pitch_notes):
            midi_number = musicxml_midi_number_for_event(event)
            if midi_number is None:
                continue
            pitches.append(midi_number)
            if len(pitches) >= sample_limit:
                break
        if len(pitches) >= sample_limit:
            break
    if pitches:
        median_pitch = sorted(pitches)[len(pitches) // 2]
        if median_pitch < 57:
            return MusicXmlClef('F', 4)
    return MusicXmlClef('G', 2)

def musicxml_beam_level_count(event: MusicEvent) -> int:
    if event.kind not in {'note', 'slash', 'unpitched'}:
        return 0
    return MUSICXML_BEAM_LEVELS_BY_DURATION.get(event.duration_name, 0)

def default_mosaic_beam_group_divisions(time_signature: tuple[int, int]) -> tuple[int, ...]:
    beats, beat_type = time_signature
    if beats <= 0 or beat_type <= 0:
        return ()
    beat_divisions = DIVISIONS_PER_QUARTER * 4 // beat_type
    measure_divisions = time_signature_duration_divisions(time_signature)
    if beat_divisions <= 0 or measure_divisions <= 0:
        return ()
    if beat_type == 8:
        if beats in {2, 3}:
            return (measure_divisions,)
        if beats % 3 == 0 and beats > 3:
            return tuple((beat_divisions * 3 for _ in range(beats // 3)))
        if beats == 5:
            return (beat_divisions * 3, beat_divisions * 2)
        if beats == 7:
            return (beat_divisions * 2, beat_divisions * 2, beat_divisions * 3)
        if beats == 8:
            return (beat_divisions * 3, beat_divisions * 3, beat_divisions * 2)
    return tuple((beat_divisions for _ in range(beats)))

def inferred_beams_for_events(events: list[MusicEvent], time_signature: tuple[int, int]=(4, 4)) -> dict[int, dict[int, str]]:
    beams: dict[int, dict[int, str]] = {}
    run: list[int] = []
    group_divisions = default_mosaic_beam_group_divisions(time_signature)
    group_ends: set[int] = set()
    position_cursor = 0
    for group_duration in group_divisions:
        position_cursor += group_duration
        group_ends.add(position_cursor)

    def flush_run() -> None:
        if len(run) < 2:
            run.clear()
            return
        run_positions = {event_index: pos for pos, event_index in enumerate(run)}
        for level in range(1, max((musicxml_beam_level_count(events[index]) for index in run)) + 1):
            level_run: list[int] = []

            def flush_level_run() -> None:
                if len(level_run) < 2:
                    if len(level_run) == 1 and len(run) >= 2:
                        event_index = level_run[0]
                        value = 'forward hook' if run_positions[event_index] == 0 else 'backward hook'
                        beams.setdefault(event_index, {})[level] = value
                    level_run.clear()
                    return
                for pos, event_index in enumerate(level_run):
                    if pos == 0:
                        value = 'begin'
                    elif pos == len(level_run) - 1:
                        value = 'end'
                    else:
                        value = 'continue'
                    beams.setdefault(event_index, {})[level] = value
                level_run.clear()
            for event_index in run:
                if musicxml_beam_level_count(events[event_index]) >= level:
                    level_run.append(event_index)
                else:
                    flush_level_run()
            flush_level_run()
        run.clear()
    position = 0
    for index, event in enumerate(events):
        if event.chord:
            continue
        duration = event_duration_divisions(event)
        if duration is not None and position > 0 and (position in group_ends):
            flush_run()
        if musicxml_beam_level_count(event) > 0:
            run.append(index)
        elif event.kind in {'control', 'articulation', 'ornament', 'harmony'}:
            continue
        else:
            flush_run()
        if duration is None:
            continue
        start_position = position
        position += duration
        if duration > 0 and (position in group_ends or any((start_position < group_end < position for group_end in group_ends))):
            flush_run()
    flush_run()
    return beams

def musicxml_note_notations(note: ET.Element) -> ET.Element:
    notations = note.find('notations')
    if notations is None:
        notations = add_text(note, 'notations')
    return notations

def add_musicxml_tied_notations(note: ET.Element, ties: tuple[str, ...]) -> None:
    if not ties:
        return
    notations = musicxml_note_notations(note)
    for tie in ties:
        add_text(notations, 'tied', type=tie)

def add_musicxml_articulations(note: ET.Element, articulations: tuple[str, ...]) -> None:
    if not articulations:
        return
    articulation_aliases = {'jazz-doit': 'doit', 'jazz-scoop': 'scoop'}
    articulation_tags = {'accent', 'staccato', 'staccatissimo', 'tenuto', 'strong-accent', 'scoop', 'plop', 'doit', 'falloff'}
    notations = musicxml_note_notations(note)
    articulation_parent = add_text(notations, 'articulations')
    for articulation in articulations:
        articulation_tag = articulation_aliases.get(articulation, articulation)
        if articulation_tag in articulation_tags:
            add_text(articulation_parent, articulation_tag)
        else:
            add_text(articulation_parent, 'other-articulation', articulation)

def add_musicxml_ornaments(note: ET.Element, ornaments: tuple[str, ...]) -> None:
    if not ornaments:
        return
    notations = musicxml_note_notations(note)
    ornament_parent = add_text(notations, 'ornaments')
    for ornament in ornaments:
        if ornament in {'trill-mark', 'turn', 'inverted-turn', 'mordent', 'inverted-mordent'}:
            add_text(ornament_parent, ornament)
        else:
            add_text(ornament_parent, 'other-ornament', ornament)

def add_musicxml_slur_notations(note: ET.Element, slurs: tuple[tuple[str, int], ...]) -> None:
    if not slurs:
        return
    notations = musicxml_note_notations(note)
    for slur_type, number in slurs:
        add_text(notations, 'slur', type=slur_type, number=str(number))

def add_musicxml_time_modification(note: ET.Element, time_modification: tuple[int, int] | None) -> None:
    if time_modification is None:
        return
    actual_notes, normal_notes = time_modification
    if actual_notes <= 0 or normal_notes <= 0:
        return
    time_mod = add_text(note, 'time-modification')
    add_text(time_mod, 'actual-notes', actual_notes)
    add_text(time_mod, 'normal-notes', normal_notes)

def add_musicxml_notehead(note: ET.Element, notehead: MusicXmlNotehead) -> None:
    attrs: dict[str, str] = {}
    if notehead.filled is not None:
        attrs['filled'] = 'yes' if notehead.filled else 'no'
    if notehead.parentheses is not None:
        attrs['parentheses'] = 'yes' if notehead.parentheses else 'no'
    add_text(note, 'notehead', notehead.value, **attrs)

def add_musicxml_tuplet_notations(note: ET.Element, tuplets: tuple[tuple[str, int], ...]) -> None:
    if not tuplets:
        return
    notations = musicxml_note_notations(note)
    for tuplet_type, number in tuplets:
        attrs = {'type': tuplet_type, 'number': str(number)}
        if tuplet_type == 'start':
            attrs.update({'bracket': 'yes', 'show-number': 'actual'})
        add_text(notations, 'tuplet', **attrs)

def parse_music_grid_at(data: bytes, marker_off: int) -> MusicGrid | None:
    if marker_off + 6 > len(data) or data[marker_off:marker_off + 2] != b'\x00\x18':
        return None
    columns = u16(data, marker_off + 2)
    row_count = u16(data, marker_off + 4)
    if not (1 <= columns <= 512 and 1 <= row_count <= 4096):
        return None
    if columns * row_count > 250000:
        return None
    pos = marker_off + 6
    rows: list[MusicRow] = []
    for row_index in range(row_count):
        row_off = pos
        if pos + 8 > len(data):
            return None
        table_kind = u16(data, pos)
        table_size = u32(data, pos + 2)
        table_ref = u16(data, pos + 6)
        if table_kind != 6:
            return None
        table_bytes = data[pos:pos + 8]
        pos += 8
        cells: list[MusicCell] = []
        for cell_index in range(columns):
            cell_off = pos
            if pos + 6 > len(data):
                return None
            part_a = s16(data, pos)
            part_b = s16(data, pos + 2)
            part_c = s16(data, pos + 4)
            if part_a < 0 or part_b < 0 or part_c < 0:
                return None
            length = part_a + part_b + part_c
            payload_start = pos + 6
            payload_end = payload_start + length
            if payload_end > len(data):
                return None
            payload = data[payload_start:payload_end]
            cells.append(MusicCell(cell_index, cell_off, length, payload, b'', (part_a, part_b, part_c)))
            pos = payload_end
        rows.append(MusicRow(row_index, row_off, pos, (table_kind, table_size, table_ref), table_bytes, cells))
    return MusicGrid(marker_off, pos, columns, row_count, rows)

def find_music_grids(data: bytes, start: int | None=None, end: int | None=None) -> list[MusicGrid]:
    if start is None:
        start = 0
    if end is None:
        end = len(data)
    grids: list[MusicGrid] = []
    off = data.find(b'\x00\x18', start, end)
    while off != -1:
        grid = parse_music_grid_at(data, off)
        if grid is not None and grid.end <= end:
            grids.append(grid)
        off = data.find(b'\x00\x18', off + 1, end)
    return grids

def find_music_grid(data: bytes, start: int | None=None, end: int | None=None) -> MusicGrid | None:
    grids = find_music_grids(data, start, end)
    if not grids:
        return None
    return max(grids, key=lambda grid: (grid.row_count * grid.columns, grid.end - grid.marker_off))

def mosaic_version(data: bytes) -> int | None:
    _magic, _tag, _length, version = mosa_header(data)
    return version

def post_grid_fixed_record_count(spec: PostGridSectionSpec, version: int | None) -> int:
    if spec.old_fixed_version_lt is not None and version is not None and (version < spec.old_fixed_version_lt) and (spec.old_fixed_record_count is not None):
        return spec.old_fixed_record_count
    return spec.fixed_record_count

def parse_post_grid_section_at(data: bytes, off: int, version: int | None=None) -> PostGridSection | None:
    if off + 4 > len(data):
        return None
    marker = u16(data, off)
    spec = POST_GRID_SECTION_SPECS.get(marker)
    if spec is None:
        return None
    if version is not None and version < spec.min_version:
        return None
    count = u16(data, off + 2)
    pos = off + 4
    header_after_count = data[pos:pos + spec.header_after_count_size]
    if len(header_after_count) != spec.header_after_count_size:
        return None
    pos += spec.header_after_count_size
    fixed_records: list[bytes] = []
    fixed_count = post_grid_fixed_record_count(spec, version)
    for _index in range(fixed_count):
        record = data[pos:pos + spec.fixed_record_size]
        if len(record) != spec.fixed_record_size:
            return None
        fixed_records.append(record)
        pos += spec.fixed_record_size
    entries: list[bytes] = []
    for _index in range(count):
        record = data[pos:pos + spec.entry_size]
        if len(record) != spec.entry_size:
            return None
        entries.append(record)
        pos += spec.entry_size
    return PostGridSection(marker, off, pos, count, header_after_count, fixed_records, entries, spec)

def parse_post_grid_sections(data: bytes, grid: MusicGrid | None=None) -> list[PostGridSection]:
    if grid is None:
        grid = find_music_grid(data)
    if grid is None:
        return []
    version = mosaic_version(data)
    pos = grid.end
    sections: list[PostGridSection] = []
    while pos + 2 <= len(data):
        marker = u16(data, pos)
        if marker not in POST_GRID_SECTION_SPECS:
            break
        section = parse_post_grid_section_at(data, pos, version)
        if section is None:
            break
        sections.append(section)
        pos = section.end
    return sections

def parse_tail_section_0033_at(data: bytes, off: int, version: int | None=None) -> MosaicTailSection33 | None:
    if off + 2 > len(data) or data[off:off + 2] != b'\x003':
        return None
    pos = off + 2
    records: list[bytes] = []
    while pos + 2 <= len(data):
        if u16(data, pos) == 65535:
            pos += 2
            break
        record = data[pos:pos + 6]
        if len(record) != 6:
            return None
        records.append(record)
        pos += 6
    else:
        return None
    nested = parse_post_grid_section_at(data, pos, version)
    if nested is not None and nested.marker == 31:
        pos = nested.end
    else:
        nested = None
    return MosaicTailSection33(off, pos, records, nested)

def tail_search_start_after_0033(data: bytes, grid: MusicGrid | None=None) -> int:
    if grid is None:
        grid = find_music_grid(data)
    if grid is None:
        return 0
    post_sections = parse_post_grid_sections(data, grid)
    pos = post_sections[-1].end if post_sections else grid.end
    if pos + 6 <= len(data) and data[pos:pos + 2] == b'\x002':
        pos += 6
    if pos + 2 <= len(data) and data[pos:pos + 2] == b'\x003':
        section_33 = parse_tail_section_0033_at(data, pos, mosaic_version(data))
        if section_33 is not None:
            pos = section_33.end
    return pos

def parse_document_info_at(data: bytes, off: int) -> MosaicDocumentInfo | None:
    if off + 2 > len(data) or data[off:off + 2] != b'\x001':
        return None
    pos = off + 2
    fields: list[str] = []
    while pos + 4 <= len(data):
        length = u32(data, pos)
        if length > 4096 or pos + 4 + length > len(data):
            return None
        text = macroman(data[pos + 4:pos + 4 + length])
        fields.append(text)
        pos += 4 + length
        if pos + 2 <= len(data) and data[pos:pos + 2] == b'\x00 ':
            return MosaicDocumentInfo(off, pos, fields)
    return None

def find_document_info(data: bytes, grid: MusicGrid | None=None) -> MosaicDocumentInfo | None:
    search_start = tail_search_start_after_0033(data, grid)
    off = data.find(b'\x001', search_start)
    while off != -1:
        info = parse_document_info_at(data, off)
        if info is not None:
            return info
        off = data.find(b'\x001', off + 1)
    return None

def useful_credit_field(value: str, *placeholders: str) -> str:
    stripped = value.strip()
    placeholder_set = {placeholder.lower() for placeholder in placeholders}
    if not stripped or stripped.lower() in placeholder_set:
        return ''
    return stripped

def mosaic_document_field(info: MosaicDocumentInfo | None, index: int, *placeholders: str) -> str:
    if info is None or index >= len(info.fields):
        return ''
    return useful_credit_field(info.fields[index], *placeholders)

def document_title(info: MosaicDocumentInfo | None, fallback: str) -> str:
    title = mosaic_document_field(info, 0, 'Title')
    if title:
        return title
    return fallback

def mosaic_document_subtitle(info: MosaicDocumentInfo | None) -> str:
    return mosaic_document_field(info, 4, '(Sub Title)', 'Sub Title', 'Subtitle', 'User Text 1')

def mosaic_document_running_title(info: MosaicDocumentInfo | None, fallback_title: str) -> str:
    return mosaic_document_field(info, 5, 'User Text 2') or fallback_title

def plausible_part_entry(data: bytes, off: int, limit: int) -> bool:
    if off < 0 or off + 22 > limit or data[off:off + 2] != b'\x00\x0f':
        return False
    name_len = s16(data, off + 2)
    if not 0 <= name_len <= 255:
        return False
    if data[off + 4] not in (0, 1) or data[off + 5] not in (0, 1):
        return False
    name_start = off + 22
    name_end = name_start + name_len
    if name_end > limit:
        return False
    blob_len = u32(data, off + 16)
    if blob_len > 512 or name_end + blob_len > limit:
        return False
    if blob_len:
        blob = data[name_end:name_end + blob_len]
        if any((byte < 32 or byte == 127 for byte in blob)):
            return False
    if name_len:
        name = data[name_start:name_end]
        if any((byte < 32 or byte == 127 for byte in name)):
            return False
    return True

def find_part_section(data: bytes, grid: MusicGrid | None=None) -> int | None:
    if grid is None:
        grid = find_music_grid(data)
    expected_count = grid.columns if grid is not None else None
    search_end = grid.marker_off if grid is not None else len(data)
    candidates: list[int] = []
    off = data.find(b'\x00\x0e', 0, search_end)
    while off != -1:
        if off + 8 <= len(data):
            count = u16(data, off + 2)
            if (expected_count is None or count == expected_count) and plausible_part_entry(data, off + 6, search_end):
                candidates.append(off)
        off = data.find(b'\x00\x0e', off + 1, search_end)
    if not candidates:
        return None
    return candidates[-1]

def find_next_part_entry(data: bytes, start: int, limit: int) -> int | None:
    off = data.find(b'\x00\x0f', start, limit)
    while off != -1:
        if plausible_part_entry(data, off, limit):
            return off
        off = data.find(b'\x00\x0f', off + 1, limit)
    return None

def find_part_record_tail_end(data: bytes, start: int, limit: int) -> int:
    sentinel = data.find(b'\xff\xff\x00\x00', start, limit)
    if sentinel == -1:
        return start
    length_pos = sentinel + 4
    if length_pos >= limit:
        return start
    length = data[length_pos]
    text_start = length_pos + 1
    text_end = text_start + length
    if text_end > limit:
        return start
    text = data[text_start:text_end]
    if not all((byte == 9 or byte == 10 or byte == 13 or (32 <= byte < 127) for byte in text)):
        return start
    return text_end

def parse_mosaic_parts(data: bytes, grid: MusicGrid | None=None) -> list[MosaicPartInfo]:
    if grid is None:
        grid = find_music_grid(data)
    section_off = find_part_section(data, grid)
    if section_off is None:
        return []
    count = u16(data, section_off + 2)
    limit = grid.marker_off if grid is not None else len(data)
    pos = section_off + 6
    parts: list[MosaicPartInfo] = []
    for index in range(count):
        if not plausible_part_entry(data, pos, limit):
            found = find_next_part_entry(data, pos, limit)
            if found is None:
                break
            pos = found
        entry_off = pos
        header = data[pos + 2:pos + 22]
        name_len = s16(header, 0)
        flags = (header[2], header[3], s16(header, 18))
        blob_len = u32(header, 14)
        name_start = pos + 22
        name_end = name_start + name_len
        name = macroman(data[name_start:name_end]) if name_len else ''
        extra_bytes = data[name_end:name_end + blob_len]
        name_extra = ''
        if extra_bytes and all((byte == 9 or byte == 10 or byte == 13 or (32 <= byte < 127) for byte in extra_bytes)):
            name_extra = macroman(extra_bytes).strip('\x00')
        pos = name_end + blob_len
        if index + 1 < count:
            next_pos = find_next_part_entry(data, pos, limit)
            entry_end = next_pos if next_pos is not None else pos
            pos = entry_end
        else:
            entry_end = find_part_record_tail_end(data, pos, limit)
            pos = entry_end
        parts.append(MosaicPartInfo(index, entry_off, entry_end, name, name_extra, header, name_len, flags, blob_len))
    return parts

def mosaic_part_display_name(part: MosaicPartInfo, fallback: str) -> str:
    name = part.name.strip()
    name_extra = part.name_extra.strip()
    if name and name_extra:
        return f'{name} {name_extra}'
    return name or name_extra or fallback

def mosaic_part_display_name_for_index(part_infos: list[MosaicPartInfo], part_index: int) -> str:
    if part_index < len(part_infos):
        return mosaic_part_display_name(part_infos[part_index], f'Part {part_index + 1}')
    return f'Part {part_index + 1}'

def mosaic_part_abbreviation_for_index(part_infos: list[MosaicPartInfo], voice_infos: dict[int, MosaicStaffVoiceInfo], part_index: int) -> str:
    name = mosaic_part_display_name_for_index(part_infos, part_index)
    voice_info = voice_infos.get(part_index)
    if voice_info is None:
        return name
    abbreviation = voice_info.abbreviation.strip()
    return abbreviation or name

def mosaic_part_staff_tail(data: bytes, part: MosaicPartInfo) -> bytes:
    tail_start = part.off + 22 + part.name_len + part.blob_len
    if tail_start > part.end:
        return b''
    return data[tail_start:part.end]
MOSAIC_STAFF_000D_HEADER_LEN = 6
MOSAIC_STAFF_000D_ENTRY_LEN = 54
MOSAIC_STAFF_000D_CLEF_CODE_OFFSET = 22
MOSAIC_STAFF_000D_CLEF_WORD12_OFFSET = 24
MOSAIC_STAFF_000D_CLEF_WORD13_OFFSET = 26
MOSAIC_STAFF_000D_KEY_OFFSET = 38
MOSAIC_STAFF_000D_TIME_SYMBOL_OFFSET = 42
MOSAIC_STAFF_000D_TIME_WORD22_OFFSET = 44
MOSAIC_STAFF_000D_TIME_BEATS_OFFSET = 46
MOSAIC_STAFF_000D_TIME_BEAT_TYPE_OFFSET = 48
MOSAIC_STAFF_000D_TIME_SYMBOLS = {2306: 'common', 2307: 'cut'}
MOSAIC_STAFF_000D_NUMERIC_TIME_SYMBOL = 2304
MOSAIC_STAFF_000D_CLEF_CODES = {0: MusicXmlClef('G', 2), 1: MusicXmlClef('F', 4), 2: MusicXmlClef('C', 3), 3: MusicXmlClef('C', 4), 4: MusicXmlClef('percussion', 2), 5: MusicXmlClef('none'), 6: MusicXmlClef('TAB', 5), 7: MusicXmlClef('G', 2, 1), 8: MusicXmlClef('G', 2, -1), 9: MusicXmlClef('F', 4, -1), 10: MusicXmlClef('F', 4, 1), 11: MusicXmlClef('G', 2, 2), 12: MusicXmlClef('G', 2, -2)}
MOSAIC_STAFF_000D_CLEF_ANCHORS = {0: (511, -512), 1: (256, 512), 2: (256, 0), 3: (256, 0), 4: (511, -512), 5: (511, -512), 6: (511, -512), 7: (511, -512), 8: (511, -512), 9: (256, 512), 10: (256, 512), 11: (511, -512), 12: (511, -512)}

def mosaic_staff_000d_clef_from_entry(entry: bytes) -> MusicXmlClef | None:
    if len(entry) != MOSAIC_STAFF_000D_ENTRY_LEN:
        return None
    code = s16(entry, MOSAIC_STAFF_000D_CLEF_CODE_OFFSET)
    anchor = (s16(entry, MOSAIC_STAFF_000D_CLEF_WORD12_OFFSET), s16(entry, MOSAIC_STAFF_000D_CLEF_WORD13_OFFSET))
    if anchor != MOSAIC_STAFF_000D_CLEF_ANCHORS.get(code):
        return None
    return MOSAIC_STAFF_000D_CLEF_CODES.get(code)

def mosaic_staff_000d_time_from_entry(entry: bytes) -> tuple[int, int, str] | None:
    if len(entry) != MOSAIC_STAFF_000D_ENTRY_LEN:
        return None
    symbol_word = u16(entry, MOSAIC_STAFF_000D_TIME_SYMBOL_OFFSET)
    if symbol_word not in MOSAIC_STAFF_000D_TIME_SYMBOLS and symbol_word != MOSAIC_STAFF_000D_NUMERIC_TIME_SYMBOL:
        return None
    if u16(entry, MOSAIC_STAFF_000D_TIME_WORD22_OFFSET) != 256:
        return None
    beats_word = u16(entry, MOSAIC_STAFF_000D_TIME_BEATS_OFFSET)
    beat_type_word = u16(entry, MOSAIC_STAFF_000D_TIME_BEAT_TYPE_OFFSET)
    if beats_word & 255 != 0 or beat_type_word & 255 != 1:
        return None
    beats = beats_word >> 8
    beat_type = beat_type_word >> 8
    if not 1 <= beats <= 32 or beat_type not in {1, 2, 4, 8, 16, 32, 64}:
        return None
    symbol = MOSAIC_STAFF_000D_TIME_SYMBOLS.get(symbol_word, '')
    if symbol == 'cut':
        return (2, 2, symbol)
    return (beats, beat_type, symbol)

def plausible_mosaic_staff_000d_entry(entry: bytes) -> bool:
    if len(entry) != MOSAIC_STAFF_000D_ENTRY_LEN:
        return False
    key_fifths = s16(entry, MOSAIC_STAFF_000D_KEY_OFFSET)
    if not -7 <= key_fifths <= 7:
        return False
    return mosaic_staff_000d_time_from_entry(entry) is not None

def mosaic_staff_leading_000d_end(tail: bytes) -> int:
    if len(tail) < MOSAIC_STAFF_000D_HEADER_LEN or tail[:2] != b'\x00\r':
        return 0
    declared_count = u16(tail, 4)
    if declared_count <= 0 or declared_count > 512:
        return 0
    candidate_counts = [declared_count]
    if declared_count > 1:
        candidate_counts.append(declared_count - 1)
    for entry_count in candidate_counts:
        end = MOSAIC_STAFF_000D_HEADER_LEN + entry_count * MOSAIC_STAFF_000D_ENTRY_LEN
        if end > len(tail):
            continue
        entries = [tail[MOSAIC_STAFF_000D_HEADER_LEN + index * MOSAIC_STAFF_000D_ENTRY_LEN:MOSAIC_STAFF_000D_HEADER_LEN + (index + 1) * MOSAIC_STAFF_000D_ENTRY_LEN] for index in range(entry_count)]
        if entries and all((plausible_mosaic_staff_000d_entry(entry) for entry in entries)):
            return end
    return 0

def mosaic_staff_tail_sentinel(tail: bytes) -> int:
    sentinel = tail.find(b'\xff\xff', mosaic_staff_leading_000d_end(tail))
    return sentinel if sentinel >= 0 else len(tail)

def mosaic_staff_abbreviation_from_tail(tail: bytes) -> str:
    sentinel = tail.find(b'\xff\xff', mosaic_staff_leading_000d_end(tail))
    if sentinel < 0:
        return ''
    pos = sentinel + 2
    if pos + 3 > len(tail) or tail[pos:pos + 2] != b'\x00\x00':
        return ''
    length = tail[pos + 2]
    text_start = pos + 3
    text_end = text_start + length
    if text_end > len(tail):
        return ''
    return macroman(tail[text_start:text_end]).strip('\x00')

def mosaic_staff_key_change_entries_from_tail(tail: bytes) -> tuple[tuple[int, int], ...]:
    end = mosaic_staff_leading_000d_end(tail)
    if not end:
        return ()
    declared_count = u16(tail, 4)
    entry_count = (end - MOSAIC_STAFF_000D_HEADER_LEN) // MOSAIC_STAFF_000D_ENTRY_LEN
    changes: list[tuple[int, int]] = []
    for index in range(entry_count):
        entry_off = MOSAIC_STAFF_000D_HEADER_LEN + index * MOSAIC_STAFF_000D_ENTRY_LEN
        entry = tail[entry_off:entry_off + MOSAIC_STAFF_000D_ENTRY_LEN]
        measure_index = s16(entry, 0)
        key_fifths = s16(entry, MOSAIC_STAFF_000D_KEY_OFFSET)
        if measure_index >= 0 and -7 <= key_fifths <= 7:
            changes.append((measure_index, key_fifths))
    if declared_count > 1 and entry_count == declared_count - 1 and changes and (changes[-1][0] == declared_count - 2) and (changes[-1][1] != 0):
        changes.append((declared_count - 1, 0))
    return tuple(changes)

def mosaic_staff_time_change_entries_from_tail(tail: bytes) -> tuple[tuple[int, int, int, str], ...]:
    end = mosaic_staff_leading_000d_end(tail)
    if not end:
        return ()
    entry_count = (end - MOSAIC_STAFF_000D_HEADER_LEN) // MOSAIC_STAFF_000D_ENTRY_LEN
    changes: list[tuple[int, int, int, str]] = []
    last_time: tuple[int, int, str] | None = None
    for index in range(entry_count):
        entry_off = MOSAIC_STAFF_000D_HEADER_LEN + index * MOSAIC_STAFF_000D_ENTRY_LEN
        entry = tail[entry_off:entry_off + MOSAIC_STAFF_000D_ENTRY_LEN]
        measure_index = s16(entry, 0)
        time_signature = mosaic_staff_000d_time_from_entry(entry)
        if measure_index < 0 or time_signature is None:
            continue
        if time_signature == last_time:
            continue
        beats, beat_type, symbol = time_signature
        changes.append((measure_index, beats, beat_type, symbol))
        last_time = time_signature
    return tuple(changes)

def mosaic_staff_key_fifths_from_tail(tail: bytes) -> int | None:
    changes = mosaic_staff_key_change_entries_from_tail(tail)
    if changes:
        return changes[0][1]
    return None

def mosaic_part_key_fifths(data: bytes, part: MosaicPartInfo | None) -> int | None:
    if part is None:
        return None
    return mosaic_staff_key_fifths_from_tail(mosaic_part_staff_tail(data, part))

def mosaic_part_key_changes(data: bytes, part: MosaicPartInfo | None) -> tuple[tuple[int, int], ...]:
    if part is None:
        return ()
    return mosaic_staff_key_change_entries_from_tail(mosaic_part_staff_tail(data, part))

def mosaic_part_time_changes(data: bytes, part: MosaicPartInfo | None) -> tuple[tuple[int, int, int, str], ...]:
    if part is None:
        return ()
    return mosaic_staff_time_change_entries_from_tail(mosaic_part_staff_tail(data, part))

def mosaic_part_staff_entry_clef(part: MosaicPartInfo, entry: bytes) -> MusicXmlClef | None:
    clef = mosaic_staff_000d_clef_from_entry(entry)
    if clef is None:
        return None
    name = mosaic_part_display_name(part, '').lower()
    if clef == MusicXmlClef('F', 4) and (any((word in name for word in ('drum', 'perc', 'percussion'))) or part.header[2] == 0):
        return MusicXmlClef('percussion', 2)
    return clef

def mosaic_part_clef_changes(data: bytes, part: MosaicPartInfo | None) -> tuple[tuple[int, MusicXmlClef], ...]:
    if part is None:
        return ()
    tail = mosaic_part_staff_tail(data, part)
    end = mosaic_staff_leading_000d_end(tail)
    if not end:
        return ()
    entry_count = (end - MOSAIC_STAFF_000D_HEADER_LEN) // MOSAIC_STAFF_000D_ENTRY_LEN
    changes: list[tuple[int, MusicXmlClef]] = []
    last_clef: MusicXmlClef | None = None
    for index in range(entry_count):
        entry_off = MOSAIC_STAFF_000D_HEADER_LEN + index * MOSAIC_STAFF_000D_ENTRY_LEN
        entry = tail[entry_off:entry_off + MOSAIC_STAFF_000D_ENTRY_LEN]
        measure_index = s16(entry, 0)
        clef = mosaic_part_staff_entry_clef(part, entry)
        if measure_index < 0 or clef is None:
            continue
        if clef == last_clef:
            continue
        changes.append((measure_index, clef))
        last_clef = clef
    return tuple(changes)

def mosaic_clef_at_measure(changes: tuple[tuple[int, MusicXmlClef], ...], measure_index: int) -> MusicXmlClef | None:
    current: MusicXmlClef | None = None
    for change_measure, clef in changes:
        if change_measure > measure_index:
            break
        current = clef
    return current

def mosaic_key_fifths_at_measure(changes: tuple[tuple[int, int], ...], measure_index: int) -> int | None:
    current: int | None = None
    for change_measure, key_fifths in changes:
        if change_measure > measure_index:
            break
        current = key_fifths
    return current

def mosaic_time_signature_at_measure(changes: tuple[tuple[int, int, int, str], ...], measure_index: int) -> tuple[int, int, str] | None:
    current: tuple[int, int, str] | None = None
    for change_measure, beats, beat_type, symbol in changes:
        if change_measure > measure_index:
            break
        current = (beats, beat_type, symbol)
    return current

def parse_mosaic_voice_lane_entries(body: bytes, pos: int, count: int, section: str, list_index: int, list_secondary: int) -> tuple[tuple[MosaicVoiceLaneRef, ...], int] | None:
    if count < 0 or count > 64:
        return None
    entries: list[MosaicVoiceLaneRef] = []
    for entry_index in range(count):
        if pos + 10 > len(body):
            return None
        rel_off = pos
        header = body[pos:pos + 10]
        payload_count = u16(header, 8)
        if payload_count <= 0 or payload_count > 32:
            return None
        payload_start = pos + 10
        payload_end = payload_start + payload_count * 2
        if payload_end > len(body):
            return None
        if header[4:8] != b'\x00\x01\x02\x03':
            return None
        voice_ids = tuple((u16(body, payload_start + index * 2) for index in range(payload_count)))
        if any((voice_id >= 256 for voice_id in voice_ids)):
            return None
        entries.append(MosaicVoiceLaneRef(section, rel_off, list_index, list_secondary, entry_index, header[0], voice_ids, header))
        pos = payload_end
    return (tuple(entries), pos)

def parse_mosaic_voice_lane_list(body: bytes, pos: int, section: str, list_index: int) -> tuple[MosaicVoiceLaneList, int] | None:
    if pos + 4 > len(body):
        return None
    rel_off = pos
    count = s16(body, pos)
    secondary = s16(body, pos + 2)
    if count < 0 or count > 64:
        return None
    parsed = parse_mosaic_voice_lane_entries(body, pos + 4, count, section, list_index, secondary)
    if parsed is None:
        return None
    entries, end = parsed
    return (MosaicVoiceLaneList(section, rel_off, list_index, count, secondary, entries), end)

def parse_mosaic_voice_lane_marker4_at(body: bytes, pos: int) -> tuple[MosaicVoiceLaneBlock, int] | None:
    if pos + 10 > len(body) or body[pos:pos + 2] != b'\x00\x04':
        return None
    count = u16(body, pos + 2)
    if count > 16:
        return None
    fields = (s16(body, pos + 4), s16(body, pos + 6), s16(body, pos + 8))
    lists: list[MosaicVoiceLaneList] = []
    end = pos + 10
    for list_index in range(count + 1):
        parsed = parse_mosaic_voice_lane_list(body, end, '0004', list_index)
        if parsed is None:
            return None
        lane_list, end = parsed
        lists.append(lane_list)
    if not any((lane_list.entries for lane_list in lists)):
        return None
    return (MosaicVoiceLaneBlock(4, '0004', pos, count, fields, tuple(lists)), end)

def parse_mosaic_voice_lane_marker10_at(body: bytes, pos: int) -> tuple[MosaicVoiceLaneBlock, int] | None:
    if pos + 4 > len(body) or body[pos:pos + 2] != b'\x00\x10':
        return None
    count = u16(body, pos + 2)
    if count > 64:
        return None
    parsed = parse_mosaic_voice_lane_entries(body, pos + 4, count, '0010', -1, 0)
    if parsed is None:
        return None
    entries, end = parsed
    if not entries:
        return None
    return (MosaicVoiceLaneBlock(16, '0010', pos, count, (), (), entries), end)

def mosaic_staff_voice_lane_blocks_from_tail(tail: bytes) -> tuple[MosaicVoiceLaneBlock, ...]:
    body = tail[:mosaic_staff_tail_sentinel(tail)]
    marker4: tuple[MosaicVoiceLaneBlock, int] | None = None
    pos = body.find(b'\x00\x04')
    while pos != -1:
        parsed = parse_mosaic_voice_lane_marker4_at(body, pos)
        if parsed is not None:
            marker4 = parsed
            break
        pos = body.find(b'\x00\x04', pos + 1)
    blocks: list[MosaicVoiceLaneBlock] = []
    marker10_start = 0
    if marker4 is not None:
        block, marker10_start = marker4
        blocks.append(block)
    pos = body.find(b'\x00\x10', marker10_start)
    while pos != -1:
        parsed = parse_mosaic_voice_lane_marker10_at(body, pos)
        if parsed is not None:
            block, _end = parsed
            blocks.append(block)
            break
        pos = body.find(b'\x00\x10', pos + 1)
    return tuple(blocks)

def mosaic_voice_ids_from_lane_blocks(blocks: tuple[MosaicVoiceLaneBlock, ...]) -> tuple[int, ...]:
    preferred_refs: tuple[MosaicVoiceLaneRef, ...] = ()
    for block in blocks:
        if block.marker == 16 and block.entries:
            preferred_refs = block.entries
            break
    if not preferred_refs:
        for block in blocks:
            if block.marker == 4 and block.lists and block.lists[0].entries:
                preferred_refs = block.lists[0].entries
                break
    voice_ids: list[int] = []
    for ref in preferred_refs:
        for voice_id in ref.voice_ids:
            if voice_id not in voice_ids:
                voice_ids.append(voice_id)
    return tuple(voice_ids)

def mosaic_preferred_lane_refs(info: MosaicStaffVoiceInfo) -> tuple[MosaicVoiceLaneRef, ...]:
    for block in info.lane_blocks:
        if block.marker == 16 and block.entries:
            return block.entries
    for block in info.lane_blocks:
        if block.marker == 4 and block.lists and block.lists[0].entries:
            return block.lists[0].entries
    return ()

def mosaic_staff_voice_ids_from_tail(tail: bytes) -> tuple[int, ...]:
    lane_voice_ids = mosaic_voice_ids_from_lane_blocks(mosaic_staff_voice_lane_blocks_from_tail(tail))
    if lane_voice_ids:
        return lane_voice_ids
    body = tail[:mosaic_staff_tail_sentinel(tail)]
    needle = b'\x02\x03\x00\x01'
    voice_ids: list[int] = []
    pos = body.find(needle)
    while pos != -1:
        if pos + len(needle) + 2 <= len(body):
            voice_id = u16(body, pos + len(needle))
            if voice_id < 256 and voice_id not in voice_ids:
                voice_ids.append(voice_id)
        pos = body.find(needle, pos + 1)
    return tuple(voice_ids)

def mosaic_staff_voice_info(data: bytes, part: MosaicPartInfo) -> MosaicStaffVoiceInfo:
    tail = mosaic_part_staff_tail(data, part)
    lane_blocks = mosaic_staff_voice_lane_blocks_from_tail(tail)
    return MosaicStaffVoiceInfo(part.index, mosaic_voice_ids_from_lane_blocks(lane_blocks) or mosaic_staff_voice_ids_from_tail(tail), mosaic_staff_abbreviation_from_tail(tail), lane_blocks)

def mosaic_staff_voice_infos(data: bytes, parts: list[MosaicPartInfo]) -> dict[int, MosaicStaffVoiceInfo]:
    return {part.index: mosaic_staff_voice_info(data, part) for part in parts}

def plausible_voice_record(data: bytes, off: int, limit: int) -> bool:
    if off < 0 or off + 20 > limit:
        return False
    name_len = u16(data, off)
    if not 0 < name_len <= 255 or off + 20 + name_len > limit:
        return False
    if data[off + 4:off + 8] != b'\x00\x01\x02\x03':
        return False
    name = data[off + 20:off + 20 + name_len]
    return all((byte == 9 or byte == 10 or byte == 13 or (32 <= byte < 127) for byte in name))

def find_plausible_voice_record(data: bytes, start: int, limit: int) -> int | None:
    marker = b'\x00\x01\x02\x03'
    off = data.find(marker, start, limit)
    while off != -1:
        record_start = off - 4
        if plausible_voice_record(data, record_start, limit):
            return record_start
        off = data.find(marker, off + 1, limit)
    return None

def find_voice_section(data: bytes, grid: MusicGrid | None=None) -> tuple[int, int] | None:
    if grid is None:
        grid = find_music_grid(data)
    part_section = find_part_section(data, grid)
    search_end = part_section if part_section is not None else grid.marker_off if grid is not None else len(data)
    best: tuple[int, int, int] | None = None
    off = data.find(b'\x00\x0e', 0, search_end)
    while off != -1:
        limit = search_end
        next_off = data.find(b'\x00\x0e', off + 2, search_end)
        if next_off != -1:
            limit = next_off
        record_start = find_plausible_voice_record(data, off + 4, limit)
        if record_start is not None:
            if plausible_voice_record(data, record_start, limit):
                count = 0
                pos = record_start
                while plausible_voice_record(data, pos, limit):
                    count += 1
                    pos += 20 + u16(data, pos)
                if count and (best is None or count > best[2]):
                    best = (off, limit, count)
        off = data.find(b'\x00\x0e', off + 1, search_end)
    if best is None:
        return None
    return (best[0], best[1])

def parse_mosaic_voices(data: bytes, grid: MusicGrid | None=None) -> list[MosaicVoiceInfo]:
    section = find_voice_section(data, grid)
    if section is None:
        return []
    section_off, section_end = section
    pos = find_plausible_voice_record(data, section_off + 4, section_end)
    if pos is None:
        return []
    voices: list[MosaicVoiceInfo] = []
    while plausible_voice_record(data, pos, section_end):
        name_len = u16(data, pos)
        header = data[pos + 2:pos + 20]
        name_start = pos + 20
        name_end = name_start + name_len
        voices.append(MosaicVoiceInfo(len(voices), pos, name_end, macroman(data[name_start:name_end]), header))
        pos = name_end
    return voices

def normalized_mosaic_part_name(name: str) -> str:
    return re.sub('\\s+', ' ', name.strip().lower())

def mosaic_staff_family_name(part: MosaicPartInfo) -> str:
    name = normalized_mosaic_part_name(mosaic_part_display_name(part, ''))
    changed = True
    while changed:
        changed = False
        for suffix in (' no chords', ' chords', ' merged', ' transposed', ' upper', ' lower'):
            if name.endswith(suffix):
                name = name[:-len(suffix)].strip()
                changed = True
    return name

def mosaic_voice_source_candidates(parts: list[MosaicPartInfo], voice_infos: dict[int, MosaicStaffVoiceInfo]) -> dict[int, tuple[int, ...]]:
    candidates: dict[int, list[int]] = {}
    for part in parts:
        info = voice_infos.get(part.index)
        if info is None or len(info.voice_ids) != 1:
            continue
        candidates.setdefault(info.voice_ids[0], []).append(part.index)
    return {voice_id: tuple(indexes) for voice_id, indexes in candidates.items()}

def mosaic_voice_display_name(voices: list[MosaicVoiceInfo], voice_id: int) -> str:
    if 0 <= voice_id < len(voices):
        return voices[voice_id].name
    return f'Voice {voice_id + 1}'

def mosaic_voice_stem_direction(voices: list[MosaicVoiceInfo], voice_id: int) -> str | None:
    name = normalized_mosaic_part_name(mosaic_voice_display_name(voices, voice_id))
    if 'stem' not in name:
        return None
    if 'up' in name:
        return 'up'
    if 'down' in name:
        return 'down'
    return None

def mosaic_voice_stem_direction_rank(voices: list[MosaicVoiceInfo], voice_id: int) -> int:
    stem_direction = mosaic_voice_stem_direction(voices, voice_id)
    if stem_direction == 'up':
        return 0
    if stem_direction == 'down':
        return 2
    return 1

def mosaic_musicxml_voice_id_order(voice_ids: tuple[int, ...], voices: list[MosaicVoiceInfo]) -> tuple[int, ...]:
    if not any((mosaic_voice_stem_direction_rank(voices, voice_id) != 1 for voice_id in voice_ids)):
        return voice_ids
    return tuple((voice_id for original_index, voice_id in sorted(enumerate(voice_ids), key=lambda indexed_voice_id: (mosaic_voice_stem_direction_rank(voices, indexed_voice_id[1]), indexed_voice_id[0]))))

def mosaic_mixed_voice_source_candidates(voice_infos: dict[int, MosaicStaffVoiceInfo], voice_id: int) -> tuple[int, ...]:
    return tuple((part_index for part_index, info in voice_infos.items() if len(info.voice_ids) > 1 and voice_id in info.voice_ids))

def mosaic_select_voice_source_part(parts: list[MosaicPartInfo], voice_infos: dict[int, MosaicStaffVoiceInfo], source_candidates: dict[int, tuple[int, ...]], target_index: int, voice_id: int) -> int | None:
    target_info = voice_infos.get(target_index)
    if target_info is not None and target_info.voice_ids == (voice_id,):
        return target_index
    candidates = source_candidates.get(voice_id, ())
    if not candidates:
        return None
    target_part = parts[target_index] if target_index < len(parts) else None
    target_family = mosaic_staff_family_name(target_part) if target_part is not None else ''
    target_transpose = mosaic_part_transpose_chromatic(target_part) if target_part is not None else 0

    def candidate_key(candidate_index: int) -> tuple[int, int, int]:
        candidate_part = parts[candidate_index]
        score = 0
        if target_family and mosaic_staff_family_name(candidate_part) == target_family:
            score += 100
        if mosaic_part_transpose_chromatic(candidate_part) == target_transpose:
            score += 20
        if candidate_index != target_index:
            score += 1
        distance = abs(candidate_index - target_index)
        return (score, -distance, -candidate_index)
    return max(candidates, key=candidate_key)

def mosaic_select_mixed_voice_source_part(parts: list[MosaicPartInfo], voice_infos: dict[int, MosaicStaffVoiceInfo], target_index: int, voice_id: int) -> int | None:
    candidates = mosaic_mixed_voice_source_candidates(voice_infos, voice_id)
    if not candidates:
        return None
    if target_index in candidates:
        return target_index
    target_part = parts[target_index] if target_index < len(parts) else None
    target_family = mosaic_staff_family_name(target_part) if target_part is not None else ''

    def candidate_key(candidate_index: int) -> tuple[int, int, int]:
        candidate_part = parts[candidate_index]
        score = 0
        if target_family and mosaic_staff_family_name(candidate_part) == target_family:
            score += 100
        distance = abs(candidate_index - target_index)
        return (score, -distance, -candidate_index)
    return max(candidates, key=candidate_key)

def mosaic_staff_voice_plans(parts: list[MosaicPartInfo], voice_infos: dict[int, MosaicStaffVoiceInfo], voices: list[MosaicVoiceInfo] | None=None) -> dict[int, MosaicStaffVoicePlan]:
    if voices is None:
        voices = []
    source_candidates = mosaic_voice_source_candidates(parts, voice_infos)
    plans: dict[int, MosaicStaffVoicePlan] = {}
    for part in parts:
        info = voice_infos.get(part.index)
        if info is None or not info.voice_ids:
            continue
        streams: list[MosaicVoiceStreamRef] = []
        for voice_id in mosaic_musicxml_voice_id_order(info.voice_ids, voices):
            source_part_index = mosaic_select_voice_source_part(parts, voice_infos, source_candidates, part.index, voice_id)
            if source_part_index is not None:
                streams.append(MosaicVoiceStreamRef(voice_id, source_part_index))
                continue
            source_part_index = mosaic_select_mixed_voice_source_part(parts, voice_infos, part.index, voice_id)
            if source_part_index is None:
                streams = []
                break
            streams = []
            break
        if streams:
            plans[part.index] = MosaicStaffVoicePlan(part.index, tuple(streams))
    return plans

def mosaic_staff_uses_separate_voice_streams(plan: MosaicStaffVoicePlan | None) -> bool:
    if plan is None or len(plan.streams) <= 1:
        return False
    return any((stream.source_part_index != plan.part_index or stream.source_kind != 'direct' for stream in plan.streams))

def mosaic_part_likely_rhythm_or_control(part: MosaicPartInfo | None) -> bool:
    if part is None:
        return False
    name = normalized_mosaic_part_name(mosaic_part_display_name(part, ''))
    if not name:
        return False
    if 'drum' in name or 'perc' in name or name == 'spacer':
        return True
    return 'chords' in name and 'no chords' not in name

def part_has_wrapped_low_pitch_candidates(rows: list[MusicRow], part_index: int) -> bool:
    has_pitch_anchor = False
    has_wrapped_low_pitch = False
    for row in rows:
        if part_index >= len(row.cells):
            continue
        for _off, token in split_raw_music_tokens(music_cell_event_payload(row.cells[part_index])):
            if not is_note_like_token(token):
                continue
            pitch_code = pitch_code_from_note_like_token(token)
            if 320 <= pitch_code <= 720:
                has_pitch_anchor = True
            elif token[-1] & 127 < 32:
                wrapped_pitch_code = pitch_code_from_note_like_token(token, wrap_low_pitch=True)
                if 320 <= wrapped_pitch_code <= 720:
                    has_wrapped_low_pitch = True
            if has_pitch_anchor and has_wrapped_low_pitch:
                return True
    return False

def mosaic_part_should_wrap_low_pitch_notes(part: MosaicPartInfo | None, rows: list[MusicRow], part_index: int) -> bool:
    if mosaic_part_likely_rhythm_or_control(part):
        return False
    return part_has_wrapped_low_pitch_candidates(rows, part_index)

def mosaic_part_transpose_chromatic(part: MosaicPartInfo) -> int:
    if len(part.header) <= 5:
        return 0
    return part.header[5] - 60
TRANSPOSITION_DIATONIC_BY_CHROMATIC = {-24: -14, -21: -12, -14: -8, -12: -7, -9: -5, -7: -4, -5: -3, -2: -1, 2: 1, 5: 3, 7: 4, 9: 5, 12: 7, 14: 8, 21: 12, 24: 14}

def mosaic_part_transpose_diatonic(part: MosaicPartInfo) -> int | None:
    chromatic = mosaic_part_transpose_chromatic(part)
    if chromatic == 0:
        return 0
    return TRANSPOSITION_DIATONIC_BY_CHROMATIC.get(chromatic)
MOSAIC_RIGHT_BARLINE_STYLES = {0: 'regular', 1: 'heavy', 2: 'light-light', 3: 'light-light', 4: 'heavy-light', 5: 'light-heavy', 7: 'light-heavy', 10: 'none', 11: 'regular'}
MOSAIC_LEFT_BARLINE_STYLES = {0: 'heavy-light', 9: 'heavy-light'}
MOSAIC_RIGHT_BARLINE_REPEAT_BY_CODE = {7: 'backward'}
MOSAIC_LEFT_BARLINE_REPEAT_BY_CODE = {0: 'forward', 9: 'forward'}

def mosaic_barlines_from_row_ref(ref: int) -> tuple[MusicXmlBarline, ...]:
    if ref == 0:
        return ()
    location_code = ref >> 8
    style_code = ref & 255
    if location_code in (0, 10):
        style = MOSAIC_RIGHT_BARLINE_STYLES.get(style_code)
        if style is None or style == 'regular':
            return ()
        return (MusicXmlBarline('right', style, MOSAIC_RIGHT_BARLINE_REPEAT_BY_CODE.get(style_code)),)
    if location_code == 6:
        style = MOSAIC_LEFT_BARLINE_STYLES.get(style_code)
        if style is None or style == 'regular':
            return ()
        return (MusicXmlBarline('left', style, MOSAIC_LEFT_BARLINE_REPEAT_BY_CODE.get(style_code)),)
    return ()

def append_unique_barline(barlines: list[MusicXmlBarline], barline: MusicXmlBarline) -> None:
    if barline not in barlines:
        barlines.append(barline)

def merge_musicxml_endings(existing: tuple[MusicXmlEnding, ...], added: tuple[MusicXmlEnding, ...]) -> tuple[MusicXmlEnding, ...]:
    merged = list(existing)
    for ending in added:
        if ending not in merged:
            merged.append(ending)
    return tuple(merged)

def merge_musicxml_barline(barlines: list[MusicXmlBarline], barline: MusicXmlBarline) -> None:
    if barline.endings and barline.style is None and (barline.repeat is None):
        for index, existing in enumerate(barlines):
            if existing.location == barline.location:
                barlines[index] = dataclasses.replace(existing, endings=merge_musicxml_endings(existing.endings, barline.endings))
                return
    append_unique_barline(barlines, barline)

def merge_musicxml_barline_sets(base_barlines: tuple[MusicXmlBarline, ...], added_barlines: tuple[MusicXmlBarline, ...]) -> tuple[MusicXmlBarline, ...]:
    merged = list(base_barlines)
    for barline in added_barlines:
        merge_musicxml_barline(merged, barline)
    return tuple(merged)

def mosaic_grid_row_barlines(rows: list[MusicRow]) -> dict[int, tuple[MusicXmlBarline, ...]]:
    by_row: dict[int, list[MusicXmlBarline]] = {}
    for row in rows:
        ref = row.header[2]
        for barline in mosaic_barlines_from_row_ref(ref):
            append_unique_barline(by_row.setdefault(row.index, []), barline)
    return {row_index: tuple(barlines) for row_index, barlines in by_row.items()}

def add_musicxml_clef(parent: ET.Element, clef: MusicXmlClef) -> ET.Element:
    clef_element = add_text(parent, 'clef')
    add_text(clef_element, 'sign', clef.sign)
    if clef.line is not None:
        add_text(clef_element, 'line', clef.line)
    if clef.octave_change is not None:
        add_text(clef_element, 'clef-octave-change', clef.octave_change)
    return clef_element

def add_musicxml_barline(parent: ET.Element, barline: MusicXmlBarline) -> ET.Element:
    barline_element = add_text(parent, 'barline', location=barline.location)
    if barline.style:
        add_text(barline_element, 'bar-style', barline.style)
    for ending in barline.endings:
        add_text(barline_element, 'ending', ending.text if ending.text else None, number=ending.number, type=ending.type)
    if barline.repeat:
        add_text(barline_element, 'repeat', direction=barline.repeat)
    return barline_element

def mosaic_lane_voice_groups(lane_refs: tuple[MosaicVoiceLaneRef, ...]) -> dict[int, tuple[int, ...]]:
    groups: dict[int, list[int]] = {}
    for ref in lane_refs:
        voice_ids = groups.setdefault(ref.lane, [])
        for voice_id in ref.voice_ids:
            if voice_id not in voice_ids:
                voice_ids.append(voice_id)
    return {lane: tuple(voice_ids) for lane, voice_ids in groups.items()}

def mosaic_voice_list_control_ref(token: ScannedMusicToken) -> tuple[int, int] | None:
    if not token.raw:
        return None
    raw = bytes.fromhex(token.raw)
    if len(raw) != 2 or raw[0] not in (64, 78) or (not raw[1] & 128):
        return None
    return (raw[0], raw[1] & 127)

def mosaic_music_group_voice_list_controls(group: MosaicMusicTokenGroup) -> tuple[tuple[ScannedMusicToken, int, int], ...]:
    controls: list[tuple[ScannedMusicToken, int, int]] = []
    for token in group.tokens[1:]:
        control = mosaic_voice_list_control_ref(token)
        if control is None:
            continue
        op, list_index = control
        controls.append((token, op, list_index))
    return tuple(controls)

def mosaic_music_same_time_runs(groups: tuple[MosaicMusicTokenGroup, ...]) -> tuple[tuple[MosaicMusicTokenGroup, ...], ...]:
    runs: list[tuple[MosaicMusicTokenGroup, ...]] = []
    current: list[MosaicMusicTokenGroup] = []
    for index, group in enumerate(groups):
        current.append(group)
        controls = mosaic_music_group_voice_list_controls(group)
        has_selector = any((op == 64 for _token, op, _list_index in controls))
        has_restore = any((op == 78 for _token, op, _list_index in controls))
        next_controls = mosaic_music_group_voice_list_controls(groups[index + 1]) if index + 1 < len(groups) else ()
        next_has_restore = any((op == 78 for _token, op, _list_index in next_controls))
        restore_only_continues = has_restore and (not has_selector) and (len(current) == 1) and next_has_restore
        if has_restore and (not restore_only_continues) or not next_has_restore:
            runs.append(tuple(current))
            current = []
    if current:
        runs.append(tuple(current))
    return tuple(runs)

def mosaic_music_group_duration_divisions(group: MosaicMusicTokenGroup) -> int | None:
    if not group.tokens:
        return None
    duration_name = duration_name_from_scanned_duration_token(group.tokens[0])
    if duration_name is None:
        return None
    return XML_DURATION_DIVISIONS.get(duration_name)

def mosaic_same_time_run_duration_divisions(run: tuple[MosaicMusicTokenGroup, ...]) -> int | None:
    durations = [duration for group in run for duration in [mosaic_music_group_duration_divisions(group)] if duration is not None]
    return max(durations) if durations else None

def first_marker_after(data: bytes, marker: int, start: int, end: int) -> int | None:
    off = data.find(marker.to_bytes(2, 'big'), start, end)
    return off if off >= 0 else None

def layout_boundaries(data: bytes) -> dict[str, int | None]:
    grid = find_music_grid(data)
    grid_off = grid.marker_off if grid is not None else len(data)
    pregrid_sections = parse_pregrid_sections(data)
    pregrid_end = pregrid_sections[-1].end if pregrid_sections else mosaic_body_start(data)
    font_off = pregrid_end if pregrid_end + 2 <= len(data) and u16(data, pregrid_end) == 36 else None
    text_off = first_marker_after(data, 33, pregrid_end, grid_off)
    style_off = first_marker_after(data, 3, text_off or pregrid_end, grid_off)
    part_off = find_part_section(data, grid)
    parts = parse_mosaic_parts(data, grid)
    parts_end = max((part.end for part in parts), default=None)
    return {'body_start': mosaic_body_start(data), 'pregrid_end': pregrid_end, 'font_0024': font_off, 'text_0021': text_off, 'style_0003': style_off, 'part_000e': part_off, 'parts_end': parts_end, 'grid_0018': grid_off if grid is not None else None}
COMMON_FONT_NAMES = {'Albuquerque', 'Arial', 'Arial Black', 'Assisi', 'B Garamond Bold', 'Cavanaugh', 'Chicago', 'Courier', 'Geneva', 'GillSans', 'Helvetica', 'Helvetica Compressed', 'Helvetica Compressed*', 'Geneva CE', 'Monaco?', 'New York', 'Palatino', 'Sonata', 'Sonatax', 'Times', 'Vivo'}

def layout_string_category(off: int, boundaries: dict[str, int | None], part_spans: list[tuple[int, int]], text: str='') -> str:
    for start, end in part_spans:
        if start <= off < end:
            return 'part/staff-name'
    body_start = boundaries['body_start'] or 0
    pregrid_end = boundaries['pregrid_end'] or body_start
    text_off = boundaries['text_0021']
    style_off = boundaries['style_0003']
    part_off = boundaries['part_000e']
    parts_end = boundaries['parts_end']
    grid_off = boundaries['grid_0018']
    if off < body_start:
        return 'file-header'
    if off < pregrid_end:
        return 'pregrid-device'
    if text_off is not None and off < text_off:
        return 'font-name' if text in COMMON_FONT_NAMES else 'score/layout-text'
    if style_off is not None and text_off is not None and (off < style_off):
        return 'text-style-font' if text in COMMON_FONT_NAMES else 'score/layout-text'
    if part_off is not None and off < part_off:
        return 'font/style-name' if text in COMMON_FONT_NAMES else 'voice/style-name'
    if parts_end is not None and off < parts_end:
        return 'part-record'
    if grid_off is not None and off < grid_off:
        return 'layout/page'
    return 'music-or-tail'

def score_layout_text_anchor(data: bytes, off: int, text: str) -> tuple[int, int] | None:
    raw_text = text.encode('mac_roman', errors='replace')
    if off < 28 or off + len(raw_text) > len(data):
        return None
    if u16(data, off - 6) != len(raw_text) or u16(data, off - 4) != 2 or u16(data, off - 2) != 1:
        return None
    words = [s16(data, off - 28 + index * 2) for index in range(14)]
    if words[11] != len(raw_text):
        return None
    top, left, bottom, right = (words[2], words[3], words[4], words[5])
    if top >= 0 and left >= 0 and (top or left):
        return (left, top)
    if bottom >= 0 and right >= 0 and (bottom or right):
        return (right, bottom)
    return None

def indexed_layout_text_records(data: bytes, grid: MusicGrid | None=None, min_len: int=1) -> list[MosaicIndexedTextRecord]:
    if grid is None:
        grid = find_music_grid(data)
    boundaries = layout_boundaries(data)
    start = boundaries['font_0024'] or boundaries['pregrid_end'] or mosaic_body_start(data)
    end = boundaries['part_000e'] or boundaries['grid_0018'] or len(data)
    results: list[MosaicIndexedTextRecord] = []
    seen_starts: set[int] = set()
    for off, length, text in printable_strings(data, start, end, min_len):
        record_start = off - 32
        if record_start < start or record_start in seen_starts:
            continue
        if record_start + 32 + length > len(data):
            continue
        record_length = u16(data, record_start)
        if record_length not in {length + 46, length + 62}:
            continue
        record_kind = u16(data, record_start + 28)
        record_style = u16(data, record_start + 30)
        if record_kind not in {2, 3} or data[record_start + 31] not in {1, 2}:
            continue
        stripped = text.strip()
        if not stripped:
            continue
        seen_starts.add(record_start)
        anchor = score_layout_text_anchor(data, off, text)
        x, y = anchor if anchor is not None else (None, None)
        results.append(MosaicIndexedTextRecord(len(results), off, stripped, x, y, record_start, record_length, u16(data, record_start + 2), record_kind, record_style))
    return results

def mosaic_text_looks_like_rehearsal_mark(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    if stripped in COMMON_FONT_NAMES or stripped in {'#', '#/Pg.#', '- # -'}:
        return False
    return re.search('[A-Za-z0-9]', stripped) is not None

def mosaic_endings(data: bytes, grid: MusicGrid | None=None) -> list[MosaicEnding]:
    if grid is None:
        grid = find_music_grid(data)
    if grid is None:
        return []
    text_records = indexed_layout_text_records(data, grid)
    results: list[MosaicEnding] = []
    seen: set[tuple[int, int, int, str]] = set()
    for section in parse_pregrid_sections(data):
        if section.marker != 40:
            continue
        for record_index, record in enumerate(section.records):
            if len(record) < 36:
                continue
            text_index = s16(record, 0)
            if text_index < 0 or text_index >= len(text_records):
                continue
            start_measure_index = s16(record, 4)
            end_measure_index = s16(record, 6)
            if start_measure_index < 0 or end_measure_index < 0:
                continue
            if start_measure_index >= grid.row_count or end_measure_index >= grid.row_count:
                continue
            if end_measure_index < start_measure_index:
                start_measure_index, end_measure_index = (end_measure_index, start_measure_index)
            text_record = text_records[text_index]
            label = text_record.text.strip()
            if not label:
                continue
            key = (start_measure_index, end_measure_index, text_index, label)
            if key in seen:
                continue
            seen.add(key)
            results.append(MosaicEnding(start_measure_index, end_measure_index, text_index, label, text_record.off, text_record.default_x, text_record.default_y))
    return sorted(results, key=lambda ending: (ending.start_measure_index, ending.end_measure_index, ending.text_index))

def mosaic_musicxml_ending(label: str, ordinal: int, ending_type: str) -> MusicXmlEnding:
    stripped = label.strip()
    if re.match('^\\d', stripped):
        return MusicXmlEnding(stripped, ending_type)
    return MusicXmlEnding(str(ordinal), ending_type, stripped)

def mosaic_ending_barlines_by_measure(data: bytes, grid: MusicGrid | None=None) -> dict[int, tuple[MusicXmlBarline, ...]]:
    endings_by_measure: dict[int, list[MusicXmlBarline]] = defaultdict(list)
    for ordinal, ending in enumerate(mosaic_endings(data, grid), start=1):
        start_barline = MusicXmlBarline('left', endings=(mosaic_musicxml_ending(ending.text, ordinal, 'start'),))
        stop_barline = MusicXmlBarline('right', endings=(mosaic_musicxml_ending(ending.text, ordinal, 'stop'),))
        merge_musicxml_barline(endings_by_measure.setdefault(ending.start_measure_index, []), start_barline)
        merge_musicxml_barline(endings_by_measure.setdefault(ending.end_measure_index, []), stop_barline)
    return {measure_index: tuple(barlines) for measure_index, barlines in endings_by_measure.items()}

def mosaic_rehearsal_marks(data: bytes, grid: MusicGrid | None=None) -> list[MosaicRehearsalMark]:
    if grid is None:
        grid = find_music_grid(data)
    if grid is None:
        return []
    text_records = indexed_layout_text_records(data, grid)
    results: list[MosaicRehearsalMark] = []
    seen: set[tuple[int, int, str]] = set()
    for section in parse_pregrid_sections(data):
        if section.marker != 39:
            continue
        for record in section.records:
            if len(record) < 14:
                continue
            measure_index = s16(record, 0)
            if measure_index < 0 or measure_index >= grid.row_count:
                continue
            text_ref = u16(record, 6)
            if not text_ref & 32768:
                continue
            text_index = text_ref & 32767
            if text_index >= len(text_records):
                continue
            text_record = text_records[text_index]
            if not mosaic_text_looks_like_rehearsal_mark(text_record.text):
                continue
            key = (measure_index, text_index, text_record.text)
            if key in seen:
                continue
            seen.add(key)
            results.append(MosaicRehearsalMark(measure_index, text_index, text_record.text, text_record.off, text_record.default_x, text_record.default_y))
    return sorted(results, key=lambda mark: (mark.measure_index, mark.text_index, mark.off))

def mosaic_rehearsal_marks_by_measure(data: bytes, grid: MusicGrid | None=None) -> dict[int, list[MosaicRehearsalMark]]:
    marks_by_measure: dict[int, list[MosaicRehearsalMark]] = defaultdict(list)
    for mark in mosaic_rehearsal_marks(data, grid):
        marks_by_measure[mark.measure_index].append(mark)
    return marks_by_measure
MOSAIC_STAFF_TEXT_UNITS_PER_QUARTER = 748

def mosaic_staff_text_position_divisions(record: bytes) -> int | None:
    if len(record) < 6:
        return None
    whole_units = s16(record, 2)
    fractional_units = s16(record, 4)
    if whole_units < MOSAIC_STAFF_TEXT_UNITS_PER_QUARTER:
        return None
    position_units = whole_units + fractional_units / 65536.0
    divisions = round(position_units * DIVISIONS_PER_QUARTER / MOSAIC_STAFF_TEXT_UNITS_PER_QUARTER)
    return divisions if divisions > 0 else None

def mosaic_staff_texts(data: bytes, grid: MusicGrid | None=None) -> list[MosaicStaffText]:
    if grid is None:
        grid = find_music_grid(data)
    if grid is None:
        return []
    text_records = indexed_layout_text_records(data, grid)
    part_count = len(parse_mosaic_parts(data, grid))
    results: list[MosaicStaffText] = []
    seen: set[tuple[int, int, int, str, int | None, int, int]] = set()
    for section in parse_pregrid_sections(data):
        if section.marker != 39:
            continue
        for record in section.records:
            if len(record) < 14:
                continue
            measure_index = s16(record, 0)
            if measure_index < 0 or measure_index >= grid.row_count:
                continue
            text_ref = u16(record, 6)
            if text_ref & 32768:
                continue
            text_index = text_ref & 32767
            if text_index >= len(text_records):
                continue
            part_index = s16(record, 12)
            if part_index < 0 or part_index >= part_count:
                continue
            text_record = text_records[text_index]
            if not text_record.text or text_record.text in COMMON_FONT_NAMES:
                continue
            position_divisions = mosaic_staff_text_position_divisions(record)
            key = (measure_index, part_index, text_index, text_record.text, position_divisions, s16(record, 8), s16(record, 10))
            if key in seen:
                continue
            seen.add(key)
            results.append(MosaicStaffText(measure_index, part_index, text_index, text_record.text, text_record.off, text_record.default_x, text_record.default_y, position_divisions))
    return sorted(results, key=lambda text: (text.part_index, text.measure_index, text.text_index, text.off))

def mosaic_staff_texts_by_part_measure(data: bytes, grid: MusicGrid | None=None) -> dict[tuple[int, int], list[MosaicStaffText]]:
    texts_by_part_measure: dict[tuple[int, int], list[MosaicStaffText]] = defaultdict(list)
    for staff_text in mosaic_staff_texts(data, grid):
        texts_by_part_measure[staff_text.part_index, staff_text.measure_index].append(staff_text)
    return texts_by_part_measure

def mosaic_text_attachment_referenced_indexes(data: bytes, grid: MusicGrid | None=None) -> set[int]:
    if grid is None:
        grid = find_music_grid(data)
    referenced: set[int] = set()
    for section in parse_pregrid_sections(data):
        if section.marker == 39:
            for record in section.records:
                if len(record) >= 8:
                    referenced.add(u16(record, 6) & 32767)
        elif section.marker == 40:
            for record in section.records:
                if len(record) >= 2:
                    text_index = s16(record, 0)
                    if text_index >= 0:
                        referenced.add(text_index)
    return referenced

def mosaic_measure_direction_texts(data: bytes, grid: MusicGrid | None=None) -> list[MosaicMeasureDirectionText]:
    if grid is None:
        grid = find_music_grid(data)
    if grid is None:
        return []
    text_records = indexed_layout_text_records(data, grid)
    results: list[MosaicMeasureDirectionText] = []
    seen: set[tuple[int, int, str, str]] = set()
    for section in parse_pregrid_sections(data):
        if section.marker != 39:
            continue
        for record in section.records:
            if len(record) < 14:
                continue
            measure_index = s16(record, 0)
            if measure_index < 0 or measure_index >= grid.row_count:
                continue
            text_ref = u16(record, 6)
            if text_ref & 32768:
                continue
            text_index = text_ref & 32767
            if text_index >= len(text_records):
                continue
            part_index = s16(record, 12)
            if part_index != -1:
                continue
            text_record = text_records[text_index]
            if not text_record.text or text_record.text in COMMON_FONT_NAMES:
                continue
            kind = 'metronome-mark' if text_record.record_kind == 3 else 'system-text'
            if kind == 'system-text' and len(record) >= 6 and (s16(record, 4) == -1):
                measure_index += 1
            if measure_index >= grid.row_count:
                continue
            position_divisions = mosaic_staff_text_position_divisions(record)
            key = (measure_index, text_index, text_record.text, kind)
            if key in seen:
                continue
            seen.add(key)
            results.append(MosaicMeasureDirectionText(measure_index, text_index, text_record.text, text_record.off, kind, text_record.default_x, text_record.default_y, position_divisions))
    return sorted(results, key=lambda text: (text.measure_index, text.text_index, text.off))

def mosaic_measure_direction_texts_by_measure(data: bytes, grid: MusicGrid | None=None) -> dict[int, list[MosaicMeasureDirectionText]]:
    texts_by_measure: dict[int, list[MosaicMeasureDirectionText]] = defaultdict(list)
    for text in mosaic_measure_direction_texts(data, grid):
        texts_by_measure[text.measure_index].append(text)
    return texts_by_measure

def mosaic_page_text_records(data: bytes, grid: MusicGrid | None=None) -> list[MosaicLayoutText]:
    if grid is None:
        grid = find_music_grid(data)
    if grid is None:
        return []
    referenced_indexes = mosaic_text_attachment_referenced_indexes(data, grid)
    existing_layout_offsets = {record.off for record in score_layout_text_records(data, grid)}
    results: list[MosaicLayoutText] = []
    seen_offsets: set[int] = set()
    for text_record in indexed_layout_text_records(data, grid):
        if text_record.index in referenced_indexes:
            continue
        if text_record.off in existing_layout_offsets or text_record.off in seen_offsets:
            continue
        if text_record.record_word_1 != 1 or text_record.record_kind != 2:
            continue
        if text_record.default_x is None or text_record.default_y is None:
            continue
        if not mosaic_text_looks_like_rehearsal_mark(text_record.text):
            continue
        seen_offsets.add(text_record.off)
        results.append(MosaicLayoutText(text_record.off, text_record.text, text_record.default_x, text_record.default_y))
    return results

def mosaic_note_attached_text_label(data: bytes, grid: MusicGrid | None=None) -> str:
    if grid is None:
        grid = find_music_grid(data)
    if grid is None:
        return ''
    referenced_indexes = mosaic_text_attachment_referenced_indexes(data, grid)
    page_offsets = {record.off for record in mosaic_page_text_records(data, grid)}
    layout_offsets = {record.off for record in score_layout_text_records(data, grid)}
    candidates = [record for record in indexed_layout_text_records(data, grid) if record.index not in referenced_indexes and record.off not in page_offsets and (record.off not in layout_offsets) and (record.record_word_1 not in {None, 1}) and mosaic_text_looks_like_rehearsal_mark(record.text)]
    if not candidates:
        return ''
    return candidates[-1].text

def signed_seven_bit(value: int) -> int:
    value &= 127
    return value - 128 if value >= 64 else value

def is_note_attached_text_control_pair(first: bytes, second: bytes | None) -> bool:
    if first not in {b'E\xb3', b'E\x93'}:
        return False
    return bool(second and second[0] in {84, 92})

def mosaic_note_attached_text_relative_x(token: bytes) -> int | None:
    if len(token) < 5 or token[:2] != b'\\z':
        return None
    value = signed_seven_bit(token[-2])
    return value * 12 if value < 0 else None

def mosaic_note_attached_texts(data: bytes, grid: MusicGrid | None=None) -> list[MosaicStaffText]:
    if grid is None:
        grid = find_music_grid(data)
    if grid is None:
        return []
    label = mosaic_note_attached_text_label(data, grid)
    if not label:
        return []
    part_infos = parse_mosaic_parts(data, grid)
    wrap_low_pitch_by_part = {part_index: mosaic_part_should_wrap_low_pitch_notes(part_infos[part_index] if part_index < len(part_infos) else None, grid.rows, part_index) for part_index in range(grid.columns)}
    unpitched_note_like_by_part = {part_index: mosaic_part_likely_rhythm_or_control(part_infos[part_index] if part_index < len(part_infos) else None) for part_index in range(grid.columns)}
    results: list[MosaicStaffText] = []
    seen: set[tuple[int, int, int, int, str]] = set()
    for row in grid.rows:
        for part_index, cell in enumerate(row.cells):
            payload = music_cell_event_payload(cell)
            if payload == b'M':
                continue
            _prefix, groups = music_token_groups(payload, wrap_low_pitch_by_part.get(part_index, False), unpitched_note_like_by_part.get(part_index, False))
            position = 0
            for run in mosaic_music_same_time_runs(groups):
                for group in run:
                    tokens = group.tokens
                    text_pairs: list[tuple[int, ScannedMusicToken, bytes]] = []
                    for index, scanned in enumerate(tokens[:-1]):
                        if not scanned.raw or not tokens[index + 1].raw:
                            continue
                        first = bytes.fromhex(scanned.raw)
                        second = bytes.fromhex(tokens[index + 1].raw)
                        if not is_note_attached_text_control_pair(first, second):
                            continue
                        text_pairs.append((index, scanned, second))
                    group_duration = mosaic_music_group_duration_divisions(group) or mosaic_same_time_run_duration_divisions(run)
                    for pair_index, (_token_index, scanned, second) in enumerate(text_pairs):
                        text_position = position
                        if group_duration is not None and len(text_pairs) > 1:
                            text_position += round(group_duration * pair_index / len(text_pairs))
                        relative_x = mosaic_note_attached_text_relative_x(second)
                        key = (row.index, part_index, text_position, group.start + scanned.off, scanned.raw)
                        if key in seen:
                            continue
                        seen.add(key)
                        results.append(MosaicStaffText(row.index, part_index, -1, label, cell.off + music_cell_structural_prefix_len(cell) + group.start + scanned.off, None, None, text_position, relative_x, None))
                duration = mosaic_same_time_run_duration_divisions(run)
                if duration is not None:
                    position += duration
    return sorted(results, key=lambda text: (text.part_index, text.measure_index, text.position_divisions or 0, text.off))

def mosaic_note_attached_texts_by_part_measure(data: bytes, grid: MusicGrid | None=None) -> dict[tuple[int, int], list[MosaicStaffText]]:
    texts_by_part_measure: dict[tuple[int, int], list[MosaicStaffText]] = defaultdict(list)
    for staff_text in mosaic_note_attached_texts(data, grid):
        texts_by_part_measure[staff_text.part_index, staff_text.measure_index].append(staff_text)
    return texts_by_part_measure

def score_layout_text_records(data: bytes, grid: MusicGrid | None=None, min_len: int=2) -> list[MosaicLayoutText]:
    if grid is None:
        grid = find_music_grid(data)
    parts = parse_mosaic_parts(data, grid)
    part_spans = [(part.off, part.end) for part in parts]
    boundaries = layout_boundaries(data)
    grid_off = boundaries['grid_0018'] or len(data)
    rehearsal_mark_offsets = {mark.off for mark in mosaic_rehearsal_marks(data, grid)}
    ending_label_offsets = {ending.off for ending in mosaic_endings(data, grid)}
    staff_text_offsets = {staff_text.off for staff_text in mosaic_staff_texts(data, grid)}
    results: list[MosaicLayoutText] = []
    for off, _length, text in printable_strings(data, 0, grid_off, min_len):
        if off in rehearsal_mark_offsets or off in ending_label_offsets or off in staff_text_offsets:
            continue
        if layout_string_category(off, boundaries, part_spans, text) != 'score/layout-text':
            continue
        stripped = text.strip()
        if not stripped or stripped in COMMON_FONT_NAMES:
            continue
        anchor = score_layout_text_anchor(data, off, text)
        x, y = anchor if anchor is not None else (None, None)
        results.append(MosaicLayoutText(off, stripped, x, y))
    return results

def mosa_header(data: bytes) -> tuple[str, int | None, int | None, int | None]:
    magic = data[:4].decode('mac_roman', errors='replace') if len(data) >= 4 else ''
    if not data.startswith(b'MOSA') or len(data) < 14:
        return (magic, None, None, None)
    tag = u16(data, 4)
    length = u32(data, 6)
    version = u32(data, 10) if tag == 25 and length == 4 else None
    return (magic, tag, length, version)

def event_nominal_duration_divisions(event: MusicEvent) -> int | None:
    if event.kind == 'forward' and event.duration_divisions is not None:
        return event.duration_divisions
    if event.kind not in {'note', 'rest', 'slash', 'unpitched', 'forward'}:
        return None
    base = XML_DURATION_DIVISIONS.get(event.duration_name)
    if base is None:
        return None
    total = base
    add = base
    for _dot in range(event.dots):
        add //= 2
        total += add
    return total

def event_musicxml_duration_divisions(event: MusicEvent) -> int | None:
    nominal = event_nominal_duration_divisions(event)
    if nominal is None:
        return None
    if event.time_modification is None:
        return nominal
    actual_notes, normal_notes = event.time_modification
    if actual_notes <= 0 or normal_notes <= 0:
        return nominal
    scaled = nominal * normal_notes
    if scaled % actual_notes == 0:
        return scaled // actual_notes
    return round(scaled / actual_notes)

def event_duration_divisions(event: MusicEvent) -> int | None:
    duration = event_musicxml_duration_divisions(event)
    if duration is None:
        return None
    return 0 if event.chord else duration

def time_signature_duration_divisions(time_signature: tuple[int, int]) -> int:
    beats, beat_type = time_signature
    return DIVISIONS_PER_QUARTER * 4 * beats // beat_type

def split_events_into_voices(events: list[MusicEvent], measure_divisions: int) -> list[tuple[int, list[MusicEvent]]]:
    if measure_divisions <= 0:
        return [(1, events)]
    duration_total = sum((divisions for event in events if (divisions := event_duration_divisions(event)) is not None))
    if duration_total <= measure_divisions or duration_total % measure_divisions != 0:
        return [(1, events)]
    voices: list[tuple[int, list[MusicEvent]]] = []
    current: list[MusicEvent] = []
    running = 0
    remaining = duration_total
    voice_number = 1
    for event in events:
        divisions = event_duration_divisions(event)
        current.append(event)
        if divisions is None:
            continue
        running += divisions
        remaining -= divisions
        if running > measure_divisions:
            return [(1, events)]
        if running == measure_divisions and remaining > 0:
            voices.append((voice_number, current))
            voice_number += 1
            current = []
            running = 0
    if running not in (0, measure_divisions):
        return [(1, events)]
    if current:
        voices.append((voice_number, current))
    if len(voices) <= 1:
        return [(1, events)]
    return voices

def cell_duration_divisions(payload: bytes, wrap_low_pitch_notes: bool=False, unpitched_note_like: bool=False, grouping_scale_entries: tuple[MosaicGroupingScaleEntry, ...]=()) -> tuple[int, bool]:
    events = music_events_from_cell(payload, wrap_low_pitch_notes=wrap_low_pitch_notes, unpitched_note_like=unpitched_note_like, grouping_scale_entries=grouping_scale_entries)
    total = 0
    has_duration = False
    for event in events:
        divisions = event_duration_divisions(event)
        if divisions is None:
            continue
        total += divisions
        has_duration = True
    known = True
    for token in scanned_music_tokens(payload, wrap_low_pitch_notes, unpitched_note_like):
        if is_decoded_music_token(token):
            continue
        known = False
        break
    return (total if has_duration else 0, known)
TIME_SIGNATURE_BY_DIVISIONS: dict[int, tuple[int, int]] = {DIVISIONS_PER_QUARTER: (1, 4), DIVISIONS_PER_QUARTER * 3 // 2: (3, 8), DIVISIONS_PER_QUARTER * 2: (2, 4), DIVISIONS_PER_QUARTER * 5 // 2: (5, 8), DIVISIONS_PER_QUARTER * 3: (3, 4), DIVISIONS_PER_QUARTER * 7 // 2: (7, 8), DIVISIONS_PER_QUARTER * 4: (4, 4), DIVISIONS_PER_QUARTER * 5: (5, 4), DIVISIONS_PER_QUARTER * 6: (6, 4), DIVISIONS_PER_QUARTER * 7: (7, 4), DIVISIONS_PER_QUARTER * 8: (8, 4)}

def infer_row_time_signature(row: MusicRow, wrap_low_pitch_by_part: dict[int, bool] | None=None, unpitched_note_like_by_part: dict[int, bool] | None=None) -> tuple[int, int] | None:
    counts: Counter[int] = Counter()
    for cell in row.cells:
        if cell.payload == b'M':
            continue
        total, _known = cell_duration_divisions(music_cell_event_payload(cell), (wrap_low_pitch_by_part or {}).get(cell.index, False), (unpitched_note_like_by_part or {}).get(cell.index, False), music_cell_grouping_scale_entries(cell))
        if total:
            counts[total] += 1
    if not counts:
        return None
    duration_cells = sum(counts.values())
    divisions, count = counts.most_common(1)[0]
    if duration_cells < 4:
        return None
    if count / duration_cells < 0.65:
        return None
    return TIME_SIGNATURE_BY_DIVISIONS.get(divisions)

def choose_document_time_signature(guess_counts: Counter[tuple[int, int]], default: tuple[int, int], min_stable_run: int) -> tuple[int, int]:
    if not guess_counts:
        return default
    dominant, dominant_count = guess_counts.most_common(1)[0]
    total_guessed = sum(guess_counts.values())
    if dominant_count < min_stable_run:
        return default
    if dominant == default:
        return default
    if dominant_count / total_guessed >= 0.8:
        return dominant
    default_count = guess_counts.get(default, 0)
    if dominant_count / total_guessed >= 1 / 3 and default_count * 2 < dominant_count:
        return dominant
    return default

def infer_grid_time_signatures(rows: list[MusicRow], default: tuple[int, int]=(4, 4), min_stable_run: int=8, wrap_low_pitch_by_part: dict[int, bool] | None=None, unpitched_note_like_by_part: dict[int, bool] | None=None) -> tuple[dict[int, tuple[int, int]], dict[int, tuple[int, int]]]:
    guesses = [infer_row_time_signature(row, wrap_low_pitch_by_part, unpitched_note_like_by_part) for row in rows]
    guess_counts = Counter((guess for guess in guesses if guess is not None))
    current = choose_document_time_signature(guess_counts, default, min_stable_run)
    changes: dict[int, tuple[int, int]] = {}
    row_time_at: dict[int, tuple[int, int]] = {}
    index = 0
    while index < len(guesses):
        guess = guesses[index]
        if guess is None or guess == current:
            index += 1
            continue
        end = index + 1
        while end < len(guesses) and guesses[end] == guess:
            end += 1
        if end - index >= min_stable_run:
            changes[index] = guess
            current = guess
        index = end
    current = choose_document_time_signature(guess_counts, default, min_stable_run)
    for row_index in range(len(rows)):
        if row_index in changes:
            current = changes[row_index]
        row_time_at[row_index] = current
    return (changes, row_time_at)

def add_text(parent: ET.Element, tag: str, text: object | None=None, **attrs: str) -> ET.Element:
    elem = ET.SubElement(parent, tag, attrs)
    if text is not None:
        elem.text = str(text)
    return elem
MUSICXML_DEFAULT_PAGE_WIDTH = 1190.55
MUSICXML_DEFAULT_PAGE_HEIGHT = 1683.78

def musicxml_credit_value(value: float | int) -> str:
    if isinstance(value, int):
        return str(value)
    return f'{value:.2f}'.rstrip('0').rstrip('.')

def add_musicxml_credit(score: ET.Element, credit_types: tuple[str, ...], text: str, *, page: int=1, attrs: dict[str, str] | None=None) -> None:
    if not text:
        return
    credit = add_text(score, 'credit', page=str(page))
    for credit_type in credit_types:
        add_text(credit, 'credit-type', credit_type)
    add_text(credit, 'credit-words', text, **attrs or {})

def add_musicxml_miscellaneous_field(identification: ET.Element, name: str, value: str) -> None:
    if not value:
        return
    miscellaneous = identification.find('miscellaneous')
    if miscellaneous is None:
        miscellaneous = add_text(identification, 'miscellaneous')
    add_text(miscellaneous, 'miscellaneous-field', value, name=name)

def estimated_musicxml_credit_page_count(part_count: int, measure_count: int) -> int:
    if measure_count <= 0:
        return 2
    if part_count >= 24:
        measures_per_page = 8
    elif part_count >= 12:
        measures_per_page = 12
    elif part_count >= 4:
        measures_per_page = 24
    else:
        measures_per_page = 48
    return max(2, min(64, math.ceil(measure_count / measures_per_page)))

def add_musicxml_document_credits(score: ET.Element, doc_info: MosaicDocumentInfo | None, explicit_title: str, subtitle: str, running_title: str, page_count: int) -> None:
    composer = mosaic_document_field(doc_info, 1, 'Composer')
    arranger = mosaic_document_field(doc_info, 2, 'Arranger')
    copyright_text = mosaic_document_field(doc_info, 3, 'Copyright')
    if explicit_title:
        add_musicxml_credit(score, ('title',), explicit_title, attrs={'default-x': musicxml_credit_value(MUSICXML_DEFAULT_PAGE_WIDTH / 2), 'default-y': musicxml_credit_value(MUSICXML_DEFAULT_PAGE_HEIGHT - 120), 'justify': 'center', 'halign': 'center', 'valign': 'top', 'font-size': '24', 'font-weight': 'bold'})
    if subtitle:
        add_musicxml_credit(score, ('subtitle',), subtitle, attrs={'default-x': musicxml_credit_value(MUSICXML_DEFAULT_PAGE_WIDTH / 2), 'default-y': musicxml_credit_value(MUSICXML_DEFAULT_PAGE_HEIGHT - 168), 'justify': 'center', 'halign': 'center', 'valign': 'top', 'font-size': '14'})
    if composer:
        add_musicxml_credit(score, ('composer',), composer, attrs={'default-x': musicxml_credit_value(MUSICXML_DEFAULT_PAGE_WIDTH - 70), 'default-y': musicxml_credit_value(MUSICXML_DEFAULT_PAGE_HEIGHT - 220), 'justify': 'right', 'halign': 'right', 'valign': 'top', 'font-size': '12'})
    if arranger:
        add_musicxml_credit(score, ('arranger',), arranger, attrs={'default-x': musicxml_credit_value(MUSICXML_DEFAULT_PAGE_WIDTH - 70), 'default-y': musicxml_credit_value(MUSICXML_DEFAULT_PAGE_HEIGHT - 252), 'justify': 'right', 'halign': 'right', 'valign': 'top', 'font-size': '12'})
    if copyright_text:
        add_musicxml_credit(score, ('rights',), copyright_text, attrs={'default-x': musicxml_credit_value(MUSICXML_DEFAULT_PAGE_WIDTH / 2), 'default-y': '55', 'justify': 'center', 'halign': 'center', 'valign': 'bottom', 'font-size': '9'})
    if running_title:
        for page in range(2, page_count + 1):
            add_musicxml_credit(score, ('title', 'mosaic-running-title'), running_title, page=page, attrs={'default-x': '70', 'default-y': '35', 'justify': 'left', 'halign': 'left', 'valign': 'bottom', 'font-size': '9'})

def prettify_xml(elem: ET.Element) -> bytes:
    ET.indent(elem, space='  ')
    return ET.tostring(elem, encoding='utf-8', xml_declaration=True)

def parse_chord_root(text: str) -> tuple[str, int, str] | None:
    if not text:
        return None
    step = text[0].upper()
    if step not in 'ABCDEFG':
        return None
    alter = 0
    pos = 1
    while pos < len(text) and text[pos] in ('b', '#'):
        alter += -1 if text[pos] == 'b' else 1
        pos += 1
    return (step, alter, text[pos:])

def musicxml_chord_kind(kind_text: str) -> tuple[str, str | None]:
    printed = kind_text.strip()
    normalized = printed.lower().replace('maj', 'ma')
    exact_kinds = {'': 'major', '2': 'suspended-second', '5': 'power', '6': 'major-sixth', '7': 'dominant', '9': 'dominant-ninth', '11': 'dominant-11th', '13': 'dominant-13th', 'sus': 'suspended-fourth', '7sus': 'suspended-fourth', 'dim': 'diminished', 'dim7': 'diminished-seventh', 'mi': 'minor', 'mi6': 'minor-sixth', 'mi7': 'minor-seventh', 'mi7-5': 'half-diminished', 'mi9': 'minor-ninth', 'mi11': 'minor-11th', 'mima7': 'major-minor', 'ma7': 'major-seventh', 'ma9': 'major-ninth'}
    if normalized in exact_kinds:
        return (exact_kinds[normalized], printed if printed else None)
    prefix_kinds = [('mi7-5', 'half-diminished'), ('mima7', 'major-minor'), ('mi11', 'minor-11th'), ('mi9', 'minor-ninth'), ('mi7', 'minor-seventh'), ('mi6', 'minor-sixth'), ('mi', 'minor'), ('ma9', 'major-ninth'), ('ma7', 'major-seventh'), ('13', 'dominant-13th'), ('11', 'dominant-11th'), ('9', 'dominant-ninth'), ('7sus', 'suspended-fourth'), ('7', 'dominant'), ('6', 'major-sixth'), ('sus', 'suspended-fourth'), ('dim7', 'diminished-seventh'), ('dim', 'diminished')]
    for prefix, xml_kind in prefix_kinds:
        if normalized.startswith(prefix):
            return (xml_kind, printed or None)
    return ('other', printed or None)

def musicxml_chord_degrees(kind_text: str) -> tuple[tuple[int, int, str], ...]:
    printed = kind_text.strip()
    normalized = printed.lower().replace('maj', 'ma')
    exact_kinds = {'', '2', '5', '6', '7', '9', '11', '13', 'sus', '7sus', 'dim', 'dim7', 'mi', 'mi6', 'mi7', 'mi7-5', 'mi9', 'mi11', 'mima7', 'ma7', 'ma9'}
    if normalized in exact_kinds:
        return ()
    prefixes = ('mi7-5', 'mima7', 'mi11', 'mi9', 'mi7', 'mi6', 'mi', 'ma9', 'ma7', '13', '11', '9', '7sus', '7', '6', 'sus', 'dim7', 'dim')
    suffix = normalized
    for prefix in prefixes:
        if normalized.startswith(prefix):
            suffix = normalized[len(prefix):]
            break
    degrees: list[tuple[int, int, str]] = []
    for match in re.finditer('([+-])(\\d+)', suffix):
        sign, degree_text = match.groups()
        alter = 1 if sign == '+' else -1
        degrees.append((int(degree_text), alter, 'alter'))
    return tuple(degrees)

def add_harmony(measure: ET.Element, symbol: str) -> None:
    main, slash, bass = symbol.partition('/')
    parsed = parse_chord_root(main)
    if parsed is None:
        direction = add_text(measure, 'direction', placement='above')
        direction_type = add_text(direction, 'direction-type')
        add_text(direction_type, 'words', symbol)
        return
    step, alter, kind_text = parsed
    harmony = add_text(measure, 'harmony')
    root = add_text(harmony, 'root')
    add_text(root, 'root-step', step)
    if alter:
        add_text(root, 'root-alter', alter)
    xml_kind, printed_kind = musicxml_chord_kind(kind_text)
    kind_attrs = {'text': printed_kind} if printed_kind else {}
    kind = ET.SubElement(harmony, 'kind', kind_attrs)
    kind.text = xml_kind
    for degree_value, degree_alter, degree_type in musicxml_chord_degrees(kind_text):
        degree = add_text(harmony, 'degree')
        add_text(degree, 'degree-value', degree_value)
        add_text(degree, 'degree-alter', degree_alter)
        add_text(degree, 'degree-type', degree_type)
    if slash:
        bass_parsed = parse_chord_root(bass)
        if bass_parsed is not None:
            bass_step, bass_alter, _bass_suffix = bass_parsed
            bass_elem = add_text(harmony, 'bass')
            add_text(bass_elem, 'bass-step', bass_step)
            if bass_alter:
                add_text(bass_elem, 'bass-alter', bass_alter)
TEXT_CONTROL_WORDS = {'da-capo': 'D.C.', 'dal-segno': 'D.S.', 'metronome-mark': 'mosaic-metronome-mark', 'system-text': 'mosaic-system-text', 'staff-text': 'mosaic-staff-text', 'rehearsal-mark': 'mosaic-rehearsal-mark', 'custom-text': 'mosaic-custom-text'}
DEFAULT_TEXT_CONTROL_ALIASES = {'coda', 'da-capo', 'dal-segno', 'metronome-mark', 'segno', 'staff-text', 'system-text', 'custom-text'}
DEFAULT_CONTROL_KINDS = {'dyna-control', 'hair-control', 'mrpt-control'}
CONTROL_KIND_WORD_PREFIX = {'acc-control': 'mosaic-accidental-control', 'cacc-control': 'mosaic-courtesy-accidental-control', 'orna-control': 'mosaic-ornament', 'hair-control': 'mosaic-hairpin', 'blin-control': 'mosaic-barline', 'mrpt-control': 'mosaic-measure-repeat', 'chrd-control': 'mosaic-chord-tool', 'grup-control': 'mosaic-grouping', 'tie-control': 'mosaic-tie-control', 'tie-span-control': 'mosaic-tie-span', 'tupl-control': 'mosaic-tuplet', 'sbra-control': 'mosaic-system-bracket', 'grouping-span-control': 'mosaic-grouping-span', 'grouping-scale-control': 'mosaic-grouping-scale', 'span-control': 'mosaic-span-control', 'slur-span-control': 'mosaic-slur-span', 'note-display-control': 'mosaic-note-display-control', 'tool-palette-control': 'mosaic-tool-palette-control'}

def musicxml_control_kind(text: str) -> str:
    return text.split(None, 1)[0] if text else ''

def musicxml_control_alias(text: str) -> str:
    match = re.search('/([^/=\\s]+)/(?:tool=)', text)
    return match.group(1) if match is not None else ''

def musicxml_control_symbol(text: str) -> str:
    match = re.search('symbol=([^/\\s]+)', text)
    return match.group(1) if match is not None else ''

def musicxml_control_field(text: str, field: str) -> str:
    match = re.search(f'\\b{re.escape(field)}=([^/\\s]+)', text)
    return match.group(1) if match is not None else ''
MUSICXML_DYNAMIC_TAGS = {'p', 'pp', 'ppp', 'mp', 'mf', 'f', 'ff', 'fff', 'sf', 'fz', 'sfz', 'fp'}
INLINE_DISPLAY_DYNAMIC_START_BYTES = frozenset({24, 25, 48, 56, 68, 84})

def is_inline_display_dynamic_collision(event: MusicEvent) -> bool:
    if event.kind != 'control' or musicxml_control_kind(event.text or '') != 'dyna-control':
        return False
    if not event.raw:
        return False
    if 'display-index' in (event.text or ''):
        return False
    raw = bytes.fromhex(event.raw)
    return bool(raw and raw[0] in INLINE_DISPLAY_DYNAMIC_START_BYTES)

def musicxml_control_dynamic_name(event: MusicEvent) -> str:
    text = event.text or ''
    alias = musicxml_control_alias(text)
    if alias in DYNAMIC_SYMBOL_ALIASES.values():
        return alias
    symbol = musicxml_control_symbol(text)
    if symbol.isdigit():
        return DYNAMIC_SYMBOL_ALIASES.get(int(symbol), '')
    return ''

def musicxml_control_raw_suffix(event: MusicEvent) -> str:
    return f' raw={event.raw}' if event.raw else ''

def musicxml_control_words(event: MusicEvent, include_raw: bool=True) -> str:
    text = event.text or ''
    kind = musicxml_control_kind(text)
    alias = musicxml_control_alias(text)
    raw_suffix = musicxml_control_raw_suffix(event) if include_raw else ''
    if kind == 'text-control':
        return TEXT_CONTROL_WORDS.get(alias, f"mosaic-text-control-{alias or 'unknown'}") + raw_suffix
    if kind == 'dyna-control':
        dynamic = musicxml_control_dynamic_name(event)
        symbol = musicxml_control_symbol(text)
        suffix = f'-{dynamic or symbol}' if dynamic or symbol else ''
        return f'mosaic-dynamic{suffix}{raw_suffix}'
    prefix = CONTROL_KIND_WORD_PREFIX.get(kind, 'mosaic-control')
    if alias and (not prefix.endswith(f'-{alias}')):
        prefix = f'{prefix}-{alias}'
    return f'{prefix}{raw_suffix}'

def should_export_music_control_by_default(event: MusicEvent) -> bool:
    if event.kind != 'control':
        return False
    if is_inline_display_dynamic_collision(event):
        return False
    kind = musicxml_control_kind(event.text or '')
    alias = musicxml_control_alias(event.text or '')
    return kind in DEFAULT_CONTROL_KINDS or (kind == 'text-control' and alias in DEFAULT_TEXT_CONTROL_ALIASES)

def musicxml_events_have_duration(events: list[MusicEvent]) -> bool:
    return any((event_duration_divisions(event) is not None for event in events))

def musicxml_events_duration_divisions(events: list[MusicEvent]) -> int:
    return sum((divisions for event in events if (divisions := event_duration_divisions(event)) is not None))

def musicxml_event_is_hidden_rest(event: MusicEvent) -> bool:
    if event.kind != 'rest' or not event.raw:
        return False
    try:
        raw = bytes.fromhex(event.raw)
    except ValueError:
        return False
    return rest_token_hidden(raw)
MUSICXML_DURATION_NAMES_BY_DIVISIONS = {divisions: duration_name for duration_name, divisions in sorted(XML_DURATION_DIVISIONS.items(), key=lambda item: item[1], reverse=True)}

def hidden_rest_raw_for_duration(duration_name: str) -> str:
    duration_codes = {name: code for code, name in NOTE_DURATION_CODES.items()}
    duration_code = duration_codes.get(duration_name, 3)
    return f'50 {duration_code << 3:02x} c0'

def hidden_rest_events_for_divisions(divisions: int) -> list[MusicEvent]:
    events: list[MusicEvent] = []
    remaining = divisions
    for duration_divisions, duration_name in MUSICXML_DURATION_NAMES_BY_DIVISIONS.items():
        while remaining >= duration_divisions:
            events.append(MusicEvent('rest', duration_name, raw=hidden_rest_raw_for_duration(duration_name)))
            remaining -= duration_divisions
    return events if remaining == 0 else []

def forward_events_for_divisions(divisions: int) -> list[MusicEvent]:
    if divisions <= 0:
        return []
    return [MusicEvent('forward', '', duration_divisions=divisions)]

def musicxml_event_is_layer_placement(event: MusicEvent) -> bool:
    return event.kind in {'harmony', 'control', 'articulation', 'ornament'}

def split_layered_hidden_rest_events(events: list[MusicEvent], measure_divisions: int) -> tuple[list[MusicEvent], list[MusicEvent]] | None:
    if measure_divisions <= 0 or not events:
        return None
    duration_total = musicxml_events_duration_divisions(events)
    if duration_total <= measure_divisions:
        return None
    visible_source_events = [event for event in events if not musicxml_event_is_hidden_rest(event)]
    if len(visible_source_events) == len(events):
        return None
    if musicxml_events_duration_divisions(visible_source_events) != measure_divisions:
        return None
    visible_events: list[MusicEvent] = []
    placement_points: list[tuple[int, int, MusicEvent]] = []
    visible_position = 0
    hidden_position = 0
    placement_order = 0
    for event in events:
        if musicxml_event_is_hidden_rest(event):
            duration = event_duration_divisions(event)
            if duration is not None:
                hidden_position += duration
            continue
        if musicxml_event_is_layer_placement(event):
            position = visible_position
            if event.kind == 'harmony' and visible_position >= measure_divisions and (0 < hidden_position < measure_divisions):
                position = hidden_position
            placement_points.append((position, placement_order, event))
            placement_order += 1
        else:
            visible_events.append(event)
        duration = event_duration_divisions(event)
        if duration is not None:
            visible_position += duration
    if visible_position != measure_divisions:
        return None
    placement_events: list[MusicEvent] = []
    placement_position = 0
    for position, _order, event in sorted(placement_points, key=lambda item: (item[0], item[1])):
        if position < placement_position:
            return None
        if position > placement_position:
            forwards = forward_events_for_divisions(position - placement_position)
            if not forwards:
                return None
            placement_events.extend(forwards)
            placement_position = position
        placement_events.append(event)
    if placement_events and placement_position < measure_divisions:
        forwards = forward_events_for_divisions(measure_divisions - placement_position)
        if not forwards:
            return None
        placement_events.extend(forwards)
    return (visible_events, placement_events)

def split_layered_hidden_rest_event_voices(event_voices: list[tuple[int, list[MusicEvent]]], measure_divisions: int) -> tuple[list[tuple[int, list[MusicEvent]]], bool]:
    next_voice_number = max((voice_number for voice_number, _events in event_voices), default=0) + 1
    visible_voice_events: list[tuple[int, list[MusicEvent]]] = []
    placement_voice_events: list[tuple[int, list[MusicEvent]]] = []
    changed = False
    for voice_number, voice_events in event_voices:
        split = split_layered_hidden_rest_events(voice_events, measure_divisions)
        if split is None:
            visible_voice_events.append((voice_number, voice_events))
            continue
        changed = True
        visible_events, placement_events = split
        if visible_events:
            visible_voice_events.append((voice_number, visible_events))
        if placement_events:
            placement_voice_events.append((next_voice_number, placement_events))
            next_voice_number += 1
    return (visible_voice_events + placement_voice_events, changed)

def pad_musicxml_voice_events(voice_events: list[MusicEvent], measure_divisions: int) -> list[MusicEvent]:
    duration = musicxml_events_duration_divisions(voice_events)
    if duration <= 0 or duration >= measure_divisions:
        return voice_events
    if any((event.kind == 'forward' for event in voice_events)):
        padding = forward_events_for_divisions(measure_divisions - duration)
    else:
        padding = hidden_rest_events_for_divisions(measure_divisions - duration)
    return voice_events + padding if padding else voice_events

def pad_musicxml_event_voices(event_voices: list[tuple[int, list[MusicEvent]]], measure_divisions: int) -> list[tuple[int, list[MusicEvent]]]:
    if measure_divisions <= 0:
        return event_voices
    return [(voice_number, pad_musicxml_voice_events(voice_events, measure_divisions)) for voice_number, voice_events in event_voices]

def musicxml_measure_repeat_style_for_events(events: list[MusicEvent]) -> tuple[str, int] | None:
    if musicxml_events_have_duration(events):
        return None
    for event in events:
        if event.kind != 'control' or musicxml_control_kind(event.text or '') != 'mrpt-control':
            continue
        repeat_type = musicxml_control_field(event.text or '', 'type') or 'start'
        if repeat_type not in {'start', 'stop'}:
            repeat_type = 'start'
        measures_text = musicxml_control_field(event.text or '', 'measures')
        try:
            measures = int(measures_text) if measures_text else 1
        except ValueError:
            measures = 1
        return (repeat_type, max(1, measures))
    return None

def add_musicxml_measure_repeat_style(measure: ET.Element, measures: int=1, repeat_type: str='start') -> None:
    attrs = add_text(measure, 'attributes')
    measure_style = add_text(attrs, 'measure-style')
    add_text(measure_style, 'measure-repeat', measures, type=repeat_type)

def add_musicxml_control_direction(measure: ET.Element, event: MusicEvent, include_raw: bool=True) -> None:
    text = event.text or (f'mosaic-control raw={event.raw}' if event.raw else 'mosaic-control')
    kind = musicxml_control_kind(text)
    alias = musicxml_control_alias(text)
    placement = 'below' if kind in {'dyna-control', 'hair-control'} else 'above'
    direction = add_text(measure, 'direction', placement=placement)
    direction_type = add_text(direction, 'direction-type')
    if kind == 'dyna-control':
        dynamics = add_text(direction_type, 'dynamics')
        dynamic = musicxml_control_dynamic_name(event)
        if dynamic in MUSICXML_DYNAMIC_TAGS:
            add_text(dynamics, dynamic)
            if include_raw:
                add_text(dynamics, 'other-dynamics', musicxml_control_words(event, include_raw))
        else:
            add_text(dynamics, 'other-dynamics', musicxml_control_words(event, include_raw))
        return
    if kind == 'hair-control' and alias in {'crescendo', 'diminuendo', 'stop'}:
        add_text(direction_type, 'wedge', type=alias)
        if include_raw:
            direction_type = add_text(direction, 'direction-type')
            add_text(direction_type, 'words', musicxml_control_words(event, include_raw))
        return
    if kind == 'text-control':
        if alias == 'segno':
            add_text(direction_type, 'segno')
            return
        if alias == 'coda':
            add_text(direction_type, 'coda')
            return
        if alias == 'rehearsal-mark':
            add_text(direction_type, 'rehearsal', TEXT_CONTROL_WORDS[alias])
            return
        add_text(direction_type, 'words', musicxml_control_words(event, include_raw))
        return
    add_text(direction_type, 'words', musicxml_control_words(event, include_raw))

def add_musicxml_rehearsal_mark_direction(measure: ET.Element, mark: MosaicRehearsalMark) -> None:
    direction = add_text(measure, 'direction', placement='above')
    direction_type = add_text(direction, 'direction-type')
    attrs: dict[str, str] = {'enclosure': 'rectangle'}
    if mark.default_x is not None:
        attrs['default-x'] = str(mark.default_x)
    if mark.default_y is not None:
        attrs['default-y'] = str(mark.default_y)
    add_text(direction_type, 'rehearsal', mark.text, **attrs)

def add_musicxml_staff_text_direction(measure: ET.Element, staff_text: MosaicStaffText) -> None:
    direction = add_text(measure, 'direction', placement='above')
    direction_type = add_text(direction, 'direction-type')
    attrs: dict[str, str] = {}
    if staff_text.default_x is not None:
        attrs['default-x'] = str(staff_text.default_x)
    if staff_text.default_y is not None:
        attrs['default-y'] = str(staff_text.default_y)
    if staff_text.relative_x is not None:
        attrs['relative-x'] = str(staff_text.relative_x)
    if staff_text.relative_y is not None:
        attrs['relative-y'] = str(staff_text.relative_y)
    add_text(direction_type, 'words', staff_text.text, **attrs)
    if staff_text.position_divisions is not None:
        add_text(direction, 'offset', staff_text.position_divisions)

def parse_mosaic_metronome_text(text: str) -> tuple[str, int] | None:
    match = re.match('^\\s*q\\s*=\\s*(\\d+)\\s*$', text, flags=re.IGNORECASE)
    if match is None:
        return None
    return ('quarter', int(match.group(1)))

def add_musicxml_measure_direction_text(measure: ET.Element, measure_text: MosaicMeasureDirectionText) -> None:
    direction_attrs = {'placement': 'above'}
    if measure_text.kind == 'system-text':
        direction_attrs['system'] = 'yes'
    direction = add_text(measure, 'direction', **direction_attrs)
    direction_type = add_text(direction, 'direction-type')
    if measure_text.kind == 'metronome-mark':
        metronome = parse_mosaic_metronome_text(measure_text.text)
        if metronome is not None:
            beat_unit, tempo = metronome
            metronome_element = add_text(direction_type, 'metronome')
            add_text(metronome_element, 'beat-unit', beat_unit)
            add_text(metronome_element, 'per-minute', tempo)
            add_text(direction, 'sound', tempo=str(tempo))
        else:
            add_text(direction_type, 'words', measure_text.text)
    else:
        attrs: dict[str, str] = {}
        if measure_text.default_x is not None:
            attrs['default-x'] = str(measure_text.default_x)
        if measure_text.default_y is not None:
            attrs['default-y'] = str(measure_text.default_y)
        add_text(direction_type, 'words', measure_text.text, **attrs)
    if measure_text.position_divisions is not None:
        add_text(direction, 'offset', measure_text.position_divisions)

def parse_omit_staff_names(exact_names: list[str] | None, comma_lists: list[str] | None) -> tuple[str, ...]:
    names: list[str] = []
    for name in exact_names or ():
        clean = name.strip()
        if clean:
            names.append(clean)
    for name_list in comma_lists or ():
        for name in name_list.split(','):
            clean = name.strip()
            if clean:
                names.append(clean)
    return tuple(names)

def filter_musicxml_export_part_indexes(part_infos: list[MosaicPartInfo], selected_part_indexes: list[int], omit_staff_names: tuple[str, ...]=()) -> tuple[list[int], list[str], list[str]]:
    if not omit_staff_names:
        return (selected_part_indexes, [], [])
    omitted_names = {normalized_mosaic_part_name(name) for name in omit_staff_names}
    exported_part_indexes: list[int] = []
    matched_omitted_staff_names: list[str] = []
    selected_names = {normalized_mosaic_part_name(mosaic_part_display_name_for_index(part_infos, part_index)) for part_index in selected_part_indexes}
    for part_index in selected_part_indexes:
        name = mosaic_part_display_name_for_index(part_infos, part_index)
        if normalized_mosaic_part_name(name) in omitted_names:
            matched_omitted_staff_names.append(name)
            continue
        exported_part_indexes.append(part_index)
    unmatched_omitted_staff_names = [name for name in omit_staff_names if normalized_mosaic_part_name(name) not in selected_names]
    return (exported_part_indexes, matched_omitted_staff_names, unmatched_omitted_staff_names)

def musicxml_export(path: Path, out: Path, max_parts: int | None=None, max_measures: int | None=None, part_offset: int=0, measure_offset: int=0, include_raw_directions: bool=False, infer_time: bool=True, key_fifths: int | None=None, default_time: tuple[int, int]=(4, 4), key_mode: str='', omit_staff_names: tuple[str, ...]=()) -> None:
    data = path.read_bytes()
    grid = find_music_grid(data)
    if grid is None:
        raise SystemExit(f'{path}: music grid not found')
    if not 0 <= part_offset < grid.columns:
        raise SystemExit(f'{path}: part offset {part_offset} is outside 0..{grid.columns - 1}')
    if not 0 <= measure_offset < grid.row_count:
        raise SystemExit(f'{path}: measure offset {measure_offset} is outside 0..{grid.row_count - 1}')
    available_parts = grid.columns - part_offset
    available_measures = grid.row_count - measure_offset
    source_part_count = min(available_parts, max_parts) if max_parts else available_parts
    measure_count = min(available_measures, max_measures) if max_measures else available_measures
    part_infos = parse_mosaic_parts(data, grid)
    voices = parse_mosaic_voices(data, grid)
    voice_infos = mosaic_staff_voice_infos(data, part_infos)
    voice_plans = mosaic_staff_voice_plans(part_infos, voice_infos, voices)
    doc_info = find_document_info(data, grid)
    selected_source_part_indexes = list(range(part_offset, part_offset + source_part_count))
    selected_part_indexes, omitted_staff_names, unmatched_omit_staff_names = filter_musicxml_export_part_indexes(part_infos, selected_source_part_indexes, omit_staff_names)
    if not selected_part_indexes:
        raise SystemExit(f'{path}: all selected staves were omitted from the MusicXML export')
    for unmatched_name in unmatched_omit_staff_names:
        print(f'warning: omit staff name {unmatched_name!r} did not match a selected Mosaic staff', file=sys.stderr)
    part_count = len(selected_part_indexes)
    wrap_low_pitch_by_part = {part_index: mosaic_part_should_wrap_low_pitch_notes(part_infos[part_index] if part_index < len(part_infos) else None, grid.rows, part_index) for part_index in range(grid.columns)}
    unpitched_note_like_by_part = {part_index: mosaic_part_likely_rhythm_or_control(part_infos[part_index] if part_index < len(part_infos) else None) for part_index in range(grid.columns)}
    row_time_signatures: dict[int, tuple[int, int]] = {}
    row_time_at: dict[int, tuple[int, int]] = {}
    if infer_time:
        row_time_signatures, row_time_at = infer_grid_time_signatures(grid.rows, default_time, wrap_low_pitch_by_part=wrap_low_pitch_by_part, unpitched_note_like_by_part=unpitched_note_like_by_part)
    row_barlines = mosaic_grid_row_barlines(grid.rows)
    ending_barlines = mosaic_ending_barlines_by_measure(data, grid)
    rehearsal_marks_by_measure = mosaic_rehearsal_marks_by_measure(data, grid)
    staff_texts_by_part_measure = mosaic_staff_texts_by_part_measure(data, grid)
    note_attached_texts_by_part_measure = mosaic_note_attached_texts_by_part_measure(data, grid)
    measure_direction_texts_by_measure = mosaic_measure_direction_texts_by_measure(data, grid)
    score = ET.Element('score-partwise', version='4.0')
    explicit_title = mosaic_document_field(doc_info, 0, 'Title')
    title = document_title(doc_info, path.name)
    subtitle = mosaic_document_subtitle(doc_info)
    running_title = mosaic_document_running_title(doc_info, explicit_title) if doc_info is not None else ''
    work = add_text(score, 'work')
    add_text(work, 'work-title', title)
    if subtitle:
        add_text(score, 'movement-title', subtitle)
    if doc_info is not None:
        identification = add_text(score, 'identification')
        composer = mosaic_document_field(doc_info, 1, 'Composer')
        if composer:
            add_text(identification, 'creator', composer, type='composer')
        arranger = mosaic_document_field(doc_info, 2, 'Arranger')
        if arranger:
            add_text(identification, 'creator', arranger, type='arranger')
        rights = mosaic_document_field(doc_info, 3, 'Copyright')
        if rights:
            add_text(identification, 'rights', rights)
        for index in range(4, min(len(doc_info.fields), len(MOSAIC_DOCUMENT_FIELD_LABELS))):
            value = mosaic_document_field(doc_info, index, '(Sub Title)', 'Sub Title', 'Subtitle', f'User Text {index - 3}')
            add_musicxml_miscellaneous_field(identification, f'mosaic-{MOSAIC_DOCUMENT_FIELD_LABELS[index]}', value)
    add_musicxml_document_credits(score, doc_info, explicit_title, subtitle, running_title, estimated_musicxml_credit_page_count(part_count, measure_count))
    for layout_text in score_layout_text_records(data, grid):
        credit = add_text(score, 'credit', page='1')
        add_text(credit, 'credit-type', 'mosaic-layout-text')
        attrs = {}
        if layout_text.default_x is not None and layout_text.default_y is not None:
            attrs = {'default-x': str(layout_text.default_x), 'default-y': str(layout_text.default_y)}
        add_text(credit, 'credit-words', layout_text.text, **attrs)
    for page_text in mosaic_page_text_records(data, grid):
        credit = add_text(score, 'credit', page='1')
        add_text(credit, 'credit-type', 'mosaic-page-text')
        attrs = {}
        if page_text.default_x is not None and page_text.default_y is not None:
            attrs = {'default-x': str(page_text.default_x), 'default-y': str(page_text.default_y)}
        add_text(credit, 'credit-words', page_text.text, **attrs)
    part_list = add_text(score, 'part-list')
    selected_part_clef_changes = {part_index: mosaic_part_clef_changes(data, part_infos[part_index] if part_index < len(part_infos) else None) for part_index in selected_part_indexes}
    selected_part_clef_change_maps = {part_index: dict(changes) for part_index, changes in selected_part_clef_changes.items()}
    selected_part_clefs = {part_index: mosaic_clef_at_measure(selected_part_clef_changes.get(part_index, ()), measure_offset) or infer_mosaic_part_clef(part_infos[part_index] if part_index < len(part_infos) else None, grid.rows, part_index, wrap_low_pitch_notes=wrap_low_pitch_by_part.get(part_index, False)) for part_index in selected_part_indexes}
    selected_part_key_changes = {part_index: () if key_fifths is not None else mosaic_part_key_changes(data, part_infos[part_index] if part_index < len(part_infos) else None) for part_index in selected_part_indexes}
    selected_part_key_change_maps = {part_index: dict(changes) for part_index, changes in selected_part_key_changes.items()}
    selected_part_key_fifths = {}
    for part_index in selected_part_indexes:
        if key_fifths is not None:
            selected_part_key_fifths[part_index] = key_fifths
            continue
        active_key = mosaic_key_fifths_at_measure(selected_part_key_changes.get(part_index, ()), measure_offset)
        selected_part_key_fifths[part_index] = active_key if active_key is not None else mosaic_part_key_fifths(data, part_infos[part_index] if part_index < len(part_infos) else None)
    selected_part_time_changes = {part_index: mosaic_part_time_changes(data, part_infos[part_index] if part_index < len(part_infos) else None) for part_index in selected_part_indexes}
    selected_part_time_change_maps = {part_index: {measure_index: (beats, beat_type, symbol) for measure_index, beats, beat_type, symbol in changes} for part_index, changes in selected_part_time_changes.items()}
    for xml_index, part_index in enumerate(selected_part_indexes, start=1):
        score_part = ET.SubElement(part_list, 'score-part', id=f'P{xml_index}')
        add_text(score_part, 'part-name', mosaic_part_display_name_for_index(part_infos, part_index))
        add_text(score_part, 'part-abbreviation', mosaic_part_abbreviation_for_index(part_infos, voice_infos, part_index))
    for xml_index, part_index in enumerate(selected_part_indexes, start=1):
        part = ET.SubElement(score, 'part', id=f'P{xml_index}')
        tied_alters: dict[tuple[int, str], int] = {}
        active_measure_repeat = False
        for local_measure_index, row in enumerate(grid.rows[measure_offset:measure_offset + measure_count], start=1):
            source_measure_number = measure_offset + local_measure_index
            measure = ET.SubElement(part, 'measure', number=str(source_measure_number))
            source_row_index = measure_offset + local_measure_index - 1
            measure_barlines = row_barlines.get(source_row_index, ())
            if xml_index == 1:
                measure_barlines = merge_musicxml_barline_sets(measure_barlines, ending_barlines.get(source_row_index, ()))
            left_barlines = [barline for barline in measure_barlines if barline.location == 'left']
            right_barlines = [barline for barline in measure_barlines if barline.location == 'right']
            serialized_time_signature = selected_part_time_change_maps.get(part_index, {}).get(source_row_index)
            inferred_time_signature = None if selected_part_time_changes.get(part_index) else row_time_signatures.get(source_row_index)
            time_signature = serialized_time_signature
            if time_signature is None and inferred_time_signature is not None:
                beats, beat_type = inferred_time_signature
                time_signature = (beats, beat_type, '')
            key_signature = None if key_fifths is not None else selected_part_key_change_maps.get(part_index, {}).get(source_row_index)
            clef_signature = selected_part_clef_change_maps.get(part_index, {}).get(source_row_index)
            if local_measure_index == 1 or time_signature is not None or key_signature is not None or (clef_signature is not None):
                attrs = add_text(measure, 'attributes')
                if local_measure_index == 1:
                    add_text(attrs, 'divisions', DIVISIONS_PER_QUARTER)
                if local_measure_index == 1 or key_signature is not None:
                    key = add_text(attrs, 'key')
                    part_key_fifths = key_signature if key_signature is not None else selected_part_key_fifths.get(part_index)
                    add_text(key, 'fifths', part_key_fifths if part_key_fifths is not None else 0)
                    if key_mode:
                        add_text(key, 'mode', key_mode)
                if local_measure_index == 1 or time_signature is not None:
                    active_time_signature = time_signature
                    if active_time_signature is None:
                        active_time_signature = mosaic_time_signature_at_measure(selected_part_time_changes.get(part_index, ()), source_row_index)
                    if active_time_signature is None:
                        beats, beat_type = row_time_at.get(source_row_index, default_time)
                        symbol = ''
                    else:
                        beats, beat_type, symbol = active_time_signature
                    time_attrs = {'symbol': symbol} if symbol else {}
                    time = add_text(attrs, 'time', **time_attrs)
                    add_text(time, 'beats', beats)
                    add_text(time, 'beat-type', beat_type)
                if local_measure_index == 1 or clef_signature is not None:
                    active_clef = clef_signature or selected_part_clefs.get(part_index) or MusicXmlClef('G', 2)
                    add_musicxml_clef(attrs, active_clef)
                if local_measure_index == 1 and part_index < len(part_infos):
                    chromatic_transpose = mosaic_part_transpose_chromatic(part_infos[part_index])
                    if chromatic_transpose:
                        transpose = add_text(attrs, 'transpose')
                        diatonic_transpose = mosaic_part_transpose_diatonic(part_infos[part_index])
                        if diatonic_transpose is not None:
                            add_text(transpose, 'diatonic', diatonic_transpose)
                        add_text(transpose, 'chromatic', chromatic_transpose)
            for barline in left_barlines:
                add_musicxml_barline(measure, barline)
            if xml_index == 1:
                for rehearsal_mark in rehearsal_marks_by_measure.get(source_row_index, ()):
                    add_musicxml_rehearsal_mark_direction(measure, rehearsal_mark)
                for measure_text in measure_direction_texts_by_measure.get(source_row_index, ()):
                    add_musicxml_measure_direction_text(measure, measure_text)
            for staff_text in staff_texts_by_part_measure.get((part_index, source_row_index), ()):
                add_musicxml_staff_text_direction(measure, staff_text)
            for staff_text in note_attached_texts_by_part_measure.get((part_index, source_row_index), ()):
                add_musicxml_staff_text_direction(measure, staff_text)
            cell = row.cells[part_index]
            event_clef = mosaic_clef_at_measure(selected_part_clef_changes.get(part_index, ()), source_row_index) or selected_part_clefs.get(part_index) or MusicXmlClef('G', 2)
            source_voice_events: list[tuple[int, list[MusicEvent]]] | None = None
            voice_plan = voice_plans.get(part_index)
            voice_info = voice_infos.get(part_index)
            voice_stem_direction_by_number: dict[int, str] = {}
            if voice_plan is not None:
                for voice_number, stream in enumerate(voice_plan.streams, start=1):
                    stem_direction = mosaic_voice_stem_direction(voices, stream.voice_id)
                    if stem_direction is not None:
                        voice_stem_direction_by_number[voice_number] = stem_direction
            uses_separate_voice_streams = mosaic_staff_uses_separate_voice_streams(voice_plan)
            is_unsplit_mixed_voice_storage = voice_info is not None and len(voice_info.voice_ids) > 1 and (not uses_separate_voice_streams)
            grouping_scale_entries = music_cell_grouping_scale_entries(cell)
            if uses_separate_voice_streams:
                assert voice_plan is not None
                collected_voice_events: list[tuple[int, list[MusicEvent]]] = []
                for voice_number, stream in enumerate(voice_plan.streams, start=1):
                    if stream.source_part_index >= len(row.cells):
                        continue
                    source_cell = row.cells[stream.source_part_index]
                    source_grouping_scale_entries = music_cell_grouping_scale_entries(source_cell)
                    voice_events = music_events_from_cell_with_same_time_chords(music_cell_event_payload(source_cell), include_raw_directions, wrap_low_pitch_by_part.get(stream.source_part_index, False), unpitched_note_like_by_part.get(stream.source_part_index, False), mosaic_clef_at_measure(selected_part_clef_changes.get(stream.source_part_index, ()), source_row_index) or selected_part_clefs.get(stream.source_part_index) or event_clef, source_grouping_scale_entries)
                    if voice_events:
                        collected_voice_events.append((voice_number, voice_events))
                if collected_voice_events:
                    source_voice_events = collected_voice_events
                    events = [event for _voice_number, voice_events in source_voice_events for event in voice_events]
                else:
                    events = music_events_from_cell_with_same_time_chords(music_cell_event_payload(cell), include_raw_directions, wrap_low_pitch_by_part.get(part_index, False), unpitched_note_like_by_part.get(part_index, False), event_clef, grouping_scale_entries)
            elif is_unsplit_mixed_voice_storage:
                assert voice_info is not None
                mixed_lane_events = music_events_by_mosaic_lane(music_cell_event_payload(cell), mosaic_preferred_lane_refs(voice_info), include_raw_directions, wrap_low_pitch_by_part.get(part_index, False), unpitched_note_like_by_part.get(part_index, False), event_clef, grouping_scale_entries)
                if mixed_lane_events is not None:
                    source_voice_events = mixed_lane_events
                    events = [event for _voice_number, voice_events in source_voice_events for event in voice_events]
                else:
                    same_lane_events = music_events_by_same_lane_voice_refs(music_cell_event_payload(cell), mosaic_preferred_lane_refs(voice_info), mosaic_voice_marker4_block(voice_info), include_raw_directions, wrap_low_pitch_by_part.get(part_index, False), unpitched_note_like_by_part.get(part_index, False), event_clef, grouping_scale_entries)
                    if same_lane_events is not None:
                        source_voice_events = same_lane_events
                        events = [event for _voice_number, voice_events in source_voice_events for event in voice_events]
                    else:
                        lane_refs = mosaic_preferred_lane_refs(voice_info)
                        mixed_lane_group_events = music_events_by_mosaic_lane_voice_groups(music_cell_event_payload(cell), lane_refs, mosaic_voice_marker4_block(voice_info), include_raw_directions, wrap_low_pitch_by_part.get(part_index, False), unpitched_note_like_by_part.get(part_index, False), event_clef, grouping_scale_entries)
                        if mixed_lane_group_events is not None:
                            source_voice_events = mixed_lane_group_events
                            events = [event for _voice_number, voice_events in source_voice_events for event in voice_events]
                        else:
                            events = music_events_from_cell_with_same_time_chords(music_cell_event_payload(cell), include_raw_directions, wrap_low_pitch_by_part.get(part_index, False), unpitched_note_like_by_part.get(part_index, False), event_clef, grouping_scale_entries)
            else:
                events = music_events_from_cell_with_same_time_chords(music_cell_event_payload(cell), include_raw_directions, wrap_low_pitch_by_part.get(part_index, False), unpitched_note_like_by_part.get(part_index, False), event_clef, grouping_scale_entries)
            measure_repeat_style = musicxml_measure_repeat_style_for_events(events)
            if active_measure_repeat and measure_repeat_style is None:
                add_musicxml_measure_repeat_style(measure, 1, 'stop')
                active_measure_repeat = False
            if not events and music_cell_event_payload(cell) == b'M':
                for barline in right_barlines:
                    add_musicxml_barline(measure, barline)
                continue
            if not events and include_raw_directions:
                direction = add_text(measure, 'direction')
                direction_type = add_text(direction, 'direction-type')
                add_text(direction_type, 'words', f"UNDECODED {cell.payload.hex(' ')}")
                for barline in right_barlines:
                    add_musicxml_barline(measure, barline)
                continue
            active_measure_time = mosaic_time_signature_at_measure(selected_part_time_changes.get(part_index, ()), source_row_index)
            if active_measure_time is None:
                measure_time = row_time_at.get(source_row_index, default_time)
            else:
                beats, beat_type, _symbol = active_measure_time
                measure_time = (beats, beat_type)
            measure_divisions = time_signature_duration_divisions(measure_time)
            layered_event_voices: list[tuple[int, list[MusicEvent]]] | None = None
            if source_voice_events is not None:
                source_voice_events, _layered_split = split_layered_hidden_rest_event_voices(source_voice_events, measure_divisions)
                events = [event for _voice_number, voice_events in source_voice_events for event in voice_events]
            else:
                layered_event_voices, layered_split = split_layered_hidden_rest_event_voices([(1, events)], measure_divisions)
                if layered_split:
                    events = [event for _voice_number, voice_events in layered_event_voices for event in voice_events]
                else:
                    layered_event_voices = None
            semantic_measure_repeat = measure_repeat_style is not None
            if measure_repeat_style is not None:
                repeat_type, repeat_measures = measure_repeat_style
                add_musicxml_measure_repeat_style(measure, repeat_measures, repeat_type)
                active_measure_repeat = repeat_type == 'start'
            if source_voice_events is not None:
                event_voices = source_voice_events
            elif layered_event_voices is not None:
                event_voices = layered_event_voices
            elif is_unsplit_mixed_voice_storage:
                event_voices = [(1, events)]
            else:
                event_voices = split_events_into_voices(events, measure_divisions)
            event_voices = pad_musicxml_event_voices(event_voices, measure_divisions)
            active_part_key_fifths = key_fifths if key_fifths is not None else mosaic_key_fifths_at_measure(selected_part_key_changes.get(part_index, ()), source_row_index)
            if active_part_key_fifths is None:
                active_part_key_fifths = selected_part_key_fifths.get(part_index)
            measure_accidental_alters = musicxml_accidental_alters_for_measure(event_voices, active_part_key_fifths if active_part_key_fifths is not None else 0, tied_alters)
            previous_voice_duration = measure_divisions
            for voice_index, (voice_number, voice_events) in enumerate(event_voices):
                if voice_index:
                    backup = add_text(measure, 'backup')
                    add_text(backup, 'duration', previous_voice_duration)
                beams = inferred_beams_for_events(voice_events, measure_time)
                for event_index, event in enumerate(voice_events):
                    if event.kind == 'harmony':
                        add_harmony(measure, event.text)
                        continue
                    if event.kind == 'control':
                        if semantic_measure_repeat and musicxml_control_kind(event.text or '') == 'mrpt-control':
                            if include_raw_directions:
                                add_musicxml_control_direction(measure, event, include_raw_directions)
                            continue
                        if include_raw_directions or should_export_music_control_by_default(event):
                            add_musicxml_control_direction(measure, event, include_raw_directions)
                        continue
                    if event.kind == 'articulation':
                        if include_raw_directions:
                            direction = add_text(measure, 'direction', placement='above')
                            direction_type = add_text(direction, 'direction-type')
                            add_text(direction_type, 'words', event.text)
                        continue
                    if event.kind == 'ornament':
                        if include_raw_directions:
                            direction = add_text(measure, 'direction', placement='above')
                            direction_type = add_text(direction, 'direction-type')
                            add_text(direction_type, 'words', event.text)
                        continue
                    if event.kind == 'forward':
                        forward = add_text(measure, 'forward')
                        add_text(forward, 'duration', event_musicxml_duration_divisions(event) or DIVISIONS_PER_QUARTER)
                        add_text(forward, 'voice', voice_number)
                        continue
                    if event.kind == 'rest':
                        note_attrs = {'print-object': 'no'} if event.raw and rest_token_hidden(bytes.fromhex(event.raw)) else {}
                        note = add_text(measure, 'note', **note_attrs)
                        add_text(note, 'rest')
                    elif event.kind == 'unpitched' or (event.kind == 'slash' and (not event.pitch)):
                        note = add_text(measure, 'note')
                        unpitched = add_text(note, 'unpitched')
                        display_step, display_octave = musicxml_unpitched_display_pitch(event, event_clef)
                        add_text(unpitched, 'display-step', display_step)
                        add_text(unpitched, 'display-octave', display_octave)
                    else:
                        note = add_text(measure, 'note')
                        if event.chord:
                            add_text(note, 'chord')
                        pitch_elem = add_text(note, 'pitch')
                        add_text(pitch_elem, 'step', event.pitch[0])
                        xml_alter = measure_accidental_alters.get((voice_number, event_index), musicxml_alter_for_event(event, active_part_key_fifths if active_part_key_fifths is not None else 0))
                        if xml_alter:
                            add_text(pitch_elem, 'alter', xml_alter)
                        add_text(pitch_elem, 'octave', event.pitch[1:])
                    add_text(note, 'duration', event_musicxml_duration_divisions(event) or DIVISIONS_PER_QUARTER)
                    if event.kind in TIE_ATTACH_EVENT_KINDS and event.pitch:
                        for tie in event.ties:
                            add_text(note, 'tie', type=tie)
                    add_text(note, 'voice', voice_number)
                    xml_type = XML_TYPE_NAMES.get(event.duration_name)
                    if xml_type is not None:
                        add_text(note, 'type', xml_type)
                    for _dot in range(event.dots):
                        add_text(note, 'dot')
                    if event.kind == 'note':
                        add_musicxml_accidental(note, event)
                    add_musicxml_time_modification(note, event.time_modification)
                    stem_direction = voice_stem_direction_by_number.get(voice_number)
                    if event.stem and event.kind in {'note', 'slash', 'unpitched'}:
                        add_text(note, 'stem', event.stem)
                    elif stem_direction is not None and event.kind in {'note', 'slash', 'unpitched'}:
                        add_text(note, 'stem', stem_direction)
                    elif event.kind == 'slash' and event.display_code == 0:
                        add_text(note, 'stem', 'none')
                    if event.notehead is not None:
                        add_musicxml_notehead(note, event.notehead)
                    elif event.kind == 'slash':
                        add_text(note, 'notehead', 'slash')
                    for beam_number, beam in sorted(beams.get(event_index, {}).items()):
                        add_text(note, 'beam', beam, number=str(beam_number))
                    if event.kind in TIE_ATTACH_EVENT_KINDS and event.pitch:
                        add_musicxml_tied_notations(note, event.ties)
                    add_musicxml_slur_notations(note, event.slurs)
                    add_musicxml_tuplet_notations(note, event.tuplets)
                    add_musicxml_articulations(note, event.articulations)
                    add_musicxml_ornaments(note, event.ornaments)
                previous_voice_duration = musicxml_events_duration_divisions(voice_events) or measure_divisions
            next_tied_alters = dict(tied_alters)
            for voice_number, voice_events in event_voices:
                for event_index, event in enumerate(voice_events):
                    if event.kind not in TIE_ATTACH_EVENT_KINDS or not event.pitch:
                        continue
                    tied_key = (voice_number, event.pitch)
                    if 'stop' in event.ties and 'start' not in event.ties:
                        next_tied_alters.pop(tied_key, None)
                    if 'start' in event.ties:
                        next_tied_alters[tied_key] = measure_accidental_alters.get((voice_number, event_index), musicxml_alter_for_event(event, active_part_key_fifths if active_part_key_fifths is not None else 0))
            tied_alters = next_tied_alters
            for barline in right_barlines:
                add_musicxml_barline(measure, barline)
    out.write_bytes(prettify_xml(score))
    omitted_text = f" omitted={', '.join((repr(name) for name in omitted_staff_names))}" if omitted_staff_names else ''
    print(f'wrote MusicXML parts={part_offset + 1}-{part_offset + source_part_count}/{grid.columns} exported={part_count}{omitted_text} measures={measure_offset + 1}-{measure_offset + measure_count}/{grid.row_count} -> {out}')

def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Convert Composer's Mosaic MOSA files to MusicXML.")
    parser.add_argument("file", type=Path, help="input Mosaic document")
    parser.add_argument("out", type=Path, help="output MusicXML path")
    parser.add_argument("--parts", type=int, help="maximum number of staves to export")
    parser.add_argument("--measures", type=int, help="maximum number of measures to export")
    parser.add_argument("--part-offset", type=int, default=0, help="zero-based source staff offset")
    parser.add_argument("--measure-offset", type=int, default=0, help="zero-based source measure offset")
    parser.add_argument("--raw-directions", action="store_true", help="include undecoded control directions")
    parser.add_argument("--no-infer-time", action="store_true", help="disable conservative time-signature inference")
    parser.add_argument("--omit-staff", dest="omit_staff_names", action="append", metavar="NAME", help="omit one staff by exact display name; repeat for multiple staves")
    parser.add_argument("--omit-staves", dest="omit_staff_name_lists", action="append", metavar="NAME[,NAME...]", help="omit one or more comma-separated staff display names")
    parser.add_argument("--default-time", type=parse_time_signature_text, default=(4, 4), metavar="BEATS/BEAT-TYPE", help="initial meter to use before/without inference")
    parser.add_argument("--key-fifths", type=int, help="MusicXML key signature override")
    parser.add_argument("--key", type=parse_key_signature_text, metavar="KEY", help="MusicXML key signature override by name, such as C, Bb, F#, Am, or G minor")
    return parser


def main() -> None:
    parser = build_arg_parser()
    args = parser.parse_args()
    key_fifths = args.key[0] if args.key is not None else args.key_fifths
    key_mode = args.key[1] if args.key is not None else ""
    musicxml_export(args.file, args.out, args.parts, args.measures, args.part_offset, args.measure_offset, args.raw_directions, not args.no_infer_time, key_fifths, args.default_time, key_mode, parse_omit_staff_names(args.omit_staff_names, args.omit_staff_name_lists))


if __name__ == "__main__":
    main()
