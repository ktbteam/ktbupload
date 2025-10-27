import os
import json
import sys
import getpass
import requests
import shlex
import time
from datetime import datetime
from dotenv import load_dotenv
from collections import defaultdict
try:
    import paramiko
except ImportError:
    print("[LOI] Chua cai thu vien 'paramiko'.")
    print("Vui long chay lenh: pip install -r requirements.txt")
    sys.exit(1)

# --- Khai bao bien va tai cau hinh ---
load_dotenv()
INPUT_DIR = 'InputZip'
CONFIG_FILE = 'config.json'

try:
    with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
        config = json.load(f)
except FileNotFoundError:
    print(f"[LOI] Khong tim thay file cau hinh {CONFIG_FILE}.")
    sys.exit(1)

# --- Ham gui Telegram (Giữ nguyên) ---
def send_telegram_message(message_content):
    # THAY ĐỔI: Đọc token và chat_id từ .env (dùng cho báo cáo của script này)
    bot_token = os.getenv('TELEGRAM_BOT_TOKEN')
    chat_id = os.getenv('TELEGRAM_CHAT_ID')
    if not bot_token or not chat_id:
        print("[LOI] Thieu TELEGRAM_BOT_TOKEN hoac TELEGRAM_CHAT_ID trong .env")
        return
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {'chat_id': chat_id, 'text': message_content}
    try:
        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        print(f"[LOI] Khong the gui tin nhan: {e}")

