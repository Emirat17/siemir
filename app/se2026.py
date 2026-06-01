"""
Blueprint SE2026 — Kontrak Sensus Ekonomi 2026.
Menangani PPL (Petugas Pendataan Lapangan) dan PML (Petugas Pemeriksa Lapangan).
"""
import io, os
from datetime import date
from flask import (Blueprint, render_template, redirect, url_for,
                   request, flash, Response)
from app.auth import login_required, role_required
from app import db
from app.models import KontrakSE2026, WilayahSE2026, PPLDiwasiSE2026, NomorUrut

se2026 = Blueprint('se2026', __name__, url_prefix='/se2026')

TEMPLATE_PPL = os.path.join(os.path.dirname(__file__), 'templates',
                             '[1] Template_SPK Petugas Lapangan SE2026 final.docx')
TEMPLATE_PML = os.path.join(os.path.dirname(__file__), 'templates',
                             '[6] Template_SPK Pemeriksa Lapangan SE2026 final.docx')


# ── Helpers ──────────────────────────────────────────────────────

def next_nomor(jenis_upper):
    key = f'SE2026-{jenis_upper}'
    rec = NomorUrut.query.filter_by(jenis=key).first()
    if not rec:
        rec = NomorUrut(jenis=key, terakhir=0)
        db.session.add(rec)
        db.session.flush()
    rec.terakhir += 1
    return rec.terakhir

def simpan_wilayah(kontrak_id, form):
    for i in range(1, 9):  # 8 baris sesuai template terbaru
        kec  = form.get(f'kode_kecamatan_{i}', '').strip()
        desa = form.get(f'kode_desa_{i}', '').strip()
        if kec or desa:
            db.session.add(WilayahSE2026(
                kontrak_id=kontrak_id, urutan=i,
                kode_kecamatan=kec, kode_desa=desa,
                jumlah_sls=int(form.get(f'jumlah_sls_{i}', 0) or 0),
                jumlah_keluarga=int(form.get(f'jumlah_keluarga_{i}', 0) or 0),
            ))

def simpan_ppl_diawasi(kontrak_id, form):
    for i in range(1, 9):
        nama = form.get(f'nama_ppl_{i}', '').strip()
        if nama:
            db.session.add(PPLDiwasiSE2026(
                kontrak_id=kontrak_id, urutan=i,
                nama_ppl=nama,
                kode_kecamatan=form.get(f'kode_kec_ppl_{i}', '').strip(),
                kode_desa=form.get(f'kode_desa_ppl_{i}', '').strip(),
                jumlah_sls=int(form.get(f'jml_sls_ppl_{i}', 0) or 0),
            ))

def buat_kontrak_dari_form(jenis_upper, form, tanggal_spk, nomor_spk=None):
    k = KontrakSE2026(
        jenis=jenis_upper,
        nomor_spk=nomor_spk,
        nama=form.get('nama', '').strip(),
        alamat=form.get('alamat', '').strip(),
        tanggal_spk=tanggal_spk,
        total_honor=float(form.get('total_honor', 0) or 0),
        honor_1_ob=float(form.get('honor_1_ob', 0) or 0),
        honor_1_5_ob=float(form.get('honor_1_5_ob', 0) or 0),
        total_ganti_rugi=float(form.get('total_ganti_rugi', 0) or 0),
        jumlah_sls=int(form.get('jumlah_sls', 0) or 0),
        jumlah_usaha=int(form.get('jumlah_usaha', 0) or 0),
        jumlah_keluarga=int(form.get('jumlah_keluarga', 0) or 0),
    )
    return k


# ── Routes ───────────────────────────────────────────────────────

@se2026.route('/')
@login_required
def index():
    jml_ppl = KontrakSE2026.query.filter_by(jenis='PPL').count()
    jml_pml = KontrakSE2026.query.filter_by(jenis='PML').count()
    return render_template('se2026/index.html', jml_ppl=jml_ppl, jml_pml=jml_pml)


@se2026.route('/<jenis>')
@login_required
def daftar(jenis):
    jenis_upper = jenis.upper()
    if jenis_upper not in ('PPL', 'PML'):
        return redirect(url_for('se2026.index'))
    kontrak_list = (KontrakSE2026.query
                    .filter_by(jenis=jenis_upper)
                    .order_by(KontrakSE2026.id).all())
    return render_template('se2026/daftar.html',
                           jenis=jenis_upper, kontrak_list=kontrak_list,
                           today=date.today().isoformat())


