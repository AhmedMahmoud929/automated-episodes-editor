# Automated Episodes Editor

سكربت Python لإنتاج فيديوهات الحلقات تلقائيًا مع intro أبيض (لوجوهات + عنوان)، fade transition، watermark أثناء المحتوى، ثم fade إلى outro أسود.

## المتطلبات

- Python 3.10+
- [FFmpeg](https://ffmpeg.org/download.html) مثبت ومضاف إلى `PATH`

### تثبيت FFmpeg على Windows

```powershell
winget install --id Gyan.FFmpeg -e
```

بعد التثبيت، أعد فتح الطرفية ثم تحقق:

```powershell
ffmpeg -version
```

## التثبيت

```powershell
cd d:\Projects\automated-episodes-editor
pip install -r requirements.txt
```

## الإعداد

عدّل [`config/episodes.json`](config/episodes.json):

- `settings` — الدقة، FPS، مدة intro/outro/fade، إعدادات watermark
- `episodes` — قائمة الحلقات مع `id`، `input`، `title`، `output`

## الاستخدام

### الوضع التفاعلي (افتراضي)

```powershell
python generate.py
```

يطلب منك السكربت:

1. **استخدام `episodes.json`؟** — نعم لاختيار الحلقات من الإعدادات، أو لا لاختيار فيديوهات من مجلد `episodes/` مباشرة
2. **اختيار الحلقة** — رقم حلقة محددة أو `A` لكل الحلقات
3. **تحسين الصوت** — إزالة الضوضاء، تعزيز الصوت، تطبيع المستوى، تعزيز الباس
4. **تأكيد** قبل بدء المعالجة

### سطر الأوامر (بدون تفاعل)

```powershell
# معالجة كل الحلقات
python generate.py --no-interactive

# حلقة واحدة
python generate.py --no-interactive --episode ep_01

# تحسين الصوت
python generate.py --no-interactive --remove-noise --voice-booster --normalize-audio

# ملف إعدادات مخصص
python generate.py --no-interactive --config config/episodes.json
```

### قصّ أجزاء من الفيديو (`cuts`)

في `config/episodes.json`، أضف مصفوفة `cuts` لكل حلقة لحذف مقاطع زمنية (بالثواني):

```json
{
  "id": "ep_01",
  "input": "episodes/ep_01.mp4",
  "title": "عنوان الحلقة",
  "output": "output/ep_01_final.mp4",
  "cuts": [
    {"start": 10.0, "end": 25.0},
    {"start": 120.0, "end": 135.5}
  ]
}
```

المقاطع بين `start` و `end` تُحذف قبل إضافة intro و watermark و outro. استخدم `[]` إذا لم تكن هناك مقاطع للحذف.

## هيكل المشروع

```
assets/          # اللوجوهات
episodes/        # الفيديوهات الخام
output/          # المخرجات النهائية
config/          # إعدادات JSON
fonts/           # خط عربي
src/             # كود Python
temp/            # ملفات مؤقتة (تُحذف تلقائيًا)
```

## خط الإنتاج

1. توليد صورة intro بيضاء (Pillow)
2. دمج intro → fade → فيديو + watermark → fade → outro أسود (FFmpeg)
