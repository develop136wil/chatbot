# -*- coding: utf-8 -*-
"""임시 Vercel 배포용 스크립트"""

import subprocess
import sys
import os

def run_command(cmd, description):
    """명령어 실행 및 결과 출력"""
    print(f"🔧 {description}")
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, encoding='utf-8')
        if result.returncode == 0:
            print(f"✅ {description} 완료")
            print(f"출력: {result.stdout.strip()}")
        else:
            print(f"❌ {description} 실패")
            print(f"오류: {result.stderr.strip()}")
    except Exception as e:
        print(f"❌ {description} 예외: {e}")

def main():
    print("🚀 Vercel 즉시 배포 시작")
    
    # 1. 현재 파일 백업
    run_command("cp utils.py utils_backup.py", "utils 파일 백업")
    
    # 2. utils_basic.py를 utils.py로 복사 (LSP 오류 있는 버전 제외)
    run_command("cp utils_basic.py utils.py", "기본 utils 파일 복사")
    
    # 3. main.py import 오류 수정
    run_command('sed -i "s/from utils import/from utils_basic import/g" main.py', 'main.py import 오류 수정')
    
    # 4. Vercel 배포
    run_command("vercel --prod --yes 2>&1", "Vercel 최종 배포")

if __name__ == "__main__":
    main()