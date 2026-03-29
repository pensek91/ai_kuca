import os
import zipfile

EXCLUDE = [
    os.path.abspath(__file__),  # installer_builder.py
    os.path.abspath(os.path.join(os.path.dirname(__file__), "ai_kuca-install.zip")),
    os.path.abspath(os.path.join(os.path.dirname(__file__), "setup.py")),
]

ROOT = os.path.dirname(os.path.abspath(__file__))
ZIP_PATH = os.path.join(ROOT, "ai_kuca-install.zip")
SETUP_PATH = os.path.join(ROOT, "setup.py")

def zip_appdaemon(root, zip_path):
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
        for dirpath, dirnames, filenames in os.walk(root):
            for fname in filenames:
                fpath = os.path.join(dirpath, fname)
                abspath = os.path.abspath(fpath)
                if abspath in EXCLUDE:
                    continue
                relpath = os.path.relpath(fpath, root)
                zipf.write(fpath, relpath)
    print(f"Backup arhiva kreirana: {zip_path}")

def write_setup_py():
    setup_code = '''import os
import zipfile
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
ZIP_PATH = os.path.join(ROOT, "ai_kuca-install.zip")

def extract_zip(zip_path, extract_to):
    with zipfile.ZipFile(zip_path, 'r') as zipf:
        zipf.extractall(extract_to)
    print(f'Arhiva {zip_path} raspakirana u {extract_to}')

def env_wizard():
    print('--- .env konfiguracija ---')
    ha_url = input('Unesi Home Assistant URL (npr. http://localhost:8123): ').strip()
    ha_key = input('Unesi Home Assistant Long-Lived Access Token: ').strip()
    log_level = input('Unesi LOG_LEVEL (DEBUG/INFO/WARNING/ERROR/CRITICAL) [INFO]: ').strip() or 'INFO'
    env_content = f'HA_URL={ha_url}\\nHA_KEY={ha_key}\\nLOG_LEVEL={log_level}\\n'
    with open('.env', 'w', encoding='utf-8') as fenv:
        fenv.write(env_content)
    print('.env datoteka je kreirana.')

def main_menu():
    while True:
        print('\\n--- GLAVNI IZBORNIK ---')
        print('1) Svježa instalacija')
        print('2) Uređivanje soba')
        print('3) Uređivanje systema')
        print('0) Izlaz')
        choice = input('Odaberi opciju: ').strip()
        if choice == '1':
            subprocess.run([sys.executable, 'editors/fresh_install.py'])
        elif choice == '2':
            subprocess.run([sys.executable, 'editors/room_editor.py'])
        elif choice == '3':
            subprocess.run([sys.executable, 'editors/system_editor.py'])
        elif choice == '0':
            print('Izlaz...')
            break
        else:
            print('Nepoznata opcija, pokušaj ponovno.')

def main():
    print("Raspakiravanje instalacione arhive...")
    extract_zip(ZIP_PATH, ROOT)
    env_wizard()
    main_menu()

if __name__ == "__main__":
    main()
'''
    with open(SETUP_PATH, "w") as f:
        f.write(setup_code)
    print(f"Setup file written to: {SETUP_PATH}")

def main():
    zip_appdaemon(ROOT, ZIP_PATH)
    write_setup_py()
    print("Instalacioni paket je uspješno kreiran!")

if __name__ == "__main__":
    main()
