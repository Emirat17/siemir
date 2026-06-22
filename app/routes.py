from flask import Blueprint, render_template, redirect, url_for, request, flash, Response, jsonify, session
from app.auth import login_required, role_required, get_current_user
from app import db
from app.models import Petugas, Kontrak, Kegiatan, NomorUrut, DaftarKegiatan, BAST, BASTKegiatan, FUNGSI_KODE
import os
import re
from datetime import date, timedelta
import calendar
import io

main = Blueprint('main', __name__)

NAMA_BULAN = ['','Januari','Februari','Maret','April','Mei','Juni',
              'Juli','Agustus','September','Oktober','November','Desember']

def tanggal_surat_otomatis(bulan, tahun):
    """Hari terakhir bulan sebelum bulan kontrak."""
    if bulan == 1:
        b, t = 12, tahun - 1
    else:
        b, t = bulan - 1, tahun
    return date(t, b, calendar.monthrange(t, b)[1])

def tanggal_mulai_otomatis(bulan, tahun):
    """Tanggal 1 dari bulan kontrak."""
    return date(tahun, bulan, 1)

def tanggal_selesai_dari_kegiatan(kegiatan_list):
    """Tanggal selesai = tgl_selesai kegiatan paling akhir."""
    if not kegiatan_list:
        return None
    return max(k.tgl_selesai for k in kegiatan_list)

def tanggal_bast_otomatis(bulan_kontrak, tahun_kontrak):
    """Hari kerja pertama (Senin-Jumat) di tanggal 1 bulan setelah bulan kontrak."""
    if bulan_kontrak == 12:
        bulan_depan, tahun_depan = 1, tahun_kontrak + 1
    else:
        bulan_depan, tahun_depan = bulan_kontrak + 1, tahun_kontrak
    candidate = date(tahun_depan, bulan_depan, 1)
    while candidate.weekday() >= 5:  # lewati Sabtu & Minggu
        candidate += timedelta(days=1)
    return candidate

def buat_nomor_spk(nomor, kode_fungsi, tahun):
    return f"PK-{nomor}/{kode_fungsi}/VS.330/{tahun}"

def buat_nomor_bast(nomor, kode_fungsi, tahun):
    return f"BAST-{nomor}/{kode_fungsi}/VS.430/{tahun}"

def next_nomor_bast():
    """Counter BAST terpisah dari SPK. Dimulai dari 1, berlanjut antar bulan."""
    rec = NomorUrut.query.filter_by(jenis='BAST').first()
    if not rec:
        rec = NomorUrut(jenis='BAST', terakhir=0)
        db.session.add(rec)
        db.session.flush()
    rec.terakhir += 1
    return rec.terakhir


def ambil_urut_bast(bast):
    """Ambil nomor urut integer dari nomor BAST (mis: 'BAST-5/...' → 5)."""
    if bast.nomor_bast:
        try:
            return int(bast.nomor_bast.split('-')[1].split('/')[0])
        except (IndexError, ValueError):
            pass
    return None


def renomor_semua_bast():
    """
    Renomor ulang SEMUA BAST secara global berdasarkan urutan id (waktu dibuat).
    Dipanggil setiap kali BAST dihapus agar nomor urut selalu rapat tanpa gap.
    Counter NomorUrut disesuaikan ke jumlah BAST yang tersisa.
    """
    semua_bast = BAST.query.filter(
        BAST.nomor_bast.isnot(None),
        BAST.nomor_bast != ''
    ).order_by(BAST.id.asc()).all()

    for i, bast in enumerate(semua_bast, 1):
        # Ambil kode fungsi dari nomor yang sudah ada
        bagian = (bast.nomor_bast or '').split('/')
        kode   = bagian[1] if len(bagian) >= 2 else (bast.kontrak.kode_fungsi or '14.101')
        tahun  = bagian[3] if len(bagian) >= 4 else str(bast.tahun_bast)
        bast.nomor_bast = buat_nomor_bast(i, kode, tahun)

    # Sesuaikan counter
    rec = NomorUrut.query.filter_by(jenis='BAST').first()
    if rec:
        rec.terakhir = len(semua_bast)
    elif semua_bast:
        db.session.add(NomorUrut(jenis='BAST', terakhir=len(semua_bast)))

def ambil_nomor_urut(kontrak):
    """Ambil nomor urut dari nomor SPK yang sudah ada. Mengembalikan None untuk SPK bersufiks (mis. 107A)."""
    if kontrak.nomor_spk:
        try:
            return int(kontrak.nomor_spk.split('-')[1].split('/')[0])
        except (IndexError, ValueError):
            pass
    return None

def parse_nomor_bagian(nomor_spk):
    """Ekstrak (base_int, suffix) dari nomor SPK.
    'PK-107A/...' -> (107, 'A'),  'PK-108/...' -> (108, ''),  invalid -> (None, '')
    """
    if not nomor_spk:
        return None, ''
    try:
        bagian = nomor_spk.split('-')[1].split('/')[0]
        m = re.match(r'^(\d+)([A-Za-z]*)$', bagian)
        if m:
            return int(m.group(1)), m.group(2).upper()
    except (IndexError, ValueError):
        pass
    return None, ''

def cari_suffix_tersedia(nomor_dasar, kode_fungsi, tahun):
    """Cari huruf sufiks pertama (A, B, C...) yang belum terpakai untuk nomor_dasar."""
    for huruf in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ':
        if not Kontrak.query.filter_by(
            nomor_spk=f"PK-{nomor_dasar}{huruf}/{kode_fungsi}/VS.330/{tahun}"
        ).first():
            return huruf
    return None

def sort_key_nomor(nomor):
    """Natural sort key untuk nomor SPK/BAST: (base_int, suffix).
    'PK-107A/...' → (107, 'A'),  'BAST-11/...' → (11, ''),  None → (99999, '')
    """
    if not nomor:
        return (99999, '')
    try:
        bagian = nomor.split('-')[1].split('/')[0]
        m = re.match(r'^(\d+)([A-Za-z]*)$', bagian)
        if m:
            return (int(m.group(1)), m.group(2).upper())
    except (IndexError, ValueError):
        pass
    return (99999, '')

def next_nomor_global():
    """
    Ambil nomor berikutnya dari tabel NomorUrut.
    Dimulai dari 1 saat pertama kali, naik 1 setiap kontrak baru.
    Tidak terpengaruh oleh penghapusan kontrak (nomor baru selalu naik).
    """
    rec = NomorUrut.query.filter_by(jenis='SPK').first()
    if not rec:
        rec = NomorUrut(jenis='SPK', terakhir=0)
        db.session.add(rec)
        db.session.flush()
    rec.terakhir += 1
    return rec.terakhir

def renomor_semua(mulai_dari=1):
    """
    Renomor ulang kontrak sequential (tanpa sufiks) berdasarkan PERIODE
    (tahun, lalu bulan), dengan id sebagai pemecah seri dalam periode yang sama.
    Sehingga urutan nomor SPK sejalan dengan periode: SPK periode lebih awal
    selalu mendapat nomor lebih kecil. SPK bersufiks huruf (mis. PK-107A)
    dilewati dan nomornya dipertahankan.
    """
    semua = Kontrak.query.order_by(
        Kontrak.tahun.asc(), Kontrak.bulan.asc(), Kontrak.id.asc()
    ).all()
    sequential = [k for k in semua if ambil_nomor_urut(k) is not None]
    for i, k in enumerate(sequential, 1):
        k.nomor_spk = buat_nomor_spk(i, k.kode_fungsi or '14.101', k.tahun)
    rec = NomorUrut.query.filter_by(jenis='SPK').first()
    if rec:
        rec.terakhir = len(sequential)
    elif sequential:
        db.session.add(NomorUrut(jenis='SPK', terakhir=len(sequential)))

def update_nomor_fungsi(kontrak):
    """Update kode fungsi di nomor SPK/BAST jika fungsi dominan berubah."""
    if kontrak.nomor_spk and kontrak.kode_fungsi:
        bagian = kontrak.nomor_spk.split('/')
        if len(bagian) >= 2 and bagian[1] != kontrak.kode_fungsi:
            kontrak.nomor_spk  = kontrak.nomor_spk.replace(bagian[1], kontrak.kode_fungsi, 1)
        if kontrak.nomor_bast:
            bagian_b = kontrak.nomor_bast.split('/')
            if len(bagian_b) >= 2 and bagian_b[1] != kontrak.kode_fungsi:
                kontrak.nomor_bast = kontrak.nomor_bast.replace(bagian_b[1], kontrak.kode_fungsi, 1)

@main.route('/')
@login_required
def index():
    bulan_ini = date.today().month
    tahun_ini = date.today().year

    FUNGSI_LIST = ['Umum','Sosial','Produksi','Distribusi','Nerwilis','IPDS']

    # Progress per fungsi untuk bulan ini
    progress_fungsi = []
    for fungsi in FUNGSI_LIST:
        # Jumlah kontrak bulan ini untuk fungsi ini
        jml_kontrak = Kontrak.query.filter(
            Kontrak.bulan == bulan_ini,
            Kontrak.tahun == tahun_ini,
            Kontrak.nama_fungsi == fungsi
        ).count()

        # Jumlah BAST bulan ini yang berasal dari kontrak fungsi ini
        # (bulan_bast = bulan ini, berdasarkan kegiatan yang selesai bulan lalu)
        jml_bast = db.session.query(BAST).join(Kontrak).filter(
            BAST.bulan_bast == bulan_ini,
            BAST.tahun_bast == tahun_ini,
            Kontrak.nama_fungsi == fungsi
        ).count()

        # Jumlah kegiatan yang seharusnya di-BAST bulan ini (pending)
        # = kegiatan dengan tgl_selesai di bulan sebelumnya
        bulan_selesai = bulan_ini - 1 if bulan_ini > 1 else 12
        jml_pending_bast = db.session.query(Kegiatan).join(Kontrak).filter(
            Kontrak.nama_fungsi == fungsi,
            db.extract('month', Kegiatan.tgl_selesai) == bulan_selesai
        ).count()

        progress_fungsi.append({
            'fungsi':       fungsi,
            'jml_kontrak':  jml_kontrak,
            'jml_bast':     jml_bast,
        })

    # Total kontrak dan BAST bulan ini
    total_kontrak_bulan = Kontrak.query.filter_by(bulan=bulan_ini, tahun=tahun_ini).count()
    total_bast_bulan    = BAST.query.filter_by(bulan_bast=bulan_ini, tahun_bast=tahun_ini).count()
    total_kontrak_all   = Kontrak.query.count()

    # 5 kontrak terbaru
    kontrak_terbaru = Kontrak.query.order_by(Kontrak.dibuat.desc()).limit(5).all()

    return render_template('index.html',
        progress_fungsi=progress_fungsi,
        total_kontrak_bulan=total_kontrak_bulan,
        total_bast_bulan=total_bast_bulan,
        total_kontrak_all=total_kontrak_all,
        bulan_ini=bulan_ini,
        tahun_ini=tahun_ini,
        kontrak_terbaru=kontrak_terbaru,
        nama_bulan=NAMA_BULAN)

# ─── DOWNLOAD TEMPLATE EXCEL ─────────────────────────────────────
@main.route('/template-excel/<jenis>')
@login_required
@role_required('admin_kabupaten', 'admin_fungsi')
def download_template(jenis):
    import io as _io
    from openpyxl import load_workbook

    TEMPLATE_PATH = {
        'kegiatan': os.path.join(os.path.dirname(__file__),
                     '..', 'templates_excel', 'Template_Upload_Entri_Kegiatan.xlsx'),
        'kontrak':  os.path.join(os.path.dirname(__file__),
                     '..', 'templates_excel', 'Template_Upload_Entri_Kontrak.xlsx'),
    }
    if jenis not in TEMPLATE_PATH:
        return "Template tidak ditemukan", 404
    with open(TEMPLATE_PATH[jenis], 'rb') as f:
        data = f.read()
    nama = f"Template_Upload_Entri_{jenis.capitalize()}.xlsx"
    return Response(data,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        headers={'Content-Disposition': f'attachment; filename="{nama}"'})


