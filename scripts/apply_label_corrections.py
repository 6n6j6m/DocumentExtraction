#!/usr/bin/env python3
"""Apply the label corrections verified against the PDFs on 2026-10-17 (total_share excluded).

Edits only the <v> value of the listed cells in Sheet1's XML; every other zip entry is
copied unchanged, and Excel is told to recalculate the ratio formulas on next open.
Prints every cell that changed and refuses if anything else changed.

    python scripts/apply_label_corrections.py            # dry run: shows what would change
    python scripts/apply_label_corrections.py --apply    # writes the two workbooks
    python scripts/apply_label_corrections.py --akra-scale [--apply]   # AKRA thousands fix only
    python scripts/apply_label_corrections.py --apex-shift [--apply]   # APEX one-column shift
    python scripts/apply_label_corrections.py --trin-shares [--apply]  # TRIN outstanding shares
"""
import os
import re
import sys
import zipfile
from pathlib import Path

REPO = Path("/Users/muhammadnajmirahmani/Belajar/ProjectDatasaur")
sys.path.insert(0, str(REPO / "src"))
from labelaudit import read_columns  # noqa: E402

EDITS = {
    # RCCC Q4 2023 held the Q2 2026 filing's figures shifted one row up. Values from
    # Q4_2023_RCCC.pdf pages 9-14. L13 (total_share) is left for the share-unit review.
    "RCCC": {"L4": 88069161715, "L5": 9158111135, "L6": 750435505, "L7": 45366760486,
             "L8": 0, "L9": 42702401229, "L10": 3501836408, "L11": 75756461938,
             "L12": 31437589559},
    # TRIN, all printed in thousands of Rupiah:
    #   C8  Q1 2026 utang_bank       printed 714.891.426            (label had ...526)
    #   I9  Q3 2024 ekuitas          printed 604.287.000, page 6    (label had 694...)
    #   I12 Q3 2024 cash from ops    printed (32.839.167), page 9   (label not x1000)
    #   E4  Q3 2025 aset             printed 2.097.742.535, page 5  (label had ...752.636)
    #   E12 Q3 2025 cash from ops    printed (31.769.558), page 9   (label not x1000)
    "TRIN": {"C8": 714891426000, "I9": 604287000000, "I12": -32839167000,
             "E4": 2097742535000, "E12": -31769558000,
             # Batch 2, found by re-extracting on 17 Oct (see the second entry file).
             # H = Q4 2024, labelled from the parent-only statements (pp. 127-132);
             # these are the consolidated figures, pp. 11-17, thousands of Rupiah.
             "H4": 2222883786000, "H5": 1408461498000, "H6": 30318046000,
             "H7": 1804103147000, "H8": 695981931000, "H9": 512068584000,
             "H10": -133851628000, "H11": 216640836000, "H12": -9620193000,
             # laba_bersih = owners of the parent, not the total or pre-tax line.
             "P10": 205740000, "L10": -90244453000, "I10": -45211769000,
             "E10": 28483202000, "D10": 12188231000,
             # Q2 2023 cash from operations: the label was the 2022 comparative
             # (-66.612.336 is H1 2022 in the Q2 2022 filing); p9 prints ( 230.537.354).
             "N12": -230537354000,
             # Q4 2022 cash from operations: the label was the INVESTING subtotal
             # (35.264.794, the next line on p18); operations print (143.820.184),
             # confirmed by the Q4 2023 filing's comparative column.
             "P12": -143820184000},
    # PURA Q1 2026 total_aset_lancar: printed "2 10.750.744.785", page 4 -- and
    # 210.750.744.785 + 434.481.634.055 non-current = 645.232.378.840 total assets.
    "PURA": {"C5": 210750744785},
    # TRUK Q4 2025 cash from operations: printed 35.868.950, page 16 (label had ...960).
    # TRUK Q2 2023 (column N): Q2_2023_TRUK.pdf is byte-identical to Q1_2023_TRUK.pdf
    # (both dated 31 Maret 2023), so this column was labelled from the Q1 report. Its
    # nine monetary cells are emptied until the real Q2 2023 report is downloaded; N13
    # (total_share) is left for the share-count review.
    # N4:N12 (Q2 2023) were emptied in batch 1 and have since been relabelled from the
    # re-downloaded filing; they must never be emptied again.
    "TRUK": {"D12": 35868950},
}


