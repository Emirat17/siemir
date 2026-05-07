from flask import Blueprint, render_template, redirect, url_for, request, flash, Response, jsonify, session
from app.auth import login_required, role_required, get_current_user
from app import db
from app.models import Petugas, Kontrak, Kegiatan, NomorUrut, DaftarKegiatan, BAST, BASTKegiatan, FUNGSI_KODE
from app.utils import generate_pdf
import os
from datetime import date
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

def next_nomor_global():
    rec = NomorUrut.query.filter_by(jenis='SPK').first()
    if not rec:
        rec = NomorUrut(jenis='SPK', terakhir=148)
        db.session.add(rec)
    rec.terakhir += 1
    nomor = rec.terakhir
    brec = NomorUrut.query.filter_by(jenis='BAST').first()
    if not brec:
        brec = NomorUrut(jenis='BAST', terakhir=148)
        db.session.add(brec)
    brec.terakhir = nomor
    return nomor

def buat_nomor_spk(nomor, kode_fungsi, tahun):
    return f"PK-{nomor}/{kode_fungsi}/VS.330/{tahun}"

def buat_nomor_bast(nomor, kode_fungsi, tahun):
    return f"BAST-{nomor}/{kode_fungsi}/VS.430/{tahun}"

def update_nomor_fungsi(kontrak):
    if kontrak.nomor_spk:
        bagian = kontrak.nomor_spk.split('/')
        if len(bagian) >= 2 and bagian[1] != kontrak.kode_fungsi:
            kontrak.nomor_spk  = kontrak.nomor_spk.replace(bagian[1], kontrak.kode_fungsi, 1)
            kontrak.nomor_bast = kontrak.nomor_bast.replace(bagian[1], kontrak.kode_fungsi, 1)

