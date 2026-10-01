"""
CSV / Excel / PDF exports of querysets.

CSV needs nothing extra. Excel and PDF need the optional extras:
``pip install 'django-paystack-wallet[export]'`` (xlsxwriter + reportlab).
"""
import csv
import datetime
import io
from decimal import Decimal

from django.core.exceptions import ImproperlyConfigured
from django.http import HttpResponse
from django.utils import timezone
from djmoney.money import Money

from wallet.conf import wallet_settings

EXPORT_FORMATS = ('csv', 'xlsx', 'pdf')


def get_export_filename(prefix, extension):
    return f"{prefix}_{timezone.now().strftime('%Y%m%d_%H%M%S')}.{extension}"


def _header(queryset, fields):
    model_fields = {f.name: f for f in queryset.model._meta.fields}
    labels = []
    for field in fields:
        if field in model_fields:
            labels.append(str(model_fields[field].verbose_name).title())
        else:
            labels.append(field.replace('.', ' ').replace('_', ' ').title())
    return labels


def _value(obj, field):
    value = obj
    for attr in field.split('.'):
        if value is None:
            return None
        value = getattr(value, attr, None)
        if callable(value) and not isinstance(value, (Money, Decimal)):
            value = value()
    return value


def _as_text(value):
    if value is None:
        return ''
    if isinstance(value, datetime.datetime):
        if timezone.is_aware(value):
            value = timezone.localtime(value)
        return value.strftime('%Y-%m-%d %H:%M:%S')
    if isinstance(value, datetime.date):
        return value.strftime('%Y-%m-%d')
    if isinstance(value, Money):
        return f"{value.amount} {value.currency}"
    return str(value)


def export_queryset_to_csv(queryset, fields, filename_prefix='export'):
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="{get_export_filename(filename_prefix, "csv")}"'
    writer = csv.writer(response)
    writer.writerow(_header(queryset, fields))
    for obj in queryset.iterator() if hasattr(queryset, 'iterator') else queryset:
        writer.writerow([_as_text(_value(obj, field)) for field in fields])
    return response


def export_queryset_to_excel(queryset, fields, filename_prefix='export', sheet_name='Sheet1'):
    try:
        import xlsxwriter
    except ImportError as exc:
        raise ImproperlyConfigured("Excel export needs: pip install 'django-paystack-wallet[export]'") from exc

    output = io.BytesIO()
    workbook = xlsxwriter.Workbook(output, {'in_memory': True})
    worksheet = workbook.add_worksheet(sheet_name[:31])
    header_format = workbook.add_format({'bold': True, 'bg_color': '#f0f0f0', 'border': 1})
    datetime_format = workbook.add_format({'num_format': 'yyyy-mm-dd hh:mm:ss'})

    for col, label in enumerate(_header(queryset, fields)):
        worksheet.write(0, col, label, header_format)
        worksheet.set_column(col, col, 18)

    for row, obj in enumerate(queryset, start=1):
        for col, field in enumerate(fields):
            value = _value(obj, field)
            if isinstance(value, datetime.datetime):
                if timezone.is_aware(value):
                    value = timezone.make_naive(value)
                worksheet.write_datetime(row, col, value, datetime_format)
            elif isinstance(value, Money):
                worksheet.write_number(row, col, float(value.amount))
            elif isinstance(value, (int, float, Decimal)) and not isinstance(value, bool):
                worksheet.write_number(row, col, float(value))
            else:
                worksheet.write(row, col, _as_text(value))
    workbook.close()

    response = HttpResponse(
        output.getvalue(), content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )
    response['Content-Disposition'] = f'attachment; filename="{get_export_filename(filename_prefix, "xlsx")}"'
    return response


def export_queryset_to_pdf(queryset, fields, filename_prefix='export', title=None):
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4, landscape, letter
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    except ImportError as exc:
        raise ImproperlyConfigured("PDF export needs: pip install 'django-paystack-wallet[export]'") from exc

    page_size = A4 if wallet_settings.EXPORT_PAGESIZE == 'A4' else letter
    if wallet_settings.EXPORT_ORIENTATION == 'landscape':
        page_size = landscape(page_size)

    buffer = io.BytesIO()
    document = SimpleDocTemplate(buffer, pagesize=page_size, rightMargin=36, leftMargin=36, topMargin=36,
                                 bottomMargin=36)
    styles = getSampleStyleSheet()
    elements = []
    if title:
        elements += [Paragraph(str(title), styles['Heading1']), Spacer(1, 12)]

    data = [_header(queryset, fields)]
    data += [[_as_text(_value(obj, field)) for field in fields] for obj in queryset]
    table = Table(data, repeatRows=1)
    style = TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 8),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
    ])
    for row in range(2, len(data), 2):
        style.add('BACKGROUND', (0, row), (-1, row), colors.whitesmoke)
    table.setStyle(style)
    elements.append(table)
    document.build(elements)

    response = HttpResponse(buffer.getvalue(), content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{get_export_filename(filename_prefix, "pdf")}"'
    return response


def export_queryset(queryset, fields, export_format='csv', filename_prefix='export', title=None):
    """Dispatch to the right exporter. Raises ValueError for unknown formats."""
    if export_format == 'csv':
        return export_queryset_to_csv(queryset, fields, filename_prefix)
    if export_format == 'xlsx':
        return export_queryset_to_excel(queryset, fields, filename_prefix, sheet_name=title or 'Export')
    if export_format == 'pdf':
        return export_queryset_to_pdf(queryset, fields, filename_prefix, title=title)
    raise ValueError(f"Unsupported export format '{export_format}'. Use one of {', '.join(EXPORT_FORMATS)}")
