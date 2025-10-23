import os
import json
import subprocess
import re
import sys
import time
import glob
import io
import shutil # <-- Thêm import để move file
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
PROCESSING_DIR = 'Processing' # <-- Thư mục xử lý tạm thời

# --- Hàm lấy SSH Key (Giữ nguyên) ---
def get_ssh_key(prefix):
    key_path = os.getenv(f"ADMIN_{prefix}_SSH_PRIVATE_KEY_PATH")
    key_content = os.getenv(f"ADMIN_{prefix}_SSH_PRIVATE_KEY")

    if not key_path and not key_content:
        key_path = os.getenv("DEFAULT_ADMIN_SSH_KEY_PATH")
        key_content = os.getenv("DEFAULT_ADMIN_SSH_PRIVATE_KEY")
    
    if key_path:
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
    
    elif key_content:
        print("Su dung SSH Key tu noi dung .env")
        key_file_obj = io.StringIO(key_content)
        try: return paramiko.Ed25519Key.from_private_key(key_file_obj)
        except paramiko.ssh_exception.SSHException:
            try: return paramiko.RSAKey.from_private_key(key_file_obj)
            except paramiko.ssh_exception.SSHException:
                 raise ValueError("Khong the tai key (Chi ho tro RSA/Ed25519)")
    else:
        raise ValueError(f"Thieu SSH Key (PATH hoac CONTENT) cho prefix {prefix}")

# --- Hàm Gửi Telegram Admin (Giữ nguyên) ---
def send_admin_telegram_message(message_content):
    bot_token = os.getenv('TELEGRAM_BOT_TOKEN')
    admin_chat_id = os.getenv('TELEGRAM_CHAT_ID_ADMIN') 

    if not bot_token or not admin_chat_id:
        print("[LOI] Thieu TELEGRAM_BOT_TOKEN hoac TELEGRAM_CHAT_ID_ADMIN trong .env")
        return
        
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {'chat_id': admin_chat_id, 'text': message_content}
    try:
        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()
        print(f"✅ Da gui bao cao xep hang den Admin Telegram. (Response: {response.json().get('ok', 'Failed')})")
    except requests.exceptions.RequestException as e:
        print(f"❌ Loi khi gui request den Telegram: {e}")

