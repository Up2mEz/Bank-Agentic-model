# การจัดโฟลเดอร์โปรเจกต์

Root ของงานนี้คือ `D:\Project\NTT-Bank-Agentic` ไฟล์ใหม่ที่เกี่ยวข้องกับงานนี้ต้องอยู่ใต้ root นี้

- `src/creditrisk/`, `tests/`: source และ tests ของงานวิจัยเครดิต
- `agent_app/`: แอป agentic แยก source, tests, tools และ Python dependencies;
  วิธีรันอยู่ใน [README ของแอป](../agent_app/README.md)
- `examples/`: ตัวอย่างและ synthetic fixtures ที่อ้างอิงร่วมกับผลทดลองเดิม
- `docs/`, `research/`, `reports/`: เอกสารและผลวิจัยที่ตั้งใจเก็บใน Git
- `scripts/`, `tools/`: คำสั่งที่ใช้ซ้ำและเครื่องมือของโปรเจกต์
- `outputs/<task-or-run>/`: ผลรันและหลักฐานชั่วคราว ไม่เข้า Git
- `.local/merchant-dev/`: SDK, cache, PostgreSQL local, demo, releases และหลักฐานทดสอบ Merchant ไม่เข้า Git
- `repos/`: repo และ Git worktree ของ Merchant แต่ละ checkout มีประวัติ Git ของตัวเอง ไม่เข้า Git ของ Bank Agentic

## การแยก Agent app วันที่ 23 ตุลาคม 2026

Implementation ของ `merchant_sandbox` อยู่ที่ `agent_app/src/merchant_sandbox/`
ใช้คำสั่ง `python agent_app/run.py` และติดตั้ง package จาก `./agent_app`
import เดิมยังทำงานผ่าน shim ที่ `src/merchant_sandbox/__init__.py`;
root `tools/` มีเฉพาะตัวส่งต่อสำหรับ runner ที่ย้ายแล้ว อย่าแก้ logic ในตัวส่งต่อ

Policy/contract อยู่ใน `docs/merchant_lending/`, fixtures อยู่ใน
`examples/merchant_sandbox/` และผลรันอยู่ใน `outputs/` ตามเดิม ไม่มีการย้าย
DB, SDK, Go/Flutter checkout หรือแก้ผลทดลองเก่า

มี junction local เพิ่มเฉพาะ `src/merchant_sandbox/static` ชี้ไป assets ใหม่
เพื่อรองรับ process ที่เปิดก่อนย้าย ไม่เข้า Git; process ใหม่อ่าน assets จาก
package ใน `agent_app` โดยตรง ห้าม recursively delete junction นี้
หลักฐานก่อน/หลังย้ายอยู่ใน `outputs/agent-app-layout-20261023/`

## ใช้ environment จากจุดเดียว

เปิด PowerShell ที่ root แล้วใช้:

```powershell
. .\scripts\project-env.ps1
```

สคริปต์ตั้ง environment เฉพาะ shell ปัจจุบันและใช้ `.local/merchant-dev` โดยตรง ไม่สร้าง SDK หรือ cache ซ้ำอีกชุด และไม่เปลี่ยน environment ระดับเครื่อง ตัวเรียกเดิม `D:\merchant-dev\env.ps1` ส่งต่อมาสคริปต์นี้เพื่อรองรับคำสั่งเก่า

## สถานะการจัดระเบียบ 22 ตุลาคม 2026

**ย้ายเสร็จแล้ว** โดยรอให้เธรดงานสินเชื่อจบก่อนหยุดบริการตามที่ผู้ใช้อนุญาต:

- ย้าย `D:\merchant-dev` ทั้งชุดมา `.local/merchant-dev` รวมเครื่องมือ, cache, PostgreSQL, demo, releases และหลักฐานทดสอบ
- ย้าย checkout หลัก `ntt_data_2026-merchant` กับ worktree `ntt_data_2026-merchant-ui` และ `ntt_data_2026-ux-r3` มา `repos/` โดยคง Git history, branches และ uncommitted work
- ปรับ Git worktree pointers ให้ชี้ตำแหน่งใหม่ และปรับ path ในสคริปต์เปิดบริการ, Android SDK/AVD config และเอกสารวิธีรัน
- เพิ่ม `.gitignore` สำหรับ `.local/`, `repos/` และ `.playwright-mcp/` กับกติกาใน `AGENTS.md` เพื่อไม่ให้ไฟล์ local เข้า Git หรือกระจายออกนอก root

ลบเฉพาะ ZIP ติดตั้ง 5 ไฟล์ของ Go, Flutter, PostgreSQL, JDK และ Android command-line tools ซึ่งตรวจ SHA-256 ตรงกับ receipt และตรวจว่ามีชุดติดตั้งแล้ว รวม **2,743,944,591 bytes (2.56 GiB)** เก็บ source catalog, version และ checksum receipt ไว้ใน `.local/merchant-dev/downloads/`

