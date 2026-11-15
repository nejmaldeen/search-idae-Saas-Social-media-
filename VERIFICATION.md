# تقرير التحقق من التكامل — Integration Verification

- **وقت التشغيل:** 2026-11-15T14:20:57Z
- **الغرض:** إثبات أن كل منصة تُسلّم ما سيحتاجه البحث الحقيقي — لا بحث سوقي.

## الملخص

| المنصة | جاهزة | النتيجة | عناصر العيّنة | زمن | ملاحظة |
|---|---|---|---|---|---|
| snapchat | ✅ | 9/10 | 44 | 2.4s | status=ok reason=search_actor=parseforge~snapchat-scraper ro |
| tiktok | ✅ | 10/12 | 22 | 68.5s | status=ok reason=search_actor=clockworks~tiktok-scraper rows |
| youtube | ✅ | 10/12 | 84 | 3.6s | status=ok reason=None |
| instagram | ✅ | 9/12 | 5 | 47.7s | status=ok reason=search_actor=apify~instagram-scraper rows=5 |

## التفاصيل

### snapchat

- **التكلفة المقاسة:** $0.0
- status=ok reason=search_actor=parseforge~snapchat-scraper rows=5 mapped=5 | embedded_comments=39 | skipped=0

| # | المعيار | الحالة | الدليل |
|---|---|---|---|
| C01 | البحث بالعربية يُرجع نتائج | ➖ NA | profile-driven platform: no keyword search exists |
| C02 | جلب تعليقات المستخدمين لا الأوصاف فقط | ✅ PASS | 39 comment item(s) retrieved |
| C03 | كل عنصر له رابط مصدر | ✅ PASS | 44/44 items carry a source URL (100%) |
| C04 | اسم المؤلف وتاريخ النشر محفوظان | ✅ PASS | author on 39/44, publish date on 44/44 |
| C05 | مقاييس التفاعل (مشاهدات/إعجابات/تعليقات/مشاركات) | ✅ PASS | 44/44 items carry metrics; fields seen: author_followers, comments_count, likes, saves, shares, views |
| C06 | الردود على التعليقات متاحة | ➖ NA | comments are returned inline; Snapchat exposes no reply threading |
| C07 | العمق والسقف لكل استعلام | ✅ PASS | requested 5, received 44 in 2.4s. Documented ceiling: NO KEYWORD SEARCH on any available actor: collection is driven by a list of usernames the operator supplies, so Snapchat is a MONITORING |
| C08 | التصفية الزمنية | ✅ PASS | window of 180d honoured: 44 item(s) inside, 0 outside, 0 undated |
| C09 | سلوك واضح عند الفشل | ✅ PASS | empty/failed result reported explicitly as 'error' with reason 'actor=parseforge~snapchat-scraper returned 1 marker row(s) and no content: error=@zzzqqqxx' - no silent success |
| C10 | التكلفة مقاسة فعلياً | ✅ PASS | measured $0.0 for 44 item(s) = $0.0 per 1,000 |
| C11 | الوصول للجمهور السعودي/العربي | ❌ FAIL | 0/44 sampled items are Arabic (0%) |
| C12 | تفريغ نصي لما يقوله الفيديو | ✅ PASS | 5/44 item(s) carry a transcript (longest 13 chars) |

### tiktok

- **التكلفة المقاسة:** $0.1234
- status=ok reason=search_actor=clockworks~tiktok-scraper rows=5 mapped=5 | comments_actor=clockworks~tiktok-comments-scraper rows=17 mapped=17 | skipped=0

| # | المعيار | الحالة | الدليل |
|---|---|---|---|
| C01 | البحث بالعربية يُرجع نتائج | ✅ PASS | query 'مشاكل متجر سلة' -> 22 items, 22 containing Arabic |
| C02 | جلب تعليقات المستخدمين لا الأوصاف فقط | ✅ PASS | 17 comment item(s) retrieved |
| C03 | كل عنصر له رابط مصدر | ✅ PASS | 22/22 items carry a source URL (100%) |
| C04 | اسم المؤلف وتاريخ النشر محفوظان | ✅ PASS | author on 22/22, publish date on 22/22 |
| C05 | مقاييس التفاعل (مشاهدات/إعجابات/تعليقات/مشاركات) | ✅ PASS | 22/22 items carry metrics; fields seen: comments_count, likes, saves, shares, views |
| C06 | الردود على التعليقات متاحة | ✅ PASS | replies enabled (replies_per_comment=3): the run returned 3 comment item(s). search_actor=clockworks~tiktok-scraper rows=2 mapped=2 / comments_actor=clockworks~tiktok-comments-scraper row |
| C07 | العمق والسقف لكل استعلام | ✅ PASS | requested 5, received 22 in 68.5s. Documented ceiling: Billed per result by the provider (~$1.70-3.70 / 1,000 as of Nov 2026). |
| C08 | التصفية الزمنية | ✅ PASS | window of 180d honoured: 9 item(s) inside, 0 outside, 0 undated |
| C09 | سلوك واضح عند الفشل | ⚠️ PARTIAL | a nonsense query still returned items - results may be fuzzy |
| C10 | التكلفة مقاسة فعلياً | ✅ PASS | measured $0.1234 for 22 item(s) = $5.609 per 1,000 |
| C11 | الوصول للجمهور السعودي/العربي | ✅ PASS | 22/22 sampled items are Arabic (100%) |
| C12 | تفريغ نصي لما يقوله الفيديو | ⚠️ PARTIAL | subtitle tracks are published (ara-SA, eng-US; Arabic available) but the subtitle CDN host is not reachable from this environment, so the text cannot be downloaded yet |

