"""
Script LOKAL — gabungkan dokumen BAPP (yang sudah disisipi screenshot)
menjadi file besar per jenis, agar mudah dicetak massal.

Sumber : tools/BAPP_Termin1_dengan_screenshot/PPL/*.docx  &  /PML/*.docx
Hasil  : tools/BAPP_Termin1_dengan_screenshot/BAPP_PPL_gabungan.docx  (dst.)

Gambar screenshot ikut tergabung dengan benar (tidak tertukar).

Jalankan:  py tools/gabung_bapp.py
"""
import os
import io
import glob
import importlib.util

HERE   = os.path.dirname(os.path.abspath(__file__))
REPO   = os.path.dirname(HERE)
INPUT  = os.path.join(HERE, 'BAPP_Termin1_dengan_screenshot')

# 0  = satu file gabungan per jenis (paling praktis untuk cetak)
# >0 = pecah tiap N dokumen (mis. 40) bila file terlalu besar/berat dibuka
BATCH_SIZE = 0


def load_docgen():
    spec = importlib.util.spec_from_file_location(
        'docgen', os.path.join(REPO, 'app', 'doc_generator.py'))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def gabung(dg, jenis):
    folder = os.path.join(INPUT, jenis)
    if not os.path.isdir(folder):
        print(f'[{jenis}] folder tidak ada: {folder}')
        return
    # '[0-9]*' → hanya file hasil (mulai nomor), abaikan file kunci ~$
    files = sorted(glob.glob(os.path.join(folder, '[0-9]*.docx')))
    if not files:
        print(f'[{jenis}] tidak ada dokumen.')
        return
    docs = [open(f, 'rb').read() for f in files]
    print(f'[{jenis}] {len(docs)} dokumen ditemukan...')

    def simpan(data, nama):
        path = os.path.join(INPUT, nama)
        with open(path, 'wb') as f:
            f.write(data)
        print(f'   -> {nama}  ({len(data)/1_048_576:.1f} MB)')

    if BATCH_SIZE <= 0:
        simpan(dg.merge_docx_list(docs), f'BAPP_{jenis}_gabungan.docx')
    else:
        bagian = 1
        for i in range(0, len(docs), BATCH_SIZE):
            batch = docs[i:i + BATCH_SIZE]
            simpan(dg.merge_docx_list(batch),
                   f'BAPP_{jenis}_gabungan_bagian{bagian}.docx')
            bagian += 1


def main():
    dg = load_docgen()
    for jenis in ('PPL', 'PML'):
        try:
            gabung(dg, jenis)
        except Exception as e:
            print(f'[{jenis}] ERROR: {e}')
    print(f'\nSelesai. File gabungan ada di: {INPUT}')


if __name__ == '__main__':
    main()