# ─── UPLOAD EXCEL ENTRI KEGIATAN ─────────────────────────────────
@main.route('/entri-kegiatan/upload', methods=['POST'])
@login_required
@role_required('admin_kabupaten', 'admin_fungsi')
def upload_kegiatan():
    import io as _io
    from openpyxl import load_workbook

    file = request.files.get('file_excel')
    if not file or not file.filename.endswith('.xlsx'):
        flash('File tidak valid. Gunakan format .xlsx sesuai template.', 'danger')
        return redirect(url_for('main.entri_kegiatan'))

    try:
        wb = load_workbook(_io.BytesIO(file.read()), read_only=True, data_only=True)
        ws = wb.active
        rows = list(ws.iter_rows(min_row=5, values_only=True))  # mulai baris 5

        berhasil = 0
        lewati = 0
        error_list = []

        for ri, row in enumerate(rows, 5):
            # Skip baris kosong
            if not row or not row[0] or str(row[0]).strip() == '':
                continue

            try:
                fungsi_val  = str(row[0]).strip() if row[0] else ''
                bulan_val   = int(row[1]) if row[1] else 0
                tahun_val   = int(row[2]) if row[2] else 0
                nama_val    = str(row[3]).strip() if row[3] else ''
                tgl_m_raw   = row[4]
                tgl_s_raw   = row[5]
                satuan_val  = str(row[6]).strip() if row[6] else 'OH'
                vol_val     = int(row[7]) if row[7] else 1
                honor_val   = float(row[8]) if row[8] else 0
                akun_val    = str(row[9]).strip() if row[9] else ''
                # Kolom ke-11 (index 10): bulan pencairan — bisa nama bulan atau angka 1-12
                bln_cair_val = None
                if len(row) > 10 and row[10]:
                    _NAMA_BLN = ['januari','februari','maret','april','mei','juni',
                                 'juli','agustus','september','oktober','november','desember']
                    raw_bln = str(row[10]).strip()
                    # Coba parse sebagai nama bulan (dari dropdown)
                    try:
                        idx = _NAMA_BLN.index(raw_bln.lower()) + 1
                        bln_cair_val = idx
                    except ValueError:
                        # Coba parse sebagai angka
                        try:
                            bln_cair_int = int(float(raw_bln))
                            if 1 <= bln_cair_int <= 12:
                                bln_cair_val = bln_cair_int
                        except (ValueError, TypeError):
                            pass

                # Validasi wajib
                if not all([fungsi_val, bulan_val, tahun_val, nama_val, akun_val]):
                    error_list.append(f'Baris {ri}: kolom wajib tidak lengkap — dilewati')
                    lewati += 1
                    continue

                # Validasi fungsi
                if fungsi_val not in FUNGSI_KODE:
                    error_list.append(f'Baris {ri}: Fungsi "{fungsi_val}" tidak valid — dilewati')
                    lewati += 1
                    continue

                # Batasan admin_fungsi
                if session.get('user_role') == 'admin_fungsi' and                    fungsi_val != session.get('user_fungsi'):
                    error_list.append(f'Baris {ri}: Anda tidak punya akses fungsi "{fungsi_val}" — dilewati')
                    lewati += 1
                    continue

                # Parse tanggal
                def parse_tgl(val, default):
                    if isinstance(val, date): return val
                    if isinstance(val, str):
                        for fmt in ('%d/%m/%Y','%Y-%m-%d','%d-%m-%Y'):
                            try:
                                from datetime import datetime
                                return datetime.strptime(val.strip(), fmt).date()
                            except: pass
                    return default

                default_tgl = date(tahun_val, bulan_val, 1)
                tgl_m = parse_tgl(tgl_m_raw, default_tgl)
                tgl_s = parse_tgl(tgl_s_raw, default_tgl)

                # Cek duplikat
                existing = DaftarKegiatan.query.filter_by(
                    fungsi=fungsi_val, bulan=bulan_val,
                    tahun=tahun_val, nama_kegiatan=nama_val
                ).first()
                if existing:
                    lewati += 1
                    continue

                db.session.add(DaftarKegiatan(
                    fungsi=fungsi_val, bulan=bulan_val, tahun=tahun_val,
                    nama_kegiatan=nama_val, tgl_mulai=tgl_m, tgl_selesai=tgl_s,
                    satuan=satuan_val, volume_default=vol_val,
                    honor_satuan=honor_val, mata_akun=akun_val,
                    bulan_pencairan=bln_cair_val,
                ))
                berhasil += 1

            except Exception as e:
                error_list.append(f'Baris {ri}: Error — {str(e)}')
                lewati += 1

        db.session.commit()
        msg = f'{berhasil} kegiatan berhasil diimport.'
        if lewati: msg += f' {lewati} baris dilewati.'
        flash(msg, 'success' if berhasil > 0 else 'warning')
        if error_list:
            flash('Detail: ' + ' | '.join(error_list[:5]) +
                  (f' (+{len(error_list)-5} lainnya)' if len(error_list)>5 else ''), 'warning')

    except Exception as e:
        db.session.rollback()
        flash(f'Gagal membaca file: {str(e)}', 'danger')

    return redirect(url_for('main.entri_kegiatan'))


# ─── UPLOAD EXCEL ENTRI KONTRAK ──────────────────────────────────
@main.route('/entri-kontrak/upload', methods=['POST'])
@login_required
@role_required('admin_kabupaten', 'admin_fungsi')
def upload_kontrak():
    import io as _io
    from openpyxl import load_workbook
    from datetime import datetime

    file = request.files.get('file_excel')
    if not file or not file.filename.endswith('.xlsx'):
        flash('File tidak valid. Gunakan format .xlsx sesuai template.', 'danger')
        return redirect(url_for('main.entri_kontrak'))

    try:
        wb = load_workbook(_io.BytesIO(file.read()), read_only=True, data_only=True)
        ws = wb.active
        rows = list(ws.iter_rows(min_row=5, values_only=True))

        berhasil = 0
        lewati   = 0
        sbml_warning = []
        error_list   = []
        SBML = 3600000

        def parse_tgl(val, default):
            if isinstance(val, date): return val
            if isinstance(val, str):
                for fmt in ('%d/%m/%Y','%Y-%m-%d','%d-%m-%Y'):
                    try: return datetime.strptime(val.strip(), fmt).date()
                    except: pass
            return default

        for ri, row in enumerate(rows, 5):
            if not row or not row[0] or str(row[0]).strip() == '':
                continue
            try:
                nama_pt  = str(row[0]).strip()
                fungsi_v = str(row[1]).strip() if row[1] else ''
                bulan_v  = int(row[2]) if row[2] else 0
                tahun_v  = int(row[3]) if row[3] else 0
                nama_keg = str(row[4]).strip() if row[4] else ''
                vol_v    = int(row[5]) if row[5] else 1
                hsat_v   = float(row[6]) if row[6] else 0
                # ket_v  = str(row[7]) if row[7] else ''

                if not all([nama_pt, fungsi_v, bulan_v, tahun_v, nama_keg]):
                    error_list.append(f'Baris {ri}: data tidak lengkap — dilewati')
                    lewati += 1; continue

                if fungsi_v not in FUNGSI_KODE:
                    error_list.append(f'Baris {ri}: Fungsi "{fungsi_v}" tidak valid — dilewati')
                    lewati += 1; continue

                if session.get('user_role') == 'admin_fungsi' and                    fungsi_v != session.get('user_fungsi'):
                    error_list.append(f'Baris {ri}: Anda tidak punya akses fungsi "{fungsi_v}" — dilewati')
                    lewati += 1; continue

                # Cari petugas
                petugas = Petugas.query.filter(
                    db.func.lower(Petugas.nama) == nama_pt.lower()
                ).first()
                if not petugas:
                    error_list.append(f'Baris {ri}: Petugas "{nama_pt}" tidak ditemukan — dilewati')
                    lewati += 1; continue

                # Ambil honor dari master jika tidak diisi
                if hsat_v == 0:
                    master = DaftarKegiatan.query.filter_by(
                        fungsi=fungsi_v, bulan=bulan_v,
                        tahun=tahun_v, nama_kegiatan=nama_keg
                    ).first()
                    if master:
                        hsat_v = float(master.honor_satuan or 0)

                honor_total_keg = vol_v * hsat_v

                # Cari/buat kontrak
                kontrak = Kontrak.query.filter_by(
                    petugas_id=petugas.id, bulan=bulan_v, tahun=tahun_v
                ).first()

                tgl_surat = tanggal_surat_otomatis(bulan_v, tahun_v)
                tgl_mulai = tanggal_mulai_otomatis(bulan_v, tahun_v)
                is_baru   = False

                if kontrak is None:
                    nomor_baru = next_nomor_global()    # ambil SEBELUM add/flush
                    kontrak = Kontrak(
                        petugas_id=petugas.id, tanggal_surat=tgl_surat,
                        tanggal_mulai=tgl_mulai, tanggal_selesai=tgl_mulai,
                        bulan=bulan_v, tahun=tahun_v, total_ganti_rugi=0
                    )
                    db.session.add(kontrak)
                    db.session.flush()
                    is_baru = True

                # Ambil tanggal dari master
                default_tgl = date(tahun_v, bulan_v, 1)
                master_keg = DaftarKegiatan.query.filter_by(
                    fungsi=fungsi_v, bulan=bulan_v,
                    tahun=tahun_v, nama_kegiatan=nama_keg
                ).first()
                tgl_m = master_keg.tgl_mulai  if master_keg else default_tgl
                tgl_s = master_keg.tgl_selesai if master_keg else default_tgl
                satuan_v = master_keg.satuan   if master_keg else 'OH'
                akun_v   = master_keg.mata_akun if master_keg else '521213'

                # Cek duplikat kegiatan
                dup = Kegiatan.query.filter_by(
                    kontrak_id=kontrak.id,
                    fungsi=fungsi_v,
                    nama_kegiatan=nama_keg
                ).first()
                if dup:
                    lewati += 1; continue

                urutan = len(kontrak.kegiatan_list)
                db.session.add(Kegiatan(
                    kontrak_id=kontrak.id, fungsi=fungsi_v,
                    nama_kegiatan=nama_keg, tgl_mulai=tgl_m, tgl_selesai=tgl_s,
                    volume=vol_v, satuan=satuan_v, honor_satuan=hsat_v,
                    honor_total=honor_total_keg, mata_akun=akun_v, urutan=urutan
                ))
                db.session.flush()

                # Update kontrak
                kontrak.tanggal_mulai = tanggal_mulai_otomatis(bulan_v, tahun_v)
                tgl_akhir = tanggal_selesai_dari_kegiatan(kontrak.kegiatan_list)
                if tgl_akhir: kontrak.tanggal_selesai = tgl_akhir
                db.session.expire(kontrak)
                kontrak.hitung_total_dan_fungsi()
                kontrak.total_ganti_rugi = kontrak.total_honor

                if is_baru:
                    kontrak.nomor_spk  = buat_nomor_spk(nomor_baru, kontrak.kode_fungsi or '14.101', tahun_v)
                    # nomor_bast di-generate saat entri BAST
                else:
                    update_nomor_fungsi(kontrak)

                # Cek SBML
                if float(kontrak.total_honor) > SBML:
                    sbml_warning.append(f'{nama_pt} (Rp {int(kontrak.total_honor):,})')

                berhasil += 1

            except Exception as e:
                error_list.append(f'Baris {ri}: {str(e)}')
                lewati += 1

        # Renomor ulang agar urutan nomor SPK mengikuti periode
        renomor_semua()
        db.session.commit()

        msg = f'{berhasil} baris kegiatan kontrak berhasil diimport.'
        if lewati: msg += f' {lewati} baris dilewati.'
        flash(msg, 'success' if berhasil > 0 else 'warning')
        if sbml_warning:
            flash('⚠ Melebihi SBML (Rp 3.600.000): ' + ', '.join(sbml_warning[:5]), 'warning')
        if error_list:
            flash('Detail error: ' + ' | '.join(error_list[:5]) +
                  (f' (+{len(error_list)-5} lainnya)' if len(error_list)>5 else ''), 'warning')

    except Exception as e:
        db.session.rollback()
        flash(f'Gagal membaca file: {str(e)}', 'danger')

    return redirect(url_for('main.entri_kontrak'))



