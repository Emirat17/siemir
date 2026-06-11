"""
Generator dokumen SPK dan BAST dari template Word.
Versi 3 — gunakan ganti_paragraf untuk semua sel, termasuk tabel lampiran.
"""
import copy
import io
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
def ganti_paragraf(p, var_map):
    """
    Ganti placeholder <<...>> di paragraf sambil mempertahankan format per-run.

    Urutan:
    1. Pola gabungan (multi-<<>>, mis. <<a>>-<<b>>-<<c>>) diganti dulu di full-text
       agar pola seperti (02-06-2026) terbentuk sebelum placeholder tunggal diganti.
    2. Placeholder tunggal diganti per-run agar format bold/italic terjaga.
    3. Fallback merge ke run[0] jika placeholder tunggal terpecah antar run.
    """
    full = ''.join(r.text for r in p.runs)
    if not any(var in full for var in var_map):
        return

    # --- Tahap 1: pola gabungan (mengandung lebih dari satu <<>>) ---
    combined_vars = {k: v for k, v in var_map.items() if k.count('<<') > 1}
    single_vars   = {k: v for k, v in var_map.items() if k.count('<<') <= 1}

    if combined_vars:
        baru_combined = full
        changed = False
        for var, val in combined_vars.items():
            if var in baru_combined:
                baru_combined = baru_combined.replace(var, str(val) if val is not None else '')
                changed = True
        if changed and p.runs:
            p.runs[0].text = baru_combined
            for r in p.runs[1:]:
                r.text = ''

    # --- Tahap 2: placeholder tunggal, per-run (preserves bold/italic) ---
    diganti = False
    for r in p.runs:
        old = r.text
        new = old
        for var, val in single_vars.items():
            new = new.replace(var, str(val) if val is not None else '')
        if new != old:
            r.text = new
            diganti = True

    if not diganti:
        # Placeholder tunggal terpecah antar run — fallback: merge ke run pertama
        full2 = ''.join(r.text for r in p.runs)
        baru2 = full2
        for var, val in single_vars.items():
            baru2 = baru2.replace(var, str(val) if val is not None else '')
        if baru2 != full2 and p.runs:
            p.runs[0].text = baru2
            for r in p.runs[1:]:
                r.text = ''

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
    }
    ganti_doc(doc, var_map)

    # ── Isi tabel lampiran kegiatan SPK ──────────────────────────
    # Struktur: 9 kolom logical, 8 sel fisik (tc[1] gridSpan=2)
    # tc[0]=No | tc[1]=Uraian(span2) | tc[2]=JangkaWaktu | tc[3]=Volume
    # tc[4]=Satuan | tc[5]=Harga/Sat | tc[6]=Honor | tc[7]=Akun
    tbl = doc.tables[-1]
    kegiatan_list = kontrak['kegiatan_list']

    baris_total_tr    = tbl.rows[-1]._tr
    baris_template_tr = copy.deepcopy(tbl.rows[3]._tr)

    # Hapus baris data lama (index 3 s/d sebelum total)
    for row in list(tbl.rows)[3:-1]:
        tbl._tbl.remove(row._tr)

    from collections import defaultdict
    kegiatan_per_fungsi = defaultdict(list)
    for k in kegiatan_list:
        kegiatan_per_fungsi[k.get('fungsi', '')].append(k)

    no_global = 0
    ref_tr    = baris_total_tr

    for fungsi, keg_list in kegiatan_per_fungsi.items():
        # ── Baris header fungsi ──
        header_tr = copy.deepcopy(baris_template_tr)
        tbl._tbl.insert(list(tbl._tbl).index(ref_tr), header_tr)

        # Cari baris yang baru dimasukkan
        for ri, row in enumerate(tbl.rows):
            if row._tr is header_tr:
                baris_h = tbl.rows[ri]
                break

        tcs_h = get_tcs(baris_h)
        # Buat var_map khusus header fungsi
        for i_h, tc_h in enumerate(tcs_h):
            warnai_tc(tc_h, 'BDD7EE')
            # Tentukan teks per posisi sel fisik
            if i_h == 1:
                val_header = f'Fungsi: {fungsi}'
            else:
                val_header = ''
            # Buat var_map yang mengganti SEMUA placeholder dengan nilai ini
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
            tbl._tbl.insert(list(tbl._tbl).index(ref_tr), new_tr)

            for ri, row in enumerate(tbl.rows):
                if row._tr is new_tr:
                    baris_baru = tbl.rows[ri]
                    break

            tcs = get_tcs(baris_baru)
            tgl_str = f"{fmt_date_normal(keg['tgl_mulai'])} s.d {fmt_date_normal(keg['tgl_selesai'])}"

            # Buat var_map yang memetakan placeholder lama → nilai baru
            # Ini bekerja karena ganti_paragraf menggabungkan multi-run sebelum replace
            vm = {
                '<<Nama Kegiatan 1>>':      keg['nama_kegiatan'],
                '<<Tgl Mulai Kegiatan 1>> s.d <<Tgl Selesai Kegiatan 1>>': tgl_str,
                '<<Volume Kegiatan 1>>':    str(keg['volume']),
                '<<Satuan Kegiatan 1>>':    keg['satuan'],
                '<<Harga/Satuan Kegiatan 1>>': fmt_rp(keg['honor_satuan']),
                '<<Honor Total Kegiatan 1>>':  fmt_rp(keg['honor_total']),
                '<<Mata Akun Kegiatan 1>>': keg['mata_akun'],
                # Nomor baris
                '1': str(no_global),
            }
            for tc in tcs:
                ganti_tc(tc, vm)

    # ── Update baris total ──
    vm_total = {
        '<<Total Honor Terbliang>>': f"Terbilang: {terbilang_rupiah(kontrak['total_honor'])}",
        '<<Total Honor Terbilang>>': f"Terbilang: {terbilang_rupiah(kontrak['total_honor'])}",
        '<<Total Honor>>':           f"Rp. {fmt_rp(kontrak['total_honor'])}",
        'Terbilang: <<Total Honor Terbl': f"Terbilang: {terbilang_rupiah(kontrak['total_honor'])}",
    }
    tcs_total = get_tcs(tbl.rows[-1])
    for tc in tcs_total:
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
        '<<40% dari Jumlah SLS>>':       str(round(jml_sls * 0.4)),
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
