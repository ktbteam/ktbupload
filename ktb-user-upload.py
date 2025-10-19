import os
import json
import sys
import getpass
import requests
import shlex
import time
from datetime import datetime
from dotenv import load_dotenv
import re  # <-- NÂNG CẤP
try:
    # Yêu cầu Python 3.9+ để có múi giờ chính xác
    from zoneinfo import ZoneInfo 
except ImportError:
    print("[CANH BAO] Khong tim thay 'zoneinfo' (can Python 3.9+).")
    print("            Se su dung gio he thong (co the sai lech ngay).")
    ZoneInfo = None # Sẽ xử lý fallback sau
try:
    import paramiko
except ImportError:
    print("[LOI] Chua cai thu vien 'paramiko'.")
    print("Vui long chay lenh: pip install -r requirements.txt")
    sys.exit(1)

# --- Khai bao bien va tai cau hinh ---
load_dotenv()  # Tai file .env
INPUT_DIR = 'InputZip'
CONFIG_FILE = 'config.json'
USER_LOG_FILE = 'userupload.log' # <-- NÂNG CẤP: Tên file log

try:
    with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
        config = json.load(f)
except FileNotFoundError:
    print(f"[LOI] Khong tim thay file cau hinh {CONFIG_FILE}.")
    sys.exit(1)
except json.JSONDecodeError:
    print(f"[LOI] File {CONFIG_FILE} bi loi cu phap JSON.")
    sys.exit(1)

# --- Ham gui Telegram ---
def send_telegram_message(message_content):
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
        print(f"Phan hoi tu Tel: {response.json().get('ok', 'Failed')}")
    except requests.exceptions.RequestException as e:
        print(f"[LOI] Khong the gui tin nhan: {e}")

# --- (NÂNG CẤP) CÁC HÀM BÁO CÁO MỚI ---

def get_previous_totals(log_file):
    """
    Đọc file log cũ (userupload.log),
    Trả về (totals_dict, log_date_str)
    Logic được mượn từ run_upload_sync.py 
    """
    totals = {}
    log_date = None
    if not os.path.exists(log_file):
        return totals, log_date

    # Regex để tìm ngày: "Timestamp: YYYY-MM-DD" (Chỉ lấy ngày)
    date_regex = re.compile(r"^Timestamp: (\d{4}-\d{2}-\d{2})")
    # Regex để tìm dòng thống kê: "ten_prefix: ... Total SỐ_LƯỢNG"
    stats_regex = re.compile(r"^(.*?):.*?Total (\d+)$")

    try:
        with open(log_file, 'r', encoding='utf-8') as f:
            for line in f:
                date_match = date_regex.search(line)
                if date_match:
                    log_date = date_match.group(1)
                
                stats_match = stats_regex.search(line)
                if stats_match:
                    # group(1) sẽ là tên prefix (ví dụ: ktbtee)
                    prefix = stats_match.group(1).strip()
                    count = int(stats_match.group(2))
                    totals[prefix] = count
    except Exception as e:
        print(f"[LOI] Khong the doc file log cu {log_file}: {e}")
    return totals, log_date

