import os
import json
import subprocess
import re
import sys
import time
import glob
import io
import shutil 
from datetime import datetime
from zoneinfo import ZoneInfo
import paramiko
import requests
from dotenv import load_dotenv
import shlex
from collections import defaultdict

# --- Cấu hình chung ---
KTB_IMAGE_PATH = "../ktbproject/ktbimage"
CONFIG_FILE = 'config.json'
PROCESSING_DIR = 'Processing' 

# --- THAY ĐỔI: Hàm lấy SSH Key đơn giản hóa ---
def get_ssh_key():
    key_path = os.getenv("SSH_KEY_PATH")
    
    if not key_path:
        raise ValueError("Thieu 'SSH_KEY_PATH' trong file .env")
    
    key_path = os.path.expanduser(key_path)
    if os.name == 'nt': # Xử lý đường dẫn Windows
        if key_path.startswith('/c/'): key_path = 'C:/' + key_path[3:]
        elif key_path.startswith('/d/'): key_path = 'D:/' + key_path[3:]
        # Thêm ổ đĩa khác nếu cần
    
    print(f"Su dung SSH Key tu duong dan: {key_path}")
    if not os.path.exists(key_path):
        raise FileNotFoundError(f"Khong tim thay file key tai: {key_path}")
        
    try: return paramiko.Ed25519Key.from_private_key_file(key_path)
    except paramiko.ssh_exception.SSHException:
        try: return paramiko.RSAKey.from_private_key_file(key_path)
        except paramiko.ssh_exception.SSHException:
            raise ValueError("Khong the tai key (Chi ho tro RSA/Ed25519)")
# --- KẾT THÚC THAY ĐỔI ---

# --- Hàm Gửi Telegram Admin (Đã sửa) ---
def send_admin_telegram_message(message_content):
    # THAY ĐỔI: Đọc token và chat_id từ .env
    bot_token = os.getenv('TELEGRAM_BOT_TOKEN')
    admin_chat_id = os.getenv('TELEGRAM_CHAT_ID') # Admin dùng chung chat_id với user

    if not bot_token or not admin_chat_id:
        print("[LOI] Thieu TELEGRAM_BOT_TOKEN hoac TELEGRAM_CHAT_ID trong .env")
        return
        
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {'chat_id': admin_chat_id, 'text': message_content}
    try:
        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()
        print(f"✅ Da gui bao cao xep hang den Admin Telegram. (Response: {response.json().get('ok', 'Failed')})")
    except requests.exceptions.RequestException as e:
        print(f"❌ Loi khi gui request den Telegram: {e}")

