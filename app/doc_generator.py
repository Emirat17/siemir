"""
Generator dokumen SPK dan BAST dari template Word.
Versi 2 — perbaikan lengkap semua tag, terbilang, dan struktur tabel.
"""
import copy
import io
from datetime import date
from docx import Document
from docx.oxml.ns import qn
from docx.oxml import OxmlElement
from docx.shared import Pt
from lxml import etree

# ── TERBILANG ────────────────────────────────────────────────────
SATUAN_TB = ['', 'Satu', 'Dua', 'Tiga', 'Empat', 'Lima',
             'Enam', 'Tujuh', 'Delapan', 'Sembilan', 'Sepuluh',
             'Sebelas', 'Dua Belas', 'Tiga Belas', 'Empat Belas',
             'Lima Belas', 'Enam Belas', 'Tujuh Belas', 'Delapan Belas',
             'Sembilan Belas']
PULUHAN_TB = ['', '', 'Dua Puluh', 'Tiga Puluh', 'Empat Puluh',
              'Lima Puluh', 'Enam Puluh', 'Tujuh Puluh', 'Delapan Puluh',
              'Sembilan Puluh']

def terbilang(n):
    n = int(n)
    if n < 0:    return 'Minus ' + terbilang(-n)
    if n == 0:   return 'Nol'
    if n < 20:   return SATUAN_TB[n]
    if n < 100:
        return PULUHAN_TB[n // 10] + ('' if n % 10 == 0 else ' ' + SATUAN_TB[n % 10])
    if n < 1000:
        k = n // 100
        r = n % 100
        prefix = 'Seratus' if k == 1 else SATUAN_TB[k] + ' Ratus'
        return prefix + ('' if r == 0 else ' ' + terbilang(r))
    if n < 1_000_000:
        k = n // 1000; r = n % 1000
        prefix = 'Seribu' if k == 1 else terbilang(k) + ' Ribu'
        return prefix + ('' if r == 0 else ' ' + terbilang(r))
    if n < 1_000_000_000:
        k = n // 1_000_000; r = n % 1_000_000
        return terbilang(k) + ' Juta' + ('' if r == 0 else ' ' + terbilang(r))
    k = n // 1_000_000_000; r = n % 1_000_000_000
    return terbilang(k) + ' Miliar' + ('' if r == 0 else ' ' + terbilang(r))

def terbilang_rupiah(n):
    return terbilang(n) + ' Rupiah'

# ── FORMAT TANGGAL ────────────────────────────────────────────────
NAMA_HARI  = ['Senin','Selasa','Rabu','Kamis','Jumat','Sabtu','Minggu']
NAMA_BULAN = ['','Januari','Februari','Maret','April','Mei','Juni',
              'Juli','Agustus','September','Oktober','November','Desember']

def tanggal_bast_dari_bulan(bulan_kontrak, tahun_kontrak):
    """Hari kerja pertama (Senin-Jumat) di tanggal 1 bulan setelah bulan kontrak."""
    from datetime import timedelta
    if bulan_kontrak == 12:
        bulan_depan, tahun_depan = 1, tahun_kontrak + 1
    else:
        bulan_depan, tahun_depan = bulan_kontrak + 1, tahun_kontrak
    candidate = date(tahun_depan, bulan_depan, 1)
    while candidate.weekday() >= 5:
        candidate += timedelta(days=1)
    return candidate

def fmt_hari(d):          return NAMA_HARI[d.weekday()]
def fmt_tgl_angka(d):     return str(d.day)
def fmt_tgl_terbilang(d): return terbilang(d.day)
def fmt_bulan_nama(d):    return NAMA_BULAN[d.month]
def fmt_tahun_terbilang(d): return terbilang(d.year)
def fmt_date_terbilang(d):
    return f"{terbilang(d.day)} {NAMA_BULAN[d.month]} Tahun {terbilang(d.year)}"
def fmt_date_normal(d):
    return f"{d.day} {NAMA_BULAN[d.month]} {d.year}"
def fmt_rp(n):
    return f"{int(n):,}".replace(',', '.')

# ── GANTI TEKS ───────────────────────────────────────────────────
def ganti_paragraf(p, var_map):
    """Gabung semua run, ganti variabel, simpan ke run pertama."""
    full = ''.join(r.text for r in p.runs)
    baru = full
    for var, val in var_map.items():
        baru = baru.replace(var, str(val) if val is not None else '')
    if baru != full and p.runs:
        p.runs[0].text = baru
        for r in p.runs[1:]:
            r.text = ''

def ganti_doc(doc, var_map):
    for p in doc.paragraphs:
        ganti_paragraf(p, var_map)
    for tbl in doc.tables:
        for row in tbl.rows:
            for cell in row.cells:
                for p in cell.paragraphs:
                    ganti_paragraf(p, var_map)

# ── SET TEKS SEL ─────────────────────────────────────────────────
def set_cell(cell, text, bold=False, font_size=11, align=None):
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    for p in cell.paragraphs:
        for r in p.runs:
            r.text = ''
    p = cell.paragraphs[0]
    if not p.runs:
        run = p.add_run(str(text))
    else:
        run = p.runs[0]
        run.text = str(text)
    run.font.size = Pt(font_size)
    run.bold = bold
    if align:
        p.alignment = align

# ── GENERATOR SPK ────────────────────────────────────────────────
def generate_spk(kontrak, template_path):
    doc = Document(template_path)
    d_surat  = kontrak['tanggal_surat']
    d_mulai  = kontrak['tanggal_mulai']
    d_selesai = kontrak['tanggal_selesai']
    bulan_idx = kontrak['bulan']
    tahun     = kontrak['tahun']

    var_map = {
        # Header & judul
        '<<BULAN>>':                NAMA_BULAN[bulan_idx].upper(),
        '<<TAHUN>>':                str(tahun),
        '<<NOMOR SPK>>':            kontrak['nomor_spk'],

        # Tanggal surat — terbilang
        '<<hari>>':                 fmt_hari(d_surat),
        '<<tanggal>>':              fmt_tgl_terbilang(d_surat),
        '<<bulan>>':                fmt_bulan_nama(d_surat),
        '<<tahun>>':                fmt_tahun_terbilang(d_surat),

        # Isi pasal
        '<<Bulan>>':                NAMA_BULAN[bulan_idx],
        '<<Tahun>>':                str(tahun),

        # Pasal 3 — tanggal mulai terbilang
        '<<Tanggal Mulai Kontrak>>': fmt_date_terbilang(d_mulai),

        # Identitas petugas
        '<<nama>>':                 kontrak['petugas_nama'],
        '<<jabatan>>':              kontrak['petugas_jabatan'] or 'Mitra',
        '<<alamat>>':               kontrak['petugas_alamat'] or '-',

        # Honor
        '<<Total Honor>>':          fmt_rp(kontrak['total_honor']),
        '<<Total Honor Terbilang>>': terbilang_rupiah(kontrak['total_honor']),
        '<<Total Honor Terbliang>>': terbilang_rupiah(kontrak['total_honor']),
    }
    ganti_doc(doc, var_map)

    # ── Isi tabel lampiran kegiatan ──
    tbl = doc.tables[-1]
    kegiatan_list = kontrak['kegiatan_list']

    # Simpan baris total (terakhir) dan baris template (index 3)
    baris_total_tr = tbl.rows[-1]._tr
    baris_template_tr = copy.deepcopy(tbl.rows[3]._tr)

    # Hapus semua baris kegiatan + dst + kosong (index 3 s/d sebelum total)
    rows_hapus = list(tbl.rows)[3:-1]
    for row in rows_hapus:
        tbl._tbl.remove(row._tr)

    # Sisipkan baris per kegiatan (dikelompokkan per fungsi)
    from collections import defaultdict
    kegiatan_per_fungsi = defaultdict(list)
    for k in kegiatan_list:
        kegiatan_per_fungsi[k.get('fungsi', '')].append(k)

    no_global = 0
    ref_tr = baris_total_tr

    for fungsi, keg_list in kegiatan_per_fungsi.items():
        # Baris header fungsi
        header_tr = copy.deepcopy(baris_template_tr)
        tbl._tbl.insert(list(tbl._tbl).index(ref_tr), header_tr)
        idx_header = len(tbl.rows) - 1
        # Cari index baris yang baru dimasukkan
        all_rows = list(tbl.rows)
        for ri, r in enumerate(all_rows):
            if r._tr is header_tr:
                idx_header = ri
                break
        baris_h = tbl.rows[idx_header]
        # Warnai header fungsi (biru muda) dan isi teks
        from docx.oxml.ns import qn as _qn
        from docx.oxml import OxmlElement as _OE
        for ci, cell in enumerate(baris_h.cells):
            tc = cell._tc
            tcPr = tc.get_or_add_tcPr()
            shd = _OE('w:shd')
            shd.set(_qn('w:val'), 'clear')
            shd.set(_qn('w:color'), 'auto')
            shd.set(_qn('w:fill'), 'BDD7EE')
            tcPr.append(shd)
            if ci == 1:
                set_cell(cell, f'Fungsi: {fungsi}', bold=True, font_size=10)
            else:
                set_cell(cell, '', font_size=10)

        # Baris data kegiatan
        for keg in keg_list:
            no_global += 1
            new_tr = copy.deepcopy(baris_template_tr)
            tbl._tbl.insert(list(tbl._tbl).index(ref_tr), new_tr)

            # Cari row yang baru
            all_rows2 = list(tbl.rows)
            for ri, r in enumerate(all_rows2):
                if r._tr is new_tr:
                    baris_baru = tbl.rows[ri]
                    break

            cells = baris_baru.cells
            tgl_m = fmt_date_normal(keg['tgl_mulai'])
            tgl_s = fmt_date_normal(keg['tgl_selesai'])

            set_cell(cells[0], str(no_global), font_size=10)
            set_cell(cells[1], keg['nama_kegiatan'], font_size=10)
            set_cell(cells[2], keg['nama_kegiatan'], font_size=10)
            set_cell(cells[3], f"{tgl_m} s.d {tgl_s}", font_size=10)
            set_cell(cells[4], str(keg['volume']), font_size=10)
            set_cell(cells[5], keg['satuan'], font_size=10)
            set_cell(cells[6], fmt_rp(keg['honor_satuan']), font_size=10)
            set_cell(cells[7], fmt_rp(keg['honor_total']), font_size=10)
            set_cell(cells[8], keg['mata_akun'], font_size=10)

    # Update baris total
    baris_akhir = tbl.rows[-1]
    cells = baris_akhir.cells
    honor_str = fmt_rp(kontrak['total_honor'])
    terbilang_str = terbilang_rupiah(kontrak['total_honor'])
    for ci in [2, 3, 4, 5, 6]:
        set_cell(cells[ci], f"Terbilang: {terbilang_str}", font_size=10, bold=True)
    set_cell(cells[7], f"Rp. {honor_str}", font_size=10, bold=True)
    set_cell(cells[8], f"Rp. {honor_str}", font_size=10, bold=True)

    buf = io.BytesIO()
    doc.save(buf)
    buf.seek(0)
    return buf.read()


# ── GENERATOR BAST ───────────────────────────────────────────────
def generate_bast(kontrak, template_path):
    doc = Document(template_path)
    d_selesai  = kontrak['tanggal_selesai']
    d_mulai    = kontrak['tanggal_mulai']
    bulan_idx  = kontrak['bulan']
    tahun      = kontrak['tahun']
    d_bast     = tanggal_bast_dari_bulan(bulan_idx, tahun)  # hari kerja pertama awal bulan berikutnya

    var_map = {
        # Header
        '<<BULAN>>':          NAMA_BULAN[bulan_idx].upper(),
        '<<TAHUN>>':          str(tahun),
        '<<NOMOR BAST>>':     kontrak['nomor_bast'],
        '<<NOMOR SPK>>':      kontrak['nomor_spk'],

        # Tanggal BAST — hari kerja pertama setelah bulan kontrak
        '<<hari>>':           fmt_hari(d_bast),
        '<<tanggal terbilang>>': fmt_tgl_terbilang(d_bast),
        '<<bulan terbilang>>':   fmt_bulan_nama(d_bast),
        '<<tahun terbilang>>':   fmt_tahun_terbilang(d_bast),

        # Identitas
        '<<Nama Petugas>>':   kontrak['petugas_nama'],
        '<<nama>>':           kontrak['petugas_nama'],
        '<<Jabatan>>':        kontrak['petugas_jabatan'] or 'Mitra',
        '<<jabatan>>':        kontrak['petugas_jabatan'] or 'Mitra',
        '<<Alamat>>':         kontrak['petugas_alamat'] or '-',
        '<<alamat>>':         kontrak['petugas_alamat'] or '-',

        # Periode
        '<<Tanggal Mulai>>':  fmt_date_terbilang(d_mulai),
        '<<Tanggal Selesai>>': fmt_date_terbilang(d_selesai),
    }
    ganti_doc(doc, var_map)

    # ── Isi tabel lampiran BAST (5 kolom: No, Uraian, Jangka Waktu, Vol, Sat) ──
    tbl = doc.tables[-1]
    kegiatan_list = kontrak['kegiatan_list']

    # Baris template ada di index 3, sisanya dihapus
    baris_template_tr = copy.deepcopy(tbl.rows[3]._tr)
    rows_hapus = list(tbl.rows)[3:]
    for row in rows_hapus:
        tbl._tbl.remove(row._tr)

    no_global = 0
    from collections import defaultdict
    kegiatan_per_fungsi = defaultdict(list)
    for k in kegiatan_list:
        kegiatan_per_fungsi[k.get('fungsi', '')].append(k)

    for fungsi, keg_list in kegiatan_per_fungsi.items():
        # Baris header fungsi
        header_tr = copy.deepcopy(baris_template_tr)
        tbl._tbl.append(header_tr)
        baris_h = tbl.rows[-1]
        from docx.oxml.ns import qn as _qn
        from docx.oxml import OxmlElement as _OE
        for ci, cell in enumerate(baris_h.cells):
            tc = cell._tc
            tcPr = tc.get_or_add_tcPr()
            shd = _OE('w:shd')
            shd.set(_qn('w:val'), 'clear')
            shd.set(_qn('w:color'), 'auto')
            shd.set(_qn('w:fill'), 'BDD7EE')
            tcPr.append(shd)
            if ci == 1:
                set_cell(cell, f'Fungsi: {fungsi}', bold=True, font_size=10)
            else:
                set_cell(cell, '', font_size=10)

        for keg in keg_list:
            no_global += 1
            new_tr = copy.deepcopy(baris_template_tr)
            tbl._tbl.append(new_tr)
            baris_baru = tbl.rows[-1]
            cells = baris_baru.cells
            tgl_m = fmt_date_normal(keg['tgl_mulai'])
            tgl_s = fmt_date_normal(keg['tgl_selesai'])
            set_cell(cells[0], str(no_global), font_size=10)
            set_cell(cells[1], keg['nama_kegiatan'], font_size=10)
            set_cell(cells[2], f"{tgl_m} s.d {tgl_s}", font_size=10)
            set_cell(cells[3], str(keg['volume']), font_size=10)
            set_cell(cells[4], keg['satuan'], font_size=10)

    buf = io.BytesIO()
    doc.save(buf)
    buf.seek(0)
    return buf.read()


# ── MERGE DOKUMEN ────────────────────────────────────────────────
def merge_docx_list(docx_bytes_list):
    """Gabungkan beberapa file .docx menjadi satu dengan page break."""
    if not docx_bytes_list:
        return None
    if len(docx_bytes_list) == 1:
        return docx_bytes_list[0]

    master = Document(io.BytesIO(docx_bytes_list[0]))

    for docx_bytes in docx_bytes_list[1:]:
        para = master.add_paragraph()
        run  = para.add_run()
        br   = OxmlElement('w:br')
        br.set(qn('w:type'), 'page')
        run._r.append(br)

        src = Document(io.BytesIO(docx_bytes))
        for element in src.element.body:
            if element.tag.endswith('}sectPr'):
                continue
            master.element.body.append(copy.deepcopy(element))

    buf = io.BytesIO()
    master.save(buf)
    buf.seek(0)
    return buf.read()