# --- Hàm Xử lý Chính (Đã sửa logic file) ---
def main():
    print("--- Bat dau quy trinh KTB Admin Upload Queue ---")
    
    # 1. Tải .env và config.json
    if not os.path.exists('.env'):
        print("Loi: File .env khong ton tai.")
        sys.exit(1)
    load_dotenv()
    
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            config = json.load(f)
        remote_queue_dir = config.get('remote_queue_dir')
        default_author = config.get('default_user_author') # <-- [SỬA 1] ĐỌC AUTHOR DEFAULT
        if not remote_queue_dir:
            raise ValueError("Thieu 'remote_queue_dir' trong config.json")
    except Exception as e:
        print(f"Loi doc config.json: {e}")
        sys.exit(1)

    admin_vps_user = os.getenv("DEFAULT_ADMIN_VPS_USERNAME") 
    if not admin_vps_user:
        print("Loi: Thieu DEFAULT_ADMIN_VPS_USERNAME trong .env")
        sys.exit(1)

    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    report_content = f"--- Bao cao KTB Admin Upload Queue ---\nUser: {default_author}\nTimestamp: {timestamp}\n"
    total_files_queued = 0

    # --- (LOGIC MỚI) DI CHUYỂN FILE VÀO PROCESSING ---
    source_dir = os.path.join(KTB_IMAGE_PATH, 'OutputImage')
    processing_dir = PROCESSING_DIR
    
    if not os.path.isdir(source_dir):
        print(f"❌ Loi: Khong tim thay thu muc nguon {source_dir}")
        sys.exit(1)
        
    # Tạo thư mục Processing nếu chưa có
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
        # Vẫn tiếp tục chạy để xử lý file cũ trong Processing (nếu có)
    
    # --- Quét file trong thư mục Processing ---
    files_to_upload = [f for f in os.listdir(processing_dir) if f.endswith('.zip')]
    if not files_to_upload:
        print(f"Khong co file .zip nao trong '{processing_dir}' de xu ly.")
        send_admin_telegram_message(report_content + f"\n\nKhong co file .zip nao trong '{processing_dir}'.")
        # Dọn dẹp file log cũ rồi thoát
        cleanup_temp_files()
        return

    # --- Sắp xếp file theo Host VPS (Giữ nguyên) ---
    files_by_host = defaultdict(list)
    print("Dang phan loai file theo Host VPS...")
    
    for filename in files_to_upload:
        # Đường dẫn bây giờ là trong Processing
        local_zip_file = os.path.join(processing_dir, filename) 
        
        site_config = next((site for site in config.get('sites', []) if filename.startswith(site['prefix'])), None)
        # ... (logic tìm config, lấy host/port/author y hệt) ...
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
        
        # --- [SỬA 2] SỬA LOGIC LẤY AUTHOR ---
        wp_author = site_config.get('wp_author') # Lấy author của site
        if not wp_author:
             wp_author = default_author # Nếu site ko có, lấy author default
        
        if not wp_author: # Nếu cả 2 đều ko có thì mới báo lỗi
             print(f"⚠️  [LOI] {filename}: Thieu 'wp_author' (site) VA 'default_user_author' (goc). File se nam lai trong '{processing_dir}'.")
             report_content += f"\n[LOI] {filename} (Thieu author config, chua xoa)"
             continue

        meta_content = {
            "wp_author": wp_author,
            "wp_path": site_config['wp_path'],
            "zip_filename": filename, 
            "prefix": site_config['prefix'] 
        }
        
        host_key = (vps_host, vps_port, vps_prefix)
        
        # --- [SỬA 3] SỬA LỖI BUG CHÍNH ---
        # Dùng `wp_author` thay vì `admin_vps_user` để tạo tên job
        unique_job_dir_name = f"job_{int(time.time())}_{wp_author}_{filename[:20]}"
        
        file_package = {
            "original_filename": filename, 
            "local_zip_path": local_zip_file, # Đường dẫn trong Processing
            "meta_content": meta_content,
            "unique_job_dir_name": unique_job_dir_name, 
        }
        files_by_host[host_key].append(file_package)

    # --- Vòng lặp kết nối và Upload (Đã sửa logic xóa) ---
    
    for (host, port, vps_prefix_key), file_list in files_by_host.items():
        print("\n" + "="*50)
        print(f"🚀 Dang ket noi den Host: {host}:{port} (User: {admin_vps_user})")
        
        ssh = None
        sftp = None
        try:
            ssh_key = get_ssh_key(vps_prefix_key) 
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ssh.connect(host, port=port, username=admin_vps_user, pkey=ssh_key, timeout=10)
            sftp = ssh.open_sftp()
            print(f"✅ Ket noi {host} thanh cong. Bat dau upload {len(file_list)} job...")

            for package in file_list:
                filename = package['original_filename']
                local_zip_path = package['local_zip_path'] # Path trong Processing
                meta_content = package['meta_content']
                job_dir_name = package['unique_job_dir_name']
                
                # Tạo file meta tạm thời (trong thư mục Processing)
                local_meta_path = os.path.join(processing_dir, f"{job_dir_name}_meta.json")
                # --- SỬA LỖI RACE CONDITION ---
                # Tạo 2 biến: 1 cho đường dẫn TẠM, 1 cho đường dẫn CUỐI CÙNG
                remote_job_dir_path_tmp = f"{remote_queue_dir}/tmp_{job_dir_name}"
                remote_job_dir_path_final = f"{remote_queue_dir}/{job_dir_name}"

                # Upload file vào thư mục TẠM
                remote_zip_path = f"{remote_job_dir_path_tmp}/{filename}"
                remote_meta_path = f"{remote_job_dir_path_tmp}/meta.json" 
                # --- KẾT THÚC SỬA LỖI ---

                # --- (LOGIC MỚI) UPLOAD VÀ XÓA CÓ ĐIỀU KIỆN ---
                upload_successful = False
                try:
                    # 1. Tạo thư mục job TẠM trên server
                    print(f"   Tao job folder tam: tmp_{job_dir_name}...")
                    sftp.mkdir(remote_job_dir_path_tmp) # <-- Sửa
                    
                    # 2. Tạo file meta.json local tạm thời
                    with open(local_meta_path, 'w', encoding='utf-8') as f:
                        json.dump(meta_content, f)

                    # 3. Upload file (Nên upload meta.json nhỏ trước)
                    print(f"   Uploading meta.json (tam)...")
                    sftp.put(local_meta_path, remote_meta_path) # <-- Đảo lên trước
                    
                    print(f"   Uploading {filename} (tam)...")
                    sftp.put(local_zip_path, remote_zip_path) # <-- Upload sau

                    # 4. (QUAN TRỌNG) Kích hoạt job bằng cách đổi tên thư mục
                    # Lệnh 'mv' là atomic (tức thời), server sẽ không thấy 
                    # thư mục này cho đến khi nó hoàn chỉnh.
                    print(f"   Kich hoat job (doi ten thu muc)...")
                    command = f"mv {shlex.quote(remote_job_dir_path_tmp)} {shlex.quote(remote_job_dir_path_final)}"
                    stdin, stdout, stderr = ssh.exec_command(command)
                    exit_status = stdout.channel.recv_exit_status()
                    
                    if exit_status != 0:
                        # Nếu đổi tên thất bại, văng lỗi để dọn dẹp
                        raise Exception(f"Loi doi ten thu muc job: {stderr.read().decode()}")

                    # => Nếu đến được đây là upload thành công
                    upload_successful = True 
                    
                    print(f"   ✅ {filename}: Da xep hang thanh cong.")
                    report_content += f"\n[OK] {filename} -> {host} (Admin)"
                    total_files_queued += 1
                    
                except Exception as e:
                    print(f"   [LOI] {filename}: Upload that bai: {e}")
                    report_content += f"\n[LOI] {filename} (Upload failed: {e})"
                    # Cố gắng dọn dẹp thư mục job TẠM rỗng trên server
                    try: 
                        sftp.remove(remote_zip_path) # Xóa file trong thư mục
                        sftp.remove(remote_meta_path)
                        sftp.rmdir(remote_job_dir_path_tmp) # Xóa thư mục tmp
                    except: pass
                    
                finally:
                    # Luôn xóa file meta local tạm thời
                    if os.path.exists(local_meta_path):
                        os.remove(local_meta_path) 
                        
                    # CHỈ XÓA FILE ZIP TRONG PROCESSING NẾU UPLOAD THÀNH CÔNG
                    if upload_successful:
                        try:
                            os.remove(local_zip_path)
                            print(f"   🧹 Da xoa file local: {local_zip_path}")
                        except Exception as e_del:
                             print(f"   [LOI] Khong the xoa file local {local_zip_path}: {e_del}")
                    else:
                        # Nếu upload thất bại, file zip vẫn nằm lại trong Processing
                        print(f"   ⚠️  File zip '{filename}' van con trong '{processing_dir}' do upload loi.")
                # --- KẾT THÚC LOGIC MỚI ---

        # ... (Phần xử lý lỗi kết nối giữ nguyên) ...
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

    # --- Gửi báo cáo cuối cùng (Giữ nguyên) ---
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
    
    # --- Dọn dẹp các file log cũ nếu có ---
    cleanup_temp_files() 
    
    print("\n--- Hoan tat quy trinh KTB-Upload Sync (Queue Mode - Admin) ---")

# --- Hàm dọn dẹp (Giữ nguyên) ---
def cleanup_temp_files():
    """Xóa các file tạm cũ (uploaded_files_*.log và script tạm)"""
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