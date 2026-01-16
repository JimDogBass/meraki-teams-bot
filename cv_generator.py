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


def add_header_logo(doc, logo_path):
    """
    Add logo to header (centered, appears on every page).
    Note: Headers appear slightly faded in Word's editing view but print full color.
    """
    for section in doc.sections:
        header = section.header
        header.is_linked_to_previous = False

        # Get or create paragraph in header
        if not header.paragraphs:
            header.add_paragraph()
        para = header.paragraphs[0]
        para.alignment = WD_ALIGN_PARAGRAPH.CENTER

        # Add centered logo
        run = para.add_run()
        run.add_picture(logo_path, width=Inches(2.5))


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

    # Set page margins (reduced top margin for logo)
    for section in doc.sections:
        section.top_margin = Inches(0.5)
        section.bottom_margin = Inches(0.5)
        section.left_margin = Inches(1.0)
        section.right_margin = Inches(1.0)

    # Add page border
    add_page_border(doc)

    # === ADD LOGO IN BODY (centered, page 1 only, full color) ===
    if os.path.exists(LOGO_PATH):
        add_blank_line(doc)  # Space before logo
        logo_para = doc.add_paragraph()
        logo_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        logo_run = logo_para.add_run()
        logo_run.add_picture(LOGO_PATH, width=Inches(3.5))
        add_blank_line(doc)  # Space after logo

    # === PERSONAL DETAILS ===
    add_section_header(doc, "PERSONAL DETAILS")
    add_blank_line(doc)
    add_field_line(doc, "Name", cv_data.get("name", ""))
    add_field_line(doc, "Location", cv_data.get("location", ""))
    add_field_line(doc, "Right to Work", cv_data.get("right_to_work", ""))
    add_field_line(doc, "Notice", cv_data.get("notice", ""))
    add_field_line(doc, "Salary expectations", cv_data.get("salary_expectations", ""))

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
                add_blank_line(doc)  # Space after position

            # Bullet points (supports nested/hierarchical structure)
            for bullet in job.get("bullets", []):
                add_nested_bullets(doc, bullet)

            # Add blank line between jobs (except last)
            if i < len(work_exp) - 1:
                add_blank_line(doc)

    # === OTHER INFORMATION (only if present and has content) ===
    other_info = cv_data.get("other_information", [])
    if other_info and len(other_info) > 0:
        add_blank_line(doc)
        add_section_header(doc, "OTHER INFORMATION")
        add_blank_line(doc)
        for i, item in enumerate(other_info):
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

            # Add space between categories (except last)
            if i < len(other_info) - 1:
                add_blank_line(doc)

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
    # Set hanging indent so wrapped text aligns with right column
    p.paragraph_format.left_indent = TAB_LEFT_POS
    p.paragraph_format.first_line_indent = -TAB_LEFT_POS
    # Add tabbed content with optional bold
    run = p.add_run(f"\t{left_text}\t{right_text}")
    if bold:
        run.bold = True
    return p


def add_indented_line(doc, text):
    """Add an indented line (for institution names, details)."""
    p = doc.add_paragraph()
    # Set up BOTH tab stops (same as main lines) for proper alignment
    tab_stops = p.paragraph_format.tab_stops
    tab_stops.add_tab_stop(TAB_RIGHT_POS, WD_TAB_ALIGNMENT.RIGHT)
    tab_stops.add_tab_stop(TAB_LEFT_POS, WD_TAB_ALIGNMENT.LEFT)
    # Set hanging indent so wrapped text aligns with content column
    p.paragraph_format.left_indent = TAB_LEFT_POS
    p.paragraph_format.first_line_indent = -TAB_LEFT_POS
    # Add double-tabbed content (first tab to RIGHT pos, second to LEFT pos)
    p.add_run(f"\t\t{text}")
    return p


def add_position_line(doc, position):
    """Add a position line with bold label and bold position value."""
    p = doc.add_paragraph()
    # Set up tab stops
    tab_stops = p.paragraph_format.tab_stops
    tab_stops.add_tab_stop(TAB_RIGHT_POS, WD_TAB_ALIGNMENT.RIGHT)
    tab_stops.add_tab_stop(TAB_LEFT_POS, WD_TAB_ALIGNMENT.LEFT)
    # Set hanging indent so wrapped lines align with position value
    p.paragraph_format.left_indent = TAB_LEFT_POS
    p.paragraph_format.first_line_indent = -TAB_LEFT_POS
    # Add tabbed position (both label and value bold)
    p.add_run("\t")
    label_run = p.add_run("Position:")
    label_run.bold = True
    p.add_run("\t")
    value_run = p.add_run(position)
    value_run.bold = True
    return p


def add_bullet_point(doc, text, level=0):
    """Add a bullet point line with proper hanging indent. Supports multiple levels."""
    p = doc.add_paragraph()

    # Different bullets for different levels
    bullets = ["•", "○", "-"]
    bullet_char = bullets[min(level, len(bullets) - 1)]

    # Indentation increases with level
    base_indent = Cm(0.6)
    level_indent = Cm(0.6 * level)

    p.paragraph_format.left_indent = base_indent + level_indent
    p.paragraph_format.first_line_indent = Cm(-0.4)
    p.add_run(f"{bullet_char}\t{text}")
    p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    return p


def add_nested_bullets(doc, bullet_item, level=0):
    """
    Recursively add bullets with nested structure.
    bullet_item can be:
    - A string (simple bullet)
    - A dict with 'text' and optional 'sub_bullets'
    """
    if isinstance(bullet_item, str):
        # Simple string bullet
        add_bullet_point(doc, bullet_item, level)
    elif isinstance(bullet_item, dict):
        # Nested bullet with potential sub-bullets
        text = bullet_item.get("text", "")
        if text:
            add_bullet_point(doc, text, level)

        # Process sub-bullets recursively
        sub_bullets = bullet_item.get("sub_bullets", [])
        for sub_item in sub_bullets:
            add_nested_bullets(doc, sub_item, level + 1)


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
  "right_to_work": "",
  "notice": "",
  "salary_expectations": "",
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
        "Simple bullet point as a string",
        {
          "text": "Main bullet point with sub-items",
          "sub_bullets": [
            "Sub-item 1",
            "Sub-item 2",
            {
              "text": "Sub-item with its own nested items",
              "sub_bullets": ["Nested item a", "Nested item b"]
            }
          ]
        }
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
- PRESERVE HIERARCHICAL BULLET STRUCTURE: If the CV has nested/indented bullets (sub-items under main bullets), use the nested format with "text" and "sub_bullets". If bullets are flat/simple, just use strings.
- NEVER infer or guess right_to_work, notice, or salary_expectations - ALWAYS leave these as empty strings "" unless EXPLICITLY stated in the CV
- "other_information" is OPTIONAL - only include if the CV has a section like Skills, Volunteering, Certifications, Languages, Interests, etc.
- If no such section exists, set "other_information" to an empty array []

Extract the CV data now:"""
