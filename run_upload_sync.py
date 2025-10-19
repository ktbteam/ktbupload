import os
import json
import subprocess
import re
import sys
import time
import glob
import io
from datetime import datetime
from zoneinfo import ZoneInfo  # Yêu cầu Python 3.9+
import paramiko
import requests
from dotenv import load_dotenv
import shlex

# --- Cấu hình chung ---
# Đổi 'nginx' nếu user web server của bạn khác
WEB_USER = "nginx" 
# Đổi '/usr/local/bin/wp' nếu đường dẫn WP-CLI của bạn khác
WP_CLI_PATH = "/usr/local/bin/wp" 

# Đường dẫn (giống run-local.sh)
KTB_IMAGE_PATH = "../ktbproject/ktbimage"
CONFIG_FILE = 'config.json'
LOG_FILE = 'upload.log'
TEMP_SCRIPT_NAME = 'temp_remote_script.py.sh'

# --- 1. Logic Upload (Thay thế upload-script.js) ---

# (Tìm hàm này trong file run_upload_sync.py và thay thế nó)

def get_ssh_key(prefix): # prefix sẽ là "KTBTEE", "AMERTEE"...
    """Lấy PKey (Ưu tiên key riêng của admin, sau đó là mặc định của admin)"""

    # 1. Ưu tiên tìm key riêng (ví dụ: ADMIN_KTBTEE_SSH_PRIVATE_KEY_PATH)
    key_path = os.getenv(f"ADMIN_{prefix}_SSH_PRIVATE_KEY_PATH")
    key_content = os.getenv(f"ADMIN_{prefix}_SSH_PRIVATE_KEY")

    # 2. Nếu không thấy, tìm key mặc định
    if not key_path and not key_content:
        key_path = os.getenv("DEFAULT_ADMIN_SSH_KEY_PATH")
        key_content = os.getenv("DEFAULT_ADMIN_SSH_PRIVATE_KEY")
    
    if key_path:
        # --- SỬA LỖI Ở ĐÂY ---
        # 1. Luôn "hiểu" ký tự ~ (thư mục nhà)
        key_path = os.path.expanduser(key_path)
        
        # 2. Dịch đường dẫn Git Bash (/c/) sang đường dẫn Windows (C:/)
        # Chỉ làm điều này nếu chúng ta đang chạy trên Windows
        if os.name == 'nt':
            if key_path.startswith('/c/'):
                key_path = 'C:/' + key_path[3:]
            elif key_path.startswith('/d/'):
                key_path = 'D:/' + key_path[3:]
            elif key_path.startswith('/e/'):
                key_path = 'E:/' + key_path[3:]
            # (Bạn có thể thêm các ổ đĩa khác nếu cần)
        
        # --- KẾT THÚC SỬA LỖI ---
        
        print(f"Su dung SSH Key tu duong dan (da xu ly): {key_path}")
        
        # Thêm kiểm tra file tồn tại để báo lỗi rõ hơn
        if not os.path.exists(key_path):
            raise FileNotFoundError(f"Khong tim thay file key tai: {key_path}")
            
        # Sửa lỗi: Phải dùng PKey.from_private_key_file thay vì RSAKey
        # Điều này hỗ trợ cả key ed25519 và rsa
        try:
             # Thử tải key ed25519 trước
            return paramiko.Ed25519Key.from_private_key_file(key_path)
        except paramiko.ssh_exception.SSHException:
            try:
                # Nếu thất bại, thử tải key RSA
                return paramiko.RSAKey.from_private_key_file(key_path)
            except paramiko.ssh_exception.SSHException:
                 # Thêm các loại key khác nếu cần (ví dụ: ecdsa)
                print("Loi: Khong the tai key. Chi ho tro RSA hoac Ed25519.")
                raise
    
    elif key_content:
        print("Su dung SSH Key tu noi dung .env")
        key_file_obj = io.StringIO(key_content)
        # Sửa tương tự ở đây
        try:
            return paramiko.Ed25519Key.from_private_key(key_file_obj)
        except paramiko.ssh_exception.SSHException:
            try:
                return paramiko.RSAKey.from_private_key(key_file_obj)
            except paramiko.ssh_exception.SSHException:
                print("Loi: Khong the tai key. Chi ho tro RSA hoac Ed25519.")
                raise
    else:
        raise ValueError(f"Thieu SSH_PRIVATE_KEY_PATH hoac SSH_PRIVATE_KEY cho prefix {prefix}")

