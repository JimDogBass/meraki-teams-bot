"""
CV Generator - Creates Meraki-formatted Word documents from structured CV data.
Logo in header (centered) so it appears on every page.
"""
import io
import json
import os
import copy
from docx import Document
from docx.shared import Pt, RGBColor, Cm, Inches
from docx.oxml.ns import qn
from docx.oxml import OxmlElement
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_TAB_ALIGNMENT

# Logo path
LOGO_PATH = os.path.join(os.path.dirname(__file__), "templates", "meraki_logo.png")

# Tab positions for two-column layout (matching Emeliene CV)
TAB_RIGHT_POS = Cm(3.5)  # Right-aligned tab for labels
TAB_LEFT_POS = Cm(4.5)   # Left-aligned tab for values

# Grey shading for section headers
HEADER_SHADING = "D9D9D9"


def add_page_border(doc):
    """Add a single-line border around the page."""
    for section in doc.sections:
        sectPr = section._sectPr
        pgBorders = OxmlElement('w:pgBorders')
        pgBorders.set(qn('w:offsetFrom'), 'page')

        for border_name in ['top', 'left', 'bottom', 'right']:
            border = OxmlElement(f'w:{border_name}')
            border.set(qn('w:val'), 'single')
            border.set(qn('w:sz'), '4')
            border.set(qn('w:space'), '24')
            border.set(qn('w:color'), 'auto')
            pgBorders.append(border)

        sectPr.append(pgBorders)


def add_floating_header_logo(doc, logo_path):
    """
    Add logo as a floating image in header.
    Positioned at top center, appears on every page in full color.
    """
    from docx.oxml import parse_xml

    # Target dimensions
    target_width = Inches(2.5)
    # Assume typical logo aspect ratio ~3:1 (width:height)
    target_height = Inches(0.8)

    # Center position: offset from left margin
    # Page is 8.5" with 1" margins = 6.5" content width
    # Center a 2.5" logo: (6.5 - 2.5) / 2 = 2"
    horiz_offset = Inches(2.0)
    vert_offset = Inches(0)

    for section in doc.sections:
        header = section.header
        header.is_linked_to_previous = False

        # Get or create paragraph in header
        if not header.paragraphs:
            header.add_paragraph()
        para = header.paragraphs[0]

        # Add the picture inline first
        run = para.add_run()
        picture = run.add_picture(logo_path, width=target_width)

        # Get the drawing element
        drawing = run._element.find(qn('w:drawing'))
        inline = drawing.find('{http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing}inline')

        if inline is not None:
            # Extract graphic and docPr from inline
            graphic = inline.find('{http://schemas.openxmlformats.org/drawingml/2006/main}graphic')
            docPr = inline.find('{http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing}docPr')
            extent = inline.find('{http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing}extent')

            doc_id = docPr.get('id') if docPr is not None else '1'
            doc_name = docPr.get('name') if docPr is not None else 'Picture'
            cx = extent.get('cx') if extent is not None else str(int(target_width))
            cy = extent.get('cy') if extent is not None else str(int(target_height))

            # Build anchor XML for floating image
            anchor_xml = f'''<wp:anchor xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
                       xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
                       distT="0" distB="0" distL="114300" distR="114300"
                       simplePos="0" relativeHeight="251659264" behindDoc="0"
                       locked="0" layoutInCell="1" allowOverlap="1">
                <wp:simplePos x="0" y="0"/>
                <wp:positionH relativeFrom="margin">
                    <wp:posOffset>{int(horiz_offset)}</wp:posOffset>
                </wp:positionH>
                <wp:positionV relativeFrom="paragraph">
                    <wp:posOffset>{int(vert_offset)}</wp:posOffset>
                </wp:positionV>
                <wp:extent cx="{cx}" cy="{cy}"/>
                <wp:effectExtent l="0" t="0" r="0" b="0"/>
                <wp:wrapNone/>
                <wp:docPr id="{doc_id}" name="{doc_name}"/>
                <wp:cNvGraphicFramePr>
                    <a:graphicFrameLocks noChangeAspect="1"/>
                </wp:cNvGraphicFramePr>
            </wp:anchor>'''

            anchor = parse_xml(anchor_xml)

            # Move graphic from inline to anchor
            if graphic is not None:
                inline.remove(graphic)
                anchor.append(graphic)

            # Replace inline with anchor
            drawing.remove(inline)
            drawing.append(anchor)


