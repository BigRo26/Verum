"""Builds a readable PDF report from fact-check results."""

from io import BytesIO
from datetime import datetime

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
)

VERDICT_COLORS = {
    "true": colors.HexColor("#1a7f37"),
    "false": colors.HexColor("#c0392b"),
    "cannot be sure": colors.HexColor("#b7791f"),
}


def _fmt_time(seconds):
    if seconds is None:
        return "--:--"
    m, s = divmod(int(seconds), 60)
    return f"{m:02d}:{s:02d}"


def build_pdf_report(eval_df, reliability_score, source_title="Audio Analysis"):
    """
    eval_df: pandas.DataFrame with columns
        statement, start_time, end_time, verdict, reasoning, sources, claim_weight
    reliability_score: float in [0,1] or None
    Returns: BytesIO containing the PDF
    """
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=letter,
        topMargin=0.75 * inch, bottomMargin=0.75 * inch,
        leftMargin=0.75 * inch, rightMargin=0.75 * inch,
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "VerumTitle", parent=styles["Title"], fontSize=22, spaceAfter=4
    )
    subtitle_style = ParagraphStyle(
        "VerumSubtitle", parent=styles["Normal"], fontSize=10, textColor=colors.grey
    )
    section_style = ParagraphStyle(
        "VerumSection", parent=styles["Heading2"], spaceBefore=16, spaceAfter=8
    )
    body_style = ParagraphStyle(
        "VerumBody", parent=styles["Normal"], fontSize=9, leading=12
    )
    reasoning_style = ParagraphStyle(
        "VerumReasoning", parent=styles["Normal"], fontSize=8, leading=11, textColor=colors.HexColor("#444444")
    )

    story = []

    story.append(Paragraph("Verum Fact-Check Report", title_style))
    story.append(Paragraph(f"{source_title} &middot; generated {datetime.now().strftime('%B %d, %Y %H:%M')}", subtitle_style))
    story.append(Spacer(1, 18))

    # Reliability summary
    if reliability_score is None:
        score_text = "No verifiable factual claims were detected in this audio."
        score_color = colors.grey
    else:
        pct = round(reliability_score * 100)
        score_text = f"Reliability Score: {pct}%"
        if reliability_score >= 0.8:
            score_color = VERDICT_COLORS["true"]
        elif reliability_score >= 0.5:
            score_color = VERDICT_COLORS["cannot be sure"]
        else:
            score_color = VERDICT_COLORS["false"]

    score_style = ParagraphStyle(
        "VerumScore", parent=styles["Heading1"], fontSize=18, textColor=score_color
    )
    story.append(Paragraph(score_text, score_style))
    story.append(Paragraph(
        "Weighted by claim length: the share of factual claims (by character count) "
        "rated \u2018true\u2019 out of all claims that were checked.",
        subtitle_style
    ))
    story.append(Spacer(1, 12))

    if reliability_score is not None and not eval_df.empty:
        verdict_counts = eval_df["verdict"].value_counts().to_dict()
        summary_rows = [["Verdict", "Count"]]
        for v in ("true", "false", "cannot be sure"):
            if v in verdict_counts:
                summary_rows.append([v.capitalize(), str(verdict_counts[v])])
        summary_table = Table(summary_rows, colWidths=[2.5 * inch, 1 * inch])
        summary_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f0f0f0")),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#dddddd")),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
        ]))
        story.append(summary_table)

    story.append(PageBreak())
    story.append(Paragraph("Claim-by-Claim Breakdown", section_style))

    if eval_df.empty:
        story.append(Paragraph("No factual claims met the confidence threshold for checking.", body_style))
    else:
        for _, row in eval_df.iterrows():
            verdict = str(row["verdict"])
            v_color = VERDICT_COLORS.get(verdict, colors.grey)

            timestamp = f"[{_fmt_time(row['start_time'])} \u2013 {_fmt_time(row['end_time'])}]"
            verdict_style = ParagraphStyle(
                "VerdictLabel", parent=styles["Normal"], fontSize=9,
                textColor=v_color, fontName="Helvetica-Bold"
            )

            story.append(Spacer(1, 8))
            story.append(Paragraph(f"{timestamp} &nbsp; <b>{verdict.upper()}</b>", verdict_style))
            story.append(Paragraph(f"\u201c{row['statement']}\u201d", body_style))
            if row.get("reasoning"):
                story.append(Paragraph(f"Reasoning: {row['reasoning']}", reasoning_style))

            sources_raw = row.get("sources")
            if sources_raw and sources_raw != "{}":
                try:
                    import json
                    src_dict = json.loads(sources_raw)
                    if src_dict:
                        src_text = " &middot; ".join(
                            f'<a href="{url}" color="blue">{title}</a>'
                            for title, url in src_dict.items()
                        )
                        story.append(Paragraph(f"Sources: {src_text}", reasoning_style))
                except (json.JSONDecodeError, TypeError):
                    pass

    doc.build(story)
    buffer.seek(0)
    return buffer