def auto_generate_bast(kontrak):
    """
    Generate BAST otomatis setelah entri kontrak,
    berdasarkan bulan_pencairan yang sudah diset di DaftarKegiatan.
    Nomor BAST belum di-assign (masih kosong) — akan di-assign saat Generate & Merge.
    """
    from collections import defaultdict

    # Kelompokkan kegiatan berdasarkan bulan_pencairan
    kegiatan_per_bulan = defaultdict(list)
    for k in kontrak.kegiatan_list:
        # Cari bulan_pencairan dari DaftarKegiatan master
        dk = DaftarKegiatan.query.filter_by(
            nama_kegiatan=k.nama_kegiatan,
            fungsi=k.fungsi,
            bulan=kontrak.bulan,
            tahun=kontrak.tahun
        ).first()
        if dk and dk.bulan_pencairan:
            bln_cair = dk.bulan_pencairan
            thn_cair = kontrak.tahun if bln_cair >= kontrak.bulan else kontrak.tahun + 1
        else:
            # Fallback: bulan setelah tgl_selesai
            bln_cair, thn_cair = bulan_pencairan_bast(k.tgl_selesai)
        kegiatan_per_bulan[(bln_cair, thn_cair)].append(k)

    for (bln_cair, thn_cair), keg_list in kegiatan_per_bulan.items():
        # Cek apakah BAST bulan ini sudah ada untuk kontrak ini
        bast_existing = BAST.query.filter_by(
            kontrak_id=kontrak.id,
            bulan_bast=bln_cair,
            tahun_bast=thn_cair
        ).first()

        if bast_existing:
            # Perbarui kegiatan yang ada (hapus lama, tambah baru)
            for bk in bast_existing.kegiatan_list:
                db.session.delete(bk)
            db.session.flush()
            bast = bast_existing
        else:
            tgl_bast = tanggal_bast_otomatis(
                bln_cair - 1 if bln_cair > 1 else 12,
                thn_cair if bln_cair > 1 else thn_cair - 1
            )
            bast = BAST(
                kontrak_id   = kontrak.id,
                bulan_bast   = bln_cair,
                tahun_bast   = thn_cair,
                tanggal_bast = tgl_bast,
                nomor_bast   = '',  # kosong — akan di-assign saat Generate & Merge
            )
            db.session.add(bast)
            db.session.flush()

        for k in keg_list:
            # Cek duplikat sebelum add
            dup = BASTKegiatan.query.filter_by(
                bast_id=bast.id, kegiatan_id=k.id
            ).first()
            if not dup:
                db.session.add(BASTKegiatan(bast_id=bast.id, kegiatan_id=k.id))
        db.session.flush()
        bast.hitung_total()


# ─── ENTRI KEGIATAN (master kegiatan per fungsi per bulan) ───────
@main.route('/entri-kegiatan', methods=['GET', 'POST'])
@login_required
@role_required('admin_kabupaten', 'admin_fungsi')
def entri_kegiatan():
    """Pendaftaran kegiatan per fungsi per bulan sebagai master data."""
    fungsi_list = list(FUNGSI_KODE.keys())
    bulan = request.args.get('bulan', type=int, default=date.today().month)
    tahun = request.args.get('tahun', type=int, default=date.today().year)

    # Batasi admin_fungsi hanya lihat fungsinya sendiri
    fungsi_filter = session.get('user_fungsi') if session.get('user_role') == 'admin_fungsi' else None

    if request.method == 'POST':
        action = request.form.get('action')

        if action == 'filter':
            bulan = int(request.form.get('bulan', bulan))
            tahun = int(request.form.get('tahun', tahun))
            return redirect(url_for('main.entri_kegiatan', bulan=bulan, tahun=tahun))

        elif action == 'tambah':
            bulan_form = int(request.form['bulan'])
            tahun_form = int(request.form['tahun'])
            fungsi_form = request.form['fungsi']

            # Admin fungsi hanya bisa tambah kegiatan sesuai fungsinya
            if session.get('user_role') == 'admin_fungsi' and fungsi_form != session.get('user_fungsi'):
                flash('Anda hanya dapat menambah kegiatan untuk fungsi Anda sendiri.', 'danger')
                return redirect(url_for('main.entri_kegiatan', bulan=bulan_form, tahun=tahun_form))

            nama_list = request.form.getlist('nama_kegiatan')
            for i, nama in enumerate(nama_list):
                if not nama.strip():
                    continue
                tgl_m_raw = request.form.getlist('tgl_mulai')[i] if i < len(request.form.getlist('tgl_mulai')) else ''
                tgl_s_raw = request.form.getlist('tgl_selesai')[i] if i < len(request.form.getlist('tgl_selesai')) else ''
                bln_cair_list = request.form.getlist('bulan_pencairan')
                bln_cair = int(bln_cair_list[i]) if i < len(bln_cair_list) and bln_cair_list[i] else None
                keg = DaftarKegiatan(
                    fungsi        = fungsi_form,
                    bulan         = bulan_form,
                    tahun         = tahun_form,
                    nama_kegiatan = nama.strip(),
                    tgl_mulai     = date.fromisoformat(tgl_m_raw) if tgl_m_raw else date(tahun_form, bulan_form, 1),
                    tgl_selesai   = date.fromisoformat(tgl_s_raw) if tgl_s_raw else date(tahun_form, bulan_form, 1),
                    satuan        = request.form.getlist('satuan')[i],
                    volume_default= int(request.form.getlist('volume_default')[i] or 1),
                    honor_satuan  = float(request.form.getlist('honor_satuan')[i] or 0),
                    mata_akun     = request.form.getlist('mata_akun')[i].strip(),
                    bulan_pencairan = bln_cair,
                )
                db.session.add(keg)
            db.session.commit()
            flash(f'{len([n for n in nama_list if n.strip()])} kegiatan berhasil didaftarkan.', 'success')
            return redirect(url_for('main.entri_kegiatan', bulan=bulan_form, tahun=tahun_form))

        elif action == 'hapus':
            keg_id = int(request.form['keg_id'])
            keg = DaftarKegiatan.query.get_or_404(keg_id)
            db.session.delete(keg)
            db.session.commit()
            flash('Kegiatan dihapus dari daftar.', 'warning')
            return redirect(url_for('main.entri_kegiatan', bulan=bulan, tahun=tahun))

        elif action == 'edit':
            keg_id      = int(request.form['keg_id'])
            keg         = DaftarKegiatan.query.get_or_404(keg_id)

            # Admin fungsi hanya bisa edit kegiatan fungsinya sendiri
            if session.get('user_role') == 'admin_fungsi' and \
               keg.fungsi != session.get('user_fungsi'):
                flash('Anda tidak memiliki akses untuk mengedit kegiatan fungsi lain.', 'danger')
                return redirect(url_for('main.entri_kegiatan', bulan=keg.bulan, tahun=keg.tahun))

            tgl_m_raw   = request.form.get('tgl_mulai', '')
            tgl_s_raw   = request.form.get('tgl_selesai', '')
            keg.nama_kegiatan  = request.form['nama_kegiatan'].strip()
            keg.tgl_mulai      = date.fromisoformat(tgl_m_raw) if tgl_m_raw else keg.tgl_mulai
            keg.tgl_selesai    = date.fromisoformat(tgl_s_raw) if tgl_s_raw else keg.tgl_selesai
            keg.satuan         = request.form['satuan']
            keg.volume_default = int(request.form.get('volume_default', 1) or 1)
            keg.honor_satuan   = float(request.form.get('honor_satuan', 0) or 0)
            keg.mata_akun      = request.form['mata_akun'].strip()
            bln_cair_edit = request.form.get('bulan_pencairan', '')
            keg.bulan_pencairan = int(bln_cair_edit) if bln_cair_edit else None
            db.session.commit()
            flash(f'Kegiatan "{keg.nama_kegiatan}" berhasil diperbarui.', 'success')
            return redirect(url_for('main.entri_kegiatan', bulan=keg.bulan, tahun=keg.tahun))

    # Ambil daftar kegiatan sesuai filter
    query = DaftarKegiatan.query.filter_by(bulan=bulan, tahun=tahun)
    if fungsi_filter:
        query = query.filter_by(fungsi=fungsi_filter)
    daftar = query.order_by(DaftarKegiatan.fungsi, DaftarKegiatan.nama_kegiatan).all()

    return render_template('entri_kegiatan.html',
        daftar=daftar, fungsi_list=fungsi_list,
        fungsi_filter=fungsi_filter,
        bulan=bulan, tahun=tahun, nama_bulan=NAMA_BULAN)

@main.route('/api/daftar-kegiatan')
@login_required
@role_required('admin_kabupaten', 'admin_fungsi')
def api_daftar_kegiatan():
    """API: ambil daftar kegiatan per fungsi+bulan+tahun untuk dropdown di entri kontrak."""
    fungsi = request.args.get('fungsi')
    bulan  = request.args.get('bulan', type=int)
    tahun  = request.args.get('tahun', type=int)
    if not all([fungsi, bulan, tahun]):
        return jsonify([])
    daftar = DaftarKegiatan.query.filter_by(
        fungsi=fungsi, bulan=bulan, tahun=tahun
    ).order_by(DaftarKegiatan.nama_kegiatan).all()
    return jsonify([{
        'id':             k.id,
        'nama_kegiatan':  k.nama_kegiatan,
        'tgl_mulai':      k.tgl_mulai.isoformat(),
        'tgl_selesai':    k.tgl_selesai.isoformat(),
        'satuan':         k.satuan,
        'volume_default': k.volume_default,
        'honor_satuan':   float(k.honor_satuan),
        'mata_akun':      k.mata_akun,
    } for k in daftar])


@main.route('/entri-kontrak', methods=['GET', 'POST'])
@login_required
@role_required('admin_kabupaten', 'admin_fungsi')
def entri_kontrak():
    petugas_list = Petugas.query.order_by(Petugas.nama).all()
    fungsi_list  = list(FUNGSI_KODE.keys())
    if request.method == 'POST':
        fungsi_dipilih = request.form['fungsi']
        petugas_id     = int(request.form['petugas_id'])
        bulan          = int(request.form['bulan'])
        tahun          = int(request.form['tahun'])
        ganti_rugi     = 0  # akan dihitung otomatis dari total_honor setelah kegiatan disimpan
        tgl_surat = tanggal_surat_otomatis(bulan, tahun)
        tgl_mulai_otomatis = tanggal_mulai_otomatis(bulan, tahun)

        kontrak = Kontrak.query.filter_by(petugas_id=petugas_id, bulan=bulan, tahun=tahun).first()
        if kontrak is None:
            nomor_baru    = next_nomor_global()          # ambil nomor SEBELUM flush
            kontrak = Kontrak(petugas_id=petugas_id, tanggal_surat=tgl_surat,
                tanggal_mulai=tgl_mulai_otomatis,
                tanggal_selesai=tgl_mulai_otomatis,
                bulan=bulan, tahun=tahun, total_ganti_rugi=0)
            db.session.add(kontrak)
            db.session.flush()
            is_baru      = True
            nomor_is_baru = nomor_baru
        else:
            is_baru       = False
            nomor_is_baru = None
        urutan_mulai = len(kontrak.kegiatan_list)
        nama_list    = request.form.getlist('nama_kegiatan')
        vol_list     = request.form.getlist('volume')
        hsat_list    = request.form.getlist('honor_satuan')
        sat_list     = request.form.getlist('satuan')
        akun_list    = request.form.getlist('mata_akun')
        tgl_m_list   = request.form.getlist('tgl_mulai')
        tgl_s_list   = request.form.getlist('tgl_selesai')

        for i, nama in enumerate(nama_list):
            if not nama.strip(): continue
            vol  = int(vol_list[i] or 1)
            hsat = float(hsat_list[i] or 0)

            # Selalu cari master kegiatan berdasarkan nama untuk ambil data lengkap
            dk = DaftarKegiatan.query.filter_by(
                nama_kegiatan=nama.strip(), fungsi=fungsi_dipilih,
                bulan=bulan, tahun=tahun
            ).first()

            # Ambil hsat dari master jika belum terisi atau 0
            if (hsat == 0) and dk:
                hsat = float(dk.honor_satuan or 0)

            # Ambil satuan dan mata akun dari master jika belum terisi
            satuan_val = sat_list[i] if i < len(sat_list) and sat_list[i] else (dk.satuan if dk else 'OH')
            akun_val   = akun_list[i] if i < len(akun_list) and akun_list[i] else (dk.mata_akun if dk else '521213')

            # Selalu hitung honor_total di server (jangan percaya dari client)
            honor_total_calc = vol * hsat

            # Ambil tanggal dari hidden field, fallback ke master, fallback ke default
            def _parse_tgl(raw, fallback):
                if raw and raw.strip():
                    try: return date.fromisoformat(raw.strip())
                    except: pass
                return fallback

            default_tgl = tanggal_mulai_otomatis(bulan, tahun)
            tgl_m_raw   = tgl_m_list[i] if i < len(tgl_m_list) else ''
            tgl_s_raw   = tgl_s_list[i] if i < len(tgl_s_list) else ''
            tgl_m = _parse_tgl(tgl_m_raw, dk.tgl_mulai   if dk else default_tgl)
            tgl_s = _parse_tgl(tgl_s_raw, dk.tgl_selesai if dk else default_tgl)

            db.session.add(Kegiatan(
                kontrak_id=kontrak.id, fungsi=fungsi_dipilih, nama_kegiatan=nama.strip(),
                tgl_mulai=tgl_m, tgl_selesai=tgl_s,
                volume=vol, satuan=satuan_val,
                honor_satuan=hsat, honor_total=honor_total_calc,
                mata_akun=akun_val, urutan=urutan_mulai+i))

        # Flush SETELAH semua kegiatan selesai di-add (bukan di dalam loop)
        db.session.flush()
        # Expire kontrak agar kegiatan_list di-reload dari DB (termasuk yang baru di-add)
        db.session.expire(kontrak)
        # Update tanggal_mulai & tanggal_selesai otomatis dari semua kegiatan
        kontrak.tanggal_mulai = tanggal_mulai_otomatis(kontrak.bulan, kontrak.tahun)
        tgl_selesai_keg = tanggal_selesai_dari_kegiatan(kontrak.kegiatan_list)
        if tgl_selesai_keg:
            kontrak.tanggal_selesai = tgl_selesai_keg
        kontrak.hitung_total_dan_fungsi()
        # Total ganti rugi = total honor (otomatis, bisa di-override lewat Edit Kontrak)
        kontrak.total_ganti_rugi = kontrak.total_honor
        if is_baru:
            kontrak.nomor_spk  = buat_nomor_spk(nomor_is_baru, kontrak.kode_fungsi or '14.101', tahun)
            # nomor_bast TIDAK di-generate saat entri kontrak.
            # Akan di-generate saat entri BAST dengan counter terpisah.
        else:
            update_nomor_fungsi(kontrak)
        # Auto-generate BAST berdasarkan bulan_pencairan dari DaftarKegiatan
        db.session.flush()
        auto_generate_bast(kontrak)
        # Renomor ulang agar urutan nomor SPK mengikuti periode
        if is_baru:
            renomor_semua()
        db.session.commit()
        petugas = Petugas.query.get(petugas_id)
        msg = (f'Kontrak baru dibuat untuk {petugas.nama} — {NAMA_BULAN[bulan]} {tahun}. SPK: {kontrak.nomor_spk}' if is_baru
               else f'Kegiatan fungsi {fungsi_dipilih} ditambahkan ke kontrak {petugas.nama} — {NAMA_BULAN[bulan]} {tahun}.')
        flash(msg, 'success')
        return redirect(url_for('main.detail_kontrak', id=kontrak.id))
    return render_template('entri_kontrak.html', petugas_list=petugas_list, fungsi_list=fungsi_list,
        nama_bulan=NAMA_BULAN, bulan_default=date.today().month,
        tahun_default=date.today().year, fungsi_kode=FUNGSI_KODE)