def create_meraki_cv(cv_data: dict) -> bytes:
    """
    Generate a Meraki-formatted CV Word document from structured data.
    Builds document from scratch with logo in body (not header).
    """
    # Create new blank document
    doc = Document()

    # Set default font to Aptos 11pt with no spacing after paragraphs
    style = doc.styles['Normal']
    style.font.name = 'Aptos'
    style.font.size = Pt(11)
    style.paragraph_format.space_after = Pt(0)
    style.paragraph_format.space_before = Pt(0)

    # Set page margins (matching Emeliene CV)
    for section in doc.sections:
        section.top_margin = Inches(1.48)
        section.bottom_margin = Inches(1.28)
        section.left_margin = Inches(1.0)
        section.right_margin = Inches(1.0)

    # Add page border
    add_page_border(doc)

    # === ADD LOGO AS FLOATING IMAGE IN HEADER (full color, every page) ===
    if os.path.exists(LOGO_PATH):
        add_floating_header_logo(doc, LOGO_PATH)

    # === PERSONAL DETAILS ===
    add_section_header(doc, "PERSONAL DETAILS")
    add_blank_line(doc)
    add_field_line(doc, "Name", cv_data.get("name", ""))
    add_field_line(doc, "Location", cv_data.get("location", ""))
    # Only show these fields if they have values
    right_to_work = cv_data.get("right_to_work", "")
    if right_to_work:
        add_field_line(doc, "Right to Work", right_to_work)
    notice = cv_data.get("notice", "")
    if notice:
        add_field_line(doc, "Notice", notice)
    salary = cv_data.get("salary_expectations", "")
    if salary:
        add_field_line(doc, "Salary expectations", salary)

    # === EDUCATION ===
    education = cv_data.get("education", [])
    if education:
        add_blank_line(doc)
        add_section_header(doc, "EDUCATION")
        add_blank_line(doc)
        for i, edu in enumerate(education):
            dates = edu.get("dates", "")
            institution = edu.get("institution", "")
            title = edu.get("title", "")
            details = edu.get("details", [])

            # Date and qualification line (bold)
            add_tabbed_line(doc, dates, title, bold=True)

            # Institution on next line (indented)
            if institution:
                add_indented_line(doc, institution)

            # Additional details
            for detail in details:
                add_indented_line(doc, detail)

            # Add blank line between education entries (except last)
            if i < len(education) - 1:
                add_blank_line(doc)

    # === CANDIDATE PROFILE ===
    add_blank_line(doc)
    add_section_header(doc, "CANDIDATE PROFILE")
    add_blank_line(doc)
    profile = cv_data.get("profile", "")
    if profile:
        # Split profile into paragraphs if it contains double newlines
        paragraphs = profile.split('\n\n') if '\n\n' in profile else [profile]
        for para_text in paragraphs:
            p = doc.add_paragraph(para_text.strip())
            p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY

    # === WORK EXPERIENCE ===
    work_exp = cv_data.get("work_experience", [])
    if work_exp:
        add_blank_line(doc)
        add_blank_line(doc)
        add_section_header(doc, "WORK EXPERIENCE")
        add_blank_line(doc)
        for i, job in enumerate(work_exp):
            dates = job.get("dates", "")
            company = job.get("company", "")
            position = job.get("position", "")

            # Date and company line (bold)
            add_tabbed_line(doc, dates, company, bold=True)

            # Position line
            if position:
                add_position_line(doc, position)

            # Bullet points as plain text
            for bullet in job.get("bullets", []):
                p = doc.add_paragraph(bullet)
                p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY

            # Add blank line between jobs (except last)
            if i < len(work_exp) - 1:
                add_blank_line(doc)

    # === OTHER INFORMATION (only if present and has content) ===
    other_info = cv_data.get("other_information", [])
    if other_info and len(other_info) > 0:
        add_blank_line(doc)
        add_section_header(doc, "OTHER INFORMATION")
        add_blank_line(doc)
        for item in other_info:
            category = item.get("category", "")
            content = item.get("content", [])

            if category:
                # Add category as sub-header
                p = doc.add_paragraph()
                run = p.add_run(category + ":")
                run.bold = True
                run.font.name = 'Aptos'
                run.font.size = Pt(11)

            # Add content items
            if isinstance(content, list) and len(content) > 0:
                p = doc.add_paragraph()
                p.add_run('\n'.join(content))
            elif content:
                p = doc.add_paragraph(str(content))

    # Save to bytes
    buffer = io.BytesIO()
    doc.save(buffer)
    buffer.seek(0)
    return buffer.getvalue()


def add_blank_line(doc):
    """Add an empty paragraph for spacing."""
    return doc.add_paragraph()


def add_section_header(doc, text):
    """Add a bold section header with grey shading."""
    p = doc.add_paragraph()
    run = p.add_run(text)
    run.bold = True
    run.font.name = 'Aptos'
    run.font.size = Pt(11)

    # Add grey shading to paragraph
    pPr = p._element.get_or_add_pPr()
    shd = OxmlElement('w:shd')
    shd.set(qn('w:val'), 'clear')
    shd.set(qn('w:color'), 'auto')
    shd.set(qn('w:fill'), HEADER_SHADING)
    pPr.append(shd)

    return p


