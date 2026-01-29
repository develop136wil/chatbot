@echo off
chcp 65001 >nul
echo 🚀 Vercel 즉시 배포 시작
echo.

echo 📋 1. 현재 파일 백업
copy utils.py utils_backup.py >nul 2>&1

echo 📋 2. 기본 파일 복사
copy utils_basic.py utils.py >nul 2>&1

echo 📋 3. import 오류 수정  
powershell -Command "sed -i \"s/from utils import/from utils_basic import/g\" main.py -OutFile temp_main.py -ErrorAction SilentlyContinue" 2>&1
if %errorlevel% equ 0 (
    move /y temp_main.py main.py >nul 2>&1
)

echo 📋 4. Vercel 배포
vercel --prod --yes > deployment.log 2>&1

echo.
echo ✅ 배포 완료! 자동으로 열립니다...
type deployment.log

pause