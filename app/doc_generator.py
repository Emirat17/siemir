"""
Generator dokumen SPK dan BAST dari template Word.
Versi 3 — gunakan ganti_paragraf untuk semua sel, termasuk tabel lampiran.
"""
import copy
import io
import math
import re
from datetime import date, timedelta
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
        k = n // 100; r = n % 100
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

# ── FORMAT TANGGAL ───────────────────────────────────────────────
NAMA_HARI  = ['Senin','Selasa','Rabu','Kamis','Jumat','Sabtu','Minggu']
NAMA_BULAN = ['','Januari','Februari','Maret','April','Mei','Juni',
              'Juli','Agustus','September','Oktober','November','Desember']

def tanggal_bast_dari_bulan(bulan_kontrak, tahun_kontrak):
    if bulan_kontrak == 12:
        bulan_depan, tahun_depan = 1, tahun_kontrak + 1
    else:
        bulan_depan, tahun_depan = bulan_kontrak + 1, tahun_kontrak
    candidate = date(tahun_depan, bulan_depan, 1)
    while candidate.weekday() >= 5:
        candidate += timedelta(days=1)
    return candidate

def fmt_hari(d):           return NAMA_HARI[d.weekday()]
def fmt_tgl_terbilang(d):  return terbilang(d.day)
def fmt_bulan_nama(d):     return NAMA_BULAN[d.month]
def fmt_tahun_terbilang(d):return terbilang(d.year)
def fmt_date_terbilang(d):
    return f"{terbilang(d.day)} {NAMA_BULAN[d.month]} Tahun {terbilang(d.year)}"
def fmt_date_normal(d):
    return f"{d.day} {NAMA_BULAN[d.month]} {d.year}"
def fmt_rp(n):
    return f"{int(n):,}".replace(',', '.')

# ── GANTI TEKS ──────────────────────────────────────────────────
def _ganti_lintas_run(runs, var, val):
    """
    Ganti SEMUA kemunculan 'var' di daftar runs, meski placeholder terpecah
    antar beberapa run. Nilai ditempatkan pada run tempat placeholder DIMULAI,
    sehingga format (bold/italic) run lain di paragraf tetap terjaga.
    """
    sval = str(val) if val is not None else ''
    guard = 0
    while guard < 1000:
        guard += 1
        texts = [r.text for r in runs]
        full = ''.join(texts)
        pos = full.find(var)
        if pos == -1:
            return
        end = pos + len(var)
        # Petakan posisi awal & akhir ke (run_idx, offset)
        cum = 0
        start_run = start_off = end_run = end_off = None
        for ri, t in enumerate(texts):
            nxt = cum + len(t)
            if start_run is None and pos < nxt:
                start_run, start_off = ri, pos - cum
            if start_run is not None and end <= nxt:
                end_run, end_off = ri, end - cum
                break
            cum = nxt
        if start_run is None or end_run is None:
            return
        if start_run == end_run:
            t = runs[start_run].text
            runs[start_run].text = t[:start_off] + sval + t[end_off:]
        else:
            runs[start_run].text = runs[start_run].text[:start_off] + sval
            for ri in range(start_run + 1, end_run):
                runs[ri].text = ''
            runs[end_run].text = runs[end_run].text[end_off:]


def ganti_paragraf(p, var_map):
    """
    Ganti placeholder <<...>> di paragraf dengan mempertahankan format tiap run.
    Pola gabungan (multi-<<>>, mis. <<a>>-<<b>>-2026) diproses lebih dulu agar
    terbentuk sebelum placeholder tunggal. Semua penggantian dilakukan lintas-run
    sehingga placeholder yang terpecah tetap tergantikan tanpa merusak bold/italic
    teks lain di paragraf yang sama.
    """
    runs = p.runs
    if not runs:
        return
    full = ''.join(r.text for r in runs)
    if not any(var in full for var in var_map):
        return

    combined = [(k, v) for k, v in var_map.items() if k.count('<<') > 1]
    single   = [(k, v) for k, v in var_map.items() if k.count('<<') <= 1]
    for var, val in combined + single:
        if var in ''.join(r.text for r in runs):
            _ganti_lintas_run(runs, var, val)

def ganti_doc(doc, var_map):
    """Ganti variabel di seluruh paragraf dan tabel dokumen."""
    for p in doc.paragraphs:
        ganti_paragraf(p, var_map)
    for tbl in doc.tables:
        for row in tbl.rows:
            for cell in row.cells:
                for p in cell.paragraphs:
                    ganti_paragraf(p, var_map)

def ganti_tc(tc, var_map):
    """Ganti variabel di semua paragraf dalam satu sel fisik <w:tc>."""
    from docx.text.paragraph import Paragraph as DocxParagraph
    for w_p in tc.findall('.//' + qn('w:p')):
        # Bungkus elemen w:p menjadi objek Paragraph agar bisa pakai .runs
        p = DocxParagraph(w_p, None)
        ganti_paragraf(p, var_map)