def add_field_line(doc, label, value):
    """Add a field line with tabbed label and value (e.g., '\tName\tJohn Smith')."""
    p = doc.add_paragraph()
    # Set up tab stops
    tab_stops = p.paragraph_format.tab_stops
    tab_stops.add_tab_stop(TAB_RIGHT_POS, WD_TAB_ALIGNMENT.RIGHT)
    tab_stops.add_tab_stop(TAB_LEFT_POS, WD_TAB_ALIGNMENT.LEFT)
    # Add tabbed content
    p.add_run(f"\t{label}\t{value if value else ''}")
    return p


def add_tabbed_line(doc, left_text, right_text, bold=False):
    """Add a line with tab-separated content (e.g., '\t2019\tMA Event Design')."""
    p = doc.add_paragraph()
    # Set up tab stops
    tab_stops = p.paragraph_format.tab_stops
    tab_stops.add_tab_stop(TAB_RIGHT_POS, WD_TAB_ALIGNMENT.RIGHT)
    tab_stops.add_tab_stop(TAB_LEFT_POS, WD_TAB_ALIGNMENT.LEFT)
    # Add tabbed content with optional bold
    run = p.add_run(f"\t{left_text}\t{right_text}")
    if bold:
        run.bold = True
    return p


def add_indented_line(doc, text):
    """Add an indented line (for institution names, details)."""
    p = doc.add_paragraph()
    # Set up tab stops
    tab_stops = p.paragraph_format.tab_stops
    tab_stops.add_tab_stop(TAB_LEFT_POS, WD_TAB_ALIGNMENT.LEFT)
    # Add double-tabbed content (to align under right column)
    p.add_run(f"\t\t{text}")
    return p


def add_position_line(doc, position):
    """Add a position line with bold label."""
    p = doc.add_paragraph()
    # Set up tab stops
    tab_stops = p.paragraph_format.tab_stops
    tab_stops.add_tab_stop(TAB_RIGHT_POS, WD_TAB_ALIGNMENT.RIGHT)
    tab_stops.add_tab_stop(TAB_LEFT_POS, WD_TAB_ALIGNMENT.LEFT)
    # Add tabbed position
    p.add_run("\t")
    run = p.add_run("Position:")
    run.bold = True
    p.add_run(f"\t{position}")
    return p


def parse_cv_json(ai_response: str) -> dict:
    """
    Parse the AI response to extract JSON CV data.
    Handles cases where JSON might be wrapped in markdown code blocks.
    """
    text = ai_response.strip()

    # Remove markdown code blocks if present
    if text.startswith("```json"):
        text = text[7:]
    elif text.startswith("```"):
        text = text[3:]

    if text.endswith("```"):
        text = text[:-3]

    text = text.strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        # Try to find JSON object in the response
        start = text.find('{')
        end = text.rfind('}')
        if start != -1 and end != -1:
            try:
                return json.loads(text[start:end+1])
            except json.JSONDecodeError:
                pass
        raise ValueError(f"Could not parse CV data as JSON: {e}")


# System prompt for CV extraction - preserves full detail
CV_EXTRACTION_PROMPT = """You are a CV data extraction assistant. Extract structured information from the provided CV and return it as valid JSON.

CRITICAL RULES:
1. Return ONLY valid JSON - no explanations, no markdown code blocks, just the JSON object
2. Keep the complete profile/summary exactly as written in the CV
3. Use short date format: "Jan 23" not "January 2023"
4. Extract ALL work experience entries
5. Preserve ALL bullet points from each role
6. Only include "other_information" if explicitly present in the CV (skills, volunteering, certifications, etc.)

REQUIRED JSON STRUCTURE:
{
  "name": "Full Name",
  "location": "City, Country",
  "right_to_work": "British Citizen (or leave empty if not stated)",
  "notice": "Available immediately (or leave empty if not stated)",
  "salary_expectations": "£45,000 (or leave empty if not stated)",
  "profile": "FULL profile/summary paragraph exactly as written",
  "education": [
    {
      "dates": "2019",
      "title": "Degree/Qualification name",
      "institution": "University/School name",
      "details": ["Additional details like grades if present"]
    }
  ],
  "work_experience": [
    {
      "dates": "Jan 23 - Present",
      "company": "Company Name",
      "position": "Job Title",
      "bullets": [
        "Full original bullet point text",
        "Another bullet with complete wording"
      ]
    }
  ],
  "other_information": [
    {
      "category": "Core Skills",
      "content": ["Skill 1", "Skill 2", "Skill 3"]
    }
  ]
}

IMPORTANT:
- Extract ALL roles from the CV
- Include ALL bullet points from each role
- Preserve original wording
- "other_information" is OPTIONAL - only include if the CV has a section like Skills, Volunteering, Certifications, Languages, Interests, etc.
- If no such section exists, set "other_information" to an empty array []

Extract the CV data now:"""