def process_site(site_config):
    """
    Kết nối, upload, và chạy script remote cho 1 site.
    Trả về tổng số ảnh đã upload thành công.
    """
    slug = site_config['slug']
    prefix = site_config['prefix']
    vps_prefix = site_config['vps_secret_prefix']
    
    print("\n" + "="*50)
    print(f"🚀 Bat dau xu ly cho trang: {slug}")
    
    # Lấy thông tin SSH từ .env
    try:
        ssh_key = get_ssh_key(vps_prefix)
        vps_host = os.getenv(f"{vps_prefix}_VPS_HOST")
        vps_user = (
        os.getenv(f"ADMIN_{vps_prefix}_VPS_USERNAME") or  # e.g., ADMIN_KTBTEE_VPS_USERNAME
        os.getenv("DEFAULT_ADMIN_VPS_USERNAME")         # e.g., "khue"
        )
        vps_port = int(os.getenv(f"{vps_prefix}_VPS_PORT"))
        if not all([vps_host, vps_user, vps_port]):
            raise ValueError(f"Thieu _HOST, _USERNAME, hoac _PORT cho prefix {vps_prefix}")
    except Exception as e:
        print(f"❌ Loi cau hinh SSH cho {slug}: {e}")
        return 0

    # Tìm file Zip
    zips_directory = os.path.join(KTB_IMAGE_PATH, 'OutputImage')
    if not os.path.isdir(zips_directory):
        print(f"❌ Loi: Khong tim thay thu muc {zips_directory}")
        return 0
    
    all_zips = [f for f in os.listdir(zips_directory) if f.endswith('.zip') and f.startswith(prefix)]
    
    # Đọc log file đã upload
    uploaded_log_file = f"uploaded_files_{slug}.log"
    logged_files = set()
    if os.path.exists(uploaded_log_file):
        with open(uploaded_log_file, 'r', encoding='utf-8') as f:
            logged_files = set(f.read().splitlines())

    total_images_uploaded = 0
    
    for filename in all_zips:
        if filename in logged_files:
            print(f"Skipping {filename}, da upload.")
            continue

        print(f"\n--- Xu ly file: {filename} ---")
        local_zip_path = os.path.join(zips_directory, filename)
        remote_temp_dir = f"/tmp/upload_{slug}_{int(time.time())}"
        remote_zip_path = f"{remote_temp_dir}/{filename}"
        remote_script_path = f"{remote_temp_dir}/{TEMP_SCRIPT_NAME}"
        
        ssh = None
        try:
            # Kết nối SSH
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ssh.connect(vps_host, port=vps_port, username=vps_user, pkey=ssh_key, timeout=10)
            
            # 1. Tạo thư mục tạm và Upload file zip (SFTP)
            print(f"Dang upload {filename} len {slug}...")
            sftp = ssh.open_sftp()
            sftp.mkdir(remote_temp_dir)
            sftp.put(local_zip_path, remote_zip_path)
            sftp.close()
            print("✅ Upload file zip thanh cong.")

            # 2. Đếm ảnh bằng unzip -l
            print("Dang dem anh trong file zip tren server...")
            count_cmd = f"unzip -l {shlex.quote(remote_zip_path)} | grep -Eic '(\\.webp|\\.jpg|\\.png)$' || echo 0"
            stdin, stdout, stderr = ssh.exec_command(count_cmd)
            image_count = int(stdout.read().decode('utf-8').strip())
            print(f"   File chua {image_count} anh.")

            # 3. Tạo và chạy script remote (Copy 1-1 từ JS)
            remote_command = f"""#!/bin/bash
              set -e
              shopt -s nullglob
              
              function cleanup {{
                echo "Don dep {remote_temp_dir}..."
                rm -rf {remote_temp_dir}
              }}
              trap cleanup EXIT

              chmod 755 "{remote_temp_dir}"
              cd {remote_temp_dir}
              unzip -o '{filename}' -d extracted_images
              chmod -R 755 extracted_images

              echo "Import vao {site_config['wp_path']} voi author {site_config['wp_author']}..."
              cd {site_config['wp_path']}
              sudo -u {WEB_USER} {WP_CLI_PATH} media import {remote_temp_dir}/extracted_images/*.{{webp,jpg,png}} --user={site_config['wp_author']}
              
              echo "--- Hoan thanh xu ly {filename} ---"
            """
            
            # Ghi script tạm ra local và upload nó
            with open(TEMP_SCRIPT_NAME, 'w', encoding='utf-8', newline='\n') as f:
                f.write(remote_command)
            
            sftp = ssh.open_sftp()
            sftp.put(TEMP_SCRIPT_NAME, remote_script_path)
            sftp.chmod(remote_script_path, 0o755) # Cấp quyền chạy
            sftp.close()
            
            print("Dang chay script import remote...")
            stdin, stdout, stderr = ssh.exec_command(f"bash {remote_script_path}")
            print(stdout.read().decode('utf-8')) # In output của script remote
            print(stderr.read().decode('utf-8')) # In lỗi nếu có

            # 4. Ghi log thành công
            with open(uploaded_log_file, 'a', encoding='utf-8') as f:
                f.write(f"{filename}\n")
            
            total_images_uploaded += image_count
            print(f"✅ Finished importing {filename} to {slug}.")

        except Exception as e:
            print(f"❌ Failed to upload {filename} to {slug}: {e}")
            # Cố gắng dọn dẹp thư mục tạm trên VPS
            try:
                ssh.exec_command(f"rm -rf {remote_temp_dir}")
            except:
                pass # Bỏ qua lỗi dọn dẹp
        finally:
            if ssh:
                ssh.close()
            print("--- Tam nghi 5 giay ---")
            time.sleep(5)
            
    return total_images_uploaded

