"""
CV Generator - Creates Meraki-formatted Word documents from structured CV data.
Uses the Meraki template to preserve logo, branding, and formatting.
"""
import io
import json
import os
import copy
from docx import Document
from docx.shared import Pt, RGBColor
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

# Template path
TEMPLATE_PATH = os.path.join(os.path.dirname(__file__), "templates", "Meraki_CV_Template.docx")

# Brand colors from template
HEADER_COLOR = RGBColor(0x1B, 0x46, 0x77)  # Blue headers
BULLET_COLOR = RGBColor(0xEC, 0x00, 0x8C)  # Pink bullets


def create_meraki_cv(cv_data: dict) -> bytes:
    """
    Generate a Meraki-formatted CV Word document from structured data.
    Uses the template to preserve logo and branding.
    """
    doc = Document(TEMPLATE_PATH)

    # Clear all paragraphs except the first (logo) and rebuild
    # Keep track of logo paragraph
    logo_para = doc.paragraphs[0]

    # Remove all paragraphs after the logo
    for para in doc.paragraphs[1:]:
        p = para._element
        p.getparent().remove(p)

    # Add a blank line after logo
    doc.add_paragraph()

    # === PERSONAL DETAILS ===
    add_section_header(doc, "Personal Details")
    add_field_line(doc, "Name", cv_data.get("name", ""))
    add_field_line(doc, "Location", cv_data.get("location", ""))
    add_field_line(doc, "Right to Work", "")  # Left blank
    add_field_line(doc, "Notice", "")  # Left blank
    doc.add_paragraph()

    # === CANDIDATE PROFILE ===
    add_section_header(doc, "Candidate Profile")
    profile = cv_data.get("profile", "")
    if profile:
        doc.add_paragraph(profile)
    doc.add_paragraph()

    # === EDUCATION ===
    education = cv_data.get("education", [])
    if education:
        add_section_header(doc, "Education")
        for edu in education:
            dates = edu.get("dates", "")
            institution = edu.get("institution", "")
            location = edu.get("location", "")
            title = edu.get("title", "")

            # Date and institution line
            inst_text = institution
            if location:
                inst_text += f", {location}"
            add_date_entry_line(doc, dates, inst_text)

            # Course title
            if title:
                p = doc.add_paragraph(title)
                p.paragraph_format.left_indent = Pt(36)

            # Details as bullets
            for detail in edu.get("details", []):
                add_bullet_point(doc, detail)

        doc.add_paragraph()

    # === WORK EXPERIENCE ===
    work_exp = cv_data.get("work_experience", [])
    if work_exp:
        add_section_header(doc, "Work Experience")
        for job in work_exp:
            dates = job.get("dates", "")
            company = job.get("company", "")
            location = job.get("location", "")
            position = job.get("position", "")

            # Date and company line
            company_text = company
            if location:
                company_text += f", {location}"
            add_date_entry_line(doc, dates, company_text)

            # Position line
            if position:
                p = doc.add_paragraph()
                run = p.add_run("Position: ")
                run.bold = True
                p.add_run(position)

            # Bullet points
            for bullet in job.get("bullets", []):
                add_bullet_point(doc, bullet)

            doc.add_paragraph()  # Space between jobs

    # === CONSULTANT CONTACT DETAILS ===
    add_section_header(doc, "Consultant Contact Details")
    add_field_line(doc, "Name", "")  # Left blank
    add_field_line(doc, "Tel", "")  # Left blank

    # Save to bytes
    buffer = io.BytesIO()
    doc.save(buffer)
    buffer.seek(0)
    return buffer.getvalue()


def add_section_header(doc, text):
    """Add a blue bold section header."""
    p = doc.add_paragraph()
    run = p.add_run(text)
    run.bold = True
    run.font.color.rgb = HEADER_COLOR
    run.font.size = Pt(11)
    return p


def add_field_line(doc, label, value):
    """Add a field line with bold label and optional value."""
    p = doc.add_paragraph()
    label_run = p.add_run(f"{label}\t")
    label_run.bold = True
    if value:
        p.add_run(value)
    return p


def add_date_entry_line(doc, dates, text):
    """Add a date/entry line (e.g., 'Jan 23\tCompany Name')."""
    p = doc.add_paragraph()
    if dates:
        date_run = p.add_run(f"{dates}\t")
        date_run.bold = True
    p.add_run(text)
    return p


def add_bullet_point(doc, text):
    """Add a bullet point with pink bullet character."""
    p = doc.add_paragraph()
    # Add pink bullet
    bullet_run = p.add_run("• ")
    bullet_run.font.color.rgb = BULLET_COLOR
    # Add text
    p.add_run(text)
    p.paragraph_format.left_indent = Pt(18)
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

REQUIRED JSON STRUCTURE:
{
  "name": "Full Name",
  "location": "City, Country",
  "profile": "FULL profile/summary paragraph exactly as written",
  "education": [
    {
      "dates": "2019 - 2023",
      "title": "Degree/Qualification name",
      "institution": "University/School name",
      "location": "City",
      "details": []
    }
  ],
  "work_experience": [
    {
      "dates": "Jan 23 - Present",
      "company": "Company Name",
      "location": "City",
      "position": "Job Title",
      "bullets": [
        "Full original bullet point text",
        "Another bullet with complete wording"
      ]
    }
  ]
}

IMPORTANT:
- Extract ALL roles from the CV
- Include ALL bullet points from each role
- Do NOT add skills/certifications sections
- Preserve original wording

Extract the CV data now:"""
