from app import db
from datetime import datetime
from collections import defaultdict
from werkzeug.security import generate_password_hash, check_password_hash

FUNGSI_KODE = {
    'Umum':       '14.101',
    'Sosial':     '14.102',
    'Produksi':   '14.103',
    'Distribusi': '14.104',
    'Nerwilis':   '14.105',
    'IPDS':       '14.106',
}

# Role: admin_kabupaten, ppk, admin_fungsi
ROLE_LABEL = {
    'admin_kabupaten': 'Admin Kabupaten',
    'ppk':             'PPK',
    'admin_fungsi':    'Admin Fungsi',
}

class User(db.Model):
    __tablename__ = 'user'
    id           = db.Column(db.Integer, primary_key=True)
    username     = db.Column(db.String(50), unique=True, nullable=False)
    password_hash= db.Column(db.String(256), nullable=False)
    nama_lengkap = db.Column(db.String(150), nullable=False)
    role         = db.Column(db.String(30), nullable=False, default='admin_fungsi')
    fungsi       = db.Column(db.String(50))   # khusus admin_fungsi
    aktif        = db.Column(db.Boolean, default=True)
    dibuat       = db.Column(db.DateTime, default=datetime.utcnow)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @property
    def role_label(self):
        return ROLE_LABEL.get(self.role, self.role)

    @property
    def is_admin_kabupaten(self): return self.role == 'admin_kabupaten'
    @property
    def is_ppk(self):             return self.role == 'ppk'
    @property
    def is_admin_fungsi(self):    return self.role == 'admin_fungsi'
    @property
    def can_input(self):          return self.role in ('admin_kabupaten', 'admin_fungsi')
    @property
    def can_manage_petugas(self): return self.role == 'admin_kabupaten'

    def __repr__(self): return f'<User {self.username}>'


class Petugas(db.Model):
    __tablename__ = 'petugas'
    id                    = db.Column(db.Integer, primary_key=True)
    nama                  = db.Column(db.String(150), nullable=False)
    jabatan               = db.Column(db.String(100))
    posisi                = db.Column(db.String(150))
    alamat                = db.Column(db.Text)
    alamat_provinsi       = db.Column(db.String(100))
    alamat_kabupaten      = db.Column(db.String(100))
    alamat_kecamatan      = db.Column(db.String(100))
    alamat_desa           = db.Column(db.String(100))
    tempat_tgl_lahir      = db.Column(db.String(200))
    jenis_kelamin         = db.Column(db.String(10))
    pendidikan            = db.Column(db.String(100))
    pekerjaan             = db.Column(db.String(100))
    deskripsi_pekerjaan   = db.Column(db.String(200))
    no_telp               = db.Column(db.String(30))
    sobat_id              = db.Column(db.String(50))
    email                 = db.Column(db.String(150))
    dibuat                = db.Column(db.DateTime, default=datetime.utcnow)
    kontrak_list = db.relationship('Kontrak', backref='petugas', lazy=True,
                                   cascade='all, delete-orphan')
    def __repr__(self): return f'<Petugas {self.nama}>'



class BAST(db.Model):
    """
    Dokumen BAST per petugas per bulan pencairan.
    Satu BAST = kegiatan dari satu SPK yang tgl_selesainya
    jatuh di bulan sebelum bulan_bast ini.
    """
    __tablename__ = 'bast'

    id              = db.Column(db.Integer, primary_key=True)
    kontrak_id      = db.Column(db.Integer, db.ForeignKey('kontrak.id'), nullable=False)
    nomor_bast      = db.Column(db.String(100))        # nomor BAST (bisa beda dengan kontrak)
    bulan_bast      = db.Column(db.Integer, nullable=False)   # bulan pencairan
    tahun_bast      = db.Column(db.Integer, nullable=False)   # tahun pencairan
    tanggal_bast    = db.Column(db.Date)               # hari kerja pertama bulan_bast
    total_honor     = db.Column(db.Numeric(15, 2), default=0)
    link_bast_ttd   = db.Column(db.Text, nullable=True)      # link dokumen BAST ttd
    dibuat          = db.Column(db.DateTime, default=datetime.utcnow)

    kontrak   = db.relationship('Kontrak', backref=db.backref('bast_list', lazy=True))
    kegiatan_list = db.relationship('BASTKegiatan', backref='bast',
                                    lazy=True, cascade='all, delete-orphan')

    def hitung_total(self):
        self.total_honor = sum(float(k.honor_total or 0) for k in self.kegiatan_list)

    def __repr__(self): return f'<BAST {self.nomor_bast}>'


