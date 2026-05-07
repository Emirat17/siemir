from xhtml2pdf import pisa
import io

def generate_pdf(html_string):
    """Konversi HTML ke bytes PDF menggunakan xhtml2pdf."""
    buffer = io.BytesIO()
    pisa.CreatePDF(io.StringIO(html_string), dest=buffer)
    return buffer.getvalue()