# ── WARNA SEL (header fungsi) ────────────────────────────────────
def warnai_tc(tc, fill_hex='BDD7EE'):
    """Beri warna background pada sel fisik <w:tc>."""
    tcPr = tc.find(qn('w:tcPr'))
    if tcPr is None:
        tcPr = OxmlElement('w:tcPr')
        tc.insert(0, tcPr)
    shd = OxmlElement('w:shd')
    shd.set(qn('w:val'),   'clear')
    shd.set(qn('w:color'), 'auto')
    shd.set(qn('w:fill'),  fill_hex)
    # Hapus shd lama jika ada
    old = tcPr.find(qn('w:shd'))
    if old is not None:
        tcPr.remove(old)
    tcPr.append(shd)

# ── GET SEL FISIK ────────────────────────────────────────────────
def get_tcs(row):
    """Ambil daftar sel fisik <w:tc> dari sebuah baris tabel."""
    return row._tr.findall(qn('w:tc'))

# ── GENERATOR SPK ────────────────────────────────────────────────
def generate_spk(kontrak, template_path):
    doc = Document(template_path)
    d_surat   = kontrak['tanggal_surat']
    d_mulai   = kontrak['tanggal_mulai']
    d_selesai = kontrak['tanggal_selesai']
    bulan_idx = kontrak['bulan']
    tahun     = kontrak['tahun']

    var_map = {
        '<<BULAN>>':                 NAMA_BULAN[bulan_idx].upper(),
        '<<TAHUN>>':                 str(tahun),
        '<<NOMOR SPK>>':             kontrak['nomor_spk'],
        '<<hari>>':                  fmt_hari(d_surat),
        '<<tanggal>>':               fmt_tgl_terbilang(d_surat),
        '<<bulan>>':                 fmt_bulan_nama(d_surat),
        '<<tahun>>':                 fmt_tahun_terbilang(d_surat),
        '<<Bulan>>':                 NAMA_BULAN[bulan_idx],
        '<<Tahun>>':                 str(tahun),
        '<<Tanggal Mulai Kontrak>>': fmt_date_terbilang(d_mulai),
        '<<nama>>':                  kontrak['petugas_nama'],
        '<<jabatan>>':               kontrak['petugas_jabatan'] or 'Mitra',
        '<<alamat>>':                kontrak['petugas_alamat'] or '-',
        '<<Total Honor>>':           fmt_rp(kontrak['total_honor']),
        '<<Total Honor Terbilang>>': terbilang_rupiah(kontrak['total_honor']),
        '<<Total Honor Terbliang>>': terbilang_rupiah(kontrak['total_honor']),
        # Template sudah ada "Rp. " sebelum placeholder → isi angka saja
        '<<Ganti Rugi>>':            fmt_rp(kontrak.get('total_ganti_rugi', 0) or 0),
    }
    ganti_doc(doc, var_map)

    # ── Isi tabel lampiran kegiatan SPK ──────────────────────────
    # Daftar kegiatan datar (No berurutan), 8 sel fisik (tc[1] gridSpan=2):
    # tc[0]=No | tc[1]=Uraian(span2) | tc[2]=JangkaWaktu | tc[3]=Volume
    # tc[4]=Satuan | tc[5]=Harga/Sat | tc[6]=Honor | tc[7]=Akun
    from docx.text.paragraph import Paragraph as _DP
    tbl = doc.tables[-1]
    kegiatan_list = kontrak['kegiatan_list']
    rows = list(tbl.rows)

    # Temukan baris template (placeholder kegiatan) & baris total berdasarkan isi
    template_idx = next((i for i, r in enumerate(rows)
                         if '<<Nama Kegiatan 1>>' in ' '.join(c.text for c in r.cells)), 3)
    total_idx = next((i for i, r in enumerate(rows)
                      if '<<Total Honor>>' in ' '.join(c.text for c in r.cells)), len(rows) - 1)

    baris_template_tr = copy.deepcopy(rows[template_idx]._tr)
    baris_total_tr    = rows[total_idx]._tr

    # Hapus semua baris contoh dari template_idx s/d sebelum baris total
    for r in rows[template_idx:total_idx]:
        tbl._tbl.remove(r._tr)

    # Sisipkan satu baris per kegiatan, sebelum baris total
    for idx, keg in enumerate(kegiatan_list, 1):
        new_tr = copy.deepcopy(baris_template_tr)
        tgl_str = f"{fmt_date_normal(keg['tgl_mulai'])} s.d {fmt_date_normal(keg['tgl_selesai'])}"
        vm = {
            '<<Nama Kegiatan 1>>':         keg['nama_kegiatan'],
            '<<Tgl Mulai Kegiatan 1>> s.d <<Tgl Selesai Kegiatan 1>>': tgl_str,
            '<<Volume Kegiatan 1>>':       str(keg['volume']),
            '<<Satuan Kegiatan 1>>':       keg['satuan'],
            '<<Harga/Satuan Kegiatan 1>>': fmt_rp(keg['honor_satuan']),
            '<<Honor Total Kegiatan 1>>':  fmt_rp(keg['honor_total']),
            '<<Mata Akun Kegiatan 1>>':    keg['mata_akun'],
        }
        tcs = new_tr.findall(qn('w:tc'))
        # Sel No (tc[0]) → nomor urut
        for w_p in tcs[0].findall('.//' + qn('w:p')):
            p_obj = _DP(w_p, None)
            full = ''.join(r.text for r in p_obj.runs)
            if full.strip() and p_obj.runs:
                p_obj.runs[0].text = str(idx)
                for r in p_obj.runs[1:]:
                    r.text = ''
                break
        # Sel lainnya → ganti placeholder kegiatan
        for tc in tcs[1:]:
            ganti_tc(tc, vm)
        baris_total_tr.addprevious(new_tr)

    # ── Update baris total ──
    vm_total = {
        '<<Total Honor Terbliang>>': f"Terbilang: {terbilang_rupiah(kontrak['total_honor'])}",
        '<<Total Honor Terbilang>>': f"Terbilang: {terbilang_rupiah(kontrak['total_honor'])}",
        '<<Total Honor>>':           f"Rp. {fmt_rp(kontrak['total_honor'])}",
    }
    for tc in baris_total_tr.findall(qn('w:tc')):
        ganti_tc(tc, vm_total)

    buf = io.BytesIO()
    doc.save(buf)
    buf.seek(0)
    return buf.read()


