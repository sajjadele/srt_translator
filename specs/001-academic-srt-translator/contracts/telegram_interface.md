# Telegram Interface Contract

## 1. Bot Commands

| Command | Arguments | Description | Response |
|---|---|---|---|
| `/start` | None | Welcome user & show instructions | Sends welcome card with instructions and topic selection inline buttons |
| `/topic` | `[topic_name]` | Set active course topic (e.g. `/topic Deep Learning`) | Confirms updated academic topic |
| `/glossary` | None | View active terminology / glossary info | Shows current dictionary info & custom overrides |
| `/cancel` | None | Abort in-progress session/job | Cancels active job for the current user |

---

## 2. Document Handling Lifecycle

1. **Upload**: User uploads an `.srt` document.
2. **Validation**:
   - Must have extension `.srt`.
   - File size $\le 20$ MB.
   - Initial quick parse check. If invalid, bot responds with specific formatting error.
3. **Acknowledgment & Status**:
   - Bot replies:
     ```text
     📥 فایل «lecture_01.srt» دریافت شد.
     📚 زمینه موضوعی: یادگیری ماشین (Machine Learning)
     📊 تعداد بلاک‌های زیرنویس: ۳۴۲ بلاک
     
     ⏳ وضعیت: در حال آماده‌سازی و ارسال به موتور ترجمان...
     ```
4. **Live Progress Milestones**:
   - Bot edits message as batches complete:
     ```text
     ⏳ در حال ترجمه: [██████░░░░] ۶۰٪ (بلاک ۲۰۵ از ۳۴۲)
     ```
5. **Delivery**:
   - Bot uploads the translated file `lecture_01_fa.srt` with caption:
     ```text
     ✅ ترجمه تخصصی با موفقیت پایان یافت!
     ⏱ زمان پردازش: ۴۲ ثانیه
     🎯 تعداد بلاک‌ها: ۳۴۲ (همگامی ۱۰۰٪)
     ```
   - Cleans up temporary working files.