def generate_and_send_report(wp_author, newly_uploaded_counts, detailed_report_content, total_new_images):
    """
    Tạo báo cáo tổng hợp, ghi file log, và gửi Telegram.
    """
    print("\n" + "="*50)
    print(f"📊 Dang tao bao cao tong hop cho user '{wp_author}'...")

    # 1. Lấy tổng cũ và ngày log
    previous_totals, log_date = get_previous_totals(USER_LOG_FILE)
    
    # 2. Lấy ngày giờ hiện tại (Chuẩn múi giờ VN)
    try:
        if ZoneInfo is None:
            raise ImportError("ZoneInfo not available")
        hcm_tz = ZoneInfo("Asia/Ho_Chi_Minh")
        current_datetime = datetime.now(hcm_tz)
    except Exception:
        # Fallback về giờ hệ thống nếu Python < 3.9
        current_datetime = datetime.now()

    current_date = current_datetime.strftime('%Y-%m-%d')
    # Format timestamp chuẩn %z (ví dụ: +0700)
    current_timestamp = current_datetime.strftime('%Y-%m-%d %H:%M:%S %z')

    # 3. Quyết định reset hay cộng dồn
    final_totals = {}
    if log_date == current_date:
        print(f"Ngay trong log ({log_date}) trung khop. Tiep tuc cong don...")
        final_totals = previous_totals.copy()
    else:
        print(f"Ngay trong log ({log_date}) khac voi hom nay ({current_date}). Reset thong ke.")
        # final_totals vẫn là {} rỗng (bắt đầu đếm lại từ đầu)

    # 4. Xây dựng nội dung log mới (theo format bạn yêu cầu)
    
    # Lấy danh sách tất cả prefix (cả cũ và mới)
    all_prefixes = sorted(list(set(final_totals.keys()) | set(newly_uploaded_counts.keys())))
    
    new_log_content = f"--- Summary of User Upload ---\n"
    new_log_content += f"Timestamp: {current_timestamp}\n"
    new_log_content += f"User: {wp_author}\n\n" # Thêm dòng User
    
    if not all_prefixes:
        new_log_content += "Khong co file nao duoc xu ly."
    else:
        for prefix in all_prefixes:
            old_total = final_totals.get(prefix, 0)
            new_count = newly_uploaded_counts.get(prefix, 0)
            current_total = old_total + new_count
            
            # Format dòng giống hệt yêu cầu: "prefix: 0 images: Total 12"
            new_log_content += f"{prefix}: {new_count} images: Total {current_total}\n"
    
    # Thêm dòng trạng thái cuối cùng
    if total_new_images > 0:
        new_log_content += "\nUpload thanh cong."
    else:
        if not previous_totals and not newly_uploaded_counts:
             new_log_content += "\nUpload THAT BAI (Khong co file .zip hoac loi)."
        else:
             new_log_content += "\nKhong co file moi nao duoc upload."

    # 5. Ghi file log mới
    try:
        with open(USER_LOG_FILE, 'w', encoding='utf-8') as f:
            f.write(new_log_content)
        print(f"✅ Da ghi bao cao vao file {USER_LOG_FILE}")
    except Exception as e:
        print(f"❌ LOI: Khong thể ghi file {USER_LOG_FILE}: {e}")

    # 6. Gửi báo cáo Telegram
    
    # --- BẮT ĐẦU SỬA ---
    # 'new_log_content' là báo cáo tóm tắt (Summary).
    # User chỉ muốn gửi báo cáo tóm tắt này.
    
    final_message = new_log_content # Chỉ lấy nội dung tóm tắt
    
    # --- KẾT THÚC SỬA ---
    
    print("--- Noi dung bao cao ---")
    print(final_message)
    print("------------------------")
    send_telegram_message(final_message)


