"""Read and write the XLSX cells and presentation used by comparison reports."""
from contextlib import contextmanager
from dataclasses import dataclass, field
from itertools import islice
import math
from pathlib import Path
import posixpath
import re
from tempfile import NamedTemporaryFile
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape, quoteattr
from zipfile import ZIP_DEFLATED, ZipFile


MAIN = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
OFFICE = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
PACKAGE = 'http://schemas.openxmlformats.org/package/2006/relationships'
TYPES = 'http://schemas.openxmlformats.org/package/2006/content-types'
CONTENT = 'application/vnd.openxmlformats-officedocument.spreadsheetml'
CONTROL = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\ufffe\uffff]|_x[0-9a-fA-F]{4}_')
CELL_ESCAPE = re.compile(r'_x([0-9a-fA-F]{4})_')
CELL_COL = re.compile(r'^[A-Z]+')

HEADER_STYLE = 1
DATA_STYLE = 2
STRIPED_STYLE = 3
RAW_HEADER_STYLE = 4


@dataclass
class Sheet:
    rows: list = field(default_factory=list)
    row_styles: dict = field(default_factory=dict)
    widths: dict = field(default_factory=dict)
    freeze: tuple = (0, 0)  # Number of frozen rows and columns.
    auto_filter: bool = False

    def iter_rows(self, max_row=None):
        return islice(self.rows, max_row)


def column_name(index):
    result = ''
    while index:
        index, remainder = divmod(index - 1, 26)
        result = chr(65 + remainder) + result
    return result


def column_number(reference):
    match = CELL_COL.match(reference)
    index = 0
    if match:
        for letter in match[0]:
            index = index * 26 + ord(letter) - 64
    return index


def _namespace(node):
    return node.tag.rsplit('}', 1)[0] + '}' if '}' in node.tag else ''


def _text(node, namespace):
    parts = node.findall(f'{namespace}t') + node.findall(f'{namespace}r/{namespace}t')
    return CELL_ESCAPE.sub(lambda match: chr(int(match[1], 16)), ''.join(p.text or '' for p in parts))


def _target(parent, target):
    if target.startswith('/'):
        return target.lstrip('/')
    return posixpath.normpath(posixpath.join(posixpath.dirname(parent), target))


def _cell_value(cell, ns, shared):
    kind = cell.get('t', 'n')
    if kind == 'inlineStr':
        value = cell.find(f'{ns}is')
        return _text(value, ns) if value is not None else None
    value = cell.findtext(f'{ns}v')
    if value in (None, ''):
        return None
    if kind == 's':
        return shared[int(value)]
    if kind == 'b':
        return value == '1'
    if kind == 'n':
        return float(value) if any(c in value for c in '.eE') else int(value)
    return value


@dataclass
class _ReadSheet:
    archive: ZipFile
    location: str
    shared: list

    def iter_rows(self, max_row=None):
        if max_row == 0:
            return
        with self.archive.open(self.location) as stream:
            events = ET.iterparse(stream, events=('start', 'end'))
            _, root = next(events)
            ns = _namespace(root)
            width = row_number = 0
            data = None
            for event, node in events:
                if node.tag == f'{ns}dimension' and event == 'end':
                    width = column_number(node.get('ref', '').split(':')[-1])
                elif node.tag == f'{ns}sheetData':
                    if event == 'end':
                        break
                    data = node
                elif node.tag == f'{ns}row' and event == 'end' and data is not None:
                    index = int(node.get('r', row_number + 1))
                    for row_number in range(row_number + 1, index):
                        if max_row is not None and row_number > max_row:
                            return
                        yield (None,) * max(width, 1)
                    if max_row is not None and index > max_row:
                        return
                    row = []
                    for cell in node.findall(f'{ns}c'):
                        col = column_number(cell.get('r', '')) or len(row) + 1
                        row.extend([None] * (col - len(row)))
                        row[col - 1] = _cell_value(cell, ns, self.shared)
                    width = max(width, len(row))
                    data.remove(node)
                    row_number = index
                    yield tuple(row) + (None,) * (max(width, 1) - len(row))