# ── GENERATOR BAST ───────────────────────────────────────────────
def generate_bast(kontrak, template_path):
    """
    Generate dokumen BAST.
    kontrak['bulan']/['tahun'] = bulan BAST (pencairan).
    kontrak['tanggal_selesai'] = tanggal BAST (hari kerja pertama bulan pencairan).
    """
    doc = Document(template_path)
    bulan_idx = kontrak['bulan']
    tahun     = kontrak['tahun']

    if kontrak.get('tanggal_selesai'):
        d_bast = kontrak['tanggal_selesai']
        if isinstance(d_bast, str):
            from datetime import datetime
            d_bast = datetime.strptime(d_bast, '%Y-%m-%d').date()
    else:
        d_bast = tanggal_bast_dari_bulan(
            bulan_idx - 1 if bulan_idx > 1 else 12,
            tahun if bulan_idx > 1 else tahun - 1
        )

    var_map = {
        '<<BULAN>>':             NAMA_BULAN[bulan_idx].upper(),
        '<<TAHUN>>':             str(tahun),
        '<<NOMOR BAST>>':        kontrak['nomor_bast'],
        '<<NOMOR SPK>>':         kontrak['nomor_spk'],
        '<<hari>>':              fmt_hari(d_bast),
        '<<tanggal terbilang>>': fmt_tgl_terbilang(d_bast),
        '<<bulan terbilang>>':   fmt_bulan_nama(d_bast),
        '<<tahun terbilang>>':   fmt_tahun_terbilang(d_bast),
        '<<Nama Petugas>>':      kontrak['petugas_nama'],
        '<<nama>>':              kontrak['petugas_nama'],
        '<<Jabatan>>':           kontrak['petugas_jabatan'] or 'Mitra',
        '<<jabatan>>':           kontrak['petugas_jabatan'] or 'Mitra',
        '<<Alamat>>':            kontrak['petugas_alamat'] or '-',
        '<<alamat>>':            kontrak['petugas_alamat'] or '-',
        '<<Tanggal Mulai>>':     fmt_date_terbilang(d_bast),
        '<<Tanggal Selesai>>':   fmt_date_terbilang(d_bast),
    }
    ganti_doc(doc, var_map)

    # ── Isi tabel lampiran kegiatan BAST ─────────────────────────
    # Struktur: 5 sel fisik (tidak ada merge)
    # tc[0]=No | tc[1]=Uraian Tugas | tc[2]=Jangka Waktu | tc[3]=Volume | tc[4]=Satuan
    tbl = doc.tables[-1]
    kegiatan_list = kontrak['kegiatan_list']

    baris_template_tr = copy.deepcopy(tbl.rows[3]._tr)
    # Hapus semua baris data (index 3 ke bawah)
    for row in list(tbl.rows)[3:]:
        tbl._tbl.remove(row._tr)

    from collections import defaultdict
    kegiatan_per_fungsi = defaultdict(list)
    for k in kegiatan_list:
        kegiatan_per_fungsi[k.get('fungsi', '')].append(k)

    no_global = 0

    for fungsi, keg_list in kegiatan_per_fungsi.items():
        # ── Baris header fungsi ──
        header_tr = copy.deepcopy(baris_template_tr)
        tbl._tbl.append(header_tr)

        for ri, row in enumerate(tbl.rows):
            if row._tr is header_tr:
                baris_h = tbl.rows[ri]
                break

        tcs_h = get_tcs(baris_h)
        for i_h, tc_h in enumerate(tcs_h):
            warnai_tc(tc_h, 'BDD7EE')
            val_header = f'Fungsi: {fungsi}' if i_h == 1 else ''
            vm_h = {}
            for w_p in tc_h.findall('.//' + qn('w:p')):
                from docx.text.paragraph import Paragraph as DP
                p_obj = DP(w_p, None)
                teks_p = ''.join(r.text for r in p_obj.runs)
                if teks_p.strip():
                    vm_h[teks_p.strip()] = val_header
            ganti_tc(tc_h, vm_h)

        # ── Baris data kegiatan ──
        for keg in keg_list:
            no_global += 1
            new_tr = copy.deepcopy(baris_template_tr)
            tbl._tbl.append(new_tr)

            baris_baru = tbl.rows[-1]
            tcs = get_tcs(baris_baru)
            tgl_str = f"{fmt_date_normal(keg['tgl_mulai'])} s.d {fmt_date_normal(keg['tgl_selesai'])}"

            vm = {
                '<<Nama Kegiatan 1>>':         keg['nama_kegiatan'],
                '<<Jangka Waktu Kegiatan 1>>': tgl_str,
                '<<Volume Kegiatan 1>>':       str(keg['volume']),
                '<<Satuan Kegiatan 1>>':       keg['satuan'],
                '1': str(no_global),
            }
            for tc in tcs:
                ganti_tc(tc, vm)

    buf = io.BytesIO()
    doc.save(buf)
    buf.seek(0)
    return buf.read()