# --- 2. Logic Báo cáo (Thay thế generate-report.js) ---

def get_previous_totals(log_file):
    """Đọc upload.log cũ, trả về (totals_dict, log_date_str)"""
    totals = {}
    log_date = None
    if not os.path.exists(log_file):
        return totals, log_date

    date_regex = re.compile(r"^Timestamp: (\d{4}-\d{2}-\d{2})")
    stats_regex = re.compile(r"^(.*?):.*?Total (\d+)$")

    with open(log_file, 'r', encoding='utf-8') as f:
        for line in f:
            date_match = date_regex.search(line)
            if date_match:
                log_date = date_match.group(1)
            
            stats_match = stats_regex.search(line)
            if stats_match:
                prefix = stats_match.group(1).strip()
                count = int(stats_match.group(2))
                totals[prefix] = count
    return totals, log_date

def generate_report(newly_uploaded_counts):
    """Tạo file upload.log mới dựa trên logic reset theo ngày"""
    print("\n" + "="*50)
    print("📊 Dang tao bao cao tong hop...")

    previous_totals, log_date = get_previous_totals(LOG_FILE)
    
    try:
        current_date = datetime.now(ZoneInfo("Asia/Ho_Chi_Minh")).strftime('%Y-%m-%d')
        current_timestamp = datetime.now(ZoneInfo("Asia/Ho_Chi_Minh")).strftime('%Y-%m-%d %H:%M:%S %z')
    except Exception as e:
        print(f"Loi ZoneInfo (can Python 3.9+): {e}. Su dung gio he thong.")
        current_date = datetime.now().strftime('%Y-%m-%d')
        current_timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    final_totals = {}
    if log_date == current_date:
        print(f"Ngay trong log ({log_date}) trung khop. Tiep tuc cong don...")
        final_totals = previous_totals.copy()
    else:
        print(f"Ngay trong log ({log_date}) khac voi hom nay ({current_date}). Reset thong ke.")
        # final_totals vẫn là {} rỗng

    # Tổng hợp tất cả các prefix
    all_prefixes = sorted(list(set(final_totals.keys()) | set(newly_uploaded_counts.keys())))
    
    new_log_content = f"--- Summary of Last Upload ---\nTimestamp: {current_timestamp}\n\n"
    
    # Tính tổng số ảnh MỚI đã upload
    total_new_images = sum(newly_uploaded_counts.values())
    
    if not all_prefixes:
        new_log_content += "Upload that bai hoac khong co file moi."
    else:
        for prefix in all_prefixes:
            old_total = final_totals.get(prefix, 0)
            new_count = newly_uploaded_counts.get(prefix, 0)
            current_total = old_total + new_count
            new_log_content += f"{prefix}: {new_count} images: Total {current_total}\n"
        
        # SỬA LOGIC Ở ĐÂY
        if total_new_images > 0:
            new_log_content += "\nUpload thanh cong."
        else:
            # Nếu không có ảnh MỚI nào, và không có ảnh CŨ nào (trường hợp reset/lỗi)
            if not previous_totals:
                 new_log_content += "\nUpload THAT BAI (Co the do loi cau hinh SSH)."
            else:
                 new_log_content += "\nKhong co file moi nao duoc upload."

    with open(LOG_FILE, 'w', encoding='utf-8') as f:
        f.write(new_log_content)
    
    print("Da ghi file upload.log")
    print("--- Noi dung bao cao ---")
    print(new_log_content)
    print("------------------------")

# --- 3. Logic Gửi Telegram (Thay thế send-telegram.js) ---