@se2026.route('/<jenis>/tambah', methods=['GET', 'POST'])
@login_required
@role_required('admin_kabupaten', 'admin_fungsi')
def tambah(jenis):
    jenis_upper = jenis.upper()
    if jenis_upper not in ('PPL', 'PML'):
        return redirect(url_for('se2026.index'))

    if request.method == 'POST':
        tgl = date.fromisoformat(request.form['tanggal_spk'])
        nomor_manual = request.form.get('nomor_spk', '').strip()
        if not nomor_manual:
            n = next_nomor(jenis_upper)
            nomor_manual = f'{n:03d}'   # hanya angka; format lengkap ada di template Word

        k = buat_kontrak_dari_form(jenis_upper, request.form, tgl, nomor_manual)
        db.session.add(k)
        db.session.flush()

        if jenis_upper == 'PPL':
            simpan_wilayah(k.id, request.form)
        else:
            simpan_ppl_diawasi(k.id, request.form)

        db.session.commit()
        flash(f'Kontrak {jenis_upper} untuk {k.nama} berhasil disimpan. '
              f'Nomor: {k.nomor_spk}', 'success')
        return redirect(url_for('se2026.daftar', jenis=jenis.lower()))

    return render_template('se2026/form.html',
                           jenis=jenis_upper, k=None,
                           today=date.today().isoformat())