# ── GENERATOR SPK SE2026 ─────────────────────────────────────────
def generate_spk_se2026(data, template_path):
    """Generate SPK SE2026 (PPL atau PML) dari template Word."""
    doc = Document(template_path)
    tanggal = data['tanggal_spk']

    jml_sls    = int(data.get('jumlah_sls', 0) or 0)
    jml_usaha  = int(data.get('jumlah_usaha', 0) or 0)
    jml_kel    = int(data.get('jumlah_keluarga', 0) or 0)

    th   = data.get('total_honor',      0) or 0
    ob1  = data.get('honor_1_ob',       0) or 0
    ob15 = data.get('honor_1_5_ob',     0) or 0
    tgr  = data.get('total_ganti_rugi', 0) or 0

    var_map = {
        # Pola gabungan didahulukan: (<<tanggal>>-<<bulan>>-YYYY) → DD-MM-YYYY
        f'<<tanggal>>-<<bulan>>-{tanggal.year}': tanggal.strftime('%d-%m-%Y'),
        '<<Nomor SPK>>':                 data.get('nomor_spk', ''),
        '<<hari>>':                      fmt_hari(tanggal),
        '<<tanggal>>':                   fmt_tgl_terbilang(tanggal),
        '<<bulan>>':                     fmt_bulan_nama(tanggal),
        '<<tahun>>':                     fmt_tahun_terbilang(tanggal),
        '<<nama>>':                      data.get('nama', ''),
        '<<alamat>>':                    data.get('alamat', ''),
        # Template sudah ada "Rp " sebelum placeholder dan ",00" sesudahnya
        # → isi hanya angka saja (mis. 2.500.000)
        '<<Total Honor>>':               fmt_rp(th),
        '<<Total Honor Terbilang>>':     terbilang_rupiah(th),
        '<<Honor 1 OB>>':                fmt_rp(ob1),
        '<<Honor 1,5 OB>>':              fmt_rp(ob15),
        '<<Total Ganti Rugi>>':          fmt_rp(tgr),
        '<<Total Ganti Rugi Terbilang>>':terbilang_rupiah(tgr),
        '<<Jumlah SLS>>':                str(jml_sls),
        # 40% dari SLS dibulatkan KE ATAS (mis. 3 SLS → 1,2 → 2). Pakai math
        # integer (×2÷5) untuk menghindari galat float pada 0.4 (mis. 25×0.4).
        '<<40% dari Jumlah SLS>>':       str(math.ceil(jml_sls * 2 / 5)),
        '<<100% dari Jumlah SLS>>':      str(jml_sls),
        # Placeholder lama (60%/usaha/keluarga) dipertahankan untuk kompatibilitas
        # template versi sebelumnya; no-op jika placeholder tidak ada di template.
        '<<60% dari Jumlah SLS>>':       str(round(jml_sls   * 0.6)),
        '<<40% dari Jumlah Usaha>>':     str(round(jml_usaha * 0.4)),
        '<<60% dari Jumlah Usaha>>':     str(round(jml_usaha * 0.6)),
        '<<40% dari Jumlah Keluarga>>':  str(round(jml_kel   * 0.4)),
        '<<60% dari Jumlah Keluarga>>':  str(round(jml_kel   * 0.6)),
    }

    # Wilayah kerja PPL (8 slot sesuai template terbaru)
    wilayah = data.get('wilayah', [])
    for i in range(1, 9):
        w = wilayah[i-1] if i <= len(wilayah) else {}
        var_map[f'<<Kode Kecamatan {i}>>'] = w.get('kode_kecamatan', '')
        var_map[f'<<Kode Desa {i}>>']       = w.get('kode_desa', '')
        var_map[f'<<Jumlah SLS {i}>>']      = str(w.get('jumlah_sls', '') or '')
        var_map[f'<<Jumlah Keluarga {i}>>'] = str(w.get('jumlah_keluarga', '') or '')

    # Daftar PPL yang diawasi PML (17 slot sesuai template terbaru)
    ppl_list = data.get('ppl_list', [])
    for i in range(1, 18):
        p = ppl_list[i-1] if i <= len(ppl_list) else {}
        var_map[f'<<Nama PPL {i}>>']           = p.get('nama_ppl', '')
        var_map[f'<<Kode Kecamatan PPL {i}>>'] = p.get('kode_kecamatan', '')
        var_map[f'<<Kode Desa PPL {i}>>']      = p.get('kode_desa', '')
        var_map[f'<<Jumlah SLS PPL {i}>>']     = str(p.get('jumlah_sls', '') or '')

    ganti_doc(doc, var_map)

    buf = io.BytesIO()
    doc.save(buf)
    buf.seek(0)
    return buf.read()


