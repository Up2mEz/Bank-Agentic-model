# ปรับ Herdr skills ให้รับมือการเปลี่ยน protocol

วันที่ 4 ตุลาคม 2026 — แก้ต้นทางที่ `D:\skill ai` ตามคำสั่งผู้ใช้

## ผลที่ทำแล้ว

ปรับ `herdr`, `herdr-a2a` และ `herdr-orchestrator` ให้เลือกช่องทางที่ใช้งานได้จากหลักฐานของรุ่นที่ติดตั้งจริง ไม่ถือว่า A2A เป็นช่องทางบังคับ และไม่ใส่เลข protocol ตายตัวลงใน skill

- แยกสถานะ native Herdr client/server ออกจาก A2A bridge และ agent CLI: ช่องทางหนึ่งล้มเหลวไม่ได้แปลว่าทุกช่องทางล้มเหลว
- อ่าน help/schema และตรวจผลการเรียกจริง; `doctor` ผ่านหรือพบ executable อย่างเดียวไม่รับรองว่าส่งงานได้
- หาก bridge ปฏิเสธ protocol ก่อนสร้างงาน สามารถใช้ native Herdr หรือ agent CLI ที่ผู้ใช้ระบุ โดยรักษา agent/model และข้อห้ามเดิม
- หาก timeout หลังอาจส่งงานแล้ว ต้องตรวจสถานะเดิมก่อนส่งซ้ำ ป้องกันงานซ้ำ
- หาก inherited pane ID หมดอายุ ต้องยืนยันตัวตนจาก process/session; ไม่เลือก focused pane ของโครงการอื่นหรือเดา ID
- ผล exit code 0 แต่ stdout ว่างหรือ tool ถูกปฏิเสธไม่ถือว่ารีวิวสำเร็จ การรีวิวจากข้อความที่ส่งให้ต้องระบุว่าไม่ได้เปิดไฟล์หรือวัดข้อมูลดิบเอง
- ไม่เปลี่ยน constant ของ bridge เพื่อให้ผ่านการตรวจโดยไม่มี compatibility evidence และไม่ restart server หรือเปิด auto-approve จากการแก้ skill

## ไฟล์ที่แก้

1. `D:\skill ai\skills\herdr\SKILL.md`
2. `D:\skill ai\skills\herdr-a2a\SKILL.md`
3. `D:\skill ai\skills\herdr-orchestrator\SKILL.md`
4. `D:\skill ai\scripts\install-skills.ps1`: เพิ่ม option `-SkipGeminiCli` โดยการเรียกแบบเดิมยังมีพฤติกรรมเดิม

รอบนี้เรียก installer ด้วย `-SkipGeminiCli` เพื่อซิงก์ Codex/Claude ตามแนวทางของคลัง โดยไม่เรียก Gemini CLI ส่วน audit ตรวจไฟล์/ลิงก์ของ profiles รวม Gemini ที่มีอยู่เดิมได้โดยไม่เปิด CLI

## ตรวจอะไรแล้ว

- PowerShell syntax parser ผ่านสำหรับ installer
- `quick_validate.py` ผ่านทั้งสาม skills เมื่อกำหนด Python UTF-8; การเรียกแรกพบปัญหา encoding cp874 ของ validator ไม่ใช่ผลยืนยันว่า skill เสีย
- Installer สำเร็จ; audit เวลา `2026-10-04T18:49:21.8815978+07:00` พบคลัง 51 skills และ `allAgentsMatch=true` ทั้งสาม profiles ใช้ต้นทางเดียวกัน
- เรียก **agy โดยตรง** ด้วย prompt ที่มีข้อความ skills จริงและสี่สถานการณ์: protocol เปลี่ยน, timeout ที่อาจส่งสำเร็จ, exit 0 แต่ review ว่าง และข้อจำกัดการรีวิว excerpts
- คำตอบ agy สอดคล้องหลักสำคัญ: เลือก native CLI ได้, ไม่ส่งซ้ำก่อนตรวจสถานะ, ไม่แตะ pane อื่น, ไม่อ้าง review ที่ไม่มี และไม่เปลี่ยนไปใช้ Gemini ที่ผู้ใช้ห้าม

การตรวจของ agy เป็นการทดสอบการตีความคำสั่งจากข้อความที่ป้อนให้ ไม่ใช่การทดสอบ transport จริงกับ server protocol 27 ซึ่งเป็นสถานการณ์สมมติ ไม่มีการอ้างว่าทำ runtime compatibility test แล้ว

## ข้อจำกัดที่ยังคงอยู่

**การแก้ skills ไม่ได้แก้ executable ของ A2A bridge** โค้ด bridge ที่ตรวจในรอบทดลองยังมี `REQUIRED_PROTOCOL = 20` และ exact-equality preflight จึงอาจแสดง `HERDR_PROTOCOL_UNSUPPORTED` ต่อไปเมื่อเรียกช่องทางนั้นกับ protocol 22 ต้องแก้และทดสอบ bridge แยกต่างหากก่อนอ้างว่า A2A รองรับรุ่นใหม่ การแก้ครั้งนี้ช่วยให้ orchestration ไปต่อผ่านช่องทางที่ใช้ได้และรายงานสาเหตุอย่างตรงไปตรงมา

หลักฐานในโครงการ:

- `outputs/diagnostics/herdr_skills_sync.txt`
- `outputs/diagnostics/herdr_skills_audit.txt`
- `outputs/diagnostics/herdr_skills_verification.json`
- `outputs/agents/agy_herdr_forward_prompt.txt`
- `outputs/agents/agy_herdr_skill_forward_test.txt`

ไม่มีการเรียก Gemini CLI ในรอบปรับ skills และลอง TabPFN ใหม่ ประวัติการเรียก Gemini ในรอบก่อนยังเก็บใน execution log โดยไม่ลบหรือเปลี่ยนเป็นผลสำเร็จ