@main.route('/api/cek-kontrak')
@login_required
@role_required('admin_kabupaten', 'admin_fungsi')
def api_cek_kontrak():
    petugas_id = request.args.get('petugas_id', type=int)
    bulan      = request.args.get('bulan', type=int)
    tahun      = request.args.get('tahun', type=int)
    if not all([petugas_id, bulan, tahun]):
        return jsonify({'ada': False})
    k = Kontrak.query.filter_by(petugas_id=petugas_id, bulan=bulan, tahun=tahun).first()
    if k:
        return jsonify({'ada': True, 'nomor_spk': k.nomor_spk,
            'total_honor': float(k.total_honor), 'fungsi_dominan': k.nama_fungsi,
            'jumlah_kegiatan': len(k.kegiatan_list),
            'kegiatan': [{'fungsi': g.fungsi, 'nama': g.nama_kegiatan,
                          'honor_total': float(g.honor_total)} for g in k.kegiatan_list]})
    return jsonify({'ada': False})

@main.route('/kegiatan/edit/<int:id>', methods=['GET', 'POST'])
@login_required
@role_required('admin_kabupaten', 'admin_fungsi')
def edit_kegiatan(id):
    keg = Kegiatan.query.get_or_404(id)
    fungsi_list = list(FUNGSI_KODE.keys())
    if request.method == 'POST':
        vol  = int(request.form['volume'] or 1)
        hsat = float(request.form['honor_satuan'] or 0)
        keg.fungsi=request.form['fungsi']; keg.nama_kegiatan=request.form['nama_kegiatan']
        keg.tgl_mulai=date.fromisoformat(request.form['tgl_mulai'])
        keg.tgl_selesai=date.fromisoformat(request.form['tgl_selesai'])
        keg.volume=vol; keg.satuan=request.form['satuan']
        keg.honor_satuan=hsat; keg.honor_total=vol*hsat
        keg.mata_akun=request.form['mata_akun']
        db.session.flush()
        keg.kontrak.tanggal_mulai = tanggal_mulai_otomatis(keg.kontrak.bulan, keg.kontrak.tahun)
        tgl_selesai_keg = tanggal_selesai_dari_kegiatan(keg.kontrak.kegiatan_list)
        if tgl_selesai_keg:
            keg.kontrak.tanggal_selesai = tgl_selesai_keg
        db.session.expire(keg.kontrak)
        keg.kontrak.hitung_total_dan_fungsi()
        keg.kontrak.total_ganti_rugi = keg.kontrak.total_honor  # sync otomatis
        update_nomor_fungsi(keg.kontrak)
        db.session.commit()
        flash('Kegiatan berhasil diperbarui.', 'success')
        return redirect(url_for('main.detail_kontrak', id=keg.kontrak_id))
    return render_template('kegiatan/form_edit.html', keg=keg, fungsi_list=fungsi_list)

@main.route('/kegiatan/hapus/<int:id>', methods=['POST'])
@login_required
@role_required('admin_kabupaten', 'admin_fungsi')
def hapus_kegiatan(id):
    keg = Kegiatan.query.get_or_404(id)
    kontrak = keg.kontrak
    db.session.delete(keg)
    db.session.flush()
    kontrak.tanggal_mulai = tanggal_mulai_otomatis(kontrak.bulan, kontrak.tahun)
    tgl_selesai_keg = tanggal_selesai_dari_kegiatan(kontrak.kegiatan_list)
    if tgl_selesai_keg:
        kontrak.tanggal_selesai = tgl_selesai_keg
    db.session.expire(kontrak)
    kontrak.hitung_total_dan_fungsi()
    kontrak.total_ganti_rugi = kontrak.total_honor  # sync otomatis
    update_nomor_fungsi(kontrak)
    db.session.commit()
    flash('Kegiatan berhasil dihapus.', 'success')
    return redirect(url_for('main.detail_kontrak', id=kontrak.id))

@main.route('/kontrak/edit/<int:id>', methods=['GET', 'POST'])
@login_required
@role_required('admin_kabupaten', 'admin_fungsi')
def edit_kontrak(id):
    kontrak = Kontrak.query.get_or_404(id)
    if request.method == 'POST':
        kontrak.tanggal_mulai    = date.fromisoformat(request.form['tanggal_mulai'])
        kontrak.tanggal_selesai  = date.fromisoformat(request.form['tanggal_selesai'])
        kontrak.total_ganti_rugi = float(request.form.get('total_ganti_rugi', 0))
        kontrak.tanggal_surat    = tanggal_surat_otomatis(kontrak.bulan, kontrak.tahun)
        db.session.commit()
        flash('Data kontrak berhasil diperbarui.', 'success')
        return redirect(url_for('main.detail_kontrak', id=kontrak.id))
    pos_lama = ambil_nomor_urut(kontrak)  # None jika SPK sudah bersufiks
    return render_template('kontrak/form_edit.html', kontrak=kontrak,
                           nama_bulan=NAMA_BULAN, pos_lama=pos_lama)

@main.route('/kontrak/<int:id>/ubah-nomor', methods=['POST'])
@login_required
@role_required('admin_kabupaten', 'admin_fungsi')
def ubah_nomor_spk(id):
    kontrak = Kontrak.query.get_or_404(id)
    nomor_dasar = request.form.get('nomor_dasar', type=int)
    pos_lama    = ambil_nomor_urut(kontrak)

    # Validasi dasar
    if not nomor_dasar or nomor_dasar < 1:
        flash('Masukkan nomor dasar yang valid.', 'danger')
        return redirect(url_for('main.edit_kontrak', id=id))
    if pos_lama is None:
        flash('SPK ini sudah bersufiks huruf dan tidak dapat diubah lagi.', 'danger')
        return redirect(url_for('main.edit_kontrak', id=id))
    if nomor_dasar >= pos_lama:
        flash(f'Nomor dasar harus lebih kecil dari nomor urut SPK saat ini ({pos_lama}).', 'danger')
        return redirect(url_for('main.edit_kontrak', id=id))

    # Cek nomor_dasar ada sebagai SPK sequential di database
    spk_dasar = next(
        (k for k in Kontrak.query.all()
         if parse_nomor_bagian(k.nomor_spk) == (nomor_dasar, '')),
        None
    )
    if not spk_dasar:
        flash(f'SPK dengan nomor urut {nomor_dasar} tidak ditemukan di database.', 'danger')
        return redirect(url_for('main.edit_kontrak', id=id))

    # Cari sufiks yang tersedia (A, B, C, ...)
    kode = kontrak.kode_fungsi or '14.101'
    suffix = cari_suffix_tersedia(nomor_dasar, kode, kontrak.tahun)
    if not suffix:
        flash('Semua sufiks (A-Z) sudah terpakai untuk nomor ini.', 'danger')
        return redirect(url_for('main.edit_kontrak', id=id))

    # Ubah nomor SPK ini menjadi sufiks
    kontrak.nomor_spk = f"PK-{nomor_dasar}{suffix}/{kode}/VS.330/{kontrak.tahun}"

    # Geser semua SPK sequential dengan posisi > pos_lama turun 1
    for k in Kontrak.query.all():
        if k.id == kontrak.id:
            continue
        base, sfx = parse_nomor_bagian(k.nomor_spk)
        if base is not None and sfx == '' and base > pos_lama:
            k.nomor_spk = buat_nomor_spk(base - 1, k.kode_fungsi or '14.101', k.tahun)

    # Kurangi counter NomorUrut
    rec = NomorUrut.query.filter_by(jenis='SPK').first()
    if rec and rec.terakhir > 0:
        rec.terakhir -= 1

    db.session.commit()
    flash(
        f'Nomor SPK berhasil diubah ke PK-{nomor_dasar}{suffix}/{kode}/VS.330/{kontrak.tahun}. '
        f'SPK dengan nomor di atas {pos_lama} telah digeser otomatis.',
        'success'
    )
    return redirect(url_for('main.detail_kontrak', id=id))

@main.route('/kontrak/hapus/<int:id>', methods=['POST'])
@login_required
@role_required('admin_kabupaten')
def hapus_kontrak(id):
    kontrak = Kontrak.query.get_or_404(id)
    # Ambil nomor urut kontrak yang akan dihapus
    nomor_dihapus = ambil_nomor_urut(kontrak)
    db.session.delete(kontrak)
    db.session.flush()
    # Renomor semua kontrak dari posisi yang dihapus
    if nomor_dihapus:
        renomor_semua(nomor_dihapus)
    db.session.commit()
    flash('Kontrak berhasil dihapus dan nomor diperbarui.', 'warning')
    return redirect(url_for('main.daftar_kontrak'))

@main.route('/kontrak/renomor-periode', methods=['POST'])
@login_required
@role_required('admin_kabupaten')
def renomor_periode_kontrak():
    """Urutkan ulang nomor SPK seluruh kontrak mengikuti periode (tahun, bulan)."""
    renomor_semua()
    db.session.commit()
    flash('Nomor SPK berhasil diurutkan ulang mengikuti periode.', 'success')
    return redirect(url_for('main.daftar_kontrak'))

