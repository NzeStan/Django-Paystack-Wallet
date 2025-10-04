import io
import csv
import datetime
import xlsxwriter
from django.http import HttpResponse
from django.utils.translation import gettext_lazy as _
from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter, A4, landscape
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet
from wallet.settings import get_wallet_setting


def get_export_filename(prefix, extension):
    """
    Generate a filename for export with timestamp
    
    Args:
        prefix (str): Prefix for the filename
        extension (str): File extension
        
    Returns:
        str: Export filename
    """
    timestamp = timezone.now().strftime('%Y%m%d_%H%M%S')
    return f"{prefix}_{timestamp}.{extension}"


def export_queryset_to_csv(queryset, fields, filename_prefix='export'):
    """
    Export a queryset to CSV
    
    Args:
        queryset: Django queryset to export
        fields (list): List of field names to export
        filename_prefix (str): Prefix for the export filename
        
    Returns:
        HttpResponse: CSV response for download
    """
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="{get_export_filename(filename_prefix, "csv")}"'
    
    writer = csv.writer(response)
    
    # Write header row
    header = [queryset.model._meta.get_field(field).verbose_name.title() 
              if field in [f.name for f in queryset.model._meta.fields] 
              else field.replace('_', ' ').title() 
              for field in fields]
    writer.writerow(header)
    
    # Write data rows
    for obj in queryset:
        row = []
        for field in fields:
            # Handle nested attributes using dots (e.g. 'wallet.user.email')
            if '.' in field:
                value = obj
                for attr in field.split('.'):
                    if value is None:
                        break
                    value = getattr(value, attr, None)
            else:
                value = getattr(obj, field, None)
                
            # Format dates and datetimes
            if isinstance(value, datetime.datetime):
                value = value.strftime('%Y-%m-%d %H:%M:%S')
            elif isinstance(value, datetime.date):
                value = value.strftime('%Y-%m-%d')
                
            row.append(str(value) if value is not None else '')
        writer.writerow(row)
    
    return response


def export_queryset_to_excel(queryset, fields, filename_prefix='export', sheet_name='Sheet1'):
    """
    Export a queryset to Excel
    
    Args:
        queryset: Django queryset to export
        fields (list): List of field names to export
        filename_prefix (str): Prefix for the export filename
        sheet_name (str): Name of the Excel sheet
        
    Returns:
        HttpResponse: Excel response for download
    """
    output = io.BytesIO()
    workbook = xlsxwriter.Workbook(output)
    worksheet = workbook.add_worksheet(sheet_name)
    
    # Add header row
    header = [queryset.model._meta.get_field(field).verbose_name.title() 
              if field in [f.name for f in queryset.model._meta.fields] 
              else field.replace('_', ' ').title() 
              for field in fields]
    
    # Add some formatting
    header_format = workbook.add_format({
        'bold': True,
        'bg_color': '#f0f0f0',
        'border': 1
    })
    
    date_format = workbook.add_format({'num_format': 'yyyy-mm-dd'})
    datetime_format = workbook.add_format({'num_format': 'yyyy-mm-dd hh:mm:ss'})
    
    # Write header row
    for col, field_name in enumerate(header):
        worksheet.write(0, col, field_name, header_format)
    
    # Write data rows
    for row_idx, obj in enumerate(queryset, start=1):
        for col_idx, field in enumerate(fields):
            # Handle nested attributes using dots (e.g. 'wallet.user.email')
            if '.' in field:
                value = obj
                for attr in field.split('.'):
                    if value is None:
                        break
                    value = getattr(value, attr, None)
            else:
                value = getattr(obj, field, None)
                
            # Format based on value type
            if isinstance(value, datetime.datetime):
                worksheet.write_datetime(row_idx, col_idx, value, datetime_format)
            elif isinstance(value, datetime.date):
                worksheet.write_datetime(row_idx, col_idx, value, date_format)
            elif value is None:
                worksheet.write(row_idx, col_idx, '')
            else:
                worksheet.write(row_idx, col_idx, value)
    
    # Auto-adjust column widths
    for col_idx, _ in enumerate(fields):
        worksheet.set_column(col_idx, col_idx, 15)
    
    workbook.close()
    
    # Create response
    output.seek(0)
    response = HttpResponse(
        output.read(),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response['Content-Disposition'] = f'attachment; filename="{get_export_filename(filename_prefix, "xlsx")}"'
    
    return response


def export_queryset_to_pdf(queryset, fields, filename_prefix='export', title=None):
    """
    Export a queryset to PDF
    
    Args:
        queryset: Django queryset to export
        fields (list): List of field names to export
        filename_prefix (str): Prefix for the export filename
        title (str): Title for the PDF document
        
    Returns:
        HttpResponse: PDF response for download
    """
    # Create a file-like buffer to receive PDF data
    buffer = io.BytesIO()
    
    # Get page size settings
    page_size_name = get_wallet_setting('EXPORT_PAGESIZE')
    page_orientation = get_wallet_setting('EXPORT_ORIENTATION')
    
    # Set page size
    if page_size_name == 'A4':
        page_size = A4
    else:
        page_size = letter
        
    # Set orientation
    if page_orientation == 'landscape':
        page_size = landscape(page_size)
    
    # Create the PDF object
    pdf = SimpleDocTemplate(
        buffer,
        pagesize=page_size,
        rightMargin=72,
        leftMargin=72,
        topMargin=72,
        bottomMargin=72
    )
    
    # Get styles
    styles = getSampleStyleSheet()
    title_style = styles['Heading1']
    normal_style = styles['Normal']
    
    # Create the PDF content
    elements = []
    
    # Add title if provided
    if title:
        elements.append(Paragraph(title, title_style))
        elements.append(Spacer(1, 12))
    
    # Generate header row
    header = [queryset.model._meta.get_field(field).verbose_name.title() 
              if field in [f.name for f in queryset.model._meta.fields] 
              else field.replace('_', ' ').title() 
              for field in fields]
    
    # Prepare data for table
    data = [header]
    
    # Add data rows
    for obj in queryset:
        row = []
        for field in fields:
            # Handle nested attributes using dots (e.g. 'wallet.user.email')
            if '.' in field:
                value = obj
                for attr in field.split('.'):
                    if value is None:
                        break
                    value = getattr(value, attr, None)
            else:
                value = getattr(obj, field, None)
                
            # Format dates and datetimes
            if isinstance(value, datetime.datetime):
                value = value.strftime('%Y-%m-%d %H:%M:%S')
            elif isinstance(value, datetime.date):
                value = value.strftime('%Y-%m-%d')
            
            row.append(str(value) if value is not None else '')
        data.append(row)
    
    # Create table
    table = Table(data)
    
    # Add style to table
    style = TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 10),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
        ('TEXTCOLOR', (0, 1), (-1, -1), colors.black),
        ('ALIGN', (0, 1), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 1), (-1, -1), 8),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
    ])
    
    # Add alternating row colors
    for row in range(1, len(data)):
        if row % 2 == 0:
            style.add('BACKGROUND', (0, row), (-1, row), colors.whitesmoke)
    
    table.setStyle(style)
    elements.append(table)
    
    # Build the PDF
    pdf.build(elements)
    
    # Get the value of the BytesIO buffer
    pdf_data = buffer.getvalue()
    buffer.close()
    
    # Create response
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{get_export_filename(filename_prefix, "pdf")}"'
    response.write(pdf_data)
    
    return response