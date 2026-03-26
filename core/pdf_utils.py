"""
PDF generation utilities for shift reports.
Uses ReportLab to create receipt-style PDFs similar to Pick n Pay/Shoprite receipts.
"""
from datetime import datetime
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from reportlab.lib import colors
from reportlab.platypus import Table, TableStyle
from io import BytesIO


def generate_shift_pdf(shift):
    """
    Generate a receipt-style PDF for a shift report.
    The company name in the header is derived from the shift's contractor_workspace
    (if set), otherwise falls back to 'DI-VISION'.
    """
    # Determine company name from workspace
    company_name = 'DI-VISION'
    if getattr(shift, 'contractor_workspace', None) and shift.contractor_workspace:
        company_name = shift.contractor_workspace.name.upper()
    buffer = BytesIO()
    
    # Create PDF (A4 size, portrait)
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    
    # Receipt style: narrow margins, monospace feel
    left_margin = 30
    right_margin = width - 30
    y = height - 40  # Start from top
    
    # Helper function to draw text lines
    def draw_line(text, size=10, bold=False, center=False):
        nonlocal y
        if bold:
            c.setFont("Helvetica-Bold", size)
        else:
            c.setFont("Helvetica", size)
        
        if center:
            text_width = c.stringWidth(text, c._fontname, size)
            x = (width - text_width) / 2
        else:
            x = left_margin
        
        c.drawString(x, y, text)
        y -= size + 4
    
    def draw_separator(char="-"):
        nonlocal y
        c.setFont("Courier", 8)
        line = char * 80
        c.drawString(left_margin, y, line[:int((right_margin - left_margin) / 5)])
        y -= 10
    
    # ======= HEADER =======
    draw_line(company_name, size=14, bold=True, center=True)
    draw_line("Daily Drill Shift Report", size=11, center=True)
    draw_separator("=")
    y -= 5
    
    # ======= SHIFT INFO =======
    draw_line(f"Report ID: #{shift.id}", size=9)
    draw_line(f"Date: {shift.date.strftime('%Y-%m-%d')}", size=9)
    draw_line(f"Shift: {shift.get_shift_type_display()}", size=9)
    if shift.start_time and shift.end_time:
        draw_line(f"Time: {shift.start_time.strftime('%H:%M')} - {shift.end_time.strftime('%H:%M')}", size=9)
    draw_line(f"Rig: {shift.rig or 'N/A'}", size=9)
    draw_line(f"Location: {shift.location or 'N/A'}", size=9)
    if shift.client:
        draw_line(f"Client: {shift.client.name}", size=9)
    draw_line(f"Status: {shift.get_status_display()}", size=9, bold=True)
    draw_separator()
    
    # ======= CREW =======
    draw_line("CREW INFORMATION", size=10, bold=True)
    y -= 2
    if shift.supervisor_name:
        draw_line(f"Supervisor: {shift.supervisor_name}", size=9)
    if shift.driller_name:
        draw_line(f"Driller: {shift.driller_name}", size=9)
    helpers = [h for h in [shift.helper1_name, shift.helper2_name, shift.helper3_name, shift.helper4_name] if h]
    if helpers:
        draw_line(f"Helpers: {', '.join(helpers)}", size=9)
    draw_separator()
    
    # ======= DRILLING PROGRESS =======
    draw_line("DRILLING PROGRESS", size=10, bold=True)
    y -= 5
    
    progress_data = []
    total_meters = 0
    
    for prog in shift.progress.all():
        progress_data.append([
            prog.hole_number or "--",
            f"{prog.start_depth}m",
            f"{prog.end_depth}m",
            f"{prog.meters_drilled}m",
        ])
        total_meters += float(prog.meters_drilled or 0)
    
    if progress_data:
        c.setFont("Helvetica", 8)
        # Column headers
        draw_line("Hole    From    To      Meters", size=9)
        draw_separator("-")
        y -= 2
        
        for row in progress_data:
            line = f"{row[0]:<8}{row[1]:<8}{row[2]:<8}{row[3]}"
            draw_line(line, size=8)
        
        draw_separator("-")
        draw_line(f"TOTAL DRILLED: {total_meters:.2f} m", size=10, bold=True)
    else:
        draw_line("No drilling progress recorded", size=9)
    
    draw_separator()
    
    # ======= ACTIVITIES =======
    if shift.activities.exists():
        draw_line("ACTIVITIES & EVENTS", size=10, bold=True)
        y -= 5
        
        for activity in shift.activities.all()[:10]:  # Limit to 10 activities
            time_str = activity.timestamp.strftime('%H:%M') if activity.timestamp else '--:--'
            activity_line = f"{time_str} {activity.get_activity_type_display()}"
            draw_line(activity_line, size=8)
            if activity.description and len(activity.description) < 60:
                draw_line(f"  {activity.description[:60]}", size=7)
                y -= 2
        
        draw_separator()
    
    # ======= MATERIALS =======
    if shift.materials.exists():
        draw_line("MATERIALS USED", size=10, bold=True)
        y -= 5
        
        for material in shift.materials.all():
            mat_line = f"{material.material_name}: {material.quantity} {material.unit}"
            draw_line(mat_line, size=8)
        
        draw_separator()
    
    # ======= SURVEYS =======
    if shift.surveys.exists():
        draw_line("SURVEYS", size=10, bold=True)
        y -= 5
        
        for survey in shift.surveys.all():
            survey_line = f"{survey.depth}m - {survey.get_survey_type_display()}"
            draw_line(survey_line, size=8)
            survey_detail = f"  Dip: {survey.dip_angle}° | Az: {survey.azimuth}°"
            draw_line(survey_detail, size=7)
            y -= 2
        
        draw_separator()
    
    # ======= CASING =======
    if shift.casings.exists():
        draw_line("CASING INSTALLED", size=10, bold=True)
        y -= 5
        
        for casing in shift.casings.all():
            casing_line = f"{casing.casing_size} {casing.get_casing_type_display()}: {casing.start_depth}m to {casing.end_depth}m"
            draw_line(casing_line, size=8)
        
        draw_separator()
    
    # ======= STANDBY =======
    if shift.standby_client or shift.standby_constructor:
        draw_line("STANDBY INFORMATION", size=10, bold=True)
        y -= 5
        
        if shift.standby_client:
            draw_line(f"Client Standby: {shift.get_standby_client_reason_display()}", size=8)
            if shift.standby_client_remarks:
                draw_line(f"  {shift.standby_client_remarks[:60]}", size=7)
                y -= 2
        
        if shift.standby_constructor:
            draw_line(f"Constructor Standby: {shift.get_standby_constructor_reason_display()}", size=8)
            if shift.standby_constructor_remarks:
                draw_line(f"  {shift.standby_constructor_remarks[:60]}", size=7)
                y -= 2
        
        draw_separator()
    
    # ======= NOTES =======
    if shift.notes:
        draw_line("COMMENTS", size=10, bold=True)
        y -= 5
        # Wrap long notes
        notes_lines = shift.notes[:200].split('\n')  # Limit to 200 chars
        for line in notes_lines[:5]:  # Max 5 lines
            if line.strip():
                draw_line(line.strip()[:70], size=8)
        
        draw_separator()
    
    # ======= FOOTER =======
    y -= 10
    draw_separator("=")
    draw_line(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", size=8, center=True)
    draw_line("Powered by VEARVE Dev & RTC", size=7, center=True)
    draw_separator("=")
    
    # Finalize PDF
    c.showPage()
    c.save()
    
    buffer.seek(0)
    return buffer
