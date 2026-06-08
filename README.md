# MOTU Composers Mosaic to MusicXML

A standalone Python converter for exporting Composer's Mosaic `.MOSA` documents to MusicXML.

This project is intended for musicians and archivists who still have old Mosaic documents and want a path into modern notation tools such as MuseScore, Dorico, Finale, or Sibelius. It reads Mosaic document files directly and writes MusicXML without depending on the original Mosaic application bundle.

## Status

This is an early public release. The converter can already handle a meaningful amount of real-world big-band notation, including:

- staves, staff names, abbreviations, clefs, key signatures, time signatures, and transposition
- notes, rests, slash notation, hidden rests, dots, tuplets, beams, ties, slurs, accidentals, and noteheads
- chord symbols, dynamics, articulations, jazz articulations, measure repeats, barlines, repeat barlines, and endings
- document text, rehearsal marks, staff text, and note-attached text
- Mosaic-style merged staves where one printed staff displays material sourced from multiple internal voices/staves

There are still likely edge cases. MusicXML output should be reviewed in your notation app, especially for dense arrangements, percussion notation, and unusual text or articulation placement.

## Requirements

- Python 3.11 or newer
- No third-party Python packages

## Usage

```sh
python3 mosaic_to_musicxml.py "path/to/input MOSA file" "path/to/output.musicxml"
```

Example:

```sh
python3 mosaic_to_musicxml.py \
  "example MOSA files/large corpus 1/Bycicle" \
  "Bycicle.musicxml"
```

## Omitting Staves

Mosaic documents sometimes contain secondary staves sharing the same voices as other staves. The converter reads and processes all staves by default, but you can omit arbitrary staves from the final MusicXML export by name.

```sh
python3 mosaic_to_musicxml.py \
  "example MOSA files/large corpus 1/Bycicle" \
  "Bycicle.musicxml" \
  --omit-staff "Piano no Chords" \
  --omit-staff "Bass no Chords"
```

You can also pass a comma-separated list:

```sh
python3 mosaic_to_musicxml.py \
  "example MOSA files/large corpus 1/Bycicle" \
  "Bycicle.musicxml" \
  --omit-staves "Piano no Chords,Bass no Chords,Piano Chords,Bass Chords"
```

## Useful Options

```text
--parts N              export at most N staves
--measures N           export at most N measures
--part-offset N        start from zero-based source staff N
--measure-offset N     start from zero-based source measure N
--default-time 4/4     default meter before or without inference
--key C                override key signature by name
--key-fifths N         override key signature by MusicXML fifths value
--no-infer-time        disable conservative time-signature inference
--raw-directions       include undecoded control directions for debugging
```

## Notes

- The output is MusicXML, not compressed `.mxl`.
- The converter, project, code, and assets are not affiliated in any way with MOTU. MOTU, Mark of the Unicorn, Composer's Mosaic are registered trademarks of MOTU, Inc.

## License

MIT License. See [LICENSE](LICENSE).