# ── GENERATOR BAPP & BAST SE2026 ─────────────────────────────────
def _parse_kode_wilayah(teks):
    """'[020] TEBING TINGGI' → ('020', 'TEBING TINGGI'). Tanpa kurung → ('', teks)."""
    if not teks:
        return '', ''
    m = re.match(r'\s*\[([^\]]*)\]\s*(.*)', str(teks))
    if m:
        return m.group(1).strip(), m.group(2).strip()
    return '', str(teks).strip()


def _var_map_umum_se2026(data, tanggal):
    """Placeholder identitas & tanggal yang dipakai bersama BAPP/BAST."""
    return {
        # Pola gabungan didahulukan: (<<tanggal>>-<<bulan>>-YYYY) → DD-MM-YYYY
        f'<<tanggal>>-<<bulan>>-{tanggal.year}': tanggal.strftime('%d-%m-%Y'),
        '<<hari>>':                fmt_hari(tanggal),
        '<<tanggal>>':             fmt_tgl_terbilang(tanggal),
        '<<bulan>>':               fmt_bulan_nama(tanggal),
        '<<nama>>':                data.get('nama', ''),
        '<<Nama>>':                data.get('nama', ''),
        '<<NIK>>':                 data.get('nik', '') or '',
        '<<Nomor SPK Petugas Lapangan SE2026>>':   data.get('nomor_spk', ''),
        '<<Nomor SPK Pemeriksa Lapangan SE2026>>': data.get('nomor_spk', ''),
    }


def generate_bapp_se2026(data, template_path):
    """
    Generate BAPP Termin I / II untuk PPL / PML.
    Satu var_map mencakup semua placeholder ke-4 varian; placeholder yang
    tidak ada di template menjadi no-op. Volume mengikuti nama placeholder:
    'keatas' → ceil, 'kebawah' → floor.
    """
    doc = Document(template_path)
    tanggal = data['tanggal']
    sls = int(data.get('jumlah_sls', 0) or 0)
    h1  = data.get('honor_1_ob',   0) or 0
    h15 = data.get('honor_1_5_ob', 0) or 0

    var_map = _var_map_umum_se2026(data, tanggal)
    var_map.update({
        '<<Nomor BAPP>>':                  data.get('nomor', ''),
        # Honor (template sudah ada "Rp " dan ", 00" → angka saja)
        '<<Honor 1 OB>>':                  fmt_rp(h1),
        '<<Total Honor 1 OB Terbilang>>':  terbilang_rupiah(h1),
        '<<Total Honor 1,5 OB>>':          fmt_rp(h15),
        '<<Total Honor 1,5 OB Terbilang>>':terbilang_rupiah(h15),
        # Volume target (40% = 2/5, 60% = 3/5) — integer math hindari galat float
        '<<Pembulatan keatas 40% dari Total SLS>>':  str(math.ceil(sls * 2 / 5)),
        '<<Pembulatan keatas 60% dari Total SLS>>':  str(math.ceil(sls * 3 / 5)),
        '<<Pembulatan kebawah 60% dari Total SLS>>': str(math.floor(sls * 3 / 5)),
    })
    for i in range(1, 6):
        var_map[f'<<Screenshoot Aplikasi Fasih {i}>>'] = ''
    ganti_doc(doc, var_map)

    buf = io.BytesIO(); doc.save(buf); buf.seek(0)
    return buf.read()


def generate_bast_se2026(data, template_path, jenis):
    """
    Generate BAST untuk PPL / PML. Tanggal biasanya 1 September 2026.
    Tabel wilayah/daftar petugas diisi dinamis: PPL dari wilayah, PML dari ppl_list.
    """
    doc = Document(template_path)
    tanggal = data['tanggal']
    sls = int(data.get('jumlah_sls', 0) or 0)
    th  = data.get('total_honor', 0) or 0

    var_map = _var_map_umum_se2026(data, tanggal)
    var_map.update({
        '<<Nomor BAST>>':          data.get('nomor', ''),
        '<<Total SLS>>':           str(sls),
        '<< Total SLS>>':          str(sls),
        '<<Total Honor>>':         fmt_rp(th),
        '<<Total Honor Terbilang>>':terbilang_rupiah(th),
    })
    for i in range(1, 6):
        var_map[f'<<Screenshoot Aplikasi Fasih {i}>>'] = ''
    ganti_doc(doc, var_map)

    items = data.get('wilayah', []) if jenis == 'PPL' else data.get('ppl_list', [])
    _isi_tabel_wilayah_bast(doc, items)

    buf = io.BytesIO(); doc.save(buf); buf.seek(0)
    return buf.read()