def send_telegram_report():
    """Đọc upload.log và gửi qua Telegram"""
    print("\n" + "="*50)
    print("📤 Dang gui thong bao Telegram...")

    try:
        with open(LOG_FILE, 'r', encoding='utf-8') as f:
            log_content = f.read()
    except FileNotFoundError:
        print(f"Loi: Khong tim thay {LOG_FILE} de gui.")
        return

    bot_token = os.getenv('TELEGRAM_BOT_TOKEN')
    chat_id = os.getenv('TELEGRAM_CHAT_ID_NU')

    if not bot_token or not chat_id:
        print("Loi: Thieu TELEGRAM_BOT_TOKEN hoac TELEGRAM_CHAT_ID trong .env")
        return

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {'chat_id': chat_id, 'text': log_content}

    try:
        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()
        print(f"✅ Da gui thong bao qua Telegram. (Response: {response.json().get('ok', 'Failed')})")
    except requests.exceptions.RequestException as e:
        print(f"❌ Loi khi gui request den Telegram: {e}")

# --- 4. Logic Git Push (Từ run-local.sh) ---

def sync_git_repo():
    """Đồng bộ repo lên GitHub"""
    print("\n" + "="*50)
    print("🔄 Bat dau dong bo hoa repo 'ktbupload' voi GitHub...")
    
    if not os.getenv('KTBGIT_PAT'):
        print(" Loi: Bien KTBGIT_PAT khong duoc thiet lap trong file .env. Bo qua git push.")
        return

    try:
        subprocess.run(['git', 'config', 'user.name', 'automation-bot'], check=True)
        subprocess.run(['git', 'config', 'user.email', 'bot@example.com'], check=True)
        subprocess.run(['git', 'add', '.'], check=True)
        
        # Kiểm tra xem có gì thay đổi không
        result = subprocess.run(['git', 'diff', '--staged', '--quiet'])
        if result.returncode == 0:
            print("👌 Khong co thay doi nao de commit.")
            return

        print("📝 Co thay doi, dang tien hanh commit...")
        subprocess.run(['git', 'commit', '--amend', '--no-edit'], check=True)
        
        # Lấy branch hiện tại
        branch_result = subprocess.run(['git', 'rev-parse', '--abbrev-ref', 'HEAD'], capture_output=True, text=True, check=True)
        current_branch = branch_result.stdout.strip()
        
        print(f"📤 Dang push len branch '{current_branch}' qua SSH...")
        subprocess.run(['git', 'push', 'origin', current_branch, '--force'], check=True)
        print("✨ Dong bo hoa thanh cong!")

    except subprocess.CalledProcessError as e:
        print(f"❌ Loi khi dong bo Git: {e}")
    except FileNotFoundError:
        print("❌ Loi: Khong tim thay lenh 'git'. Vui long cai dat Git.")

# --- 5. Logic Dọn dẹp (Từ run-local.sh) ---

def cleanup_temp_files():
    """Xóa các file tạm sau khi chạy"""
    print("\n" + "="*50)
    print("🧹 Don dep cac file log va report tam...")
    
    # Xóa file report (dù script này ko tạo ra, nhưng để cho chắc)
    for f in glob.glob('*_report.txt'):
        os.remove(f)
    
    # Xóa file log chi tiết của từng site
    for f in glob.glob('uploaded_files_*.log'):
        os.remove(f)
    
    # Xóa script tạm đã upload
    if os.path.exists(TEMP_SCRIPT_NAME):
        os.remove(TEMP_SCRIPT_NAME)
        
    print("✅ Don dep hoan tat.")

# --- Hàm chạy chính (Thay thế run-local.sh) ---

def main():
    print("--- Bat dau quy trinh Upload Local (Python Version) ---")
    
    # 1. Tải .env
    if not os.path.exists('.env'):
        print("Loi: File .env khong ton tai.")
        sys.exit(1)
    load_dotenv()
    
    # 2. Tải config.json
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            config = json.load(f)
    except FileNotFoundError:
        print(f"Loi: File {CONFIG_FILE} khong ton tai.")
        sys.exit(1)

    # 3. Chạy upload cho từng site và thu thập kết quả
    newly_uploaded_counts = {}
    for site in config.get('sites', []):
        new_count = process_site(site)
        prefix = site['prefix']
        current_count = newly_uploaded_counts.get(prefix, 0)
        newly_uploaded_counts[prefix] = current_count + new_count
    
    # 4. Tạo báo cáo
    generate_report(newly_uploaded_counts)
    
    # 5. Gửi Telegram
    send_telegram_report()
    
    # 6. Đồng bộ Git
    #sync_git_repo()
    
    # 7. Dọn dẹp
    cleanup_temp_files()
    
    print("\n--- Hoan tat toan bo quy trinh KTB-Upload ---")

if __name__ == "__main__":
    main()