@main.route('/kontrak/<int:id>/spk.docx')
@login_required
def generate_spk(id):
    from app.doc_generator import generate_spk as gen_spk
    kontrak = Kontrak.query.get_or_404(id)
    template = os.path.join(os.path.dirname(__file__), 'templates', 'DOKUMEN_SPK.docx')
    data = {
        'nomor_spk':       kontrak.nomor_spk,
        'nomor_bast':      kontrak.nomor_bast,
        'bulan':           kontrak.bulan,
        'tahun':           kontrak.tahun,
        'tanggal_surat':   kontrak.tanggal_surat,
        'tanggal_mulai':   kontrak.tanggal_mulai,
        'tanggal_selesai': kontrak.tanggal_selesai,
        'petugas_nama':    kontrak.petugas.nama,
        'petugas_jabatan': kontrak.petugas.jabatan or 'Mitra',
        'petugas_alamat':  kontrak.petugas.alamat or '-',
        'total_honor':     float(kontrak.total_honor),
        'total_ganti_rugi': float(kontrak.total_ganti_rugi or 0),
        'kegiatan_list': [{
            'nama_kegiatan': k.nama_kegiatan,
            'tgl_mulai':     k.tgl_mulai,
            'tgl_selesai':   k.tgl_selesai,
            'volume':        k.volume,
            'satuan':        k.satuan,
            'honor_satuan':  float(k.honor_satuan),
            'honor_total':   float(k.honor_total),
            'mata_akun':     k.mata_akun,
        } for k in sorted(kontrak.kegiatan_list, key=lambda x: x.urutan)],
    }
    docx_bytes = gen_spk(data, template)
    nama = f"SPK_{kontrak.nomor_spk.replace('/', '-')}.docx"
    return Response(docx_bytes,
        mimetype='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        headers={'Content-Disposition': f'attachment; filename="{nama}"'})

@main.route('/kontrak/<int:id>/bast.docx')
@login_required
def generate_bast(id):
    from app.doc_generator import generate_bast as gen_bast
    kontrak = Kontrak.query.get_or_404(id)
    template = os.path.join(os.path.dirname(__file__), 'templates', 'DOKUMEN_BAST.docx')
    data = {
        'nomor_spk':       kontrak.nomor_spk,
        'nomor_bast':      kontrak.nomor_bast,
        'bulan':           kontrak.bulan,
        'tahun':           kontrak.tahun,
        'tanggal_surat':   kontrak.tanggal_surat,
        'tanggal_mulai':   kontrak.tanggal_mulai,
        'tanggal_selesai': kontrak.tanggal_selesai,
        'petugas_nama':    kontrak.petugas.nama,
        'petugas_jabatan': kontrak.petugas.jabatan or 'Mitra',
        'petugas_alamat':  kontrak.petugas.alamat or '-',
        'total_honor':     float(kontrak.total_honor),
        'kegiatan_list': [{
            'nama_kegiatan': k.nama_kegiatan,
            'tgl_mulai':     k.tgl_mulai,
            'tgl_selesai':   k.tgl_selesai,
            'volume':        k.volume,
            'satuan':        k.satuan,
            'honor_satuan':  float(k.honor_satuan),
            'honor_total':   float(k.honor_total),
            'mata_akun':     k.mata_akun,
        } for k in sorted(kontrak.kegiatan_list, key=lambda x: x.urutan)],
    }
    docx_bytes = gen_bast(data, template)
    nama = f"BAST_{kontrak.nomor_bast.replace('/', '-')}.docx"
    return Response(docx_bytes,
        mimetype='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        headers={'Content-Disposition': f'attachment; filename="{nama}"'})

@main.route('/petugas')
@login_required
@role_required('admin_kabupaten')
def daftar_petugas():
    page  = request.args.get('page', 1, type=int)
    cari  = request.args.get('q', '').strip()
    query = Petugas.query
    if cari:
        query = query.filter(Petugas.nama.ilike(f'%{cari}%'))
    pagination = query.order_by(Petugas.nama).paginate(page=page, per_page=10, error_out=False)
    return render_template('petugas/daftar.html',
                           petugas_list=pagination.items,
                           pagination=pagination,
                           cari=cari)

@main.route('/petugas/tambah', methods=['GET', 'POST'])
@login_required
@role_required('admin_kabupaten')
def tambah_petugas():
    if request.method == 'POST':
        db.session.add(Petugas(
            nama=request.form['nama'], jabatan=request.form.get('jabatan'),
            posisi=request.form.get('posisi'), alamat=request.form.get('alamat'),
            alamat_provinsi=request.form.get('alamat_provinsi'),
            alamat_kabupaten=request.form.get('alamat_kabupaten'),
            alamat_kecamatan=request.form.get('alamat_kecamatan'),
            alamat_desa=request.form.get('alamat_desa'),
            tempat_tgl_lahir=request.form.get('tempat_tgl_lahir'),
            jenis_kelamin=request.form.get('jenis_kelamin'),
            pendidikan=request.form.get('pendidikan'),
            pekerjaan=request.form.get('pekerjaan'),
            deskripsi_pekerjaan=request.form.get('deskripsi_pekerjaan'),
            no_telp=request.form.get('no_telp'),
            sobat_id=request.form.get('sobat_id'),
            email=request.form.get('email'),
        ))
        db.session.commit()
        flash('Petugas berhasil ditambahkan.', 'success')
        return redirect(url_for('main.daftar_petugas'))
    return render_template('petugas/form.html', judul='Tambah Petugas', petugas=None)

@main.route('/petugas/edit/<int:id>', methods=['GET', 'POST'])
@login_required
@role_required('admin_kabupaten')
def edit_petugas(id):
    p = Petugas.query.get_or_404(id)
    if request.method == 'POST':
        p.nama=request.form['nama']; p.jabatan=request.form.get('jabatan')
        p.posisi=request.form.get('posisi'); p.alamat=request.form.get('alamat')
        p.alamat_provinsi=request.form.get('alamat_provinsi')
        p.alamat_kabupaten=request.form.get('alamat_kabupaten')
        p.alamat_kecamatan=request.form.get('alamat_kecamatan')
        p.alamat_desa=request.form.get('alamat_desa')
        p.tempat_tgl_lahir=request.form.get('tempat_tgl_lahir')
        p.jenis_kelamin=request.form.get('jenis_kelamin')
        p.pendidikan=request.form.get('pendidikan')
        p.pekerjaan=request.form.get('pekerjaan')
        p.deskripsi_pekerjaan=request.form.get('deskripsi_pekerjaan')
        p.no_telp=request.form.get('no_telp')
        p.sobat_id=request.form.get('sobat_id')
        p.email=request.form.get('email')
        db.session.commit()
        flash('Data petugas berhasil diperbarui.', 'success')
        return redirect(url_for('main.daftar_petugas'))
    return render_template('petugas/form.html', judul='Edit Petugas', petugas=p)

@main.route('/petugas/hapus/<int:id>', methods=['POST'])
@login_required
@role_required('admin_kabupaten')
def hapus_petugas(id):
    p = Petugas.query.get_or_404(id)
    nama = p.nama
    db.session.delete(p)
    db.session.commit()
    flash(f'Petugas "{nama}" telah dihapus.', 'warning')
    return redirect(url_for('main.daftar_petugas'))

@main.route('/petugas/import', methods=['POST'])
@login_required
@role_required('admin_kabupaten')
def import_petugas():
    file = request.files.get('file_excel')
    skip_duplikat = 'skip_duplikat' in request.form
    if not file or not file.filename.endswith('.xlsx'):
        flash('File tidak valid.', 'danger')
        return redirect(url_for('main.daftar_petugas'))
    try:
        from openpyxl import load_workbook
        wb = load_workbook(io.BytesIO(file.read()), read_only=True)
        if 'Mitra' not in wb.sheetnames:
            flash('Sheet "Mitra" tidak ditemukan.', 'danger')
            return redirect(url_for('main.daftar_petugas'))
        ws = wb['Mitra']
        rows = list(ws.iter_rows(values_only=True))
        header = [str(h).strip() if h else '' for h in rows[0]]
        def col(n):
            try: return header.index(n)
            except ValueError: return None
        idx = {
            'nama': col('Nama Lengkap'), 'jabatan': col('Jabatan'),
            'posisi': col('Posisi'), 'alamat': col('Alamat Detail'),
            'alamat_provinsi': col('Alamat Prov'), 'alamat_kabupaten': col('Alamat Kab'),
            'alamat_kecamatan': col('Alamat Kecamatan'), 'alamat_desa': col('Alamat Desa'),
            'tempat_tgl_lahir': col('Tempat, Tanggal Lahir (Umur)*'),
            'jenis_kelamin': col('Jenis Kelamin'), 'pendidikan': col('Pendidikan'),
            'pekerjaan': col('Pekerjaan'), 'deskripsi_pekerjaan': col('Deskripsi Pekerjaan Lain'),
            'no_telp': col('No Telp'), 'sobat_id': col('SOBAT ID'), 'email': col('Email'),
        }
        def ambil(row, key):
            i = idx.get(key)
            if i is None or i >= len(row): return None
            s = str(row[i]).strip() if row[i] is not None else None
            return None if not s or s in ('#ERROR!', 'None') else s
        masuk = 0; lewat = 0
        nama_ada = {p.nama.strip().lower() for p in Petugas.query.all()} if skip_duplikat else set()
        for row in rows[1:]:
            nama = ambil(row, 'nama')
            if not nama: continue
            if skip_duplikat and nama.lower() in nama_ada:
                lewat += 1; continue
            db.session.add(Petugas(
                nama=nama, jabatan=ambil(row,'jabatan'), posisi=ambil(row,'posisi'),
                alamat=ambil(row,'alamat'), alamat_provinsi=ambil(row,'alamat_provinsi'),
                alamat_kabupaten=ambil(row,'alamat_kabupaten'),
                alamat_kecamatan=ambil(row,'alamat_kecamatan'),
                alamat_desa=ambil(row,'alamat_desa'),
                tempat_tgl_lahir=ambil(row,'tempat_tgl_lahir'),
                jenis_kelamin=ambil(row,'jenis_kelamin'), pendidikan=ambil(row,'pendidikan'),
                pekerjaan=ambil(row,'pekerjaan'),
                deskripsi_pekerjaan=ambil(row,'deskripsi_pekerjaan'),
                no_telp=ambil(row,'no_telp'), sobat_id=ambil(row,'sobat_id'),
                email=ambil(row,'email'),
            ))
            nama_ada.add(nama.lower()); masuk += 1
        db.session.commit()
        flash(f'{masuk} petugas diimport.' + (f' {lewat} dilewati.' if lewat else ''), 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Gagal: {str(e)}', 'danger')
    return redirect(url_for('main.daftar_petugas'))

# ─── GENERATE BULANAN ────────────────────────────────────────────
@main.route('/generate')
@login_required
def generate_bulanan():
    """Redirect ke halaman generate SPK (default)."""
    return redirect(url_for('main.generate_spk_bulanan'))


@main.route('/generate/spk')
@login_required
def generate_spk_bulanan():
    """Halaman generate & merge SPK — filter per bulan SPK dan fungsi."""
    bulan  = request.args.get('bulan', type=int)
    tahun  = request.args.get('tahun', type=int)
    fungsi = request.args.get('fungsi', '').strip()
    kontrak_list = []
    if bulan and tahun:
        q = Kontrak.query.filter_by(bulan=bulan, tahun=tahun)
        if fungsi:
            q = q.filter(Kontrak.nama_fungsi == fungsi)
        kontrak_list = sorted(q.all(), key=lambda k: sort_key_nomor(k.nomor_spk))
    return render_template('generate_spk_bulanan.html',
                           bulan=bulan, tahun=tahun, fungsi=fungsi,
                           kontrak_list=kontrak_list,
                           fungsi_list=list(FUNGSI_KODE.keys()),
                           nama_bulan=NAMA_BULAN)


@main.route('/generate/bast')
@login_required
def generate_bast_bulanan():
    """Halaman generate & merge BAST — filter per bulan BAST dan fungsi."""
    bulan  = request.args.get('bulan', type=int)
    tahun  = request.args.get('tahun', type=int)
    fungsi = request.args.get('fungsi', '').strip()
    bast_list = []
    if bulan and tahun:
        q = BAST.query.join(Kontrak).filter(
            BAST.bulan_bast == bulan,
            BAST.tahun_bast == tahun
        )
        if fungsi:
            q = q.filter(Kontrak.nama_fungsi == fungsi)
        bast_list = sorted(q.all(), key=lambda b: sort_key_nomor(b.nomor_bast))
    return render_template('generate_bast_bulanan.html',
                           bulan=bulan, tahun=tahun, fungsi=fungsi,
                           bast_list=bast_list,
                           fungsi_list=list(FUNGSI_KODE.keys()),
                           nama_bulan=NAMA_BULAN)

@main.route('/generate/merge-spk')
@login_required
def merge_spk():
    from app.doc_generator import generate_spk as gen_spk, merge_docx_list
    bulan  = request.args.get('bulan', type=int)
    tahun  = request.args.get('tahun', type=int)
    fungsi = request.args.get('fungsi', '').strip()
    if not bulan or not tahun:
        flash('Pilih bulan dan tahun terlebih dahulu.', 'warning')
        return redirect(url_for('main.generate_spk_bulanan'))

    q = Kontrak.query.filter_by(bulan=bulan, tahun=tahun)
    if fungsi:
        q = q.filter(Kontrak.nama_fungsi == fungsi)
    kontrak_list = sorted(q.all(), key=lambda k: sort_key_nomor(k.nomor_spk))

    if not kontrak_list:
        flash('Tidak ada kontrak untuk filter yang dipilih.', 'warning')
        return redirect(url_for('main.generate_spk_bulanan',
                                bulan=bulan, tahun=tahun, fungsi=fungsi))

    template = os.path.join(os.path.dirname(__file__), 'templates', 'DOKUMEN_SPK.docx')
    docx_list = []
    for kontrak in kontrak_list:
        data = {
            'nomor_spk':       kontrak.nomor_spk,
            'nomor_bast':      kontrak.nomor_bast,
            'bulan':           kontrak.bulan,
            'tahun':           kontrak.tahun,
            'tanggal_surat':   kontrak.tanggal_surat,
            'tanggal_mulai':   kontrak.tanggal_mulai,
            'tanggal_selesai': kontrak.tanggal_selesai,
            'petugas_nama':    kontrak.petugas.nama,
            'petugas_jabatan': kontrak.petugas.jabatan or 'Mitra',
            'petugas_alamat':  kontrak.petugas.alamat or '-',
            'total_honor':     float(kontrak.total_honor),
            'kegiatan_list': [{
                'nama_kegiatan': k.nama_kegiatan,
                'fungsi':        k.fungsi,
                'tgl_mulai':     k.tgl_mulai,
                'tgl_selesai':   k.tgl_selesai,
                'volume':        k.volume,
                'satuan':        k.satuan,
                'honor_satuan':  float(k.honor_satuan),
                'honor_total':   float(k.honor_total),
                'mata_akun':     k.mata_akun,
            } for k in sorted(kontrak.kegiatan_list, key=lambda x: x.urutan)],
        }
        docx_list.append(gen_spk(data, template))

    merged = merge_docx_list(docx_list)
    suffix_fungsi = f"_{fungsi}" if fungsi else ""
    nama_file = f"SPK_Gabungan_{NAMA_BULAN[bulan]}_{tahun}{suffix_fungsi}.docx"
    return Response(merged,
        mimetype='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        headers={'Content-Disposition': f'attachment; filename="{nama_file}"'})

@main.route('/generate/merge-bast')
@login_required
def merge_bast():
    """
    Merge BAST — assign nomor urut BAST saat ini (bukan saat entri kontrak).
    Redirect ke halaman hasil dengan daftar BAST dan warning SBML.
    """
    from app.doc_generator import generate_bast as gen_bast, merge_docx_list
    bulan  = request.args.get('bulan', type=int)
    tahun  = request.args.get('tahun', type=int)
    fungsi = request.args.get('fungsi', '').strip()
    if not bulan or not tahun:
        flash('Pilih bulan dan tahun BAST terlebih dahulu.', 'warning')
        return redirect(url_for('main.generate_bast_bulanan'))

    q = BAST.query.join(Kontrak).filter(
        BAST.bulan_bast == bulan,
        BAST.tahun_bast == tahun
    )
    if fungsi:
        q = q.filter(Kontrak.nama_fungsi == fungsi)
    bast_list = q.order_by(BAST.id).all()  # urut by id (waktu dibuat)

    if not bast_list:
        flash('Tidak ada BAST untuk filter yang dipilih.', 'warning')
        return redirect(url_for('main.generate_bast_bulanan',
                                bulan=bulan, tahun=tahun, fungsi=fungsi))

    # Assign nomor BAST untuk yang belum bernomor, hitung ulang fungsi dominan
    from collections import defaultdict
    perlu_commit = False
    for bast in bast_list:
        # Hitung fungsi dominan dari kegiatan BAST
        honor_per_fungsi = defaultdict(float)
        for bk in bast.kegiatan_list:
            honor_per_fungsi[bk.kegiatan.fungsi] += float(bk.kegiatan.honor_total or 0)

        if honor_per_fungsi:
            fd   = max(honor_per_fungsi, key=honor_per_fungsi.get)
            kode = FUNGSI_KODE.get(fd, bast.kontrak.kode_fungsi or '14.101')
        else:
            kode = bast.kontrak.kode_fungsi or '14.101'

        if not bast.nomor_bast:
            no_bast         = next_nomor_bast()
            bast.nomor_bast = buat_nomor_bast(no_bast, kode, tahun)
            perlu_commit    = True
        else:
            # Update kode fungsi jika berubah
            bagian = bast.nomor_bast.split('/')
            if len(bagian) >= 2 and bagian[1] != kode:
                bast.nomor_bast = bast.nomor_bast.replace(
                    '/' + bagian[1] + '/', '/' + kode + '/', 1)
                perlu_commit = True

    if perlu_commit:
        db.session.commit()

    # Generate dan merge dokumen
    template = os.path.join(os.path.dirname(__file__), 'templates', 'DOKUMEN_BAST.docx')
    docx_list = []
    for bast in sorted(bast_list, key=lambda b: b.nomor_bast or ''):
        kontrak = bast.kontrak
        data = {
            'nomor_spk':       kontrak.nomor_spk,
            'nomor_bast':      bast.nomor_bast,
            'bulan':           bast.bulan_bast,
            'tahun':           bast.tahun_bast,
            'tanggal_mulai':   bast.tanggal_bast,
            'tanggal_selesai': bast.tanggal_bast,
            'petugas_nama':    kontrak.petugas.nama,
            'petugas_jabatan': kontrak.petugas.jabatan or 'Mitra',
            'petugas_alamat':  kontrak.petugas.alamat or '-',
            'total_honor':     float(bast.total_honor),
            'kegiatan_list': [{
                'nama_kegiatan': bk.kegiatan.nama_kegiatan,
                'fungsi':        bk.kegiatan.fungsi,
                'tgl_mulai':     bk.kegiatan.tgl_mulai,
                'tgl_selesai':   bk.kegiatan.tgl_selesai,
                'volume':        bk.kegiatan.volume,
                'satuan':        bk.kegiatan.satuan,
                'honor_satuan':  float(bk.kegiatan.honor_satuan),
                'honor_total':   float(bk.kegiatan.honor_total),
                'mata_akun':     bk.kegiatan.mata_akun,
            } for bk in bast.kegiatan_list],
        }
        docx_list.append(gen_bast(data, template))

    merged = merge_docx_list(docx_list)
    suffix_fungsi_b = f"_{fungsi}" if fungsi else ""
    nama_file = f"BAST_Gabungan_{NAMA_BULAN[bulan]}_{tahun}{suffix_fungsi_b}.docx"
    return Response(merged,
        mimetype='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        headers={'Content-Disposition': f'attachment; filename="{nama_file}"'})


@main.route('/generate/hasil-bast')
@login_required
def hasil_merge_bast():
    """Halaman hasil merge BAST — daftar lengkap dengan warning SBML."""
    bulan  = request.args.get('bulan', type=int)
    tahun  = request.args.get('tahun', type=int)
    fungsi = request.args.get('fungsi', '').strip()
    SBML   = 3600000

    if not bulan or not tahun:
        return redirect(url_for('main.generate_bast_bulanan'))

    q = BAST.query.join(Kontrak).filter(
        BAST.bulan_bast == bulan,
        BAST.tahun_bast == tahun
    )
    if fungsi:
        q = q.filter(Kontrak.nama_fungsi == fungsi)
    bast_list  = sorted(q.all(), key=lambda b: sort_key_nomor(b.nomor_bast))
    total_all  = sum(float(b.total_honor) for b in bast_list)
    n_sbml     = sum(1 for b in bast_list if float(b.total_honor) > SBML)

    return render_template('hasil_merge_bast.html',
        bast_list=bast_list, bulan=bulan, tahun=tahun, fungsi=fungsi,
        total_all=total_all, n_sbml=n_sbml, SBML=SBML,
        nama_bulan=NAMA_BULAN, fungsi_list=list(FUNGSI_KODE.keys()))


@main.route('/kontrak/<int:id>/link-ttd', methods=['POST'])
@login_required
@role_required('admin_kabupaten', 'admin_fungsi', 'ppk')
def simpan_link_spk(id):
    kontrak = Kontrak.query.get_or_404(id)
    link = request.form.get('link_spk_ttd', '').strip()
    kontrak.link_spk_ttd = link if link else None
    db.session.commit()
    if link:
        flash('Link dokumen SPK bertanda tangan berhasil disimpan.', 'success')
    else:
        flash('Link dokumen SPK bertanda tangan dihapus.', 'warning')
    return redirect(request.referrer or url_for('main.daftar_kontrak'))


@main.route('/bast/<int:id>/link-ttd', methods=['POST'])
@login_required
@role_required('admin_kabupaten', 'admin_fungsi', 'ppk')
def simpan_link_bast(id):
    bast = BAST.query.get_or_404(id)
    link = request.form.get('link_bast_ttd', '').strip()
    bast.link_bast_ttd = link if link else None
    db.session.commit()
    if link:
        flash('Link dokumen BAST bertanda tangan berhasil disimpan.', 'success')
    else:
        flash('Link dokumen BAST bertanda tangan dihapus.', 'warning')
    return redirect(request.referrer or url_for('main.daftar_bast'))


# ─── REKAP HONOR ─────────────────────────────────────────────────
@main.route('/rekap')
@login_required
def rekap_honor():
    """Rekap honor berdasarkan bulan BAST (bulan pencairan), bukan bulan SPK."""
    bulan = request.args.get('bulan', type=int)
    tahun = request.args.get('tahun', type=int)
    rekap_list = []

    if bulan and tahun:
        bast_list = (BAST.query
                     .filter_by(bulan_bast=bulan, tahun_bast=tahun).all())
        bast_list = sorted(bast_list, key=lambda b: sort_key_nomor(b.nomor_bast))
        for bast in bast_list:
            kontrak = bast.kontrak
            rekap_list.append({
                'petugas_nama':      kontrak.petugas.nama,
                'petugas_kecamatan': kontrak.petugas.alamat_kecamatan or '—',
                'nama_fungsi':       kontrak.nama_fungsi or '—',
                'nomor_spk':         kontrak.nomor_spk or '—',
                'nomor_bast':        bast.nomor_bast or '—',
                'bulan_spk':         NAMA_BULAN[kontrak.bulan],
                'tahun_spk':         kontrak.tahun,
                'jml_kegiatan':      len(bast.kegiatan_list),
                'total_honor':       float(bast.total_honor or 0),
                'total_ganti_rugi':  float(kontrak.total_ganti_rugi or 0),
                'tanggal_bast':      bast.tanggal_bast,
                'bast_id':           bast.id,
            })
        rekap_list.sort(key=lambda x: x['petugas_nama'])

    return render_template('rekap_honor.html',
                           bulan=bulan, tahun=tahun,
                           rekap_list=rekap_list, nama_bulan=NAMA_BULAN)

# ─── LAPORAN GRAFIK ──────────────────────────────────────────────
@main.route('/laporan')
@login_required
def laporan():
    from collections import defaultdict
    tahun = request.args.get('tahun', type=int, default=2026)
    tahun_list = sorted(set(
        t for (t,) in db.session.query(Kontrak.tahun).distinct().all()
    ), reverse=True) or [2026]

    # Data per bulan
    labels_bulan = [NAMA_BULAN[i] for i in range(1, 13)]
    data_mitra  = [0] * 12
    data_honor  = [0.0] * 12
    kontrak_tahun = Kontrak.query.filter_by(tahun=tahun).all()
    for k in kontrak_tahun:
        idx = k.bulan - 1
        data_mitra[idx] += 1
        data_honor[idx] += float(k.total_honor or 0)

    # Rekap per fungsi
    rekap_fungsi = defaultdict(lambda: {'jumlah': 0, 'honor': 0.0})
    for k in kontrak_tahun:
        f = k.nama_fungsi or 'Lainnya'
        rekap_fungsi[f]['jumlah'] += 1
        rekap_fungsi[f]['honor']  += float(k.total_honor or 0)

    labels_fungsi = list(rekap_fungsi.keys())
    data_fungsi   = [rekap_fungsi[f]['jumlah'] for f in labels_fungsi]

    return render_template('laporan.html',
        tahun=tahun, tahun_list=tahun_list,
        labels_bulan=labels_bulan,
        data_mitra=data_mitra, data_honor=data_honor,
        labels_fungsi=labels_fungsi, data_fungsi=data_fungsi,
        rekap_fungsi=dict(rekap_fungsi))


# ─── HELPER: bulan BAST dari tgl_selesai kegiatan ────────────────
def bulan_pencairan_bast(tgl_selesai):
    """Kegiatan selesai bulan X → masuk BAST bulan X+1."""
    if tgl_selesai.month == 12:
        return 1, tgl_selesai.year + 1
    return tgl_selesai.month + 1, tgl_selesai.year

# ─── ENTRI BAST ──────────────────────────────────────────────────
@main.route('/entri-bast', methods=['GET', 'POST'])
@login_required
@role_required('admin_kabupaten', 'admin_fungsi')
def entri_bast():
    """
    Halaman Entri BAST — dua panel:
    Kiri: daftar petugas yang masih ada kegiatan pending BAST bulan ini.
    Kanan: form pilih kegiatan untuk petugas yang dipilih.
    """
    petugas_list = Petugas.query.order_by(Petugas.nama).all()
    bulan = request.args.get('bulan', type=int, default=date.today().month)
    tahun = request.args.get('tahun', type=int, default=date.today().year)

    if request.method == 'POST':
        action = request.form.get('action', 'simpan')

        if action == 'simpan':
            petugas_id   = int(request.form['petugas_id'])
            bulan_bast_v = int(request.form['bulan_bast'])
            tahun_bast_v = int(request.form['tahun_bast'])
            kontrak_id   = int(request.form['kontrak_id'])
            keg_ids      = request.form.getlist('kegiatan_ids')

            if not keg_ids:
                flash('Pilih minimal satu kegiatan untuk dimasukkan ke BAST.', 'warning')
                return redirect(url_for('main.entri_bast', bulan=bulan_bast_v, tahun=tahun_bast_v))

            kontrak = Kontrak.query.get_or_404(kontrak_id)

            # Cek apakah BAST bulan ini untuk kontrak ini sudah ada
            bast_existing = BAST.query.filter_by(
                kontrak_id=kontrak_id,
                bulan_bast=bulan_bast_v,
                tahun_bast=tahun_bast_v
            ).first()

            if bast_existing:
                # Hapus kegiatan lama, ganti dengan yang baru
                for bk in bast_existing.kegiatan_list:
                    db.session.delete(bk)
                db.session.flush()
                bast = bast_existing
            else:
                # Buat BAST baru — nomor di-generate setelah fungsi dominan diketahui
                tgl_bast = tanggal_bast_otomatis(
                    bulan_bast_v - 1 if bulan_bast_v > 1 else 12,
                    tahun_bast_v if bulan_bast_v > 1 else tahun_bast_v - 1
                )
                bast = BAST(
                    kontrak_id   = kontrak_id,
                    bulan_bast   = bulan_bast_v,
                    tahun_bast   = tahun_bast_v,
                    tanggal_bast = tgl_bast,
                    nomor_bast   = '',  # sementara, diupdate setelah fungsi dominan dihitung
                )
                db.session.add(bast)
                db.session.flush()

            # Tambah kegiatan yang dipilih
            for keg_id in keg_ids:
                bk = BASTKegiatan(bast_id=bast.id, kegiatan_id=int(keg_id))
                db.session.add(bk)
            db.session.flush()

            # Hitung fungsi dominan dari kegiatan yang masuk BAST
            # (fungsi dengan total honor terbesar di antara kegiatan yang dipilih)
            from collections import defaultdict
            honor_per_fungsi = defaultdict(float)
            for bk in bast.kegiatan_list:
                keg = bk.kegiatan
                honor_per_fungsi[keg.fungsi] += float(keg.honor_total or 0)

            if honor_per_fungsi:
                fungsi_dominan_bast = max(honor_per_fungsi, key=honor_per_fungsi.get)
                kode_fungsi_bast    = FUNGSI_KODE.get(fungsi_dominan_bast, '14.101')
            else:
                fungsi_dominan_bast = kontrak.nama_fungsi or 'Umum'
                kode_fungsi_bast    = kontrak.kode_fungsi or '14.101'

            # Assign atau update nomor BAST
            if not bast.nomor_bast:
                # BAST baru — generate nomor
                no_bast        = next_nomor_bast()
                bast.nomor_bast = buat_nomor_bast(no_bast, kode_fungsi_bast, tahun_bast_v)
            else:
                # BAST existing yang di-edit — update kode fungsi di nomor jika berubah
                bagian = bast.nomor_bast.split('/')
                if len(bagian) >= 2 and bagian[1] != kode_fungsi_bast:
                    bast.nomor_bast = bast.nomor_bast.replace(
                        '/' + bagian[1] + '/', '/' + kode_fungsi_bast + '/', 1
                    )

            bast.hitung_total()
            db.session.commit()


            flash(f'BAST {NAMA_BULAN[bulan_bast_v]} {tahun_bast_v} untuk {kontrak.petugas.nama} berhasil disimpan ({len(keg_ids)} kegiatan). Nomor: {bast.nomor_bast}', 'success')

            return redirect(url_for('main.daftar_bast',
                                    bulan=bulan_bast_v, tahun=tahun_bast_v))
        return redirect(url_for('main.entri_bast', bulan=bulan, tahun=tahun))

    return render_template('entri_bast.html',
        petugas_list=petugas_list,
        bulan=bulan, tahun=tahun,
        nama_bulan=NAMA_BULAN)


@main.route('/api/kegiatan-bast')
@login_required
@role_required('admin_kabupaten', 'admin_fungsi')
def api_kegiatan_bast():
    """
    API: ambil kegiatan dari kontrak petugas yang perlu masuk BAST bulan tertentu.
    Kegiatan dikelompokkan: 'saran' (otomatis sesuai bulan) dan 'semua' (manual).
    """
    petugas_id   = request.args.get('petugas_id', type=int)
    bulan_bast_v = request.args.get('bulan_bast', type=int)
    tahun_bast_v = request.args.get('tahun_bast', type=int)

    if not all([petugas_id, bulan_bast_v, tahun_bast_v]):
        return jsonify({'kontrak_list': []})

    # Ambil semua kontrak petugas yang memiliki kegiatan relevan
    # Kegiatan relevan = tgl_selesai jatuh di bulan sebelum bulan_bast
    # (tgl_selesai.month+1 == bulan_bast)
    kontrak_list = Kontrak.query.filter_by(petugas_id=petugas_id).all()

    result = []
    for kontrak in kontrak_list:
        kegiatan_saran = []   # otomatis cocok bulan ini
        kegiatan_lain  = []   # bisa dipilih manual

        for k in sorted(kontrak.kegiatan_list, key=lambda x: x.urutan):
            # Prioritaskan bulan_pencairan dari DaftarKegiatan jika ada
            dk = DaftarKegiatan.query.filter_by(
                nama_kegiatan=k.nama_kegiatan,
                fungsi=k.fungsi,
                bulan=kontrak.bulan,
                tahun=kontrak.tahun
            ).first()
            if dk and dk.bulan_pencairan:
                b_bast = dk.bulan_pencairan
                t_bast = kontrak.tahun if b_bast >= kontrak.bulan else kontrak.tahun + 1
            else:
                b_bast, t_bast = bulan_pencairan_bast(k.tgl_selesai)
            is_saran = (b_bast == bulan_bast_v and t_bast == tahun_bast_v)

            # Cek apakah kegiatan ini sudah masuk BAST lain
            sudah_di_bast = any(ref.bast.bulan_bast == bulan_bast_v and
                                ref.bast.tahun_bast == tahun_bast_v
                                for ref in k.bast_refs)

            keg_data = {
                'id':             k.id,
                'nama_kegiatan':  k.nama_kegiatan,
                'fungsi':         k.fungsi,
                'tgl_mulai':      k.tgl_mulai.strftime('%d/%m/%Y'),
                'tgl_selesai':    k.tgl_selesai.strftime('%d/%m/%Y'),
                'volume':         k.volume,
                'satuan':         k.satuan,
                'honor_satuan':   float(k.honor_satuan),
                'honor_total':    float(k.honor_total),
                'mata_akun':      k.mata_akun,
                'bulan_bast_saran': NAMA_BULAN[b_bast] + ' ' + str(t_bast),
                'is_saran':       is_saran,
                'sudah_di_bast':  sudah_di_bast,
            }
            if is_saran:
                kegiatan_saran.append(keg_data)
            else:
                kegiatan_lain.append(keg_data)

        if kegiatan_saran or kegiatan_lain:
            # Cek BAST existing
            bast_existing = BAST.query.filter_by(
                kontrak_id=kontrak.id,
                bulan_bast=bulan_bast_v,
                tahun_bast=tahun_bast_v
            ).first()
            existing_ids = [bk.kegiatan_id for bk in bast_existing.kegiatan_list] if bast_existing else []

            result.append({
                'kontrak_id':      kontrak.id,
                'nomor_spk':       kontrak.nomor_spk,
                'nomor_bast':      kontrak.nomor_bast,
                'bulan_spk':       NAMA_BULAN[kontrak.bulan],
                'tahun_spk':       kontrak.tahun,
                'kegiatan_saran':  kegiatan_saran,
                'kegiatan_lain':   kegiatan_lain,
                'existing_ids':    existing_ids,
                'sudah_ada_bast':  bast_existing is not None,
            })

    return jsonify({'kontrak_list': result})


@main.route('/api/pending-bast')
@login_required
@role_required('admin_kabupaten', 'admin_fungsi')
def api_pending_bast():
    """
    Kembalikan daftar petugas yang MASIH ADA kegiatan belum di-BAST
    untuk bulan pencairan tertentu.

    Logika:
    - Ambil semua kegiatan yang bulan_pencairan_bast(tgl_selesai) == bulan_bast
    - Cek apakah kegiatan tersebut sudah ada di tabel BASTKegiatan untuk bulan_bast ini
    - Jika masih ada yang belum → petugas masuk daftar PENDING
    - Jika semua sudah → petugas tidak muncul (selesai)
    """
    bulan_bast_v = request.args.get('bulan_bast', type=int)
    tahun_bast_v = request.args.get('tahun_bast', type=int)

    if not bulan_bast_v or not tahun_bast_v:
        return jsonify({'pending': [], 'selesai': []})

    # Kumpulkan semua kegiatan yang seharusnya masuk BAST bulan ini
    # = kegiatan dengan bulan_pencairan_bast(tgl_selesai) == bulan_bast_v
    from collections import defaultdict
    petugas_pending = {}   # id -> info + list kegiatan pending
    petugas_selesai = {}   # id -> info (semua kegiatan sudah di-BAST)

    # Ambil semua BAST yang bulan_bast-nya == bulan yang dipilih
    # Ini lebih akurat karena BAST sudah di-generate otomatis saat entri kontrak
    # berdasarkan bulan_pencairan dari DaftarKegiatan
    bast_bulan_ini = BAST.query.filter_by(
        bulan_bast=bulan_bast_v, tahun_bast=tahun_bast_v
    ).all()

    kegiatan_per_petugas = defaultdict(list)
    for bast in bast_bulan_ini:
        pid = bast.kontrak.petugas_id
        for bk in bast.kegiatan_list:
            kegiatan_per_petugas[pid].append(bk.kegiatan)

    # Juga cek kegiatan yang punya bulan_pencairan manual tapi belum punya BAST
    semua_kegiatan = Kegiatan.query.join(Kontrak).all()
    for k in semua_kegiatan:
        pid = k.kontrak.petugas_id
        # Tentukan bulan pencairan kegiatan ini
        dk = DaftarKegiatan.query.filter_by(
            nama_kegiatan=k.nama_kegiatan,
            fungsi=k.fungsi,
            bulan=k.kontrak.bulan,
            tahun=k.kontrak.tahun
        ).first()
        if dk and dk.bulan_pencairan:
            b = dk.bulan_pencairan
            t = k.kontrak.tahun if b >= k.kontrak.bulan else k.kontrak.tahun + 1
        else:
            b, t = bulan_pencairan_bast(k.tgl_selesai)

        if b == bulan_bast_v and t == tahun_bast_v:
            # Cek duplikat
            if k not in kegiatan_per_petugas[pid]:
                kegiatan_per_petugas[pid].append(k)

    for petugas_id, keg_list in kegiatan_per_petugas.items():
        petugas = Petugas.query.get(petugas_id)
        if not petugas:
            continue

        pending = []
        sudah   = []
        for k in keg_list:
            # Cek apakah kegiatan ini ada di BASTKegiatan untuk bulan_bast ini
            sudah_bast = BASTKegiatan.query.join(BAST).filter(
                BASTKegiatan.kegiatan_id == k.id,
                BAST.bulan_bast == bulan_bast_v,
                BAST.tahun_bast == tahun_bast_v
            ).first()
            if sudah_bast:
                sudah.append(k)
            else:
                pending.append(k)

        info_petugas = {
            'petugas_id':   petugas_id,
            'nama':         petugas.nama,
            'kecamatan':    petugas.alamat_kecamatan or '—',
            'jml_pending':  len(pending),
            'jml_sudah':    len(sudah),
            'jml_total':    len(keg_list),
            'kegiatan_pending': [{
                'id':           k.id,
                'nama':         k.nama_kegiatan,
                'fungsi':       k.fungsi,
                'tgl_selesai':  k.tgl_selesai.strftime('%d/%m/%Y'),
                'honor_total':  float(k.honor_total),
                'kontrak_id':   k.kontrak_id,
            } for k in pending],
        }

        if pending:
            petugas_pending[petugas_id] = info_petugas
        else:
            petugas_selesai[petugas_id] = info_petugas

    pending_sorted = sorted(petugas_pending.values(), key=lambda x: x['nama'])
    selesai_sorted = sorted(petugas_selesai.values(), key=lambda x: x['nama'])

    return jsonify({
        'pending': pending_sorted,
        'selesai': selesai_sorted,
        'bulan':   bulan_bast_v,
        'tahun':   tahun_bast_v,
    })


# ─── DAFTAR BAST ─────────────────────────────────────────────────
@main.route('/bast/<int:bast_id>/hapus-kegiatan/<int:keg_id>', methods=['POST'])
@login_required
@role_required('admin_kabupaten', 'admin_fungsi')
def hapus_kegiatan_bast(bast_id, keg_id):
    """Hapus satu kegiatan dari BAST dan recalculate total + nomor."""
    bast = BAST.query.get_or_404(bast_id)
    bk   = BASTKegiatan.query.filter_by(bast_id=bast_id, kegiatan_id=keg_id).first_or_404()

    db.session.delete(bk)
    db.session.flush()

    if len(bast.kegiatan_list) == 0:
        # BAST kosong → hapus seluruh BAST
        bulan_kembali = bast.bulan_bast
        tahun_kembali = bast.tahun_bast
        db.session.delete(bast)
        db.session.flush()
        renomor_semua_bast()
        db.session.commit()
        flash('Semua kegiatan dihapus — BAST dihapus otomatis. Nomor urut disesuaikan.', 'warning')
        return redirect(url_for('main.daftar_bast',
                                bulan=bulan_kembali, tahun=tahun_kembali))

    # Recalculate honor & fungsi dominan
    from collections import defaultdict
    honor_per_fungsi = defaultdict(float)
    for bk2 in bast.kegiatan_list:
        honor_per_fungsi[bk2.kegiatan.fungsi] += float(bk2.kegiatan.honor_total or 0)

    fungsi_dom  = max(honor_per_fungsi, key=honor_per_fungsi.get)
    kode_baru   = FUNGSI_KODE.get(fungsi_dom, '14.101')

    # Update kode fungsi di nomor BAST jika berubah
    if bast.nomor_bast:
        bagian = bast.nomor_bast.split('/')
        if len(bagian) >= 2 and bagian[1] != kode_baru:
            bast.nomor_bast = bast.nomor_bast.replace(
                '/' + bagian[1] + '/', '/' + kode_baru + '/', 1)

    db.session.expire(bast)
    bast.hitung_total()
    db.session.commit()
    flash('Kegiatan dihapus dari BAST. Total honor diperbarui.', 'success')
    return redirect(url_for('main.detail_bast', id=bast_id))



@main.route('/bast/generate-massal', methods=['GET', 'POST'])
@login_required
@role_required('admin_kabupaten', 'admin_fungsi')
def generate_bast_massal():
    """
    Generate BAST massal — buat BAST untuk semua petugas
    yang memiliki kegiatan di bulan pencairan tertentu,
    sekaligus dalam satu klik.
    """
    if request.method == 'POST':
        bulan_bast_v = int(request.form['bulan_bast'])
        tahun_bast_v = int(request.form['tahun_bast'])
        fungsi_filter = request.form.get('fungsi', '').strip()

        # Ambil semua BAST yang sudah ada untuk bulan ini
        q_existing = BAST.query.filter_by(
            bulan_bast=bulan_bast_v, tahun_bast=tahun_bast_v
        )
        if fungsi_filter:
            q_existing = q_existing.join(Kontrak).filter(
                Kontrak.nama_fungsi == fungsi_filter)
        existing_kontrak_ids = {b.kontrak_id for b in q_existing.all()}

        # Ambil semua kegiatan yang belum di-BAST untuk bulan ini
        # berdasarkan bulan_pencairan dari DaftarKegiatan
        semua_kegiatan = Kegiatan.query.join(Kontrak).all()
        if fungsi_filter:
            if session.get('user_role') == 'admin_fungsi':
                fungsi_filter = session.get('user_fungsi', fungsi_filter)
            semua_kegiatan = [k for k in semua_kegiatan
                              if k.fungsi == fungsi_filter]

        from collections import defaultdict
        kegiatan_per_kontrak = defaultdict(list)
        for keg in semua_kegiatan:
            # Cek sudah di-BAST bulan ini?
            sudah = BASTKegiatan.query.join(BAST).filter(
                BASTKegiatan.kegiatan_id == keg.id,
                BAST.bulan_bast == bulan_bast_v,
                BAST.tahun_bast == tahun_bast_v
            ).first()
            if sudah:
                continue

            # Tentukan bulan pencairan
            dk = DaftarKegiatan.query.filter_by(
                nama_kegiatan=keg.nama_kegiatan,
                fungsi=keg.fungsi,
                bulan=keg.kontrak.bulan,
                tahun=keg.kontrak.tahun
            ).first()
            if dk and dk.bulan_pencairan:
                b = dk.bulan_pencairan
                t = keg.kontrak.tahun if b >= keg.kontrak.bulan else keg.kontrak.tahun + 1
            else:
                b, t = bulan_pencairan_bast(keg.tgl_selesai)

            if b == bulan_bast_v and t == tahun_bast_v:
                kegiatan_per_kontrak[keg.kontrak_id].append(keg)

        dibuat = 0
        diupdate = 0
        dilewati = 0
        SBML = 3600000
        sbml_warning = []

        for kontrak_id, keg_list in kegiatan_per_kontrak.items():
            kontrak = Kontrak.query.get(kontrak_id)
            if not kontrak:
                continue

            # Cek BAST existing
            bast_existing = BAST.query.filter_by(
                kontrak_id=kontrak_id,
                bulan_bast=bulan_bast_v,
                tahun_bast=tahun_bast_v
            ).first()

            if bast_existing:
                bast = bast_existing
                diupdate += 1
            else:
                tgl_bast = tanggal_bast_otomatis(
                    bulan_bast_v - 1 if bulan_bast_v > 1 else 12,
                    tahun_bast_v if bulan_bast_v > 1 else tahun_bast_v - 1
                )
                bast = BAST(
                    kontrak_id=kontrak_id,
                    bulan_bast=bulan_bast_v,
                    tahun_bast=tahun_bast_v,
                    tanggal_bast=tgl_bast,
                    nomor_bast='',
                )
                db.session.add(bast)
                db.session.flush()
                dibuat += 1

            for keg in keg_list:
                dup = BASTKegiatan.query.filter_by(
                    bast_id=bast.id, kegiatan_id=keg.id).first()
                if not dup:
                    db.session.add(BASTKegiatan(
                        bast_id=bast.id, kegiatan_id=keg.id))

            db.session.flush()
            db.session.expire(bast)

            # Hitung fungsi dominan & assign nomor
            honor_per_fungsi = defaultdict(float)
            for bk2 in bast.kegiatan_list:
                honor_per_fungsi[bk2.kegiatan.fungsi] += float(
                    bk2.kegiatan.honor_total or 0)

            if honor_per_fungsi:
                fd   = max(honor_per_fungsi, key=honor_per_fungsi.get)
                kode = FUNGSI_KODE.get(fd, kontrak.kode_fungsi or '14.101')
            else:
                kode = kontrak.kode_fungsi or '14.101'

            if not bast.nomor_bast:
                no_b = next_nomor_bast()
                bast.nomor_bast = buat_nomor_bast(no_b, kode, tahun_bast_v)
            else:
                bagian = bast.nomor_bast.split('/')
                if len(bagian) >= 2 and bagian[1] != kode:
                    bast.nomor_bast = bast.nomor_bast.replace(
                        '/' + bagian[1] + '/', '/' + kode + '/', 1)

            bast.hitung_total()

            if float(bast.total_honor) > SBML:
                sbml_warning.append(
                    f"{kontrak.petugas.nama} — Rp {int(bast.total_honor):,}"
                )

        db.session.commit()

        msg = f'Generate massal selesai: {dibuat} BAST baru dibuat'
        if diupdate: msg += f', {diupdate} diperbarui'
        flash(msg + '.', 'success')
        if sbml_warning:
            flash('⚠ Melebihi SBML: ' + ' | '.join(sbml_warning[:5])
                  + (f' +{len(sbml_warning)-5} lainnya' if len(sbml_warning) > 5 else ''),
                  'warning')
        return redirect(url_for('main.daftar_bast',
                                bulan=bulan_bast_v, tahun=tahun_bast_v))

    # GET: tampilkan form preview
    bulan = request.args.get('bulan', type=int) or date.today().month
    tahun = request.args.get('tahun', type=int) or date.today().year
    fungsi = request.args.get('fungsi', '').strip()
    if session.get('user_role') == 'admin_fungsi':
        fungsi = session.get('user_fungsi', '')

    return render_template('generate_bast_massal.html',
        bulan=bulan, tahun=tahun, fungsi=fungsi,
        fungsi_list=list(FUNGSI_KODE.keys()),
        nama_bulan=NAMA_BULAN)


@main.route('/daftar-bast')
@login_required
def daftar_bast():
    """Daftar BAST per bulan pencairan, filter per fungsi."""
    bulan  = request.args.get('bulan', type=int) or date.today().month
    tahun  = request.args.get('tahun', type=int) or date.today().year
    fungsi = request.args.get('fungsi', '').strip()

    q = (BAST.query.join(Kontrak)
         .filter(BAST.bulan_bast == bulan, BAST.tahun_bast == tahun))
    if fungsi:
        q = q.filter(Kontrak.nama_fungsi == fungsi)
    bast_list = sorted(q.all(), key=lambda b: sort_key_nomor(b.nomor_bast))

    return render_template('daftar_bast.html',
        bast_list=bast_list, bulan=bulan, tahun=tahun,
        fungsi=fungsi,
        fungsi_list=list(FUNGSI_KODE.keys()),
        nama_bulan=NAMA_BULAN)


@main.route('/bast/<int:id>')
@login_required
def detail_bast(id):
    bast = BAST.query.get_or_404(id)
    return render_template('detail_bast.html', bast=bast, nama_bulan=NAMA_BULAN)


@main.route('/bast/hapus/<int:id>', methods=['POST'])
@login_required
@role_required('admin_kabupaten', 'admin_fungsi')
def hapus_bast(id):
    bast = BAST.query.get_or_404(id)
    bulan_kembali = bast.bulan_bast
    tahun_kembali = bast.tahun_bast
    db.session.delete(bast)
    db.session.flush()
    renomor_semua_bast()
    db.session.commit()
    flash('BAST berhasil dihapus. Nomor urut BAST disesuaikan.', 'warning')
    return redirect(url_for('main.daftar_bast',
                            bulan=bulan_kembali, tahun=tahun_kembali))


@main.route('/bast/<int:id>/bast.docx')
@login_required
def generate_bast_doc(id):
    from app.doc_generator import generate_bast as gen_bast
    bast = BAST.query.get_or_404(id)
    kontrak = bast.kontrak
    template = os.path.join(os.path.dirname(__file__), 'templates', 'DOKUMEN_BAST.docx')
    data = {
        'nomor_spk':       kontrak.nomor_spk,
        'nomor_bast':      bast.nomor_bast or kontrak.nomor_bast,
        'bulan':           bast.bulan_bast,
        'tahun':           bast.tahun_bast,
        'tanggal_surat':   kontrak.tanggal_surat,
        'tanggal_mulai':   kontrak.tanggal_mulai,
        'tanggal_selesai': bast.tanggal_bast,  # tanggal BAST = hari kerja pertama bulan pencairan
        'petugas_nama':    kontrak.petugas.nama,
        'petugas_jabatan': kontrak.petugas.jabatan or 'Mitra',
        'petugas_alamat':  kontrak.petugas.alamat or '-',
        'total_honor':     float(bast.total_honor),
        'kegiatan_list': [{
            'nama_kegiatan': bk.kegiatan.nama_kegiatan,
            'fungsi':        bk.kegiatan.fungsi,
            'tgl_mulai':     bk.kegiatan.tgl_mulai,
            'tgl_selesai':   bk.kegiatan.tgl_selesai,
            'volume':        bk.kegiatan.volume,
            'satuan':        bk.kegiatan.satuan,
            'honor_satuan':  float(bk.kegiatan.honor_satuan),
            'honor_total':   float(bk.kegiatan.honor_total),
            'mata_akun':     bk.kegiatan.mata_akun,
        } for bk in bast.kegiatan_list],
    }
    docx_bytes = gen_bast(data, template)
    nama = f"BAST_{(bast.nomor_bast or kontrak.nomor_bast).replace('/', '-')}_{NAMA_BULAN[bast.bulan_bast]}.docx"
    return Response(docx_bytes,
        mimetype='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        headers={'Content-Disposition': f'attachment; filename="{nama}"'})


@main.route('/kontrak')
@login_required
def daftar_kontrak():
    bulan = request.args.get('bulan', type=int)
    tahun = request.args.get('tahun', type=int)
    query = Kontrak.query
    if bulan: query = query.filter_by(bulan=bulan)
    if tahun: query = query.filter_by(tahun=tahun)
    return render_template('kontrak/daftar.html',
                           kontrak_list=query.order_by(Kontrak.tanggal_surat.desc()).all(),
                           bulan=bulan, tahun=tahun, nama_bulan=NAMA_BULAN)

@main.route('/kontrak/<int:id>')
@login_required
def detail_kontrak(id):
    return render_template('kontrak/detail.html',
                           kontrak=Kontrak.query.get_or_404(id), nama_bulan=NAMA_BULAN)
