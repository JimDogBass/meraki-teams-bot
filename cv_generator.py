"""
CV Generator - Creates Meraki-formatted Word documents from structured CV data.
"""
import io
import json
from docx import Document
from docx.shared import Pt, Inches, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.style import WD_STYLE_TYPE


def create_meraki_cv(cv_data: dict) -> bytes:
    """
    Generate a Meraki-formatted CV Word document from structured data.

    Args:
        cv_data: Dictionary containing extracted CV information

    Returns:
        bytes: The Word document as bytes
    """
    doc = Document()

    # Set up styles
    style = doc.styles['Normal']
    style.font.name = 'Calibri'
    style.font.size = Pt(11)

    # Add header styling function
    def add_section_header(text):
        p = doc.add_paragraph()
        run = p.add_run(text)
        run.bold = True
        run.font.size = Pt(12)
        run.font.color.rgb = RGBColor(0, 112, 192)  # Blue color like template
        p.space_after = Pt(6)
        return p

    def add_field_line(label, value=""):
        p = doc.add_paragraph()
        label_run = p.add_run(f"{label}\t")
        label_run.bold = True
        if value:
            p.add_run(value)
        return p

    def add_bullet(text):
        p = doc.add_paragraph(style='List Bullet')
        p.add_run(text)
        p.paragraph_format.left_indent = Inches(0.25)
        return p

    # === PERSONAL DETAILS ===
    add_section_header("Personal Details")
    add_field_line("Name", cv_data.get("name", ""))
    add_field_line("Location", cv_data.get("location", ""))
    add_field_line("Right to Work", "")  # Left blank for consultant
    add_field_line("Notice", "")  # Left blank for consultant

    doc.add_paragraph()  # Spacing

    # === CANDIDATE PROFILE ===
    add_section_header("Candidate Profile")
    profile = cv_data.get("profile", "")
    if profile:
        p = doc.add_paragraph(profile)
        p.paragraph_format.space_after = Pt(12)

    # === EDUCATION ===
    education = cv_data.get("education", [])
    if education:
        add_section_header("Education")
        for edu in education:
            # Date and title line
            p = doc.add_paragraph()
            dates = edu.get("dates", "")
            title = edu.get("title", "")
            institution = edu.get("institution", "")
            location = edu.get("location", "")

            if dates:
                date_run = p.add_run(f"{dates}\t\t")
                date_run.bold = False

            if institution:
                p.add_run(f"{institution}")
                if location:
                    p.add_run(f", {location}")

            # Course/degree title
            if title:
                p2 = doc.add_paragraph(title)
                p2.paragraph_format.left_indent = Inches(0.5)

            # Additional details as bullets
            details = edu.get("details", [])
            for detail in details:
                add_bullet(detail)

        doc.add_paragraph()  # Spacing

    # === WORK EXPERIENCE ===
    work_exp = cv_data.get("work_experience", [])
    if work_exp:
        add_section_header("Work Experience")
        for job in work_exp:
            # Date and company line
            p = doc.add_paragraph()
            dates = job.get("dates", "")
            company = job.get("company", "")
            location = job.get("location", "")

            if dates:
                date_run = p.add_run(f"{dates}\t")

            company_text = company
            if location:
                company_text += f", {location}"
            if company_text:
                p.add_run(company_text)

            # Position line
            position = job.get("position", "")
            if position:
                p2 = doc.add_paragraph()
                p2.add_run("Position:\t").bold = True
                p2.add_run(position)

            # Bullet points
            bullets = job.get("bullets", [])
            for bullet in bullets:
                add_bullet(bullet)

            doc.add_paragraph()  # Spacing between jobs

    # === OTHER INFORMATION / SKILLS ===
    skills = cv_data.get("skills", {})
    other_info = cv_data.get("other_information", {})

    # Combine skills sections
    has_other = False

    # Technical skills
    tech_skills = skills.get("technical", []) or other_info.get("technical_skills", [])
    soft_skills = skills.get("soft", []) or other_info.get("soft_skills", [])
    certifications = other_info.get("certifications", [])
    languages = other_info.get("languages", [])

    if tech_skills or soft_skills or certifications or languages:
        add_section_header("Other Information")
        has_other = True

        if tech_skills:
            p = doc.add_paragraph()
            p.add_run("Technical Skills").bold = True
            for skill in tech_skills:
                add_bullet(skill)

        if soft_skills:
            p = doc.add_paragraph()
            p.add_run("Soft Skills").bold = True
            for skill in soft_skills:
                add_bullet(skill)

        if languages:
            p = doc.add_paragraph()
            p.add_run("Languages").bold = True
            for lang in languages:
                add_bullet(lang)

        if certifications:
            p = doc.add_paragraph()
            p.add_run("Certifications").bold = True
            for cert in certifications:
                add_bullet(cert)

    # Skillset section (alternative format from some CVs)
    skillset = cv_data.get("skillset", {})
    if skillset and not has_other:
        add_section_header("Skillset")
        business_skills = skillset.get("business", [])
        technical = skillset.get("technical", [])

        if business_skills:
            p = doc.add_paragraph()
            p.add_run("Business & Leadership Skills: ").bold = True
            p.add_run(", ".join(business_skills))

        if technical:
            p = doc.add_paragraph()
            p.add_run("Technical Skills: ").bold = True
            p.add_run(", ".join(technical))

    doc.add_paragraph()  # Spacing

    # === CONSULTANT CONTACT DETAILS ===
    add_section_header("Consultant Contact Details")
    add_field_line("Name", "")  # Left blank for consultant
    add_field_line("Tel", "")  # Left blank for consultant

    # Save to bytes
    buffer = io.BytesIO()
    doc.save(buffer)
    buffer.seek(0)
    return buffer.getvalue()


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


# System prompt for CV extraction
CV_EXTRACTION_PROMPT = """You are a CV data extraction assistant. Extract structured information from the provided CV and return it as valid JSON.

IMPORTANT RULES:
1. Return ONLY valid JSON - no explanations, no markdown, just the JSON object
2. Extract actual content from the CV - do not make up information
3. Keep bullet points concise but informative
4. Dates should be in format like "Jan 2023 - Present" or "2019 - 2023"
5. For profile/summary, use the candidate's own words or create a professional summary based on their experience

REQUIRED JSON STRUCTURE:
{
  "name": "Full Name",
  "location": "City, Country",
  "profile": "Professional summary paragraph",
  "education": [
    {
      "dates": "Start - End",
      "title": "Degree/Qualification name",
      "institution": "University/School name",
      "location": "City",
      "details": ["Grade/GPA if notable", "Honours/Awards"]
    }
  ],
  "work_experience": [
    {
      "dates": "Start - End",
      "company": "Company Name",
      "location": "City",
      "position": "Job Title",
      "bullets": [
        "Key achievement or responsibility",
        "Another achievement with metrics if available"
      ]
    }
  ],
  "skills": {
    "technical": ["Skill 1", "Skill 2"],
    "soft": ["Skill 1", "Skill 2"]
  },
  "other_information": {
    "languages": ["English - Native", "Spanish - Fluent"],
    "certifications": ["Certification 1", "Certification 2"]
  }
}

NOTES:
- List work experience in reverse chronological order (most recent first)
- Include 3-5 bullet points per role, focusing on achievements and impact
- If the CV has a skillset/competencies section, include those appropriately
- Extract languages if mentioned
- Keep the profile to 2-4 sentences maximum

Now extract the CV data:"""