# --- Hàm Xử lý Chính ---
def main():
    print("--- Bat dau quy trinh KTB Admin Upload Queue ---")
    
    if not os.path.exists('.env'):
        print("Loi: File .env khong ton tai.")
        sys.exit(1)
    load_dotenv()
    
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            config = json.load(f)
        remote_queue_dir = config.get('remote_queue_dir')
        default_author = config.get('default_user_author') 
        if not remote_queue_dir:
            raise ValueError("Thieu 'remote_queue_dir' trong config.json")
    except Exception as e:
        print(f"Loi doc config.json: {e}")
        sys.exit(1)

    # --- THAY ĐỔI: Đọc .env mới ---
    admin_vps_user = os.getenv("VPS_USERNAME") 
    telegram_bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    telegram_chat_id = os.getenv("TELEGRAM_CHAT_ID")
    # SSH_KEY_PATH sẽ được đọc bởi hàm get_ssh_key()
    
    if not admin_vps_user or not telegram_bot_token or not telegram_chat_id:
        print("Loi: Thieu 'VPS_USERNAME', 'TELEGRAM_BOT_TOKEN', 'TELEGRAM_CHAT_ID' trong .env")
        sys.exit(1)
    # --- KẾT THÚC THAY ĐỔI ---

    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    report_content = f"--- Bao cao KTB Admin Upload Queue ---\nUser: {default_author}\nTimestamp: {timestamp}\n"
    total_files_queued = 0

    # ... (Logic di chuyển file vào Processing giữ nguyên) ...
    source_dir = os.path.join(KTB_IMAGE_PATH, 'OutputImage')
    processing_dir = PROCESSING_DIR
    os.makedirs(processing_dir, exist_ok=True)
    
    print(f"Dang di chuyen file tu '{source_dir}' vao '{processing_dir}'...")
    moved_count = 0
    initial_zip_files = [f for f in os.listdir(source_dir) if f.endswith('.zip')]
    
    for filename in initial_zip_files:
        source_path = os.path.join(source_dir, filename)
        dest_path = os.path.join(processing_dir, filename)
        try:
            shutil.move(source_path, dest_path)
            moved_count += 1
        except Exception as e:
            print(f"⚠️  [LOI] Khong the di chuyen file {filename}: {e}")
            report_content += f"\n[LOI] MOVE: {filename} ({e})"

    if moved_count > 0:
        print(f"✅ Da di chuyen {moved_count} file zip.")
    else:
        print("Khong co file zip moi nao trong 'OutputImage'.")
    
    files_to_upload = [f for f in os.listdir(processing_dir) if f.endswith('.zip')]
    if not files_to_upload:
        print(f"Khong co file .zip nao trong '{processing_dir}' de xu ly.")
        send_admin_telegram_message(report_content + f"\n\nKhong co file .zip nao trong '{processing_dir}'.")
        cleanup_temp_files()
        return

    # --- Sắp xếp file theo Host VPS ---
    files_by_host = defaultdict(list)
    print("Dang phan loai file theo Host VPS...")
    
    for filename in files_to_upload:
        local_zip_file = os.path.join(processing_dir, filename) 
        
        site_config = next((site for site in config.get('sites', []) if filename.startswith(site['prefix'])), None)
        if not site_config:
            print(f"⚠️  [LOI] {filename}: Khong tim thay site config. File se nam lai trong '{processing_dir}'.")
            report_content += f"\n[LOI] {filename} (Khong tim thay site config, chua xoa)"
            continue
        
        vps_prefix = site_config['vps_secret_prefix'] 
        vps_host = os.getenv(f"{vps_prefix}_VPS_HOST")
        vps_port = int(os.getenv(f"{vps_prefix}_VPS_PORT"))
        
        if not vps_host or not vps_port:
             print(f"⚠️  [LOI] {filename}: Khong tim thay HOST/PORT. File se nam lai trong '{processing_dir}'.")
             report_content += f"\n[LOI] {filename} (Loi .env, chua xoa)"
             continue
        
        wp_author = site_config.get('wp_author')
        if not wp_author:
             wp_author = default_author 
        
        if not wp_author:
             print(f"⚠️  [LOI] {filename}: Thieu 'wp_author' (site) VA 'default_user_author' (goc). File se nam lai trong '{processing_dir}'.")
             report_content += f"\n[LOI] {filename} (Thieu author config, chua xoa)"
             continue

        # --- THAY ĐỔI: Thêm thông tin Telegram vào meta.json ---
        meta_content = {
            "wp_author": wp_author,
            "wp_path": site_config['wp_path'],
            "zip_filename": filename, 
            "prefix": site_config['prefix'],
            "telegram_bot_token": telegram_bot_token,
            "telegram_chat_id": telegram_chat_id
        }
        # --- KẾT THÚC THAY ĐỔI ---
        
        host_key = (vps_host, vps_port, vps_prefix)
        unique_job_dir_name = f"job_{int(time.time())}_{wp_author}_{filename[:20]}"
        
        file_package = {
            "original_filename": filename, 
            "local_zip_path": local_zip_file,
            "meta_content": meta_content,
            "unique_job_dir_name": unique_job_dir_name, 
        }
        files_by_host[host_key].append(file_package)

    # --- Vòng lặp kết nối và Upload ---
    
    # --- THAY ĐỔI: Lấy key 1 lần duy nhất ---
    try:
        ssh_key = get_ssh_key() 
    except Exception as e:
        print(f"❌ LOI FATAL: Khong the tai SSH Key. Dung script. Loi: {e}")
        send_admin_telegram_message(f"LỖI ADMIN UPLOAD: KHÔNG THỂ TẢI SSH KEY. \nLỗi: {e}")
        sys.exit(1)
    # --- KẾT THÚC THAY ĐỔI ---

    for (host, port, vps_prefix_key), file_list in files_by_host.items():
        print("\n" + "="*50)
        print(f"🚀 Dang ket noi den Host: {host}:{port} (User: {admin_vps_user}) - Su dung SSH Key")
        
        ssh = None
        sftp = None
        try:
            # --- THAY ĐỔI: Sử dụng PKey (SSH Key) ---
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ssh.connect(host, port=port, username=admin_vps_user, pkey=ssh_key, timeout=10)
            # --- KẾT THÚC THAY ĐỔI ---
            
            sftp = ssh.open_sftp()
            print(f"✅ Ket noi {host} thanh cong. Bat dau upload {len(file_list)} job...")

            # ... (Logic upload và dọn dẹp file trong Processing giữ nguyên) ...
            for package in file_list:
                filename = package['original_filename']
                local_zip_path = package['local_zip_path']
                meta_content = package['meta_content']
                job_dir_name = package['unique_job_dir_name']
                
                local_meta_path = os.path.join(processing_dir, f"{job_dir_name}_meta.json")
                remote_job_dir_path_tmp = f"{remote_queue_dir}/tmp_{job_dir_name}"
                remote_job_dir_path_final = f"{remote_queue_dir}/{job_dir_name}"

                remote_zip_path = f"{remote_job_dir_path_tmp}/{filename}"
                remote_meta_path = f"{remote_job_dir_path_tmp}/meta.json" 

                upload_successful = False
                try:
                    print(f"   Tao job folder tam: tmp_{job_dir_name}...")
                    sftp.mkdir(remote_job_dir_path_tmp) 
                    
                    with open(local_meta_path, 'w', encoding='utf-8') as f:
                        json.dump(meta_content, f)

                    print(f"   Uploading meta.json (tam)...")
                    sftp.put(local_meta_path, remote_meta_path) 
                    
                    print(f"   Uploading {filename} (tam)...")
                    sftp.put(local_zip_path, remote_zip_path)

                    print(f"   Kich hoat job (doi ten thu muc)...")
                    command = f"mv {shlex.quote(remote_job_dir_path_tmp)} {shlex.quote(remote_job_dir_path_final)}"
                    stdin, stdout, stderr = ssh.exec_command(command)
                    exit_status = stdout.channel.recv_exit_status()
                    
                    if exit_status != 0:
                        raise Exception(f"Loi doi ten thu muc job: {stderr.read().decode()}")

                    upload_successful = True 
                    
                    print(f"   ✅ {filename}: Da xep hang thanh cong.")
                    report_content += f"\n[OK] {filename} -> {host} (Admin)"
                    total_files_queued += 1
                    
                except Exception as e:
                    print(f"   [LOI] {filename}: Upload that bai: {e}")
                    report_content += f"\n[LOI] {filename} (Upload failed: {e})"
                    try: 
                        sftp.remove(remote_zip_path)
                        sftp.remove(remote_meta_path)
                        sftp.rmdir(remote_job_dir_path_tmp)
                    except: pass
                    
                finally:
                    if os.path.exists(local_meta_path):
                        os.remove(local_meta_path) 
                        
                    if upload_successful:
                        try:
                            os.remove(local_zip_path)
                            print(f"   🧹 Da xoa file local: {local_zip_path}")
                        except Exception as e_del:
                             print(f"   [LOI] Khong the xoa file local {local_zip_path}: {e_del}")
                    else:
                        print(f"   ⚠️  File zip '{filename}' van con trong '{processing_dir}' do upload loi.")

        except paramiko.AuthenticationException:
            print(f"❌ LOI: Xac thuc SSH Key voi {host} that bai! Kiem tra key.")
            report_content += f"\n\n❌ LỖI KẾT NỐI {host}: XÁC THỰC SSH KEY THẤT BẠI."
        except Exception as e:
            print(f"❌ LOI SCRIPT voi {host}: {e}")
            report_content += f"\n\n❌ LỖI SCRIPT {host}: {e}"
        finally:
            if sftp: sftp.close()
            if ssh: ssh.close()
            print(f"--- Da ngat ket noi khoi {host} ---")

    # ... (Gửi báo cáo và dọn dẹp giữ nguyên) ...
    print("\n" + "="*50)
    print("📊 Gui bao cao tong ket xep hang (Admin)...")
    if total_files_queued > 0:
        report_content += f"\n\nTong cong: {total_files_queued} file da duoc xep hang boi Admin."
    else:
        report_content += f"\n\nKhong co file nao duoc xep hang thanh cong."

    print("--- Noi dung bao cao Admin ---")
    print(report_content)
    print("----------------------------")
    send_admin_telegram_message(report_content)
    
    cleanup_temp_files() 
    
    print("\n--- Hoan tat quy trinh KTB-Upload Sync (Queue Mode - Admin) ---")

def cleanup_temp_files():
    print("\n" + "="*50)
    print("🧹 Don dep cac file log va report tam cu...")
    
    count = 0
    for pattern in ['uploaded_files_*.log', 'temp_remote_script.py.sh']:
        for f in glob.glob(pattern):
            try:
                os.remove(f)
                count += 1
            except Exception as e:
                print(f"   [Loi] Khong the xoa {f}: {e}")

    if count > 0:
         print(f"✅ Da xoa {count} file tam cu.")
    else:
         print("👌 Khong co file tam cu nao de xoa.")

if __name__ == "__main__":
    main()