# --- Ham thuc thi chinh ---
def main():
    print("--- Bat dau quy trinh KTB Upload (Queue Mode) ---")

    if not os.path.isdir(INPUT_DIR):
        print(f"[LOI] Khong tim thay thu muc '{INPUT_DIR}'.")
        sys.exit(1)

    try:
        # Lấy các cấu hình chung
        wp_author = config.get('default_user_author')
        remote_queue_dir = config.get('remote_queue_dir')
        delete_zip = config.get('delete_zip_after_upload', False)

        # --- THAY ĐỔI: Đọc config từ .env mới ---
        vps_user = os.getenv("VPS_USERNAME")
        telegram_bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
        telegram_chat_id = os.getenv("TELEGRAM_CHAT_ID")
        # --- KẾT THÚC THAY ĐỔI ---

        if not wp_author or not vps_user or not remote_queue_dir or not telegram_bot_token or not telegram_chat_id:
            print("❌ Loi: Kiem tra thieu 'default_user_author', 'remote_queue_dir' trong config.json")
            print("   hoac 'VPS_USERNAME', 'TELEGRAM_BOT_TOKEN', 'TELEGRAM_CHAT_ID' trong .env")
            sys.exit(1)

        # Hỏi mật khẩu 1 lần
        vps_password = getpass.getpass(f"Nhap Mat khau VPS cho user '{vps_user}' (se bi an): ")
        if not vps_password:
            print("[LOI] Mat khau khong duoc de trong.")
            sys.exit(1)

    except EOFError:
        print("\nDa huy bo.")
        sys.exit(1)
    except Exception as e:
        print(f"[LOI] Gap loi khi doc cau hinh: {e}")
        sys.exit(1)

    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    report_content = f"--- Bao cao KTB User Upload Queue ---\nUser: {wp_author}\nTimestamp: {timestamp}\n"
    total_files_queued = 0
    files_to_upload = [f for f in os.listdir(INPUT_DIR) if f.endswith('.zip')]

    if not files_to_upload:
        print("Khong tim thay file .zip nao trong 'InputZip'.")
        send_telegram_message(report_content + "\n\nKhong co file .zip nao trong 'InputZip'.")
        return

    # --- Sắp xếp file theo Host VPS ---
    files_by_host = defaultdict(list)
    
    print("Dang phan loai file theo Host VPS...")
    for filename in files_to_upload:
        local_zip_file = os.path.join(INPUT_DIR, filename)
        
        site_config = next((site for site in config.get('sites', []) if filename.startswith(site['prefix'])), None)
        if not site_config:
            print(f"⚠️  [LOI] {filename}: Khong tim thay site config. Bo qua.")
            report_content += f"\n[LOI] {filename} (Khong tim thay site config)"
            continue
        
        vps_prefix = site_config['vps_secret_prefix']
        vps_host = os.getenv(f"{vps_prefix}_VPS_HOST")
        vps_port = int(os.getenv(f"{vps_prefix}_VPS_PORT"))
        
        if not vps_host or not vps_port:
            print(f"⚠️  [LOI] {filename}: Khong tim thay HOST/PORT cho prefix '{vps_prefix}'. Bo qua.")
            report_content += f"\n[LOI] {filename} (Loi .env)"
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
        
        host_key = (vps_host, vps_port)
        unique_job_dir_name = f"job_{int(time.time())}_{wp_author}_{filename[:20]}"
        
        file_package = {
            "original_filename": filename,
            "local_zip_path": local_zip_file,
            "meta_content": meta_content,
            "unique_job_dir_name": unique_job_dir_name,
        }
        
        files_by_host[host_key].append(file_package)
    
    # --- Vòng lặp kết nối và Upload ---
    
    for (host, port), file_list in files_by_host.items():
        print("\n" + "="*60)
        print(f"🚀 Dang ket noi den Host: {host}:{port} (User: {vps_user}) - Su dung Password")
        
        ssh = None
        sftp = None
        try:
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            # --- QUAN TRỌNG: Chỉ dùng Password, tắt SSH Key ---
            ssh.connect(
                host, 
                port=port, 
                username=vps_user, 
                password=vps_password, 
                timeout=10,
                disabled_algorithms={'publickey': []} # <-- Dòng này bắt buộc dùng password
            )
            # --- KẾT THÚC ---
            
            sftp = ssh.open_sftp()
            print(f"✅ Ket noi {host} thanh cong. Bat dau upload {len(file_list)} job...")

            # ... (Logic upload, tạo thư mục tạm, rename... giữ nguyên) ...
            for package in file_list:
                filename = package['original_filename']
                local_zip_path = package['local_zip_path']
                meta_content = package['meta_content']
                job_dir_name = package['unique_job_dir_name']
                
                local_meta_path = os.path.join(INPUT_DIR, f"{job_dir_name}_meta.json") # Tạm thời
                
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
                    report_content += f"\n[OK] {filename} -> {host} (Da xep hang)"
                    total_files_queued += 1
                        
                except Exception as e:
                    print(f"   [LOI] {filename}: Upload that bai: {e}")
                    report_content += f"\n[LOI] {filename} (Upload failed: {e})"
                    try: 
                        sftp.remove(remote_meta_path)
                        sftp.remove(remote_zip_path)
                        sftp.rmdir(remote_job_dir_path_tmp)
                    except: pass
                
                finally:
                    if os.path.exists(local_meta_path):
                        os.remove(local_meta_path)
                    
                    if upload_successful and delete_zip:
                        os.remove(local_zip_path)
                        print(f"   🧹 Da xoa file local: {filename}")

        except paramiko.AuthenticationException:
            print(f"❌ LOI: Xac thuc {host} that bai! Kiem tra lai mat khau VPS.")
            report_content += f"\n\n❌ LỖI KẾT NỐI {host}: XÁC THỰC THẤT BẠI."
        except Exception as e:
            print(f"❌ LOI SCRIPT voi {host}: {e}")
            report_content += f"\n\n❌ LỖI SCRIPT {host}: {e}"
        finally:
            if sftp: sftp.close()
            if ssh: ssh.close()
            print(f"--- Da ngat ket noi khoi {host} ---")

    # --- Gửi báo cáo cuối cùng ---
    print("\n" + "="*50)
    print("📊 Gui bao cao tong ket xep hang...")
    if total_files_queued > 0:
        report_content += f"\n\nTong cong: {total_files_queued} file da duoc xep hang."
    else:
        report_content += f"\n\nKhong co file nao duoc xep hang thanh cong."

    print(report_content)
    send_telegram_message(report_content)

if __name__ == "__main__":
    main()