class BASTKegiatan(db.Model):
    """Relasi many-to-many antara BAST dan Kegiatan (dari kontrak)."""
    __tablename__ = 'bast_kegiatan'

    id          = db.Column(db.Integer, primary_key=True)
    bast_id     = db.Column(db.Integer, db.ForeignKey('bast.id'), nullable=False)
    kegiatan_id = db.Column(db.Integer, db.ForeignKey('kegiatan.id'), nullable=False)

    kegiatan = db.relationship('Kegiatan', backref=db.backref('bast_refs', lazy=True))

    def __repr__(self): return f'<BASTKegiatan bast={self.bast_id} keg={self.kegiatan_id}>'

    @property
    def honor_total(self):
        return self.kegiatan.honor_total if self.kegiatan else 0

    @property
    def nama_kegiatan(self):
        return self.kegiatan.nama_kegiatan if self.kegiatan else ''


class NomorUrut(db.Model):
    __tablename__ = 'nomor_urut'
    id       = db.Column(db.Integer, primary_key=True)
    jenis    = db.Column(db.String(10), unique=True, nullable=False)
    terakhir = db.Column(db.Integer, nullable=False, default=148)



class DaftarKegiatan(db.Model):
    """Master daftar kegiatan per fungsi per bulan — diinput oleh Admin Fungsi."""
    __tablename__ = 'daftar_kegiatan'

    id            = db.Column(db.Integer, primary_key=True)
    fungsi        = db.Column(db.String(50), nullable=False)
    bulan         = db.Column(db.Integer, nullable=False)
    tahun         = db.Column(db.Integer, nullable=False)
    nama_kegiatan = db.Column(db.String(200), nullable=False)
    tgl_mulai     = db.Column(db.Date, nullable=False)
    tgl_selesai   = db.Column(db.Date, nullable=False)
    satuan        = db.Column(db.String(50), nullable=False, default='OH')
    volume_default= db.Column(db.Integer, default=1)   # volume default per petugas
    honor_satuan  = db.Column(db.Numeric(15, 2), default=0)
    mata_akun     = db.Column(db.String(100), nullable=False)
    bulan_pencairan = db.Column(db.Integer, nullable=True)  # bulan BAST otomatis
    dibuat        = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self): return f'<DaftarKegiatan {self.nama_kegiatan}>'


class Kontrak(db.Model):
    __tablename__ = 'kontrak'
    id                 = db.Column(db.Integer, primary_key=True)
    petugas_id         = db.Column(db.Integer, db.ForeignKey('petugas.id'), nullable=False)
    nomor_spk          = db.Column(db.String(100), unique=True)
    nomor_bast         = db.Column(db.String(100), unique=True)
    kode_fungsi        = db.Column(db.String(20))
    nama_fungsi        = db.Column(db.String(50))
    tanggal_surat      = db.Column(db.Date, nullable=False)
    tanggal_mulai      = db.Column(db.Date, nullable=False)
    tanggal_selesai    = db.Column(db.Date, nullable=False)
    bulan              = db.Column(db.Integer, nullable=False)
    tahun              = db.Column(db.Integer, nullable=False)
    total_honor        = db.Column(db.Numeric(15, 2), default=0)
    total_ganti_rugi   = db.Column(db.Numeric(15, 2), default=0)
    link_spk_ttd       = db.Column(db.Text, nullable=True)   # link dokumen SPK ttd
    dibuat             = db.Column(db.DateTime, default=datetime.utcnow)
    diperbarui         = db.Column(db.DateTime, onupdate=datetime.utcnow)
    kegiatan_list = db.relationship('Kegiatan', backref='kontrak', lazy=True,
                                    cascade='all, delete-orphan')

    def hitung_total_dan_fungsi(self):
        honor_per_fungsi = defaultdict(float)
        for k in self.kegiatan_list:
            honor_per_fungsi[k.fungsi] += float(k.honor_total or 0)
        self.total_honor = sum(honor_per_fungsi.values())
        if honor_per_fungsi:
            fungsi_dominan = max(honor_per_fungsi, key=honor_per_fungsi.get)
            self.nama_fungsi = fungsi_dominan
            self.kode_fungsi = FUNGSI_KODE.get(fungsi_dominan, '14.101')

    def __repr__(self): return f'<Kontrak {self.nomor_spk}>'


