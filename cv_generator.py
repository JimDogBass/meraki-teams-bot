"""
CV Generator - Creates Meraki-formatted Word documents from structured CV data.
Builds document from scratch with logo in body (not header) to avoid greyed-out appearance.
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


def create_meraki_cv(cv_data: dict) -> bytes:
    """
    Generate a Meraki-formatted CV Word document from structured data.
    Builds document from scratch with logo in body (not header).
    """
    # Create new blank document
    doc = Document()

    # Set default font to Aptos 11pt
    style = doc.styles['Normal']
    style.font.name = 'Aptos'
    style.font.size = Pt(11)

    # === ADD LOGO (in body, not header) ===
    if os.path.exists(LOGO_PATH):
        logo_para = doc.add_paragraph()
        logo_run = logo_para.add_run()
        logo_run.add_picture(LOGO_PATH, width=Inches(2.5))
        doc.add_paragraph()  # Blank line after logo

    # === PERSONAL DETAILS ===
    add_section_header(doc, "PERSONAL DETAILS")
    doc.add_paragraph()
    add_field_line(doc, "Name", cv_data.get("name", ""))
    add_field_line(doc, "Location", cv_data.get("location", ""))
    add_field_line(doc, "Right to Work", cv_data.get("right_to_work", ""))
    add_field_line(doc, "Notice", cv_data.get("notice", ""))
    salary = cv_data.get("salary_expectations", "")
    if salary:
        add_field_line(doc, "Salary expectations", salary)
    doc.add_paragraph()

    # === EDUCATION ===
    education = cv_data.get("education", [])
    if education:
        add_section_header(doc, "EDUCATION")
        doc.add_paragraph()
        for edu in education:
            dates = edu.get("dates", "")
            institution = edu.get("institution", "")
            title = edu.get("title", "")
            details = edu.get("details", [])

            # Date and qualification line
            add_tabbed_line(doc, dates, title)

            # Institution on next line (indented)
            if institution:
                add_indented_line(doc, institution)

            # Additional details
            for detail in details:
                add_indented_line(doc, detail)

        doc.add_paragraph()

    # === CANDIDATE PROFILE ===
    add_section_header(doc, "CANDIDATE PROFILE")
    doc.add_paragraph()
    profile = cv_data.get("profile", "")
    if profile:
        # Split profile into paragraphs if it contains double newlines
        paragraphs = profile.split('\n\n') if '\n\n' in profile else [profile]
        for para_text in paragraphs:
            p = doc.add_paragraph(para_text.strip())
            p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    doc.add_paragraph()

    # === WORK EXPERIENCE ===
    work_exp = cv_data.get("work_experience", [])
    if work_exp:
        add_section_header(doc, "WORK EXPERIENCE")
        doc.add_paragraph()
        for job in work_exp:
            dates = job.get("dates", "")
            company = job.get("company", "")
            position = job.get("position", "")

            # Date and company line
            add_tabbed_line(doc, dates, company)

            # Position line
            if position:
                add_position_line(doc, position)

            # Bullet points as plain text (no bullets in this format)
            for bullet in job.get("bullets", []):
                p = doc.add_paragraph(bullet)
                p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY

            doc.add_paragraph()  # Space between jobs

    # === OTHER INFORMATION (only if present) ===
    other_info = cv_data.get("other_information", [])
    if other_info:
        add_section_header(doc, "OTHER INFORMATION")
        doc.add_paragraph()
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
            if isinstance(content, list):
                p = doc.add_paragraph()
                p.add_run('\n'.join(content))
            else:
                p = doc.add_paragraph(str(content))
        doc.add_paragraph()

    # Save to bytes
    buffer = io.BytesIO()
    doc.save(buffer)
    buffer.seek(0)
    return buffer.getvalue()


def add_section_header(doc, text):
    """Add a bold section header (uppercase, no color)."""
    p = doc.add_paragraph()
    run = p.add_run(text)
    run.bold = True
    run.font.name = 'Aptos'
    run.font.size = Pt(11)
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


def add_tabbed_line(doc, left_text, right_text):
    """Add a line with tab-separated content (e.g., '\t2019\tMA Event Design')."""
    p = doc.add_paragraph()
    # Set up tab stops
    tab_stops = p.paragraph_format.tab_stops
    tab_stops.add_tab_stop(TAB_RIGHT_POS, WD_TAB_ALIGNMENT.RIGHT)
    tab_stops.add_tab_stop(TAB_LEFT_POS, WD_TAB_ALIGNMENT.LEFT)
    # Add tabbed content
    p.add_run(f"\t{left_text}\t{right_text}")
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