ตำแหน่งเก่า 4 จุด (`D:\merchant-dev` และ checkout เดิมทั้ง 3) เป็น **compatibility junction** ชี้กลับมาข้อมูลชุดเดียวใต้ root นี้ ไม่ใช่โฟลเดอร์ข้อมูลหรือ SDK สำรองอีกชุด ยังเก็บไว้เพราะผลทดสอบเก่า, generated metadata และลิงก์จากบทสนทนามี path เดิมอยู่ งานใหม่ให้ใช้ path ใต้ root โดยตรง

โครงสร้างปัจจุบัน:

```text
NTT-Bank-Agentic/
  .local/merchant-dev/             # เครื่องมือและข้อมูล local ทั้งชุด
  repos/
    ntt_data_2026-merchant/         # checkout หลักของ repo Merchant
    ntt_data_2026-merchant-ui/      # worktree UI
    ntt_data_2026-ux-r3/            # worktree UX
```

หลักฐานการตรวจและย้ายอยู่ใน `outputs/project-layout-20261022/`:

- `content-verification.json`: SHA-256 ของ source 1,130 ไฟล์ และไฟล์ฐานข้อมูล 2,558 ไฟล์ตรงกับก่อนย้ายทั้งหมด ตรวจฐานข้อมูลตอนปิดอยู่ก่อนเริ่ม smoke test
- `git-before-final-move.json` / `git-after-final-move.json`: commit, branch และ working changes ของทั้ง 3 checkout ตรงเดิม
- `postgres-startup-verification.json`: เปิด PostgreSQL จาก data directory ใหม่ได้ ฐานข้อมูลครบ 5 ฐานและขนาดตรงเดิม จากนั้นปิดอย่างเรียบร้อยแล้ว
- `updated-paths.json`: รายการสคริปต์และ configuration ที่ปรับ path พร้อม hash ก่อน/หลัง
- `cleanup-receipt.json`: ZIP ทั้ง 5 ไฟล์ที่ลบและพื้นที่คืน 2.56 GiB
- `report-recovery-manifest.json`: ระหว่างย้ายพบ Guest LAN เปิด log ค้าง จึงหยุดบริการนั้นแล้วตรวจรายงานทั้ง 187 ไฟล์ว่าคง SHA-256 เดิม ไม่มีการทับไฟล์

ตรวจการเรียก Go 1.27.0, Flutter 3.47.7, JDK 17.0.20.1, PostgreSQL 18.6, ADB และ Gradle 9.3.1 จากตำแหน่งใหม่ รวมถึงการค้นพบ AVD `MerchantDemo` แล้ว รอบนี้ไม่ได้ build แอปใหม่หรือรันชุดทดสอบผลิตภัณฑ์ทั้งหมด

**บริการที่ใช้โฟลเดอร์ที่ย้ายปิดอยู่หลังจัดระเบียบ:** PostgreSQL, Merchant/Bank Go API, เว็บ Merchant/Guest ที่เกี่ยวข้อง, Android emulator และ build daemons ไม่ได้เปิดทิ้งไว้หลัง smoke test ส่วนบริการ Python sandbox ที่อยู่ใน root เดิมไม่ได้ย้ายหรือหยุด

เมื่อต้องใช้ฐานข้อมูลให้รัน `.\.local\merchant-dev\tools\Start-MerchantTestPostgres.ps1`; ตัวเปิด demo อยู่ที่ `.local/merchant-dev/demo/Start-MerchantDemo.ps1` ตามคู่มือเดิม

ขนาดใน inventory เป็น logical bytes ไม่ใช่ allocated space โดย scan ก่อนย้ายมี path ยาว/ไฟล์ที่เปลี่ยนระหว่าง scan อ่านไม่ครบ ส่วน scan หลังย้าย (`inventory-after.json`) ใช้ Windows extended paths และอ่านครบโดยไม่มี error: runtime 28.63 GiB กับ checkout รวมประมาณ 4.64 GiB ตรวจ directory links ภายใน 388 จุดแล้วไม่พบ link เสีย และ junction ภายนอกทั้ง 4 ชี้เข้ามาข้อมูลชุดเดียวใต้ root นี้

## กติกาป้องกันไฟล์กระจายและพื้นที่โต

1. ใช้ environment และ cache ชุดเดียวภายใต้ `.local/merchant-dev` ห้ามสร้าง `D:\merchant-dev` ใหม่
2. เก็บ checkout/worktree ใหม่ใต้ `repos/` และใช้ `git worktree move` / `git worktree repair` เมื่อต้องย้าย ห้ามลบ checkout ที่มี uncommitted work เพื่อประหยัดพื้นที่
3. ลบ installer archive หลังตรวจติดตั้งและ checksum สำเร็จ โดยเก็บ receipt ไว้
4. ล้างเฉพาะ cache/build ที่สร้างใหม่ได้เมื่อไม่มีงานใช้งาน ห้ามลบฐานข้อมูล, source, original test oracle, releases หรือผลทดสอบเพียงเพราะขนาดใหญ่
5. อย่าคัดลอก `.local/` หรือ `repos/` ลง Git หรือสร้าง backup ซ้ำทั้งโฟลเดอร์โดยไม่จำเป็น
6. อย่าลบ junction แบบ recursive ตำแหน่งเก่ายังจำเป็นต่อสคริปต์เก่าและ generated metadata ระหว่างเปลี่ยน path
