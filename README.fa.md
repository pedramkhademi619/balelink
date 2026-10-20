<div dir="rtl">

# balesdk

با **حساب شخصی** (نه ربات) وارد [بله](https://bale.ai) شوید و از پایتون، خط فرمان یا HTTP پیام بفرستید و دریافت کنید. [English](README.md)

> **غیررسمی است و ممکن است حساب شما مسدود شود.** رابط رسمی بله «API ربات» است. این کتابخانه یک حساب کاربری عادی را با پروتکل داخلی بله کنترل می‌کند و ممکن است قوانین بله را نقض کند. پیش از استفاده [SECURITY.md](SECURITY.md) را بخوانید و از شماره‌ای استفاده کنید که از دست دادنش مهم نیست. هیچ ارتباطی با بله ندارد.

> **وضعیت: آلفا.** تست‌ها با نسخه‌ی شبیه‌سازی‌شده انجام شده‌اند و روی یک حساب واقعی فقط این‌ها دستی امتحان شده: ورود با کد، اتصال دوباره از لاگین ذخیره‌شده، ارسال متن و خواندن تاریخچه. دریافت پیام، فایل، ویرایش/حذف/واکنش و درگاه HTTP هنوز روی حساب واقعی امتحان نشده‌اند. اول [`examples/smoke_test.py`](examples/smoke_test.py) را اجرا کنید و اگر خطایی بود خروجی‌اش را گزارش کنید.

```python
import asyncio
from balesdk import BaleClient, filters as F

bale = BaleClient("me")


@bale.on_message(F.private & F.command("ping"))
async def ping(msg):
    await msg.reply("pong")


async def main():
    async with bale:  # از لاگین ذخیره‌شده استفاده می‌کند
        await bale.send_text("09121234567", "سلام")  # با شماره تلفن
        await bale.run_forever()


asyncio.run(main())
```

## نصب

```bash
pip install balesdk
pip install "balesdk[gateway]"     # همراه با درگاه HTTP
```

پایتون ۳٫۹ به بالا. بر پایه‌ی [aiobale](https://github.com/aminmadaniofficial/aiobale) (MIT) ساخته شده که کار پروتکل را انجام می‌دهد؛ [NOTICE](NOTICE) را ببینید.

## ورود

```python
await bale.login(
    "09121234567", code=lambda: input("کد: "), password=lambda: input("رمز دومرحله‌ای: ")
)  # فقط اگر تنظیم کرده‌اید
```

یا `balesdk login me`. لاگین در `~/.balesdk/me.bale` ذخیره می‌شود و دفعه‌ی بعد کد نمی‌خواهد. **این فایل همان حساب شماست؛** آن را محرمانه نگه دارید و هرگز در گیت قرار ندهید. شماره می‌تواند `0912...`، `+98 912...` یا با ارقام فارسی باشد.

## دریافت پیام

```python
@bale.on_message(F.private & F.text)
@bale.on_message(F.group & F.text_contains("کمک"))
@bale.on_message(F.command("start", "help"))
```

فیلترها با `&` و `|` و `~` ترکیب می‌شوند. پیام‌های خودتان به‌طور پیش‌فرض تحویل داده نمی‌شوند. اتصال خودکار دوباره برقرار می‌شود.

## ارسال

```python
await bale.send_text("09121234567", "سلام")  # شماره، شناسه‌ی چت، کاربر یا پیام
await msg.reply("پاسخ")
await bale.send_file(chat, "report.pdf", caption="گزارش")
await sent.edit("متن جدید")
await sent.react("👍")
await sent.delete()
```

متن بلندتر از ۴۰۰۰ نویسه خودکار تکه‌تکه می‌شود و بین ارسال‌ها فاصله‌ی کوتاهی می‌افتد تا حساب مشکوک به ربات‌بودن نشود.

## درگاه HTTP

```bash
BALESDK_API_KEY=change-me balesdk serve
```

هر زبانی می‌تواند حساب‌ها را مثل WAHA از طریق HTTP کنترل کند: ساخت نشست، ورود با کد، ارسال پیام و فایل، ویرایش، حذف، واکنش، تاریخچه و **وب‌هوک** برای پیام‌های ورودی (امضای HMAC-SHA256 در هدر `X-Balesdk-Signature`، با تلاش مجدد). جزئیات در [README انگلیسی](README.md).

بدون `BALESDK_API_KEY` فقط روی `127.0.0.1` اجرا می‌شود؛ برای دسترسی بیرونی حتماً پشت HTTPS قرار دهید.

## مستندات

[شروع سریع](docs/getting-started.md) · [راهنما](docs/guide.md) · [درگاه HTTP](docs/gateway.md) · [عیب‌یابی](docs/troubleshooting.md) (همه‌ی مستندات انگلیسی هستند)

## خطاها

همه‌ی خطاها `BaleError` با `.code` ثابت‌اند (مثل `WRONG_CODE`، `RATE_LIMITED`، `NUMBER_BANNED`). به کلاس یا کد تکیه کنید، نه به متن.

مجوز: MIT.

</div>
