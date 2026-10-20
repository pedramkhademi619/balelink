<div align="center">

# balelink

<p dir="rtl"><b>با حساب شخصی خودتان وارد <a href="https://bale.ai">بله</a> شوید و از پایتون، خط فرمان یا HTTP پیام بفرستید و دریافت کنید.</b></p>

[![PyPI](https://img.shields.io/pypi/v/balelink?color=2b7de9)](https://pypi.org/project/balelink/)
[![Python](https://img.shields.io/pypi/pyversions/balelink)](https://pypi.org/project/balelink/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

<p dir="rtl"><a href="README.md">English</a> &nbsp;·&nbsp; <a href="docs/getting-started.md">شروع سریع</a> &nbsp;·&nbsp; <a href="docs/guide.md">راهنما</a> &nbsp;·&nbsp; <a href="docs/gateway.md">درگاه HTTP</a></p>

</div>

<div dir="rtl">

> [!WARNING]
> **غیررسمی است و ممکن است حساب شما مسدود شود.** رابط رسمی بله «API ربات» است و این کتابخانه یک حساب کاربری عادی را با پروتکل داخلی بله کنترل می‌کند. پیش از استفاده [SECURITY.md](SECURITY.md) را بخوانید و از شماره‌ای استفاده کنید که از دست دادنش مهم نیست. هیچ ارتباطی با بله ندارد.

</div>

```python
import asyncio
from balelink import BaleClient, filters as F

bale = BaleClient("me")

@bale.on_message(F.private & F.command("ping"))
async def ping(msg):
    await msg.reply("pong")

async def main():
    async with bale:                                   # reuses the saved login
        await bale.send_text("09121234567", "hello")    # by phone number
        await bale.run_forever()

asyncio.run(main())
```

<div dir="rtl">

## امکانات

| بخش | امکانات |
|---|---|
| **پیام** | متن، عکس، ویس، ویدیو، فایل و **لوکیشن**؛ پاسخ، ویرایش، حذف، فوروارد، پین، واکنش، تایپینگ |
| **دریافت** | handler با فیلترهای قابل ترکیب، `async for`، رویداد پیام جدید/ویرایش‌شده/حذف‌شده و وضعیت اتصال |
| **چت‌ها** | تاریخچه‌ی کامل (صفحه‌به‌صفحه)، لیست چت‌ها، پاک‌کردن و حذف |
| **مخاطبین** | بررسی وجود شماره، افزودن، تغییر نام، بلاک و آنبلاک |
| **گروه‌ها** | ساخت، ویرایش، اعضا، ادمین، لینک دعوت، پیوستن و خروج |
| **ورود** | با شماره و کد، رمز دومرحله‌ای اختیاری، ذخیره و استفاده‌ی دوباره |
| **درگاه HTTP** | شبیه WAHA: نشست‌ها، وب‌هوک با امضا و فیلتر رویداد، ارسال با آدرس، دانلود فایل |
| **ابزار** | خط فرمان `balelink`، `FakeTransport` برای تست بدون شبکه، کدهای خطای ثابت |

## نصب

</div>

```bash
pip install balelink                 # library and CLI
pip install "balelink[gateway]"      # plus the HTTP gateway
```

<div dir="rtl">

پایتون ۳٫۹ به بالا. بر پایه‌ی [aiobale](https://github.com/aminmadaniofficial/aiobale) (MIT) ساخته شده که کار پروتکل را انجام می‌دهد؛ [NOTICE](NOTICE) را ببینید.

## ورود

</div>

```bash
balelink login me
```

<div dir="rtl">

شماره‌تان را می‌پرسد، بله کدی می‌فرستد و شما آن را وارد می‌کنید (و رمز دومرحله‌ای، اگر دارید). لاگین در `~/.balelink/me.bale` ذخیره می‌شود و دفعه‌ی بعد کد نمی‌خواهد.

> [!IMPORTANT]
> **این فایل همان حساب شماست.** هر کس آن را داشته باشد می‌تواند چت‌هایتان را بخواند و به نام شما پیام بفرستد. آن را محرمانه نگه دارید و هرگز در گیت قرار ندهید.

از داخل کد:

</div>

```python
await bale.login("09121234567",
                 code=lambda: input("code: "),
                 password=lambda: input("password: "))   # only asked if needed
```

<div dir="rtl">

شماره می‌تواند `0912...`، `+98 912...` یا با ارقام فارسی باشد.

## دریافت پیام

</div>

```python
@bale.on_message(F.private & F.text)
@bale.on_message(F.group & F.text_contains("help"))
@bale.on_message(F.command("start", "help"))
@bale.on_message(F.photo)          # also F.voice, F.video, F.location
@bale.on_edited(F.private)
```

<div dir="rtl">

فیلترها با `&` و `|` و `~` ترکیب می‌شوند. پیام‌های خودتان به‌طور پیش‌فرض تحویل داده نمی‌شوند و اتصال بعد از قطع‌شدن خودکار برقرار می‌شود.

## ارسال

</div>

```python
await bale.send_text("09121234567", "hello")      # phone, chat id, User or Message
await msg.reply("reply")
await bale.send_photo(chat, "pic.jpg", caption="look")
await bale.send_file(chat, "note.ogg", kind=FileKind.VOICE)
await bale.send_location(chat, 35.7, 51.4)
await sent.edit("new text"); await sent.react("👍"); await sent.delete()
```

<div dir="rtl">

متن بلندتر از ۴۰۰۰ نویسه خودکار تکه‌تکه می‌شود و بین ارسال‌ها فاصله‌ی کوتاهی می‌افتد تا حساب مشکوک به ربات‌بودن نشود.

## درگاه HTTP

</div>

```bash
BALELINK_API_KEY=change-me balelink serve        # http://127.0.0.1:8787
```

<div dir="rtl">

هر زبانی می‌تواند حساب‌ها را مثل WAHA از طریق HTTP کنترل کند: ساخت نشست، ورود با کد، ارسال پیام، عکس، ویس و لوکیشن، مخاطبین، گروه‌ها و **وب‌هوک** برای پیام‌های ورودی. بدنه‌ی وب‌هوک امضای HMAC-SHA256 دارد و در صورت خطا چند بار دوباره تلاش می‌شود. جزئیات در [راهنمای درگاه](docs/gateway.md) (انگلیسی).

بدون `BALELINK_API_KEY` فقط روی `127.0.0.1` اجرا می‌شود؛ برای دسترسی بیرونی حتماً پشت HTTPS قرار دهید.

## وضعیت

نسخه‌ی آلفا. روی یک حساب واقعی این‌ها دستی امتحان شده‌اند:

| کار می‌کند (امتحان زنده) | هنوز امتحان نشده |
|---|---|
| ورود با کد و اتصال دوباره از لاگین ذخیره‌شده | گروه‌ها |
| ارسال و دریافت متن، **عکس، ویس و لوکیشن** | تغییر مخاطبین، بلاک |
| دانلود فایل و خواندن تاریخچه | فوروارد و پین |
| مخاطبین، لیست بلاک و لیست چت (فقط خواندن) | رویداد ویرایش/حذف و درگاه HTTP |

بیش از ۱۵۰ تست آفلاین هم دارد. [`examples/smoke_test.py`](examples/smoke_test.py) را روی حساب خودتان اجرا کنید و اگر خطایی بود خروجی‌اش را گزارش کنید.

## خطاها

همه‌ی خطاها از `BaleError` هستند و `.code` ثابت دارند (مثل `WRONG_CODE`، `RATE_LIMITED`، `NUMBER_BANNED`). به کلاس یا کد تکیه کنید، نه به متن.

## محدودیت‌ها

فقط چت خصوصی و گروه (بدون کانال و تماس). متن قالب‌دار، دکمه و نظرسنجی هنوز نیست. بله جستجوی شماره را محدود می‌کند؛ برای همین هر شماره‌ای که پیدا شود روی دیسک ذخیره می‌شود. پاسخ دادن به کسی که پیام داده، اصلاً جستجو لازم ندارد.

---

مجوز: MIT.

</div>
