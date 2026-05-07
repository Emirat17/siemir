from functools import wraps
from flask import Blueprint, render_template, redirect, url_for, request, flash, session, g
from app import db
from app.models import User

auth = Blueprint('auth', __name__)

# ── Decorator: login required ────────────────────────────────────
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            flash('Silakan login terlebih dahulu.', 'warning')
            return redirect(url_for('auth.login', next=request.url))
        return f(*args, **kwargs)
    return decorated

def role_required(*roles):
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if 'user_id' not in session:
                flash('Silakan login terlebih dahulu.', 'warning')
                return redirect(url_for('auth.login'))
            if session.get('user_role') not in roles:
                flash('Anda tidak memiliki akses ke halaman ini.', 'danger')
                return redirect(url_for('main.index'))
            return f(*args, **kwargs)
        return decorated
    return decorator

def get_current_user():
    if 'user_id' in session:
        return User.query.get(session['user_id'])
    return None

# ── LOGIN ────────────────────────────────────────────────────────
@auth.route('/login', methods=['GET', 'POST'])
def login():
    if 'user_id' in session:
        return redirect(url_for('main.index'))
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        user = User.query.filter_by(username=username, aktif=True).first()
        if user and user.check_password(password):
            session['user_id']   = user.id
            session['user_role'] = user.role
            session['user_nama'] = user.nama_lengkap
            session['user_fungsi'] = user.fungsi or ''
            flash(f'Selamat datang, {user.nama_lengkap}!', 'success')
            next_page = request.args.get('next')
            return redirect(next_page or url_for('main.index'))
        flash('Username atau password salah.', 'danger')
    return render_template('auth/login.html')

# ── LOGOUT ───────────────────────────────────────────────────────
@auth.route('/logout')
def logout():
    session.clear()
    flash('Anda telah keluar dari sistem.', 'info')
    return redirect(url_for('auth.login'))

# ── MANAJEMEN USER (hanya admin_kabupaten) ───────────────────────
@auth.route('/pengguna')
@login_required
@role_required('admin_kabupaten')
def daftar_pengguna():
    users = User.query.order_by(User.role, User.nama_lengkap).all()
    return render_template('auth/daftar_pengguna.html', users=users)

@auth.route('/pengguna/tambah', methods=['GET', 'POST'])
@login_required
@role_required('admin_kabupaten')
def tambah_pengguna():
    from app.models import FUNGSI_KODE
    fungsi_list = list(FUNGSI_KODE.keys())
    if request.method == 'POST':
        username = request.form['username'].strip()
        if User.query.filter_by(username=username).first():
            flash(f'Username "{username}" sudah digunakan.', 'danger')
            return redirect(url_for('auth.tambah_pengguna'))
        user = User(
            username     = username,
            nama_lengkap = request.form['nama_lengkap'],
            role         = request.form['role'],
            fungsi       = request.form.get('fungsi') or None,
            aktif        = True,
        )
        user.set_password(request.form['password'])
        db.session.add(user)
        db.session.commit()
        flash(f'Pengguna "{username}" berhasil ditambahkan.', 'success')
        return redirect(url_for('auth.daftar_pengguna'))
    return render_template('auth/form_pengguna.html',
                           judul='Tambah Pengguna', user=None, fungsi_list=fungsi_list)

@auth.route('/pengguna/edit/<int:id>', methods=['GET', 'POST'])
@login_required
@role_required('admin_kabupaten')
def edit_pengguna(id):
    from app.models import FUNGSI_KODE
    fungsi_list = list(FUNGSI_KODE.keys())
    user = User.query.get_or_404(id)
    if request.method == 'POST':
        user.nama_lengkap = request.form['nama_lengkap']
        user.role         = request.form['role']
        user.fungsi       = request.form.get('fungsi') or None
        user.aktif        = 'aktif' in request.form
        if request.form.get('password'):
            user.set_password(request.form['password'])
        db.session.commit()
        flash('Data pengguna berhasil diperbarui.', 'success')
        return redirect(url_for('auth.daftar_pengguna'))
    return render_template('auth/form_pengguna.html',
                           judul='Edit Pengguna', user=user, fungsi_list=fungsi_list)

@auth.route('/pengguna/hapus/<int:id>', methods=['POST'])
@login_required
@role_required('admin_kabupaten')
def hapus_pengguna(id):
    user = User.query.get_or_404(id)
    if user.id == session.get('user_id'):
        flash('Tidak dapat menghapus akun sendiri.', 'danger')
        return redirect(url_for('auth.daftar_pengguna'))
    db.session.delete(user)
    db.session.commit()
    flash(f'Pengguna "{user.username}" dihapus.', 'warning')
    return redirect(url_for('auth.daftar_pengguna'))

@auth.route('/ganti-password', methods=['GET', 'POST'])
@login_required
def ganti_password():
    user = get_current_user()
    if request.method == 'POST':
        if not user.check_password(request.form['password_lama']):
            flash('Password lama tidak sesuai.', 'danger')
        elif request.form['password_baru'] != request.form['konfirmasi']:
            flash('Konfirmasi password tidak cocok.', 'danger')
        else:
            user.set_password(request.form['password_baru'])
            db.session.commit()
            flash('Password berhasil diubah.', 'success')
            return redirect(url_for('main.index'))
    return render_template('auth/ganti_password.html', user=user)
