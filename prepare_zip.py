import os
import json
import shutil
import sys
from dotenv import load_dotenv

# --- CẤU HÌNH ---
load_dotenv()
INPUT_ZIP_DIR = 'InputZip'
CONFIG_FILE = 'config.json'

# Đường dẫn folder ảnh (Nằm ngang hàng với folder chứa script này)
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR) 
IMAGE_SOURCE_DIR = os.path.join(PROJECT_ROOT, 'ktbproject', 'ktbimage', 'OutputImage')

VALID_IMG_EXTS = ('.jpg', '.jpeg', '.png', '.webp', '.gif', '.bmp')

def main():
    print("--- [PRE-PROCESS] Quet folder anh & Tao Zip ---")

    # 1. Kiểm tra tài nguyên
    if not os.path.exists(INPUT_ZIP_DIR):
        os.makedirs(INPUT_ZIP_DIR)
    
    if not os.path.exists(CONFIG_FILE):
        print(f"[LOI] Khong tim thay {CONFIG_FILE}")
        return

    if not os.path.exists(IMAGE_SOURCE_DIR):
        print(f"[LOI] Khong tim thay folder anh: {IMAGE_SOURCE_DIR}")
        return

    # 2. Đọc Config để lấy Prefix và Author
    with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
        config = json.load(f)
    
    wp_author = config.get('default_user_author', 'unknown')
    sites = config.get('sites', [])
    
    # 3. Quét folder
    subfolders = [f for f in os.listdir(IMAGE_SOURCE_DIR) if os.path.isdir(os.path.join(IMAGE_SOURCE_DIR, f))]
    count = 0

    for folder_name in subfolders:
        folder_path = os.path.join(IMAGE_SOURCE_DIR, folder_name)
        
        # Check Prefix
        matched_site = next((site for site in sites if folder_name.startswith(site['prefix'])), None)
        if not matched_site:
            continue 

        # Check có ảnh không
        has_image = any(f.lower().endswith(VALID_IMG_EXTS) for f in os.listdir(folder_path))
        if not has_image:
            print(f"   ⚠️ Bo qua {folder_name} (Khong co anh)")
            continue

        # Tạo tên file Zip
        prefix = matched_site['prefix']
        base_zip_name = f"{prefix}.{wp_author}"
        zip_filename = f"{base_zip_name}.zip"
        
        # Xử lý trùng tên (tăng số đếm)
        counter = 1
        while os.path.exists(os.path.join(INPUT_ZIP_DIR, zip_filename)):
            counter += 1
            zip_filename = f"{base_zip_name}{counter}.zip"

        output_zip_path_no_ext = os.path.join(INPUT_ZIP_DIR, zip_filename.replace('.zip', ''))
        
        try:
            print(f"   📦 Dang nen: {folder_name} -> {zip_filename}...")
            shutil.make_archive(output_zip_path_no_ext, 'zip', folder_path)
            
            # --- QUAN TRỌNG: Xóa folder gốc sau khi nén thành công ---
            # Vì tool upload gốc sẽ xóa file zip sau khi up, 
            # nên ta cần xóa folder gốc ngay tại đây để tránh duplicate lần sau.
            shutil.rmtree(folder_path) 
            print(f"      ✅ Da nen & xoa folder goc: {folder_name}")
            count += 1
        except Exception as e:
            print(f"      ❌ Loi nen {folder_name}: {e}")

    print(f"--- [DONE] Da tao {count} file zip moi ---\n")

if __name__ == "__main__":
    main()