# --- Ham thuc thi chinh ---
def main():
    print("--- Bat dau quy trinh KTB Upload Don gian ---")

    if not os.path.isdir(INPUT_DIR):
        print(f"[LOI] Khong tim thay thu muc '{INPUT_DIR}'.")
        sys.exit(1)

    # --- THAY ĐỔI LOGIC LẤY THÔNG TIN ---
    try:
        # 1. Lấy author chung từ config
        wp_author = config.get('default_user_author')
        if not wp_author:
            print("[LOI] Khong tim thay 'default_user_author' trong config.json.")
            sys.exit(1)
        
        print(f"Su dung WP Author tu dong: {wp_author}")

        # 2. Chỉ hỏi mật khẩu
        vps_password = getpass.getpass("Nhap Mat khau VPS (se bi an): ")
        
    except EOFError:
        print("\nDa huy bo.")
        sys.exit(1)

    if not vps_password: # Chỉ kiểm tra mật khẩu
        print("[LOI] Mat khau khong duoc de trong.")
        sys.exit(1)
    
    # 3. Lấy cấu hình xóa file từ config
    delete_zip = config.get('delete_zip_after_upload', False)
    
    # --- SỬA 1: LẤY USER VPS CHUNG (CHO SCRIPT USER) ---
    vps_user_default = os.getenv("DEFAULT_USER_VPS_USERNAME")
    if not vps_user_default:
        print("❌ Loi: Khong tim thay 'DEFAULT_USER_VPS_USERNAME' trong file .env")
        sys.exit(1)
    print(f"Su dung user VPS mac dinh: {vps_user_default}")
    # --- KẾT THÚC SỬA 1 ---

    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    # 'report_content' sẽ là báo cáo chi tiết (danh sách file)
    report_content = f"--- Bao cao KTB Upload ---\nUser: {wp_author}\nTimestamp: {timestamp}\n"
    
    total_image_count = 0 # Tổng ảnh của CHỈ LẦN CHẠY NÀY
    # (NÂNG CẤP) Báo cáo tổng hợp theo prefix
    newly_uploaded_counts = {}

    zip_files = [f for f in os.listdir(INPUT_DIR) if f.endswith('.zip')]
    if not zip_files:
        print("Khong tim thay file .zip nao trong thu muc 'InputZip'.")
        # Vẫn gọi hàm báo cáo để log lại là không có gì
        generate_and_send_report(wp_author, {}, report_content, 0)
        return

    for filename in zip_files:
        local_zip_file = os.path.join(INPUT_DIR, filename)
        print("\n" + "="*50)
        print(f"🚀 Xu ly file: {filename}")

        site_config = next((site for site in config.get('sites', []) if filename.startswith(site['prefix'])), None)
        if not site_config:
            print(f"⚠️  Khong tim thay site config co prefix khop voi '{filename}'. Bo qua.")
            report_content += f"\n[LOI] {filename} (Khong tim thay site)"
            continue
            
        # Lấy prefix (ví dụ: 'ktbtee')
        prefix = site_config['prefix'] 
        vps_secret_prefix = site_config['vps_secret_prefix']
        vps_host = os.getenv(f"{vps_secret_prefix}_VPS_HOST")
        # Luôn luôn dùng user mặc định đã lấy ở trên
        vps_user = vps_user_default 
        vps_port = int(os.getenv(f"{vps_secret_prefix}_VPS_PORT"))

        if not all([vps_host, vps_user, vps_port]):
            print(f"❌ Loi: Khong tim thay _HOST, _USERNAME, _PORT cho prefix '{vps_secret_prefix}' trong .env")
            report_content += f"\n[LOI] {filename} (Loi cau hinh .env)"
            continue

        # Đổi đường dẫn upload sang đường dẫn chung (NẾU BẠN ĐÃ ĐỔI)
        # Ví dụ: "/home/ktb_uploads"
        remote_base_dir = config['remote_temp_upload_dir']
        remote_zip_path = f"{remote_base_dir}/{filename}"
        
        # Bien de luu loi
        error_message = ""
        
        # Ket noi SSH bang PARAMIKO
        ssh = None
        try:
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            
            # --- SỬA 2: ÉP DÙNG MẬT KHẨU, CẤM SSH KEY ---
            ssh.connect(
                vps_host, 
                port=vps_port, 
                username=vps_user, 
                password=vps_password, 
                timeout=10,
                disabled_algorithms={'publickey': []} # <-- ÉP DÙNG MẬT KHẨU
            )
            # --- KẾT THÚC SỬA 2 ---

            # 4.4. Upload file (dung SFTP)
            print(f"Dang upload len '{site_config['slug']}' ({vps_host})...")
            sftp = ssh.open_sftp()
            sftp.put(local_zip_file, remote_zip_path)
            sftp.close()
            print("✅ Upload thanh cong.")

            # 4.5. Dem anh tren server (dung exec_command)
            print("Dang dem anh trong file zip tren server...")
            count_cmd = f"unzip -l {shlex.quote(remote_zip_path)} | grep -Eic '(\\.webp|\\.jpg|\\.png)$' || echo 0"
            stdin, stdout, stderr = ssh.exec_command(count_cmd)
            image_count_output = stdout.read().decode('utf-8').strip()
            image_count = int(image_count_output)
            print(f"   File chua {image_count} anh.")

            # 4.6. Kich hoat xu ly ngam
            print("Kich hoat xu ly ngam...")
            remote_script = shlex.quote(config['remote_import_script_path'])
            remote_zip_quoted = shlex.quote(remote_zip_path)
            wp_author_quoted = shlex.quote(wp_author)
            wp_path_quoted = shlex.quote(site_config['wp_path'])
            log_file = shlex.quote(f"/tmp/import_{filename}.log") # Log import vẫn ở /tmp
            
            nohup_cmd = f"nohup {remote_script} {remote_zip_quoted} {wp_author_quoted} {wp_path_quoted} > {log_file} 2>&1 &"
            ssh.exec_command(nohup_cmd)
            print("✨ Kich hoat xong. Server se tu dong import.")

            # 4.7. Cap nhat bao cao chi tiet
            report_content += f"\n[OK] {filename} ({image_count} anh) -> {site_config['slug']}"
            total_image_count += image_count
            
            # --- (NÂNG CẤP) Cập nhật báo cáo tổng hợp ---
            current_prefix_count = newly_uploaded_counts.get(prefix, 0)
            newly_uploaded_counts[prefix] = current_prefix_count + image_count
            # --- KẾT THÚC NÂNG CẤP ---

            # 4.8. Xoa file local
            if delete_zip:
                os.remove(local_zip_file)
                print(f"🧹 Da xoa file local: {filename}")

        except paramiko.AuthenticationException:
            error_message = "Xac thuc that bai! Kiem tra lai mat khau VPS."
        except paramiko.SSHException as e:
            error_message = f"Loi SSH: {e}"
        except Exception as e:
            error_message = f"Loi script: {e}"
        finally:
            if ssh:
                ssh.close()
        
        # Ghi loi vao bao cao chi tiet
        if error_message:
            print(f"❌ LOI khi xu ly {filename}: {error_message}")
            report_content += f"\n[LOI] {filename} (That bai: {error_message.splitlines()[0] if error_message else 'Unknown'})"


    # 5. Gui bao cao Telegram (ĐÃ NÂNG CẤP)
    # Báo cáo chi tiết (report_content) và
    # Báo cáo tổng hợp (newly_uploaded_counts) sẽ được xử lý bên trong hàm này
    generate_and_send_report(wp_author, newly_uploaded_counts, report_content, total_image_count)

# --- Entry point de chay script ---
if __name__ == "__main__":
    main()