class Kegiatan(db.Model):
    __tablename__ = 'kegiatan'
    id              = db.Column(db.Integer, primary_key=True)
    kontrak_id      = db.Column(db.Integer, db.ForeignKey('kontrak.id'), nullable=False)
    fungsi          = db.Column(db.String(50), nullable=False)
    nama_kegiatan   = db.Column(db.String(200), nullable=False)
    tgl_mulai       = db.Column(db.Date, nullable=False)
    tgl_selesai     = db.Column(db.Date, nullable=False)
    volume          = db.Column(db.Integer, nullable=False, default=1)
    satuan          = db.Column(db.String(50), nullable=False)
    honor_satuan    = db.Column(db.Numeric(15, 2), nullable=False, default=0)
    honor_total     = db.Column(db.Numeric(15, 2), nullable=False, default=0)
    mata_akun       = db.Column(db.String(100), nullable=False)
    urutan          = db.Column(db.Integer, default=0)
    def __repr__(self): return f'<Kegiatan {self.nama_kegiatan}>'


# ── SE2026 ───────────────────────────────────────────────────────────────────

class KontrakSE2026(db.Model):
    """Kontrak Sensus Ekonomi 2026 untuk PPL dan PML."""
    __tablename__ = 'kontrak_se2026'
    id               = db.Column(db.Integer, primary_key=True)
    jenis            = db.Column(db.String(5),  nullable=False)   # 'PPL' or 'PML'
    nomor_spk        = db.Column(db.String(100))
    nama             = db.Column(db.String(200), nullable=False)
    alamat           = db.Column(db.Text)
    tanggal_spk      = db.Column(db.Date)
    total_honor      = db.Column(db.Numeric(15, 2), default=0)
    honor_1_ob       = db.Column(db.Numeric(15, 2), default=0)
    honor_1_5_ob     = db.Column(db.Numeric(15, 2), default=0)
    total_ganti_rugi = db.Column(db.Numeric(15, 2), default=0)
    jumlah_sls       = db.Column(db.Integer, default=0)
    jumlah_usaha     = db.Column(db.Integer, default=0)
    jumlah_keluarga  = db.Column(db.Integer, default=0)
    dibuat           = db.Column(db.DateTime, default=datetime.utcnow)

    wilayah_list = db.relationship('WilayahSE2026', backref='kontrak',
                                   lazy=True, cascade='all, delete-orphan',
                                   order_by='WilayahSE2026.urutan')
    ppl_list     = db.relationship('PPLDiwasiSE2026', backref='kontrak_pml',
                                   lazy=True, cascade='all, delete-orphan',
                                   order_by='PPLDiwasiSE2026.urutan')

    def __repr__(self): return f'<SE2026 {self.jenis} {self.nama}>'


class WilayahSE2026(db.Model):
    """Wilayah kerja PPL SE2026 (maks 3 baris)."""
    __tablename__ = 'wilayah_se2026'
    id             = db.Column(db.Integer, primary_key=True)
    kontrak_id     = db.Column(db.Integer, db.ForeignKey('kontrak_se2026.id'), nullable=False)
    urutan         = db.Column(db.Integer, nullable=False)
    kode_kecamatan = db.Column(db.String(20))
    kode_desa      = db.Column(db.String(20))
    jumlah_sls     = db.Column(db.Integer, default=0)
    jumlah_keluarga= db.Column(db.Integer, default=0)


class PPLDiwasiSE2026(db.Model):
    """Daftar PPL yang diawasi oleh PML SE2026 (maks 8 orang)."""
    __tablename__ = 'ppl_diawasi_se2026'
    id             = db.Column(db.Integer, primary_key=True)
    kontrak_id     = db.Column(db.Integer, db.ForeignKey('kontrak_se2026.id'), nullable=False)
    urutan         = db.Column(db.Integer, nullable=False)
    nama_ppl       = db.Column(db.String(200))
    kode_kecamatan = db.Column(db.String(20))
    kode_desa      = db.Column(db.String(20))
    jumlah_sls     = db.Column(db.Integer, default=0)