@main.route('/')
@login_required
def index():
    total_petugas   = Petugas.query.count()
    total_kontrak   = Kontrak.query.count()
    bulan_ini       = date.today().month
    tahun_ini       = date.today().year
    kontrak_bulan   = Kontrak.query.filter_by(bulan=bulan_ini, tahun=tahun_ini).count()
    kontrak_terbaru = Kontrak.query.order_by(Kontrak.dibuat.desc()).limit(5).all()
    return render_template('index.html',
        total_petugas=total_petugas, total_kontrak=total_kontrak,
        kontrak_bulan=kontrak_bulan, kontrak_terbaru=kontrak_terbaru,
        nama_bulan=NAMA_BULAN)

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
                keg = DaftarKegiatan(
                    fungsi        = fungsi_form,
                    bulan         = bulan_form,
                    tahun         = tahun_form,
                    nama_kegiatan = nama.strip(),
                    tgl_mulai     = date.fromisoformat(request.form.getlist('tgl_mulai')[i]),
                    tgl_selesai   = date.fromisoformat(request.form.getlist('tgl_selesai')[i]),
                    satuan        = request.form.getlist('satuan')[i],
                    volume_default= int(request.form.getlist('volume_default')[i] or 1),
                    honor_satuan  = float(request.form.getlist('honor_satuan')[i] or 0),
                    mata_akun     = request.form.getlist('mata_akun')[i].strip(),
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
        ganti_rugi     = float(request.form.get('total_ganti_rugi', 0))
        tgl_surat = tanggal_surat_otomatis(bulan, tahun)
        tgl_mulai_otomatis = tanggal_mulai_otomatis(bulan, tahun)

        kontrak = Kontrak.query.filter_by(petugas_id=petugas_id, bulan=bulan, tahun=tahun).first()
        if kontrak is None:
            kontrak = Kontrak(petugas_id=petugas_id, tanggal_surat=tgl_surat,
                tanggal_mulai=tgl_mulai_otomatis,
                tanggal_selesai=tgl_mulai_otomatis,  # placeholder, diupdate setelah kegiatan
                bulan=bulan, tahun=tahun, total_ganti_rugi=ganti_rugi)
            db.session.add(kontrak)
            db.session.flush()
            is_baru = True
        else:
            kontrak.total_ganti_rugi = float(kontrak.total_ganti_rugi or 0) + ganti_rugi
            is_baru = False
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
            # Ambil tanggal dari hidden field (diisi JS dari data DaftarKegiatan)
            tgl_m = date.fromisoformat(tgl_m_list[i]) if tgl_m_list[i] else tanggal_mulai_otomatis(bulan, tahun)
            tgl_s = date.fromisoformat(tgl_s_list[i]) if tgl_s_list[i] else tanggal_mulai_otomatis(bulan, tahun)
            db.session.add(Kegiatan(
                kontrak_id=kontrak.id, fungsi=fungsi_dipilih, nama_kegiatan=nama.strip(),
                tgl_mulai=tgl_m, tgl_selesai=tgl_s,
                volume=vol, satuan=sat_list[i],
                honor_satuan=hsat, honor_total=vol*hsat,
                mata_akun=akun_list[i], urutan=urutan_mulai+i))
        db.session.flush()
        # Update tanggal_mulai & tanggal_selesai otomatis dari semua kegiatan
        kontrak.tanggal_mulai = tanggal_mulai_otomatis(kontrak.bulan, kontrak.tahun)
        tgl_selesai_keg = tanggal_selesai_dari_kegiatan(kontrak.kegiatan_list)
        if tgl_selesai_keg:
            kontrak.tanggal_selesai = tgl_selesai_keg
        kontrak.hitung_total_dan_fungsi()
        if is_baru:
            nomor = next_nomor_global()
            kontrak.nomor_spk  = buat_nomor_spk(nomor, kontrak.kode_fungsi, tahun)
            kontrak.nomor_bast = buat_nomor_bast(nomor, kontrak.kode_fungsi, tahun)
        else:
            update_nomor_fungsi(kontrak)
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
        keg.kontrak.hitung_total_dan_fungsi()
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
    kontrak.hitung_total_dan_fungsi()
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
    return render_template('kontrak/form_edit.html', kontrak=kontrak, nama_bulan=NAMA_BULAN)

@main.route('/kontrak/hapus/<int:id>', methods=['POST'])
@login_required
@role_required('admin_kabupaten')
def hapus_kontrak(id):
    kontrak = Kontrak.query.get_or_404(id)
    db.session.delete(kontrak); db.session.commit()
    flash('Kontrak berhasil dihapus.', 'warning')
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
def daftar_petugas():
    return render_template('petugas/daftar.html',
                           petugas_list=Petugas.query.order_by(Petugas.nama).all())

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
    bulan = request.args.get('bulan', type=int)
    tahun = request.args.get('tahun', type=int)
    kontrak_list = []
    if bulan and tahun:
        kontrak_list = (Kontrak.query
                        .filter_by(bulan=bulan, tahun=tahun)
                        .order_by(Kontrak.nomor_spk)
                        .all())
    return render_template('generate_bulanan.html',
                           bulan=bulan, tahun=tahun,
                           kontrak_list=kontrak_list,
                           nama_bulan=NAMA_BULAN)

@main.route('/generate/merge-spk')
@login_required
def merge_spk():
    from app.doc_generator import generate_spk as gen_spk, merge_docx_list
    bulan = request.args.get('bulan', type=int)
    tahun = request.args.get('tahun', type=int)
    if not bulan or not tahun:
        flash('Pilih bulan dan tahun terlebih dahulu.', 'warning')
        return redirect(url_for('main.generate_bulanan'))

    kontrak_list = (Kontrak.query
                    .filter_by(bulan=bulan, tahun=tahun)
                    .order_by(Kontrak.nomor_spk)
                    .all())
    if not kontrak_list:
        flash('Tidak ada kontrak untuk periode ini.', 'warning')
        return redirect(url_for('main.generate_bulanan', bulan=bulan, tahun=tahun))

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
    nama_bulan_str = NAMA_BULAN[bulan]
    nama_file = f"SPK_Gabungan_{nama_bulan_str}_{tahun}.docx"
    return Response(merged,
        mimetype='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        headers={'Content-Disposition': f'attachment; filename="{nama_file}"'})

@main.route('/generate/merge-bast')
@login_required
def merge_bast():
    from app.doc_generator import generate_bast as gen_bast, merge_docx_list
    bulan = request.args.get('bulan', type=int)
    tahun = request.args.get('tahun', type=int)
    if not bulan or not tahun:
        flash('Pilih bulan dan tahun terlebih dahulu.', 'warning')
        return redirect(url_for('main.generate_bulanan'))

    kontrak_list = (Kontrak.query
                    .filter_by(bulan=bulan, tahun=tahun)
                    .order_by(Kontrak.nomor_bast)
                    .all())
    if not kontrak_list:
        flash('Tidak ada kontrak untuk periode ini.', 'warning')
        return redirect(url_for('main.generate_bulanan', bulan=bulan, tahun=tahun))

    template = os.path.join(os.path.dirname(__file__), 'templates', 'DOKUMEN_BAST.docx')
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
                'tgl_mulai':     k.tgl_mulai,
                'tgl_selesai':   k.tgl_selesai,
                'volume':        k.volume,
                'satuan':        k.satuan,
                'honor_satuan':  float(k.honor_satuan),
                'honor_total':   float(k.honor_total),
                'mata_akun':     k.mata_akun,
            } for k in sorted(kontrak.kegiatan_list, key=lambda x: x.urutan)],
        }
        docx_list.append(gen_bast(data, template))

    merged = merge_docx_list(docx_list)
    nama_bulan_str = NAMA_BULAN[bulan]
    nama_file = f"BAST_Gabungan_{nama_bulan_str}_{tahun}.docx"
    return Response(merged,
        mimetype='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        headers={'Content-Disposition': f'attachment; filename="{nama_file}"'})


# ─── REKAP HONOR ─────────────────────────────────────────────────
@main.route('/rekap')
@login_required
def rekap_honor():
    bulan = request.args.get('bulan', type=int)
    tahun = request.args.get('tahun', type=int)
    kontrak_list = []
    if bulan and tahun:
        kontrak_list = (Kontrak.query
                        .filter_by(bulan=bulan, tahun=tahun)
                        .order_by(Kontrak.nomor_spk).all())
    return render_template('rekap_honor.html',
                           bulan=bulan, tahun=tahun,
                           kontrak_list=kontrak_list, nama_bulan=NAMA_BULAN)

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
def entri_bast():
    """
    Halaman entri BAST per bulan pencairan.
    User memilih petugas, bulan BAST, dan kegiatan mana yang masuk.
    Sistem menyarankan otomatis kegiatan yang tgl_selesai-nya <= akhir bulan SPK.
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
                bast = bast_existing
            else:
                # Buat BAST baru
                tgl_bast = tanggal_bast_otomatis(bulan_bast_v - 1 if bulan_bast_v > 1 else 12,
                                                  tahun_bast_v if bulan_bast_v > 1 else tahun_bast_v - 1)
                bast = BAST(
                    kontrak_id   = kontrak_id,
                    bulan_bast   = bulan_bast_v,
                    tahun_bast   = tahun_bast_v,
                    tanggal_bast = tgl_bast,
                    nomor_bast   = kontrak.nomor_bast,
                )
                db.session.add(bast)
                db.session.flush()

            # Tambah kegiatan yang dipilih
            for keg_id in keg_ids:
                bk = BASTKegiatan(bast_id=bast.id, kegiatan_id=int(keg_id))
                db.session.add(bk)

            db.session.flush()
            bast.hitung_total()
            db.session.commit()

            flash(f'BAST {NAMA_BULAN[bulan_bast_v]} {tahun_bast_v} untuk {kontrak.petugas.nama} '
                  f'berhasil disimpan ({len(keg_ids)} kegiatan).', 'success')
            return redirect(url_for('main.daftar_bast'))

        return redirect(url_for('main.entri_bast', bulan=bulan, tahun=tahun))

    return render_template('entri_bast.html',
        petugas_list=petugas_list,
        bulan=bulan, tahun=tahun,
        nama_bulan=NAMA_BULAN)


@main.route('/api/kegiatan-bast')
@login_required
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


# ─── DAFTAR BAST ─────────────────────────────────────────────────
@main.route('/daftar-bast')
@login_required
def daftar_bast():
    bulan = request.args.get('bulan', type=int)
    tahun = request.args.get('tahun', type=int)
    query = BAST.query
    if bulan: query = query.filter_by(bulan_bast=bulan)
    if tahun: query = query.filter_by(tahun_bast=tahun)
    bast_list = query.order_by(BAST.nomor_bast).all()
    return render_template('daftar_bast.html',
        bast_list=bast_list, bulan=bulan, tahun=tahun,
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
    db.session.delete(bast)
    db.session.commit()
    flash('BAST berhasil dihapus.', 'warning')
    return redirect(url_for('main.daftar_bast'))


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
        'tanggal_selesai': bast.tanggal_bast or kontrak.tanggal_selesai,
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
