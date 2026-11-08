#!/usr/bin/env python3
"""Render the canonical FlatSplit review draft.
Run from the repository root:
  uv run --no-project --with reportlab tools/report/render_report.py
The component figure is a report-specific layout of the source Mermaid paths.
"""

from __future__ import annotations

import argparse
import html
import math
import re
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.utils import simpleSplit
from reportlab.platypus import (
    Flowable,
    LongTable,
    PageBreak,
    Paragraph,
    Preformatted,
    SimpleDocTemplate,
    Spacer,
    TableStyle,
)

REPO = Path(__file__).resolve().parents[2]
SOURCE = REPO / "docs/report/final-report-draft.md"
OUTPUT = REPO / "output/pdf/flatsplit-final-report-draft.pdf"
INK = colors.HexColor("#173b39")
ACCENT = colors.HexColor("#167468")
MUTED = colors.HexColor("#536467")
WIDTH = A4[0] - 76


def inline(text: str) -> str:
    text = html.escape(text.replace("—", "-").replace("–", "-").replace("×", "x"))

    def link(m):
        label, target = m.group(1), html.unescape(m.group(2))
        if not re.match(r"https?://", target):
            target = (
                "https://github.com/horiiiiii032929/CS5225-teams12-2026/blob/main/"
                + str((Path("docs/report") / target).as_posix())
            )
        return (
            '<link href="'
            + html.escape(target, quote=True)
            + '" color="#167468">'
            + label
            + "</link>"
        )

    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", link, text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"`([^`]+)`", r'<font name="Courier">\1</font>', text)
    text = re.sub(
        r"&lt;(https?://.*?)&gt;", r'<link href="\1" color="#167468">\1</link>', text
    )
    return text


class Architecture(Flowable):
    """Compact vector component paths; repeated DynamoDB labels denote one table."""

    def __init__(self):
        super().__init__()
        self.width, self.height = WIDTH, 270

    def draw(self):
        c = self.canv
        scale = WIDTH / 510
        c.saveState()
        c.scale(scale, 1)

        def arrow(x1, y1, x2, y2):
            c.setStrokeColor(MUTED)
            c.setFillColor(MUTED)
            c.setLineWidth(0.7)
            c.line(x1, y1, x2, y2)
            angle = math.atan2(y2 - y1, x2 - x1)
            d = 4
            p = c.beginPath()
            p.moveTo(x2, y2)
            p.lineTo(x2 - d * math.cos(angle - 0.5), y2 - d * math.sin(angle - 0.5))
            p.lineTo(x2 - d * math.cos(angle + 0.5), y2 - d * math.sin(angle + 0.5))
            p.close()
            c.drawPath(p, fill=1, stroke=0)

        def box(x, y, label):
            c.setFillColor(colors.HexColor("#eef5f2"))
            c.setStrokeColor(ACCENT)
            c.roundRect(x, y, 90, 28, 4, fill=1, stroke=1)
            c.setFillColor(INK)
            c.setFont("Helvetica", 7.4)
            lines = simpleSplit(label, "Helvetica", 7.4, 82)
            for i, line in enumerate(lines):
                c.drawCentredString(x + 45, y + 17 - i * 9, line)

        c.setFillColor(MUTED)
        c.setFont("Helvetica-Bold", 8)
        c.drawString(0, 258, "Interactive requests and asynchronous routes")
        for a in [
            (90, 183, 105, 183),
            (195, 183, 210, 183),
            (300, 183, 315, 183),
            (405, 183, 420, 183),
            (150, 197, 150, 211),
            (360, 197, 465, 211),
            (360, 169, 255, 147),
            (300, 133, 315, 133),
            (405, 133, 420, 133),
            (360, 147, 465, 169),
        ]:
            arrow(*a)
        for x, y, label in [
            (0, 169, "Browser"),
            (105, 169, "CloudFront"),
            (210, 169, "HTTP API"),
            (315, 169, "HTTP Lambda"),
            (420, 169, "DynamoDB"),
            (105, 211, "Private web S3"),
            (420, 211, "OneMap search"),
            (210, 119, "SQS + DLQ"),
            (315, 119, "Worker Lambda"),
            (420, 119, "OneMap routing"),
        ]:
            box(x, y, label)
        c.setFillColor(MUTED)
        c.setFont("Helvetica-Bold", 8)
        c.drawString(0, 99, "Scheduled publication, credentials and observability")
        for a in [
            (90, 67, 105, 67),
            (195, 67, 210, 67),
            (300, 67, 315, 67),
            (45, 53, 45, 31),
            (90, 17, 105, 17),
            (195, 17, 210, 17),
        ]:
            arrow(*a)
        for x, y, label in [
            (0, 53, "EventBridge"),
            (105, 53, "HDB ingestion"),
            (210, 53, "Raw evidence S3"),
            (315, 53, "DynamoDB snapshots"),
            (420, 53, "CloudWatch"),
            (0, 3, "EventBridge"),
            (105, 3, "Token refresh"),
            (210, 3, "Secrets Manager"),
        ]:
            box(x, y, label)
        c.setFillColor(MUTED)
        c.setFont("Helvetica", 7.1)
        c.drawString(315, 23, "API/worker read the token secret.")
        c.drawString(315, 12, "Lambda logs/metrics feed CloudWatch.")
        c.restoreState()


def render(source: Path, output: Path):
    styles = getSampleStyleSheet()
    body = ParagraphStyle(
        "Body",
        parent=styles["BodyText"],
        fontName="Helvetica",
        fontSize=9.2,
        leading=12,
        textColor=INK,
        spaceAfter=4.0,
        splitLongWords=1,
    )
    small = ParagraphStyle(
        "Small", parent=body, fontSize=8.1, leading=10.2, spaceAfter=0
    )
    heading = ParagraphStyle(
        "Section",
        parent=styles["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=13,
        leading=16,
        textColor=ACCENT,
        spaceBefore=12,
        spaceAfter=6,
        keepWithNext=True,
    )
    sub = ParagraphStyle(
        "Subsection", parent=heading, fontSize=10.5, leading=13, spaceBefore=9
    )
    title = ParagraphStyle(
        "ReportTitle",
        parent=heading,
        fontSize=23,
        leading=28,
        spaceBefore=30,
        spaceAfter=18,
    )
    code = ParagraphStyle(
        "Code",
        fontName="Courier",
        fontSize=8,
        leading=10,
        textColor=INK,
        backColor=colors.HexColor("#f3f6f5"),
        borderPadding=6,
        spaceBefore=4,
        spaceAfter=8,
    )
    story = []
    lines = source.read_text().splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if not line:
            i += 1
            continue
        if line.startswith("# "):
            story.append(Paragraph(inline(line[2:]), title))
            i += 1
            continue
        if line == "## Abstract":
            story.append(PageBreak())
        if line.startswith("### "):
            story.append(Paragraph(inline(line[4:]), sub))
            i += 1
            continue
        if line.startswith("## "):
            story.append(Paragraph(inline(line[3:]), heading))
            i += 1
            continue
        if line.startswith("```"):
            language = line[3:]
            block = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                block.append(lines[i])
                i += 1
            if language == "mermaid":
                story.append(Architecture())
            else:
                wrapped = []
                for row in block:
                    wrapped.extend(simpleSplit(row, "Courier", 8, WIDTH - 16) or [""])
                story.append(Preformatted("\n".join(wrapped), code))
            i += 1
            continue
        if line.startswith("|"):
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                cells = [v.strip() for v in lines[i].strip().strip("|").split("|")]
                if not all(re.fullmatch(r":?-+:?", v.replace(" ", "")) for v in cells):
                    rows.append(cells)
                i += 1
            count = len(rows[0])
            if count == 5:
                widths = [118, 55, 57, 55, WIDTH - 285]
            elif count == 4:
                widths = [72, 101, 174, WIDTH - 347]
            elif count == 2:
                widths = [116, WIDTH - 116]
            else:
                widths = [WIDTH / count] * count
            data = [[Paragraph(inline(cell), small) for cell in row] for row in rows]
            table = LongTable(data, colWidths=widths, repeatRows=1, hAlign="LEFT")
            table.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e4efeb")),
                        ("LINEBELOW", (0, 0), (-1, 0), 0.7, ACCENT),
                        (
                            "LINEBELOW",
                            (0, 1),
                            (-1, -1),
                            0.3,
                            colors.HexColor("#d3dedb"),
                        ),
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ("LEFTPADDING", (0, 0), (-1, -1), 5),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                        ("TOPPADDING", (0, 0), (-1, -1), 4),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                    ]
                )
            )
            story.extend([table, Spacer(1, 7)])
            continue
        prefix = ""
        bullet = re.match(r"^(- |\d+\. )", line)
        if bullet:
            prefix = bullet.group(0).strip()
            line = line[len(bullet.group(0)) :]
        quote = line.startswith("> ")
        if quote:
            line = line[2:]
        parts = [line]
        i += 1
        while i < len(lines) and lines[i].strip():
            next_line = lines[i].strip()
            if next_line.startswith(("#", "|", "```")) or re.match(
                r"^(- |\d+\. )", next_line
            ):
                break
            parts.append(next_line.removeprefix("> "))
            i += 1
        text = " ".join(parts)
        text = text.replace("[ ]", "[pending]").replace("[x]", "[done]")
        ps = (
            ParagraphStyle("List", parent=body, leftIndent=12, firstLineIndent=0)
            if prefix
            else body
        )
        story.append(Paragraph(inline(text), ps, bulletText=prefix or None))
    output.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(output),
        pagesize=A4,
        rightMargin=38,
        leftMargin=38,
        topMargin=37,
        bottomMargin=35,
        title="FlatSplit Final Report Draft v0.2",
        author="CS5224 Group 12",
        subject="Evidence-backed review draft; pending gates retained",
    )

    def frame(c, doc):
        c.saveState()
        c.setFillColor(MUTED)
        c.setFont("Helvetica", 7)
        if doc.page > 1:
            c.drawString(
                38, A4[1] - 22, "FlatSplit - evidence-backed review draft v0.2"
            )
        c.drawString(38, 20, "CS5224 Group 12 | Review draft, not a submission receipt")
        c.drawRightString(A4[0] - 38, 20, str(doc.page))
        c.restoreState()

    doc.build(story, onFirstPage=frame, onLaterPages=frame)
    if doc.page > 10:
        raise RuntimeError(f"Report has {doc.page} pages; maximum is 10")
    print(f"Rendered {doc.page} A4 pages: {output}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=SOURCE)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    render(args.source, args.output)