@contextmanager
def open_workbook(path):
    """Open comparison workbooks lazily, including native Excel shared strings."""
    if path is None:
        yield {}
        return
    with ZipFile(path) as archive:
        root_rels = ET.fromstring(archive.read('_rels/.rels'))
        book_path = _target('', next(r.get('Target') for r in root_rels
                                     if r.get('Type', '').endswith('/officeDocument')))
        rels_path = posixpath.join(posixpath.dirname(book_path), '_rels',
                                  posixpath.basename(book_path) + '.rels')
        rels = ET.fromstring(archive.read(rels_path))
        targets = {r.get('Id'): _target(book_path, r.get('Target')) for r in rels}
        shared_path = next((targets[r.get('Id')] for r in rels
                            if r.get('Type', '').endswith('/sharedStrings')), None)
        shared = []
        if shared_path:
            strings = ET.fromstring(archive.read(shared_path))
            ns = _namespace(strings)
            shared = [_text(item, ns) for item in strings.findall(f'{ns}si')]
        root = ET.fromstring(archive.read(book_path))
        ns = _namespace(root)
        workbook = {}
        for sheet in root.findall(f'{ns}sheets/{ns}sheet'):
            # Support both Transitional and Strict OOXML relationship namespaces.
            rel_id = next(value for key, value in sheet.attrib.items() if key.endswith('}id'))
            workbook[sheet.get('name')] = _ReadSheet(archive, targets[rel_id], shared)
        yield workbook


def _rels(entries):
    parts = [f'<Relationships xmlns="{PACKAGE}">']
    for rel_id, kind, target in entries:
        parts.append(f'<Relationship Id="{rel_id}" Type="{OFFICE}/{kind}" Target="{target}"/>')
    return ''.join(parts) + '</Relationships>'


STYLES = f'''<styleSheet xmlns="{MAIN}">
<fonts count="4">
<font><sz val="11"/><name val="Calibri"/></font>
<font><b/><sz val="11"/><color rgb="FFFFFFFF"/><name val="Arial"/></font>
<font><sz val="11"/><name val="Arial"/></font>
<font><b/><sz val="11"/><name val="Calibri"/></font>
</fonts>
<fills count="4">
<fill><patternFill patternType="none"/></fill>
<fill><patternFill patternType="gray125"/></fill>
<fill><patternFill patternType="solid"><fgColor rgb="FF7C3AED"/><bgColor indexed="64"/></patternFill></fill>
<fill><patternFill patternType="solid"><fgColor rgb="FFF6F7F9"/><bgColor indexed="64"/></patternFill></fill>
</fills>
<borders count="3"><border/><border>
{''.join(f'<{edge} style="thin"><color rgb="FFE2E5EA"/></{edge}>' for edge in ('left','right','top','bottom'))}
</border><border>{''.join(f'<{edge} style="thin"/>' for edge in ('left','right','top','bottom'))}</border></borders>
<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
<cellXfs count="5">
<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>
<xf numFmtId="0" fontId="1" fillId="2" borderId="1" xfId="0" applyAlignment="1"><alignment horizontal="center" vertical="center" wrapText="1"/></xf>
<xf numFmtId="0" fontId="2" fillId="0" borderId="1" xfId="0" applyAlignment="1"><alignment horizontal="left" vertical="center" wrapText="1"/></xf>
<xf numFmtId="0" fontId="2" fillId="3" borderId="1" xfId="0" applyAlignment="1"><alignment horizontal="left" vertical="center" wrapText="1"/></xf>
<xf numFmtId="0" fontId="3" fillId="0" borderId="2" xfId="0" applyAlignment="1"><alignment horizontal="center" vertical="top"/></xf>
</cellXfs>
<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>
</styleSheet>'''


def _encoded_text(value):
    value = CONTROL.sub(lambda m: '_x005F_' + m[0][1:] if len(m[0]) > 1
                        else f'_x{ord(m[0]):04X}_', value[:32767])
    return escape(value, {'\r': '&#13;'})


def _cell(reference, value, style):
    attrs = f'r="{reference}"' + (f' s="{style}"' if style else '')
    if value is None or value == '':
        return f'<c {attrs}/>' if style else ''
    if isinstance(value, bool):
        return f'<c {attrs} t="b"><v>{int(value)}</v></c>'
    if isinstance(value, int):
        return f'<c {attrs}><v>{value}</v></c>'
    if isinstance(value, float):
        if math.isfinite(value):
            return f'<c {attrs}><v>{value:.16g}</v></c>'
        if math.isnan(value):
            return f'<c {attrs}/>' if style else ''
    text = _encoded_text(str(value))
    return f'<c {attrs} t="inlineStr"><is><t xml:space="preserve">{text}</t></is></c>'