# Batch 3 is a PROPOSAL: applied only with --batch3, after the user has checked it.
PROPOSED_BATCH3 = {'AADI': {'H8': 659419354839}, 'ADMR': {'C8': 637406779661, 'B8': 3833410714286, 'F8': 0, 'R6': 5495776552239}, 'CPIN': {'H8': 5400000000000}, 'TLDN': {'M8': 441100000000}}


# AKRA Q1 2022 - Q3 2023 (columns N-T, rows 4-12), approved 2026-11-03: every filing
# heads its statements "(Angka disajikan dalam ribuan Rupiah, ...", which the scale
# reader missed, so the labels were the printed figures taken as full Rupiah. Each is
# the printed figure x 1000. Applied with --akra-scale. Two cells were also wrong in
# themselves: P8 (Q1 2023 utang_bank) added the Dec 2022 comparative short-term loan
# 1.573.705 to the current maturity 548.258.806, and O11 (Q2 2023 pendapatan) took
# the contract line where the filing prints Sub-total 19.854.711.809 -- the figure the
# Q2 2024 filing prints as its "Total Pendapatan" comparative.
AKRA_SCALE = {'AKRA': {'N4': 28805583681000, 'N5': 17541144449000, 'N6': 6481188040000, 'N7': 15702313441000, 'N8': 1044014780000, 'N9': 10693870959000, 'N10': 1710154691000, 'N11': 29977491121000, 'N12': 2723134212000, 'O4': 25429779397000, 'O5': 14442876393000, 'O6': 4574454670000, 'O7': 12145436508000, 'O8': 1021379217000, 'O9': 10985245142000, 'O10': 1030932791000, 'O11': 19854711809000, 'O12': -262248326000, 'P4': 23825391538000, 'P5': 12587821125000, 'P6': 1787578483000, 'P7': 10020258508000, 'P8': 548258806000, 'P9': 11548170155000, 'P10': 607276343000, 'P11': 10891301304000, 'P12': -2207509699000, 'Q4': 27187608036000, 'Q5': 15841294251000, 'Q6': 4337980751000, 'Q7': 14032797261000, 'Q8': 556213226000, 'Q9': 10968862687000, 'Q10': 2403334889000, 'Q11': 47269426164000, 'Q12': 2628813082000, 'R4': 26669680510000, 'R5': 15104364802000, 'R6': 4372802040000, 'R7': 14538119699000, 'R8': 614411333000, 'R9': 10115336971000, 'R10': 1563829837000, 'R11': 34371743798000, 'R12': 2599605994000, 'S4': 27834656130000, 'S5': 16144242761000, 'S6': 3567924937000, 'S7': 15843104993000, 'S8': 564565865000, 'S9': 9986018782000, 'S10': 955461820000, 'S11': 21983258400000, 'S12': 1247260314000, 'T4': 25263441466000, 'T5': 13558920762000, 'T6': 2237649922000, 'T7': 13537518358000, 'T8': 617070011000, 'T9': 9776099273000, 'T10': 427977332000, 'T11': 10071527947000, 'T12': -446655511000}}


