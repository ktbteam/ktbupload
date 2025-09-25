const fs = require("fs");
const { execSync } = require("child_process");
const path = require("path");
const os = require("os");

const site = JSON.parse(process.env.SITE_CONFIG_JSON);
if (!site) {
  console.error("Site configuration not found.");
  process.exit(1);
}

const ktbImagePath = process.env.KTB_IMAGE_PATH || 'ktb-image';
const zipsDirectory = path.join(ktbImagePath, 'generated-zips');

if (!fs.existsSync(zipsDirectory)) {
  console.error(`Lỗi: Không tìm thấy thư mục chứa file zip tại: ${zipsDirectory}`);
  process.exit(1);
}

const zipFiles = fs.readdirSync(zipsDirectory).filter(file => file.endsWith(".zip"));
let uploadedCount = 0;
const uploadedFiles = [];

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
  try {
    console.log(`Uploading ${file} to ${site.slug}...`);
    
    let sshKeyPath = process.env[`${site.vps_secret_prefix}_SSH_PRIVATE_KEY_PATH`];
    
    if (!sshKeyPath) {
        console.log("Không tìm thấy SSH_PRIVATE_KEY_PATH, đang tìm SSH_PRIVATE_KEY (nội dung key)...");
        const vpsSshKeyContent = process.env[`${site.vps_secret_prefix}_SSH_PRIVATE_KEY`];
        
        if (!vpsSshKeyContent) {
            throw new Error(`Missing VPS secrets: Cần có SSH_PRIVATE_KEY_PATH (cho PC) hoặc SSH_PRIVATE_KEY (cho Actions) cho prefix: ${site.vps_secret_prefix}`);
        }
        
        sshKeyPath = path.join(os.tmpdir(), `ssh_key_${site.slug}`);
        fs.writeFileSync(sshKeyPath, vpsSshKeyContent, { mode: 0o600 });
        console.log(`SSH key được tạo tạm thời tại: ${sshKeyPath} (cho GitHub Actions)`);
    } else {
        console.log(`Sử dụng SSH key từ đường dẫn được cung cấp: ${sshKeyPath} (cho PC)`);
    }
    
    const vpsHost = process.env[`${site.vps_secret_prefix}_VPS_HOST`];
    const vpsUser = process.env[`${site.vps_secret_prefix}_VPS_USERNAME`];
    const vpsPort = process.env[`${site.vps_secret_prefix}_VPS_PORT`];
    
    if (!vpsHost || !vpsUser || !vpsPort || !sshKeyPath) {
        throw new Error(`Missing VPS secrets for prefix: ${site.vps_secret_prefix}`);
    }
    
    const zipSourcePath = path.join(zipsDirectory, file);
    const remoteTempDir = `/tmp/upload_${Date.now()}`;
    const remoteZipPath = `${remoteTempDir}/${path.basename(file)}`;
    const remoteScriptPath = `${remoteTempDir}/remote_script.sh`;

    // SỬA ĐỔI: Thêm cờ "-n"
    execSync(`ssh -T -n -o StrictHostKeyChecking=no -i "${sshKeyPath}" -p ${vpsPort} ${vpsUser}@${vpsHost} "mkdir -p ${remoteTempDir}"`, { stdio: 'inherit' });
    execSync(`scp -o StrictHostKeyChecking=no -i "${sshKeyPath}" -P ${vpsPort} ${zipSourcePath} ${vpsUser}@${vpsHost}:${remoteZipPath}`, { stdio: 'inherit' });

    const remoteCommand = `#!/bin/bash
      set -e
      shopt -s nullglob
      cd ${remoteTempDir}
      unzip -o '${path.basename(file)}' -d extracted_images
      cd ${site.wp_path}
      wp media import ${remoteTempDir}/extracted_images/*.{webp,jpg} --user=${site.wp_author}
      rm -rf ${remoteTempDir}
    `;

    const localScriptPath = path.join(__dirname, 'temp_remote_script.sh');
    fs.writeFileSync(localScriptPath, remoteCommand);

    execSync(`scp -o StrictHostKeyChecking=no -i "${sshKeyPath}" -P ${vpsPort} ${localScriptPath} ${vpsUser}@${vpsHost}:${remoteScriptPath}`, { stdio: 'inherit' });
    
    // SỬA ĐỔI: Thêm cờ "-n"
    execSync(`ssh -T -n -o StrictHostKeyChecking=no -i "${sshKeyPath}" -p ${vpsPort} ${vpsUser}@${vpsHost} "bash ${remoteScriptPath}"`, { stdio: 'inherit' });

    fs.unlinkSync(localScriptPath);

    fs.appendFileSync(logFile, `${file}\n`);
    uploadedCount++;
    uploadedFiles.push(file);
    console.log(`✅ Finished importing ${file} to ${site.slug}.`);
  } catch (error) {
    console.error(`❌ Failed to upload ${file} to ${site.slug}: ${error.message}`);
  }
});

console.log(`Total files uploaded for ${site.slug}: ${uploadedCount}`);

if (process.env.GITHUB_OUTPUT) {
  fs.appendFileSync(process.env.GITHUB_OUTPUT, `uploaded_count=${uploadedCount}\n`);
}

if (uploadedFiles.length > 0) {
  const reportContent = uploadedFiles.join('\n');
  fs.writeFileSync(`${site.slug}_report.txt`, reportContent);
}