### youtube

- **التكلفة المقاسة:** $0.0063
- status=ok reason=None

| # | المعيار | الحالة | الدليل |
|---|---|---|---|
| C01 | البحث بالعربية يُرجع نتائج | ✅ PASS | query 'مشاكل المتاجر الإلكترونية' -> 84 items, 84 containing Arabic |
| C02 | جلب تعليقات المستخدمين لا الأوصاف فقط | ✅ PASS | 79 comment item(s) retrieved |
| C03 | كل عنصر له رابط مصدر | ✅ PASS | 84/84 items carry a source URL (100%) |
| C04 | اسم المؤلف وتاريخ النشر محفوظان | ✅ PASS | author on 84/84, publish date on 84/84 |
| C05 | مقاييس التفاعل (مشاهدات/إعجابات/تعليقات/مشاركات) | ✅ PASS | 84/84 items carry metrics; fields seen: comments_count, likes, views |
| C06 | الردود على التعليقات متاحة | ⚠️ PARTIAL | commentThreads reports totalReplyCount (21 sampled item(s) have replies) but fetching the reply bodies needs a second comments.list call, which is not implemented |
| C07 | العمق والسقف لكل استعلام | ✅ PASS | requested 5, received 84 in 3.6s. Documented ceiling: 10,000 quota units/day. search.list costs 100 units; commentThreads.list costs 1. |
| C08 | التصفية الزمنية | ✅ PASS | window of 180d honoured: 104 item(s) inside, 0 outside, 0 undated |
| C09 | سلوك واضح عند الفشل | ✅ PASS | empty/failed result reported explicitly as 'ok' with reason 'None' - no silent success |
| C10 | التكلفة مقاسة فعلياً | ✅ PASS | measured $0.0063 for 84 item(s) = $0.075 per 1,000 |
| C11 | الوصول للجمهور السعودي/العربي | ✅ PASS | 84/84 sampled items are Arabic (100%) |
| C12 | تفريغ نصي لما يقوله الفيديو | ❓ UNTESTED | a dedicated transcription actor exists (pintostudio~youtube-transcript-scraper) but is not wired in |

### instagram

- **التكلفة المقاسة:** $0.0215
- status=ok reason=search_actor=apify~instagram-scraper rows=5 mapped=5 | comments_actor=apify~instagram-comment-scraper rows=1 mapped=0 | skipped=1

| # | المعيار | الحالة | الدليل |
|---|---|---|---|
| C01 | البحث بالعربية يُرجع نتائج | ✅ PASS | query 'متجر_الكتروني' -> 5 items, 5 containing Arabic |
| C02 | جلب تعليقات المستخدمين لا الأوصاف فقط | ❌ FAIL | items returned but none are comments - only captions/metadata |
| C03 | كل عنصر له رابط مصدر | ✅ PASS | 5/5 items carry a source URL (100%) |
| C04 | اسم المؤلف وتاريخ النشر محفوظان | ✅ PASS | author on 5/5, publish date on 5/5 |
| C05 | مقاييس التفاعل (مشاهدات/إعجابات/تعليقات/مشاركات) | ✅ PASS | 5/5 items carry metrics; fields seen: comments_count, likes |
| C06 | الردود على التعليقات متاحة | ❌ FAIL | enabling replies produced no comments: ok search_actor=apify~instagram-scraper rows=2 mapped=2 / comments_actor=apify~instagram-comment-scraper rows=1 mapped=0 /  |
| C07 | العمق والسقف لكل استعلام | ✅ PASS | requested 5, received 5 in 47.7s. Documented ceiling: ~$1.50-2.70 / 1,000 results as of Nov 2026. |
| C08 | التصفية الزمنية | ✅ PASS | window of 180d honoured: 5 item(s) inside, 0 outside, 0 undated |
| C09 | سلوك واضح عند الفشل | ✅ PASS | empty/failed result reported explicitly as 'error' with reason 'actor=apify~instagram-scraper returned 1 marker row(s) and no content: error=no_items. The' - no silent success |
| C10 | التكلفة مقاسة فعلياً | ✅ PASS | measured $0.0215 for 5 item(s) = $4.3 per 1,000 |
| C11 | الوصول للجمهور السعودي/العربي | ✅ PASS | 5/5 sampled items are Arabic (100%) |
| C12 | تفريغ نصي لما يقوله الفيديو | ❓ UNTESTED | a dedicated transcription actor exists (steadyfetch~instagram-reel-transcript-scraper) but is not wired in |

## مفتاح الحالات

- ✅ **PASS** — مُثبت بدليل من تشغيل حقيقي
- ⚠️ **PARTIAL** — يعمل جزئياً أو القدرة موجودة ولم تُفعّل في هذا الفحص
- ❌ **FAIL** — لا يعمل، والسبب مذكور
- ➖ **NA** — لا ينطبق على هذه المنصة
- ❓ **UNTESTED** — لم يُشغَّل؛ **لا يُحسب نجاحاً**

## التكلفة المقاسة فعلياً (C10)

- أُنفق خلال هذا التحقق: **$0.1511**
- عناصر مجلوبة: **155**
- **التكلفة لكل ١٠٠٠ عنصر: $0.975**