# APEX rows 4-13, PROPOSED 2026-11-10 (applied with --apex-shift after the user agrees):
# every period column held the PREVIOUS quarter's figures -- "Q3 2026" carried the Q2
# 2026 filing, "Q2 2022" the Q1 2022 one, Q1 2022 was empty. Shifted one column right
# (B->C ... S->T); B (Q3 2026, not yet filed) is emptied. Row 14 (price) is per its own
# header and is not touched. After the shift all 180 cells equal the extraction, whose
# every figure is printed in its filing as the first figure on its line.
APEX_SHIFT = {'APEX': {'B4': None, 'B5': None, 'B6': None, 'B7': None, 'B8': None, 'B9': None, 'B10': None, 'B11': None, 'B12': None, 'B13': None, 'C4': 4512312979200, 'C5': 1238208124608, 'C6': 500495055552, 'C7': 3230307550656, 'C8': 46790023104, 'C9': 1282005607104, 'C10': 45904311936, 'C11': 599340300480, 'C12': 235962950976, 'C13': 3546466661, 'D4': 4444985081067, 'D5': 1276174452937, 'D6': 511357145439, 'D7': 3249845096251, 'D8': 86161460137, 'D9': 1195140137753, 'D10': 18635509394, 'D11': 337593932471, 'D12': 116872280296, 'D13': 3546466661, 'E4': 4404502944090, 'E5': 1199508453108, 'E6': 451701391932, 'E7': 3245978434116, 'E8': 85091603838, 'E9': 1158524661012, 'E10': 68109679872, 'E11': 1413702036234, 'E12': 514335105204, 'E13': 3546466661, 'F4': 4051115518440, 'F5': 1158445865880, 'F6': 431658600840, 'F7': 2941339023600, 'F8': 84574422120, 'F9': 1109776628280, 'F10': 25332633240, 'F11': 1062866697000, 'F12': 394086083520, 'F13': 3546466661, 'G4': 3986793096951, 'G5': 1127765013732, 'G6': 368062334430, 'G7': 2917657815765, 'G8': 82307949297, 'G9': 1069135411050, 'G10': 12194667891, 'G11': 695728848360, 'G12': 264092810205, 'G13': 3546466661, 'H4': 4038927488024, 'H5': 1085446147500, 'H6': 277173619580, 'H7': 2946150738388, 'H8': 84107944492, 'H9': 1092776865752, 'H10': 7256437188, 'H11': 379524067780, 'H12': 128025636596, 'H13': 3546466661, 'I4': 4056657959500, 'I5': 1147314359180, 'I6': 192271556240, 'I7': 3000469788758, 'I8': 81947950258, 'I9': 1056188267714, 'I10': 8773137650, 'I11': 1367021330632, 'I12': 166531292398, 'I13': 3546466661, 'J4': 3854317651902, 'J5': 1175726497464, 'J6': 137859192540, 'J7': 2859227140860, 'J8': 76755851442, 'J9': 995090511042, 'J10': 14713848378, 'J11': 920770182144, 'J12': 157770476424, 'J13': 3546466661, 'K4': 4221646810090, 'K5': 1290731948078, 'K6': 208703668339, 'K7': 3151187026325, 'K8': 83261186189, 'K9': 1070459783765, 'K10': 5507274980, 'K11': 699179660085, 'K12': 183181345510, 'K13': 2933628566, 'L4': 4116184097089, 'L5': 1262032092024, 'L6': 118816491170, 'L7': 3058603215782, 'L8': 72454693877, 'L9': 1057580881307, 'L10': 27021834825, 'L11': 377086591850, 'L12': 43130543715, 'L13': 2933628566, 'M4': 3965723898904, 'M5': 1151520288208, 'M6': 132778023416, 'M7': 2964638765944, 'M8': 62749425144, 'M9': 1001085132960, 'M10': -20758584376, 'M11': 960030351712, 'M12': -73003408376, 'M13': 2830004997, 'N4': 4000808180712, 'N5': 1127681124962, 'N6': 207712821036, 'N7': 2954184466828, 'N8': 55434170134, 'N9': 1046623713884, 'N10': 17096641212, 'N11': 727779355828, 'N12': -28052997840, 'N13': 2830004997, 'O4': 3926578738038, 'O5': 1144520953620, 'O6': 310943325836, 'O7': 2908078787856, 'O8': 46135965634, 'O9': 1018499950182, 'O10': 23528056398, 'O11': 497907456244, 'O12': 46558962560, 'O13': 2830004997, 'P4': 3942449942448, 'P5': 1084884244862, 'P6': 343426854560, 'P7': 2927059747278, 'P8': 46246500358, 'P9': 1015390195170, 'P10': 15586729956, 'P11': 234548913198, 'P12': 27675009172, 'P13': 2830004997, 'Q4': 4136730542028, 'Q5': 1112391756043, 'Q6': 358639585370, 'Q7': 3092219136424, 'Q8': 48300603979, 'Q9': 1044511405604, 'Q10': -1018429879534, 'Q11': 1273845584601, 'Q12': 293385840001, 'Q13': 2796804997, 'R4': 4028024898497, 'R5': 1139565476076, 'R6': 278746751784, 'R7': 2994749019128, 'R8': 46814526023, 'R9': 1033275879369, 'R10': -966789734934, 'R11': 988066008614, 'R12': 147218704495, 'R13': 2796804997, 'S4': 5267053920768, 'S5': 1061436154880, 'S6': 237447849984, 'S7': 3287890993152, 'S8': 51652361216, 'S9': 1979162927616, 'S10': 31879814144, 'S11': 693913677824, 'S12': 73564326912, 'S13': 2796804997, 'T4': 5078697883209, 'T5': 942398910990, 'T6': 160178931316, 'T7': 3184640702472, 'T8': 38198140796, 'T9': 1894057180738, 'T10': 10801016391, 'T11': 345941817434, 'T12': -12082612569, 'T13': 2796804997}}