def _isi_tabel_wilayah_bast(doc, items):
    """Isi tabel wilayah kerja BAST secara dinamis (satu baris per item).
    Baris 'No' memakai auto-numbering Word, jadi tidak disentuh."""
    target = None
    for tbl in doc.tables:
        alltext = ' '.join(c.text for r in tbl.rows for c in r.cells)
        if '<<KODE KECAMATAN 1>>' in alltext:
            target = tbl
            break
    if target is None:
        return

    rows = list(target.rows)
    tpl_idx = next(i for i, r in enumerate(rows)
                   if '<<KODE KECAMATAN 1>>' in ' '.join(c.text for c in r.cells))
    # Kumpulkan baris contoh berturut (punya <<KODE KECAMATAN N>>)
    data_idxs = []
    for i in range(tpl_idx, len(rows)):
        if re.search(r'<<KODE KECAMATAN \d+>>', ' '.join(c.text for c in rows[i].cells)):
            data_idxs.append(i)
        else:
            break
    # Baris anchor (biasanya 'Dst.') tepat setelah baris contoh terakhir
    after = data_idxs[-1] + 1
    anchor_tr = rows[after]._tr if after < len(rows) else None
    tpl_tr = copy.deepcopy(rows[tpl_idx]._tr)

    for i in data_idxs:
        target._tbl.remove(rows[i]._tr)

    for it in items:
        new_tr = copy.deepcopy(tpl_tr)
        kk, nk = _parse_kode_wilayah(it.get('kode_kecamatan', ''))
        kd, nd = _parse_kode_wilayah(it.get('kode_desa', ''))
        vm = {
            '<<KODE KECAMATAN 1>>': kk, '<<KECAMATAN 1>>': nk,
            '<<KODE DESA 1>>':      kd, '<<DESA 1>>':      nd,
            '<<Jumlah SLS 1>>':     str(it.get('jumlah_sls', '') or ''),
            '<<Nama Petugas Lapangan 1>>': it.get('nama_ppl', '') or '',
        }
        for tc in new_tr.findall(qn('w:tc')):
            ganti_tc(tc, vm)
        if anchor_tr is not None:
            anchor_tr.addprevious(new_tr)
        else:
            target._tbl.append(new_tr)


# ── GENERATOR SPPL SE2026 ────────────────────────────────────────
def _fmt_persen(realisasi, target):
    """realisasi/target*100 → '88,63' (2 desimal, koma)."""
    try:
        t = float(target or 0)
        if t == 0:
            return '0'
        return f'{float(realisasi or 0) / t * 100:.2f}'.replace('.', ',')
    except (TypeError, ValueError):
        return '0'


def _set_sel_teks(tc, teks):
    """Set teks paragraf pertama sebuah sel <w:tc>, pertahankan run pertama."""
    from docx.text.paragraph import Paragraph as _DP
    for w_p in tc.findall('.//' + qn('w:p')):
        p = _DP(w_p, None)
        if p.runs:
            p.runs[0].text = teks
            for r in p.runs[1:]:
                r.text = ''
            return
        p.add_run(teks)
        return


def _baris_contoh(r):
    """True bila baris tabel adalah baris contoh/template (punya placeholder <<>>
    atau berisi 'Dst') dan bukan baris 'Jumlah'."""
    txt = ' '.join(c.text for c in r.cells)
    if r.cells[0].text.strip().lower().startswith('jumlah'):
        return False
    return ('<<' in txt) or ('dst' in txt.lower())


def _isi_tabel_sppl(tbl, marker, items, buat_vm):
    """Isi tabel SPPL: baris ber-marker jadi template, hapus semua baris contoh
    (placeholder / 'Dst'), sisipkan satu baris per item sebelum baris 'Jumlah'."""
    rows = list(tbl.rows)
    tpl_row = next((r for r in rows if marker in ' '.join(c.text for c in r.cells)), None)
    if tpl_row is None:
        return
    tpl_tr = copy.deepcopy(tpl_row._tr)
    anchor = next((r._tr for r in rows
                   if r.cells[0].text.strip().lower().startswith('jumlah')), None)
    for r in rows:
        if _baris_contoh(r) and r._tr.getparent() is not None:
            tbl._tbl.remove(r._tr)
    for idx, it in enumerate(items, 1):
        new_tr = copy.deepcopy(tpl_tr)
        tcs = new_tr.findall(qn('w:tc'))
        if tcs:
            _set_sel_teks(tcs[0], f'{idx}.')
        vm = buat_vm(it)
        for tc in tcs:
            ganti_tc(tc, vm)
        if anchor is not None:
            anchor.addprevious(new_tr)
        else:
            tbl._tbl.append(new_tr)


def generate_sppl_ppl(data, template_path):
    """SPPL Petugas Lapangan (per PPL) — penggantian paragraf sederhana."""
    doc = Document(template_path)
    persen = _fmt_persen(data.get('realisasi'), data.get('target'))
    var_map = {
        '<<Nomor SPPL dimulai dari 25>>':      str(data.get('nomor_sppl', '')),
        '<<Nama PPL>>':                        data.get('nama', ''),
        '<<NIK PPL>>':                         data.get('nik', '') or '',
        '<<Nomor SPK PPL SE2026>>':            data.get('nomor_spk', ''),
        '<<Realisasi PPL>>':                   str(data.get('realisasi', '')),
        '<<Target PPL>>':                      str(data.get('target', '')),
        '<<(Realisasi PPL/Target PPL)*100>>':  persen,
    }
    ganti_doc(doc, var_map)
    buf = io.BytesIO(); doc.save(buf); buf.seek(0)
    return buf.read()