@se2026.route('/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@role_required('admin_kabupaten', 'admin_fungsi')
def edit(id):
    k = KontrakSE2026.query.get_or_404(id)
    if request.method == 'POST':
        k.nama             = request.form.get('nama', '').strip()
        k.alamat           = request.form.get('alamat', '').strip()
        k.tanggal_spk      = date.fromisoformat(request.form['tanggal_spk'])
        k.nomor_spk        = request.form.get('nomor_spk', k.nomor_spk).strip()
        k.total_honor      = float(request.form.get('total_honor', 0) or 0)
        k.honor_1_ob       = float(request.form.get('honor_1_ob', 0) or 0)
        k.honor_1_5_ob     = float(request.form.get('honor_1_5_ob', 0) or 0)
        k.total_ganti_rugi = float(request.form.get('total_ganti_rugi', 0) or 0)
        k.jumlah_sls       = int(request.form.get('jumlah_sls', 0) or 0)
        k.jumlah_usaha     = int(request.form.get('jumlah_usaha', 0) or 0)
        k.jumlah_keluarga  = int(request.form.get('jumlah_keluarga', 0) or 0)

        # Hapus dan isi ulang relasi
        if k.jenis == 'PPL':
            for w in k.wilayah_list: db.session.delete(w)
            db.session.flush()
            simpan_wilayah(k.id, request.form)
        else:
            for p in k.ppl_list: db.session.delete(p)
            db.session.flush()
            simpan_ppl_diawasi(k.id, request.form)

        db.session.commit()
        flash('Data kontrak SE2026 berhasil diperbarui.', 'success')
        return redirect(url_for('se2026.daftar', jenis=k.jenis.lower()))

    return render_template('se2026/form.html',
                           jenis=k.jenis, k=k,
                           today=k.tanggal_spk.isoformat() if k.tanggal_spk else date.today().isoformat())


@se2026.route('/<int:id>/hapus', methods=['POST'])
@login_required
@role_required('admin_kabupaten', 'admin_fungsi')
def hapus(id):
    k = KontrakSE2026.query.get_or_404(id)
    jenis = k.jenis.lower()
    nama  = k.nama
    db.session.delete(k)
    db.session.commit()
    flash(f'Kontrak SE2026 {nama} berhasil dihapus.', 'warning')
    return redirect(url_for('se2026.daftar', jenis=jenis))


@se2026.route('/<int:id>/spk.docx')
@login_required
def generate(id):
    from app.doc_generator import generate_spk_se2026
    k = KontrakSE2026.query.get_or_404(id)
    template = TEMPLATE_PPL if k.jenis == 'PPL' else TEMPLATE_PML

    data = {
        'nomor_spk':       k.nomor_spk or '',
        'tanggal_spk':     k.tanggal_spk or date.today(),
        'nama':            k.nama,
        'alamat':          k.alamat or '',
        'total_honor':     float(k.total_honor or 0),
        'honor_1_ob':      float(k.honor_1_ob or 0),
        'honor_1_5_ob':    float(k.honor_1_5_ob or 0),
        'total_ganti_rugi':float(k.total_ganti_rugi or 0),
        'jumlah_sls':      k.jumlah_sls or 0,
        'jumlah_usaha':    k.jumlah_usaha or 0,
        'jumlah_keluarga': k.jumlah_keluarga or 0,
        'wilayah': [{'kode_kecamatan': w.kode_kecamatan,
                     'kode_desa':      w.kode_desa,
                     'jumlah_sls':     w.jumlah_sls,
                     'jumlah_keluarga':w.jumlah_keluarga}
                    for w in k.wilayah_list],
        'ppl_list': [{'nama_ppl':       p.nama_ppl,
                      'kode_kecamatan': p.kode_kecamatan,
                      'kode_desa':      p.kode_desa,
                      'jumlah_sls':     p.jumlah_sls}
                     for p in k.ppl_list],
    }

    docx_bytes = generate_spk_se2026(data, template)
    nama_file  = f"SPK_{k.jenis}_{k.nama.replace(' ', '_')}.docx"
    return Response(docx_bytes,
        mimetype='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        headers={'Content-Disposition': f'attachment; filename="{nama_file}"'})


@se2026.route('/<jenis>/import', methods=['POST'])
@login_required
@role_required('admin_kabupaten', 'admin_fungsi')
def import_excel(jenis):
    import openpyxl
    jenis_upper = jenis.upper()
    file = request.files.get('file_excel')
    if not file or not file.filename.endswith('.xlsx'):
        flash('Upload file Excel (.xlsx) diperlukan.', 'danger')
        return redirect(url_for('se2026.daftar', jenis=jenis.lower()))

    tgl_str = request.form.get('tanggal_spk', date.today().isoformat())
    tanggal_spk = date.fromisoformat(tgl_str)

    # Helper: ambil nilai sel dengan aman
    def xval(row, idx, default=0):
        v = row[idx] if idx < len(row) else None
        return v if v is not None else default

    def xfloat(row, idx):
        v = xval(row, idx, 0)
        try:
            if isinstance(v, str):
                v = v.replace('.', '').replace(',', '.')
            return float(v)
        except (ValueError, TypeError):
            return 0.0

    def xint(row, idx):
        v = xval(row, idx, 0)
        try:
            return int(float(v))
        except (ValueError, TypeError):
            return 0

    def xstr(row, idx):
        """Konversi nilai sel ke string; float integer (1410010.0) → '1410010'."""
        v = xval(row, idx, '')
        if v is None or v == '':
            return ''
        if isinstance(v, float):
            return str(int(v)) if v == int(v) else str(v)
        return str(v).strip()

    wb = openpyxl.load_workbook(file, data_only=True)
    ws = wb.active
    berhasil = gagal = 0
    pesan_error = []

    for baris, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
        nama = xstr(row, 0)
        if not nama:
            continue
        try:
            n = next_nomor(jenis_upper)
            k = KontrakSE2026(
                jenis=jenis_upper,
                nama=nama,
                nomor_spk=f'{n:03d}',
                alamat=xstr(row, 1),
                tanggal_spk=tanggal_spk,
                total_honor=xfloat(row, 2),
                honor_1_ob=xfloat(row, 3),
                honor_1_5_ob=xfloat(row, 4),
                total_ganti_rugi=xfloat(row, 5),
                jumlah_sls=xint(row, 6),
                jumlah_usaha=xint(row, 7),
                jumlah_keluarga=xint(row, 8),
            )
            db.session.add(k)
            db.session.flush()

            if jenis_upper == 'PPL':
                for i in range(8):
                    base = 9 + i * 4
                    kec  = xstr(row, base)
                    desa = xstr(row, base + 1)
                    sls  = xint(row, base + 2)
                    kel  = xint(row, base + 3)
                    if kec or desa:
                        db.session.add(WilayahSE2026(
                            kontrak_id=k.id, urutan=i + 1,
                            kode_kecamatan=kec, kode_desa=desa,
                            jumlah_sls=sls, jumlah_keluarga=kel,
                        ))
            else:  # PML
                for i in range(8):
                    base     = 9 + i * 4
                    nama_ppl = xstr(row, base)
                    kec      = xstr(row, base + 1)
                    desa     = xstr(row, base + 2)
                    sls      = xint(row, base + 3)
                    if nama_ppl:
                        db.session.add(PPLDiwasiSE2026(
                            kontrak_id=k.id, urutan=i + 1,
                            nama_ppl=nama_ppl, kode_kecamatan=kec,
                            kode_desa=desa, jumlah_sls=sls,
                        ))
            berhasil += 1

        except Exception as e:
            db.session.rollback()
            gagal += 1
            pesan_error.append(f'Baris {baris} ({nama}): {e}')

    if berhasil:
        db.session.commit()
    msg = f'Import selesai: {berhasil} berhasil'
    if gagal:
        msg += f', {gagal} gagal'
    flash(msg + '.', 'success' if not gagal else 'warning')
    for pe in pesan_error[:3]:   # tampilkan maks 3 error detail
        flash(pe, 'danger')
    return redirect(url_for('se2026.daftar', jenis=jenis.lower()))


@se2026.route('/template/<jenis>.xlsx')
@login_required
def download_template(jenis):
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

    jenis_upper = jenis.upper()
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = f'Template {jenis_upper} SE2026'

    biru   = PatternFill('solid', fgColor='1341A0')
    muda   = PatternFill('solid', fgColor='BDD7EE')
    f_putih= Font(bold=True, color='FFFFFF', size=10)
    f_biru = Font(bold=True, color='1A3A6B', size=9)
    thin   = Side(style='thin', color='AAAAAA')
    bdr    = Border(left=thin, right=thin, top=thin, bottom=thin)
    center = Alignment(horizontal='center', vertical='center', wrap_text=True)

    def hdr(col, text, fill=biru, font=f_putih):
        c = ws.cell(row=1, column=col, value=text)
        c.fill, c.font, c.alignment, c.border = fill, font, center, bdr
        import openpyxl.utils as u
        ws.column_dimensions[u.get_column_letter(col)].width = 20

    kolom_umum = [
        'Nama Lengkap', 'Alamat', 'Total Honor (Rp)',
        'Honor 1 OB (Rp)', 'Honor 1,5 OB (Rp)', 'Total Ganti Rugi (Rp)',
        'Jumlah SLS (Total)', 'Jumlah Usaha (Total)', 'Jumlah Keluarga (Total)',
    ]
    for i, h in enumerate(kolom_umum, 1):
        hdr(i, h)

    if jenis_upper == 'PPL':
        for s in range(1, 9):  # 8 wilayah
            base = 9 + (s-1)*4
            for j, h in enumerate([f'Kode Kecamatan', f'Kode Desa',
                                    f'Jml SLS', f'Jml Keluarga']):
                hdr(base+j, f'Wilayah {s}\n{h}', fill=muda, font=f_biru)
        contoh_extra = ['1410010', '1410010001', 5, 20] + [''] * 28
    else:
        for s in range(1, 9):
            base = 9 + (s-1)*4
            for j, h in enumerate([f'Nama PPL {s}', f'Kode Kec {s}',
                                    f'Kode Desa {s}', f'Jml SLS {s}']):
                hdr(base+j, h, fill=muda, font=f_biru)
        contoh_extra = ['Budi Santoso', '1410010', '1410010001', 3] + [''] * 28

    ws.row_dimensions[1].height = 42

    # Baris contoh
    contoh = ['Nama Petugas Contoh', 'Jl. Contoh No. 1, Desa X',
              2500000, 1000000, 1500000, 2500000, 10, 15, 30] + contoh_extra
    for i, v in enumerate(contoh, 1):
        c = ws.cell(row=2, column=i, value=v)
        c.border = bdr

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return Response(buf.read(),
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        headers={'Content-Disposition':
                 f'attachment; filename="Template_SE2026_{jenis_upper}.xlsx"'})