def _pane(rows, cols):
    position = f'{column_name(cols + 1)}{rows + 1}'
    active = 'bottomRight' if rows and cols else 'bottomLeft' if rows else 'topRight'
    split = (f' xSplit="{cols}"' if cols else '') + (f' ySplit="{rows}"' if rows else '')
    return (f'<sheetViews><sheetView workbookViewId="0">'
            f'<pane{split} topLeftCell="{position}" activePane="{active}" state="frozen"/>'
            f'<selection pane="{active}" activeCell="{position}" sqref="{position}"/>'
            '</sheetView></sheetViews>')


def _sheet_xml(sheet):
    max_col = max(map(len, sheet.rows), default=0)
    extent = f'A1:{column_name(max_col)}{len(sheet.rows)}' if max_col else 'A1'
    yield f'<worksheet xmlns="{MAIN}"><dimension ref="{extent}"/>'
    if any(sheet.freeze):
        yield _pane(*sheet.freeze)
    if sheet.widths:
        yield '<cols>'
        for index, width in sorted(sheet.widths.items()):
            yield f'<col min="{index}" max="{index}" width="{width}" customWidth="1"/>'
        yield '</cols>'
    yield '<sheetData>'
    columns = [column_name(col) for col in range(1, max_col + 1)]
    for index, row in enumerate(sheet.rows, 1):
        cells = ''.join(_cell(f'{col}{index}', value, sheet.row_styles.get(index, 0))
                        for col, value in zip(columns, row))
        if cells:
            yield f'<row r="{index}">{cells}</row>'
    yield '</sheetData>'
    if sheet.auto_filter and max_col:
        yield f'<autoFilter ref="{extent}"/>'
    yield '</worksheet>'


def write_workbook(path, workbook):
    """Write report tables as Excel worksheets and publish the completed file atomically."""
    path = Path(path)
    items = tuple(workbook.items()) or (('Sheet', Sheet()),)
    entries = [(f'rId{i}', 'worksheet', f'worksheets/sheet{i}.xml')
               for i in range(1, len(items) + 1)]
    overrides = [('/xl/workbook.xml', 'sheet.main'), ('/xl/styles.xml', 'styles')]
    overrides.extend((f'/xl/{location}', 'worksheet') for _, _, location in entries)
    types = (f'<Types xmlns="{TYPES}">'
             '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
             '<Default Extension="xml" ContentType="application/xml"/>'
             + ''.join(f'<Override PartName="{name}" ContentType="{CONTENT}.{kind}+xml"/>'
                       for name, kind in overrides) + '</Types>')
    book = (f'<workbook xmlns="{MAIN}" xmlns:r="{OFFICE}"><bookViews><workbookView/></bookViews><sheets>'
            + ''.join(f'<sheet name={quoteattr(name)} sheetId="{i}" r:id="rId{i}"/>'
                      for i, (name, _) in enumerate(items, 1)) + '</sheets></workbook>')
    with NamedTemporaryFile(dir=path.parent, prefix=path.name + '.', suffix='.tmp', delete=False) as tmp:
        temporary = Path(tmp.name)
    try:
        with ZipFile(temporary, 'w', ZIP_DEFLATED) as archive:
            archive.writestr('[Content_Types].xml', types)
            archive.writestr('_rels/.rels', _rels([('rId1', 'officeDocument', 'xl/workbook.xml')]))
            archive.writestr('xl/workbook.xml', book)
            archive.writestr('xl/_rels/workbook.xml.rels',
                             _rels([*entries, (f'rId{len(items) + 1}', 'styles', 'styles.xml')]))
            archive.writestr('xl/styles.xml', STYLES)
            for (_, sheet), (_, _, location) in zip(items, entries):
                with archive.open(f'xl/{location}', 'w') as stream:
                    for fragment in _sheet_xml(sheet):
                        stream.write(fragment.encode('utf-8'))
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
