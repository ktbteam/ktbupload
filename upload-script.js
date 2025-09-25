const fs = require("fs");
const { execSync } = require("child_process");
const path = require("path");
const os = require("os");

const site = JSON.parse(process.env.SITE_CONFIG_JSON);
if (!site) {
  console.error("Site configuration not found.");
  process.exit(1);
}

const ktbImagePath = process.env.KTB_IMAGE_PATH || '../ktbproject/ktbimage';
const zipsDirectory = path.join(ktbImagePath, 'OutputImage');

if (!fs.existsSync(zipsDirectory)) {
  console.error(`Lỗi: Không tìm thấy thư mục chứa file zip tại: ${zipsDirectory}`);
  process.exit(1);
}

const zipFiles = fs.readdirSync(zipsDirectory).filter(file => file.endsWith(".zip"));
let uploadedCount = 0;
const reportLines = [];

const logFile = `uploaded_files_${site.slug}.log`;
if (!fs.existsSync(logFile)) {
  fs.writeFileSync(logFile, "");
}
const logContent = fs.readFileSync(logFile, "utf8");

zipFiles.forEach(file => {
  if (!file.startsWith(site.prefix)) {
    return;
  }
  if (logContent.includes(file)) {
    console.log(`Skipping ${file} for ${site.slug}, already uploaded.`);
    return;
  }
  
  let sshKeyPath = "";
  let vpsHost = "";
  let vpsUser = "";
  let vpsPort = "";
  let imageCount = 0; // Biến đếm ảnh
  const remoteTempDir = `/tmp/upload_${site.slug}_${Date.now()}`;
  const remoteZipPath = `${remoteTempDir}/${path.basename(file)}`;
  const remoteScriptPath = `${remoteTempDir}/remote_script.sh`;

  try {
    console.log(`Uploading ${file} to ${site.slug}...`);
    
    // --- 1. Lấy thông tin SSH ---
    sshKeyPath = process.env[`${site.vps_secret_prefix}_SSH_PRIVATE_KEY_PATH`];
    
    if (!sshKeyPath) {
        console.log("Không tìm thấy SSH_PRIVATE_KEY_PATH, đang tìm SSH_PRIVATE_KEY...");
        const vpsSshKeyContent = process.env[`${site.vps_secret_prefix}_SSH_PRIVATE_KEY`];
        if (!vpsSshKeyContent) throw new Error(`Missing SSH_PRIVATE_KEY_PATH hoặc SSH_PRIVATE_KEY cho prefix: ${site.vps_secret_prefix}`);
        
        sshKeyPath = path.join(os.tmpdir(), `ssh_key_${site.slug}`);
        fs.writeFileSync(sshKeyPath, vpsSshKeyContent, { mode: 0o600 });
    }
    
    vpsHost = process.env[`${site.vps_secret_prefix}_VPS_HOST`];
    vpsUser = process.env[`${site.vps_secret_prefix}_VPS_USERNAME`]; // Phải là 'ktb'
    vpsPort = process.env[`${site.vps_secret_prefix}_VPS_PORT`];
    
    if (!vpsHost || !vpsUser || !vpsPort) {
        throw new Error(`Missing VPS secrets for prefix: ${site.vps_secret_prefix}`);
    }
    
    const zipSourcePath = path.join(zipsDirectory, file);

    // --- 2. Tạo thư mục tạm và Upload file zip ---
    execSync(`ssh -T -n -o StrictHostKeyChecking=no -i "${sshKeyPath}" -p ${vpsPort} ${vpsUser}@${vpsHost} "mkdir -p ${remoteTempDir}"`, { stdio: 'inherit' });
    execSync(`scp -o StrictHostKeyChecking=no -i "${sshKeyPath}" -P ${vpsPort} ${zipSourcePath} ${vpsUser}@${vpsHost}:${remoteZipPath}`, { stdio: 'inherit' });
    console.log("✅ Upload file zip thành công.");

    // --- 3. (SỬA ĐỔI) Đếm ảnh bằng unzip -l ---
    console.log("Đang đếm ảnh trong file zip trên server...");
    const countCmd = `ssh -T -n -o StrictHostKeyChecking=no -i "${sshKeyPath}" -p ${vpsPort} ${vpsUser}@${vpsHost} "unzip -l ${remoteZipPath} | grep -Eic '(\\.webp|\\.jpg|\\.png)$' || echo 0"`;
    const imageCountOutput = execSync(countCmd).toString().trim();
    imageCount = parseInt(imageCountOutput, 10) || 0;
    console.log(`   File chứa ${imageCount} ảnh.`);

    // --- 4. Tạo và chạy script remote (Đã cập nhật sudo) ---
    const remoteCommand = `#!/bin/bash
      set -e
      shopt -s nullglob
      WEB_USER="nginx" # <-- Đổi 'nginx' nếu user web của bạn khác
      
      # Tự động dọn dẹp
      function cleanup {
        echo "Dọn dẹp ${remoteTempDir}..."
        rm -rf ${remoteTempDir}
      }
      trap cleanup EXIT

      # Cho phép nginx đọc thư mục tạm (Lỗi "File doesn't exist")
      chmod 755 "${remoteTempDir}"
      
      cd ${remoteTempDir}
      unzip -o '${path.basename(file)}' -d extracted_images
      
      # Cấp quyền đọc file ảnh
      chmod -R 755 extracted_images

      # Import với sudo
      echo "Import vào ${site.wp_path} với author ${site.wp_author}..."
      cd ${site.wp_path}
      sudo -u nginx /usr/local/bin/wp media import ${remoteTempDir}/extracted_images/*.{webp,jpg,png} --user=${site.wp_author}
      
      echo "--- Hoàn thành xử lý $file ---"
    `;

    const localScriptPath = path.join(__dirname, 'temp_remote_script.sh');
    fs.writeFileSync(localScriptPath, remoteCommand);
    
    execSync(`scp -o StrictHostKeyChecking=no -i "${sshKeyPath}" -P ${vpsPort} ${localScriptPath} ${vpsUser}@${vpsHost}:${remoteScriptPath}`, { stdio: 'inherit' });
    execSync(`ssh -T -n -o StrictHostKeyChecking=no -i "${sshKeyPath}" -p ${vpsPort} ${vpsUser}@${vpsHost} "bash ${remoteScriptPath}"`, { stdio: 'inherit' });

    fs.unlinkSync(localScriptPath);

    // --- 5. Ghi log thành công (Cả 2 file) ---
    fs.appendFileSync(logFile, `${file}\n`);
    uploadedCount++;
    
    // (SỬA ĐỔI) Ghi báo cáo dựa trên số ảnh đã đếm
    if (imageCount > 0) {
        reportLines.push(`${site.prefix}:${imageCount}`);
    }

    console.log(`✅ Finished importing ${file} to ${site.slug}.`);

  } catch (error) {
    console.error(`❌ Failed to upload ${file} to ${site.slug}: ${error.message}`);
    // Nếu lỗi, cố gắng dọn dẹp thư mục tạm trên VPS
    if (vpsHost && vpsUser && vpsPort && sshKeyPath) {
      console.log("Đang cố gắng dọn dẹp thư mục tạm trên VPS sau lỗi...");
      execSync(`ssh -T -n -o StrictHostKeyChecking=no -i "${sshKeyPath}" -p ${vpsPort} ${vpsUser}@${vpsHost} "rm -rf ${remoteTempDir}"`, { stdio: 'ignore' });
    }
  }
  
  // Xóa file key tạm nếu nó được tạo ra
  if (process.env[`${site.vps_secret_prefix}_SSH_PRIVATE_KEY`]) {
      fs.unlinkSync(sshKeyPath);
  }

  console.log("--- Tạm nghỉ 5 giây để tránh bị firewall chặn ---");
  execSync('sleep 5'); 
});

console.log(`Total files uploaded for ${site.slug}: ${uploadedCount}`);

if (process.env.GITHUB_OUTPUT) {
  fs.appendFileSync(process.env.GITHUB_OUTPUT, `uploaded_count=${uploadedCount}\n`);
}

// Ghi nội dung report mới vào file
if (reportLines.length > 0) {
  const reportContent = reportLines.join('\n');
  fs.writeFileSync(`${site.slug}_report.txt`, reportContent);
  console.log(`Đã ghi báo cáo: ${site.slug}_report.txt`);
} else {
  console.log("Không có ảnh mới nào được ghi vào báo cáo.");
}