def generate_sppl_pml(data, template_path):
    """SPPL Pemeriksa Lapangan (per PML) + tabel daftar PPL yang diawasi."""
    doc = Document(template_path)
    var_map = {
        '<<Nomor SPPL dimulai dari 2>>': str(data.get('nomor_sppl', '')),
        '<<Nama PML>>':                  data.get('nama', ''),
        '<<NIK PML>>':                   data.get('nik', '') or '',
        '<<Nomor SPK PML SE2026>>':      data.get('nomor_spk', ''),
    }
    ganti_doc(doc, var_map)

    ppl_list = data.get('ppl_list', [])
    tbl = next((t for t in doc.tables
                if '<<Nama PPL 1>>' in ' '.join(c.text for r in t.rows for c in r.cells)), None)
    if tbl is not None:
        def vm(p):
            return {
                '<<Nama PPL 1>>':      p.get('nama', ''),
                '<<Target PPL 1>>':    str(p.get('target', '')),
                '<<Realisasi PPL 1>>': str(p.get('realisasi', '')),
                '<<(Realisasi PPL 1/Target PPL 1)*100%>>': _fmt_persen(p.get('realisasi'), p.get('target')),
            }
        _isi_tabel_sppl(tbl, '<<Nama PPL 1>>', ppl_list, vm)
        # Isi baris Jumlah
        st = sum(float(p.get('target', 0) or 0) for p in ppl_list)
        sr = sum(float(p.get('realisasi', 0) or 0) for p in ppl_list)
        jrow = next((r for r in tbl.rows if r.cells[0].text.strip().lower().startswith('jumlah')), None)
        if jrow is not None:
            tcs = jrow._tr.findall(qn('w:tc'))
            if len(tcs) >= 3:   # 3 sel terakhir = Target, Realisasi, Persentase
                _set_sel_teks(tcs[-3], f'{int(st)}')
                _set_sel_teks(tcs[-2], f'{int(sr)}')
                _set_sel_teks(tcs[-1], _fmt_persen(sr, st))

    buf = io.BytesIO(); doc.save(buf); buf.seek(0)
    return buf.read()


def generate_sppl_kepala(data, template_path):
    """SPPL Kepala BPS — rekap seluruh petugas (PML lalu PPL) + total."""
    doc = Document(template_path)
    pml = data.get('pml_list', [])
    ppl = data.get('ppl_list', [])
    st = sum(float(x.get('target', 0) or 0) for x in pml + ppl)
    sr = sum(float(x.get('realisasi', 0) or 0) for x in pml + ppl)
    var_map = {
        '<<Jumlah Target Seluruhnya>>':     f'{int(st)}',
        '<<Jumlah Realisasi Seluruhnya>>':  f'{int(sr)}',
        '<<Jumlah Persentase Seluruhnya>>': _fmt_persen(sr, st),
    }
    ganti_doc(doc, var_map)

    tbl = next((t for t in doc.tables
                if '<<Nama PML 1>>' in ' '.join(c.text for r in t.rows for c in r.cells)), None)
    if tbl is None:
        buf = io.BytesIO(); doc.save(buf); buf.seek(0); return buf.read()

    rows = list(tbl.rows)
    tr_pml = copy.deepcopy(next(r._tr for r in rows
                                if '<<Nama PML 1>>' in ' '.join(c.text for c in r.cells)))
    tr_ppl = copy.deepcopy(next(r._tr for r in rows
                                if '<<Nama PPL 1>>' in ' '.join(c.text for c in r.cells)))
    anchor = next((r._tr for r in rows
                   if r.cells[0].text.strip().lower().startswith('jumlah')), None)
    # hapus semua baris contoh (punya placeholder / 'Dst') sebelum Jumlah
    for r in rows:
        if _baris_contoh(r) and r._tr.getparent() is not None:
            tbl._tbl.remove(r._tr)

    no = 0
    def sisip(tr_tpl, item, jabatan, ph_nama, ph_tgt, ph_real, ph_pct):
        nonlocal no
        no += 1
        new_tr = copy.deepcopy(tr_tpl)
        tcs = new_tr.findall(qn('w:tc'))
        _set_sel_teks(tcs[0], f'{no}.')
        vm = {
            ph_nama: item.get('nama', ''),
            ph_tgt:  str(item.get('target', '')),
            ph_real: str(item.get('realisasi', '')),
            ph_pct:  _fmt_persen(item.get('realisasi'), item.get('target')),
        }
        for tc in tcs:
            ganti_tc(tc, vm)
        if anchor is not None:
            anchor.addprevious(new_tr)
        else:
            tbl._tbl.append(new_tr)

    for it in pml:
        sisip(tr_pml, it, 'PML', '<<Nama PML 1>>', '<<Target PML 1>>',
              '<<Realisasi PML 1>>', '<<(Realisasi PML 1/Target PML 1)*100%>>')
    for it in ppl:
        sisip(tr_ppl, it, 'PPL', '<<Nama PPL 1>>', '<<Target PPL 1>>',
              '<<Realisasi PPL 1>>', '<<(Realisasi PPL 1/Target PPL 1)*100%>>')

    buf = io.BytesIO(); doc.save(buf); buf.seek(0)
    return buf.read()


