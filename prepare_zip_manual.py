import os
import json
import shutil
import sys
from dotenv import load_dotenv

# --- CẤU HÌNH ---
load_dotenv()
INPUT_ZIP_DIR = 'InputZip'
CONFIG_FILE = 'config.json'

# Tên folder cụ thể cần xử lý (nằm ngang hàng với ktbupload)
TARGET_FOLDER_NAME = 'printiment.chi' 

# Các đuôi file ảnh hợp lệ
VALID_IMG_EXTS = ('.jpg', '.jpeg', '.png', '.webp', '.gif', '.bmp')

def main():
    # 1. Xác định đường dẫn
    current_dir = os.path.dirname(os.path.abspath(__file__)) # Folder ktbupload
    parent_dir = os.path.dirname(current_dir)                # Folder cha chung
    target_folder_path = os.path.join(parent_dir, TARGET_FOLDER_NAME)

    print(f"--- [MANUAL PREPARE] Xu ly folder: {TARGET_FOLDER_NAME} ---")
    print(f"📂 Duong dan tuyet doi: {target_folder_path}")

    # 2. Kiểm tra folder tồn tại
    if not os.path.exists(target_folder_path):
        print(f"❌ [LOI] Khong tim thay folder '{TARGET_FOLDER_NAME}' ngang hang voi ktbupload.")
        return
    
    if not os.path.exists(INPUT_ZIP_DIR):
        os.makedirs(INPUT_ZIP_DIR)

    if not os.path.exists(CONFIG_FILE):
        print(f"[LOI] Khong tim thay {CONFIG_FILE}")
        return

    # 3. Kiểm tra xem trong đó có ảnh không
    files_in_folder = os.listdir(target_folder_path)
    image_files = [f for f in files_in_folder if f.lower().endswith(VALID_IMG_EXTS)]
    
    if not image_files:
        print("⚠️  Khong tim thay file anh nao trong folder nay -> Dung lai.")
        return

    print(f"✅ Tim thay {len(image_files)} file anh.")

    # 4. Đọc Config để lấy Author (dùng cho tên zip)
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            config = json.load(f)
        wp_author = config.get('default_user_author', 'manual')
        sites = config.get('sites', [])
    except Exception as e:
        print(f"[LOI] Doc config that bai: {e}")
        return

    # 5. Xác định Prefix từ tên folder (ktbtee.chi -> prefix là ktbtee)
    # Logic: Lấy phần đầu trước dấu chấm làm prefix
    prefix_candidate = TARGET_FOLDER_NAME.split('.')[0] 
    
    # Kiểm tra prefix này có trong config không
    matched_site = next((site for site in sites if site['prefix'] == prefix_candidate), None)
    
    if not matched_site:
        print(f"❌ [LOI] Prefix '{prefix_candidate}' khong co trong config.json.")
        print("   Hay dam bao ten folder bat dau bang prefix hop le (vi du: ktbtee.chi).")
        return

    # 6. Tạo tên file Zip
    base_zip_name = f"{prefix_candidate}.{wp_author}"
    zip_filename = f"{base_zip_name}.zip"
    
    # Xử lý trùng tên (tăng số đếm)
    counter = 1
    while os.path.exists(os.path.join(INPUT_ZIP_DIR, zip_filename)):
        counter += 1
        zip_filename = f"{base_zip_name}{counter}.zip"

    output_zip_path_no_ext = os.path.join(INPUT_ZIP_DIR, zip_filename.replace('.zip', ''))

    # 7. Thực hiện Nén & Xóa file
    try:
        print(f"📦 Dang nen thanh: {zip_filename}...")
        shutil.make_archive(output_zip_path_no_ext, 'zip', target_folder_path)
        print("✅ Nen thanh cong.")

        # --- QUAN TRỌNG: Chỉ xóa file ảnh, KHÔNG xóa folder ---
        print("🧹 Dang don dep cac file anh da nen...")
        deleted_count = 0
        for img_file in image_files:
            file_path = os.path.join(target_folder_path, img_file)
            try:
                os.remove(file_path)
                deleted_count += 1
            except Exception as del_err:
                print(f"   ⚠️ Khong xoa duoc {img_file}: {del_err}")

        print(f"✅ Da xoa {deleted_count} file anh khoi folder '{TARGET_FOLDER_NAME}'.")
        print(f"📁 Folder '{TARGET_FOLDER_NAME}' van duoc giu nguyen.")
        print(f"👉 File zip da san sang tai: {INPUT_ZIP_DIR}/{zip_filename}")

    except Exception as e:
        print(f"❌ Gặp lỗi trong quá trình nén/xóa: {e}")

if __name__ == "__main__":
    main()