# TRIN total_share, PROPOSED 2026-11-10 (--trin-shares): total_share is OUTSTANDING.
#   P13 TAHUNAN 2022: Q4_2022_TRIN.pdf p101 "Sub-total 4.205.476 ... Saham treasuri
#       199.000 ... Total 4.404.476"; the label was the Total (issued).
#   D13 Q4 2025: Q4_2025_TRIN.pdf p103 2025 table "Sub-total 4.424.040 ... Saham treasuri
#       127.417"; the label 4.352.457 is the 2024 comparative table's Sub-total.
TRIN_SHARES = {'TRIN': {'P13': 4205476, 'D13': 4424040}}


def main(apply: bool) -> int:
    if "--akra-scale" in sys.argv:
        # Its own batch: the earlier ones are already in the workbooks and logged.
        edits = {k: dict(v) for k, v in AKRA_SCALE.items()}
    elif "--apex-shift" in sys.argv:
        edits = {k: dict(v) for k, v in APEX_SHIFT.items()}
    elif "--trin-shares" in sys.argv:
        edits = {k: dict(v) for k, v in TRIN_SHARES.items()}
    else:
        edits = {k: dict(v) for k, v in EDITS.items()}
    if "--batch3" in sys.argv:
        for workbook, cells in PROPOSED_BATCH3.items():
            edits.setdefault(workbook, {}).update(cells)
    for workbook, cells in edits.items():
        path = REPO / "data" / "ground_truth" / f"{workbook}.xlsx"
        if path.with_name("~$" + path.name).exists():
            print(f"✗ {path.name} is open in Excel; close it first")
            return 1
        before, _ = read_columns(path)
        source = zipfile.ZipFile(path)
        book = source.read("xl/workbook.xml").decode()
        rels = source.read("xl/_rels/workbook.xml.rels").decode()
        rid = re.search(r'<sheet [^>]*name="Sheet1"[^>]*r:id="(rId\d+)"', book).group(1)
        rel = re.search(rf'<Relationship [^>]*Id="{rid}"[^>]*>', rels).group(0)
        target = "xl/" + re.search(r'Target="([^"]+)"', rel).group(1).lstrip("/").replace("xl/", "")
        sheet = source.read(target).decode()
        for ref, value in cells.items():
            pattern = re.compile(rf'<c r="{ref}"( s="\d+")?(?: t="n")?(?:\s*/>|><v>[^<]*</v></c>)')
            match = pattern.search(sheet)
            if not match:
                print(f"✗ {workbook} {ref}: cell not found as a plain number; nothing written")
                return 1
            cell = (f'<c r="{ref}"{match.group(1) or ""}/>' if value is None else
                    f'<c r="{ref}"{match.group(1) or ""}><v>{value}</v></c>')
            sheet = sheet[:match.start()] + cell + sheet[match.end():]
        if "fullCalcOnLoad" not in book:
            book = (re.sub(r"<calcPr", '<calcPr fullCalcOnLoad="1"', book, count=1)
                    if "<calcPr" in book else
                    book.replace("</workbook>", '<calcPr fullCalcOnLoad="1"/></workbook>'))
        temp = path.with_suffix(".tmp.xlsx")
        with zipfile.ZipFile(temp, "w") as out:
            for item in source.infolist():
                data = source.read(item.filename)
                if item.filename == target:
                    data = sheet.encode()
                elif item.filename == "xl/workbook.xml":
                    data = book.encode()
                out.writestr(item, data)
        source.close()
        after, letters = read_columns(temp)
        changed = [(p, f, before[p][f], after[p][f]) for p in before for f in before[p]
                   if before[p][f] != after[p][f]]
        expected = {f"{letters[p]}{r}" for p, f, _, _ in changed
                    for name, (r, _l) in __import__("schema").EXCEL_ROWS.items() if name == f}
        print(f"{workbook}: {len(changed)} cell(s) change")
        for p, f, old, new in changed:
            print(f"   {p[0]} {p[1]} {f:28s} {old!s:>18} -> "
                  f"{'(empty)' if new is None else f'{new:,.0f}'}")
        # Idempotent: cells already at their target are fine; anything that changed
        # must be planned, and every planned cell must end at its target.
        target_ok = all(
            (after[p][f] is None) if cells.get(f"{letters[p]}{r}", 0) is None else
            (after[p][f] is not None and abs(after[p][f] - cells[f"{letters[p]}{r}"]) < 0.5)
            for p in after for f, (r, _l) in __import__("schema").EXCEL_ROWS.items()
            if f"{letters.get(p)}{r}" in cells)
        if not expected <= set(cells) or not target_ok:
            print(f"✗ changed cells {sorted(expected)} are not all planned, or a planned "
                  f"cell did not reach its value; nothing written")
            temp.unlink()
            return 1
        if apply:
            os.replace(temp, path)
        else:
            temp.unlink()
    if apply:
        log = REPO / "data" / "ground_truth" / "CORRECTIONS.md"
        for name, marker in (("label_corrections_2026-10-17.md",
                              "first check of the four new workbooks"),
                             ("label_corrections_2026-10-17b.md",
                              "TRIN consolidated figures and parent-attributable profit")) + (
                             (("label_corrections_2026-10-18_batch3.md",
                               "utang_bank (and one kas) in four older workbooks"),)
                             if "--batch3" in sys.argv else ()) + (
                             (("label_corrections_2026-11-03_akra_scale.md",
                               "AKRA Q1 2022 - Q3 2023 printed in thousands"),)
                             if "--akra-scale" in sys.argv else ()) + (
                             (("label_corrections_2026-11-10_apex_shift.md",
                               "APEX columns shifted one quarter"),)
                             if "--apex-shift" in sys.argv else ()) + (
                             (("label_corrections_2026-11-10_trin_shares.md",
                               "TRIN total_share outstanding"),)
                             if "--trin-shares" in sys.argv else ()):
            if marker not in log.read_text():
                with log.open("a", encoding="utf-8") as handle:
                    handle.write(Path(__file__).with_name(name).read_text())
                print(f"logged {name} in {log.relative_to(REPO)}")
    print("written." if apply else "dry run only; re-run with --apply to write.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main("--apply" in sys.argv))