# ── MERGE DOKUMEN ────────────────────────────────────────────────
def _get_numbering_el(doc):
    """Ambil elemen <w:numbering> dari dokumen, atau None jika tidak ada."""
    try:
        return doc.part.numbering_part.element
    except Exception:
        return None


def _remap_numbering(master_numbering, src_numbering, src_body):
    """
    Salin definisi numbering dari dokumen sumber ke master dengan ID baru
    yang unik, lalu remap referensi <w:numId> di body sumber.

    Akibatnya tiap dokumen punya instance daftar sendiri → penomoran
    tabel & heading restart dari 1 / I, tidak melanjutkan dokumen lain.
    """
    if src_numbering is None or master_numbering is None:
        return

    VAL   = qn('w:val')
    A_ID  = qn('w:abstractNumId')
    N_ID  = qn('w:numId')

    # ID maksimum yang sedang ada di master
    max_abs = 0
    for an in master_numbering.findall(qn('w:abstractNum')):
        try: max_abs = max(max_abs, int(an.get(A_ID)))
        except (TypeError, ValueError): pass
    max_num = 0
    for nm in master_numbering.findall(qn('w:num')):
        try: max_num = max(max_num, int(nm.get(N_ID)))
        except (TypeError, ValueError): pass

    # Salin abstractNum dengan abstractNumId baru
    abs_map   = {}
    next_abs  = max_abs + 1
    first_num = master_numbering.find(qn('w:num'))   # abstractNum harus sebelum num
    for an in src_numbering.findall(qn('w:abstractNum')):
        old = an.get(A_ID)
        new_an = copy.deepcopy(an)
        new_an.set(A_ID, str(next_abs))
        # Hapus nsid agar Word tidak menggabungkan list dengan master
        nsid = new_an.find(qn('w:nsid'))
        if nsid is not None:
            new_an.remove(nsid)
        abs_map[old] = str(next_abs)
        if first_num is not None:
            first_num.addprevious(new_an)
        else:
            master_numbering.append(new_an)
        next_abs += 1

    # Salin num dengan numId baru, update referensi abstractNumId
    num_map  = {}
    next_num = max_num + 1
    for nm in src_numbering.findall(qn('w:num')):
        old = nm.get(N_ID)
        new_nm = copy.deepcopy(nm)
        new_nm.set(N_ID, str(next_num))
        ref = new_nm.find(qn('w:abstractNumId'))
        if ref is not None and ref.get(VAL) in abs_map:
            ref.set(VAL, abs_map[ref.get(VAL)])
        num_map[old] = str(next_num)
        master_numbering.append(new_nm)
        next_num += 1

    # Remap referensi <w:numId w:val="..."> di body sumber (termasuk sel tabel)
    for numId_el in src_body.iter(N_ID):
        v = numId_el.get(VAL)
        if v in num_map:
            numId_el.set(VAL, num_map[v])


def merge_docx_list(docx_bytes_list):
    """
    Gabungkan beberapa .docx menjadi satu file.

    Menangani:
    - Penomoran daftar (numId) di-remap per dokumen → tabel & heading
      restart dari 1 / I di setiap dokumen (tidak melanjutkan nomor
      dokumen sebelumnya).
    - Orientasi halaman (portrait/landscape) tiap dokumen dipertahankan
      lewat section break dari sectPr masing-masing dokumen.
    - Tidak ada halaman kosong ganda antar dokumen.
    """
    if not docx_bytes_list:
        return None
    if len(docx_bytes_list) == 1:
        return docx_bytes_list[0]

    TAG_SECT = qn('w:sectPr')

    master           = Document(io.BytesIO(docx_bytes_list[0]))
    master_body      = master.element.body
    master_numbering = _get_numbering_el(master)

    for docx_bytes in docx_bytes_list[1:]:
        src      = Document(io.BytesIO(docx_bytes))
        src_body = src.element.body

        # Remap numbering dokumen ini agar penomoran restart
        _remap_numbering(master_numbering, _get_numbering_el(src), src_body)

        # Pindahkan sectPr final master ke paragraf kosong (inner section break)
        # agar orientasi landscape lampiran dokumen sebelumnya tetap terjaga.
        master_final = master_body.find(TAG_SECT)
        if master_final is not None:
            master_body.remove(master_final)
            brk_p   = OxmlElement('w:p')
            brk_pPr = OxmlElement('w:pPr')
            brk_pPr.append(copy.deepcopy(master_final))
            brk_p.insert(0, brk_pPr)
            master_body.append(brk_p)

        # Salin seluruh elemen body sumber (termasuk sectPr finalnya) ke master
        for el in src_body:
            master_body.append(copy.deepcopy(el))

    buf = io.BytesIO()
    master.save(buf)
    buf.seek(0)
    return buf.read()
